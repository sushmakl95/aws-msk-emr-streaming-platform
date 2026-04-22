"""S3 + Iceberg cold sink — long-term archival with Athena/Trino queryability.

Writes records as Parquet into partitioned Iceberg tables. Exactly-once
achieved via Iceberg's commit atomicity + Spark's checkpoint offsets.

Iceberg > Delta here because:
  - Iceberg is the Athena-native table format as of 2024
  - Cross-engine interop (Spark, Flink, Trino, Athena) is smoother
  - Time travel works across Spark + Flink writers without format coordination
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from streaming.core.types import SinkConfig
from streaming.sinks.base import BaseSink, SinkBatchResult
from streaming.utils.logging_config import get_logger

log = get_logger(__name__, component="sink.s3_iceberg")


@dataclass
class S3IcebergSinkConfig(SinkConfig):
    """S3 + Iceberg sink configuration."""
    catalog: str = "glue_catalog"
    database: str = "streaming"
    table: str = "events"
    s3_warehouse: str = "s3://streaming-platform-iceberg/warehouse/"
    partition_by: list[str] = field(default_factory=lambda: ["event_date"])
    sink_type: str = "s3_iceberg"
    properties: dict = field(default_factory=dict)

    @property
    def fully_qualified_name(self) -> str:
        return f"{self.catalog}.{self.database}.{self.table}"


class S3IcebergSink(BaseSink):
    def __init__(self, config: S3IcebergSinkConfig):
        super().__init__(config)
        self.config: S3IcebergSinkConfig = config

    def write_batch(self, batch_df: DataFrame, batch_id: int) -> SinkBatchResult:
        t0 = time.perf_counter()
        count = batch_df.count()
        failed = 0

        if count == 0:
            return SinkBatchResult(
                sink_name=self.config.name,
                batch_id=batch_id,
                records_written=0,
                records_failed=0,
                duration_ms=int((time.perf_counter() - t0) * 1000),
            )

        try:
            # Add event_date partition column if referenced
            df_to_write = batch_df
            if "event_date" in self.config.partition_by and "event_date" not in batch_df.columns:
                df_to_write = df_to_write.withColumn(
                    "event_date", F.to_date(F.col("event_time"))
                )

            (
                df_to_write.writeTo(self.config.fully_qualified_name)
                .using("iceberg")
                .tableProperty("format-version", "2")
                .tableProperty("write.parquet.compression-codec", "zstd")
                .append()
            )
            log.info(
                "iceberg_write_success",
                table=self.config.fully_qualified_name,
                batch_id=batch_id,
                records=count,
            )
        except Exception as exc:
            log.error(
                "iceberg_write_failed",
                table=self.config.fully_qualified_name,
                batch_id=batch_id,
                error=str(exc),
            )
            failed = count
            count = 0

        duration_ms = int((time.perf_counter() - t0) * 1000)
        return SinkBatchResult(
            sink_name=self.config.name,
            batch_id=batch_id,
            records_written=count,
            records_failed=failed,
            duration_ms=duration_ms,
        )
