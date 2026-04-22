"""ClickHouse sink — warm-tier columnar analytics (OLAP).

Uses clickhouse-connect for HTTP-based bulk insert. Works against ClickHouse
running as an ECS Fargate service (see infra/terraform/modules/ecs_clickhouse).

Insert mode: BUFFER table + MergeTree table for transparent async insert with
strong deduplication via ReplacingMergeTree when the target table is
configured with a version column.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import clickhouse_connect
from pyspark.sql import DataFrame

from streaming.core.types import SinkConfig
from streaming.sinks.base import BaseSink, SinkBatchResult
from streaming.utils.logging_config import get_logger

log = get_logger(__name__, component="sink.clickhouse")


@dataclass
class ClickHouseSinkConfig(SinkConfig):
    """ClickHouse sink configuration."""
    host: str = "localhost"
    port: int = 8123
    username: str = "default"
    password: str = ""
    database: str = "streaming"
    target_table: str = "events"
    """Should be a BUFFER table writing into a MergeTree underneath."""
    secure: bool = True
    sink_type: str = "clickhouse"
    properties: dict = field(default_factory=dict)


class ClickHouseSink(BaseSink):
    def __init__(self, config: ClickHouseSinkConfig):
        super().__init__(config)
        self.config: ClickHouseSinkConfig = config
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = clickhouse_connect.get_client(
                host=self.config.host,
                port=self.config.port,
                username=self.config.username,
                password=self.config.password,
                database=self.config.database,
                secure=self.config.secure,
                connect_timeout=10,
                send_receive_timeout=30,
            )
        return self._client

    def write_batch(self, batch_df: DataFrame, batch_id: int) -> SinkBatchResult:
        t0 = time.perf_counter()

        # Convert Spark DF → Pandas → columnar format for ClickHouse bulk insert
        pandas_df = batch_df.toPandas()
        written = 0
        failed = 0

        if pandas_df.empty:
            return SinkBatchResult(
                sink_name=self.config.name,
                batch_id=batch_id,
                records_written=0,
                records_failed=0,
                duration_ms=int((time.perf_counter() - t0) * 1000),
            )

        client = self._get_client()
        try:
            client.insert_df(
                table=self.config.target_table,
                df=pandas_df,
                database=self.config.database,
            )
            written = len(pandas_df)
        except Exception as exc:
            log.error("clickhouse_insert_failed", batch_id=batch_id, error=str(exc))
            failed = len(pandas_df)

        duration_ms = int((time.perf_counter() - t0) * 1000)
        return SinkBatchResult(
            sink_name=self.config.name,
            batch_id=batch_id,
            records_written=written,
            records_failed=failed,
            duration_ms=duration_ms,
        )
