"""Base sink abstraction.

All concrete sinks implement a `foreachBatch` writer that handles:
  - Idempotency via a stable token per record
  - Batched writes (flush at batch_size or flush_interval_ms)
  - Partial-failure handling with error_tolerance_pct
  - Metrics emission to CloudWatch
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pyspark.sql import DataFrame

from streaming.core.types import SinkConfig
from streaming.utils.logging_config import get_logger
from streaming.utils.metrics import StreamingMetricsEmitter

log = get_logger(__name__, component="sink.base")


@dataclass
class SinkBatchResult:
    """Result of writing one micro-batch to a sink."""
    sink_name: str
    batch_id: int
    records_written: int
    records_failed: int
    duration_ms: int

    @property
    def failure_rate(self) -> float:
        total = self.records_written + self.records_failed
        return self.records_failed / total if total > 0 else 0.0


class BaseSink(ABC):
    """Abstract base for all sinks."""

    def __init__(self, config: SinkConfig):
        self.config = config
        self.metrics = StreamingMetricsEmitter()

    @abstractmethod
    def write_batch(self, batch_df: DataFrame, batch_id: int) -> SinkBatchResult:
        """Write one micro-batch. Subclasses implement this."""

    def make_foreach_batch_fn(self) -> Callable[[DataFrame, int], None]:
        """Build the foreachBatch callback Spark will invoke per micro-batch.

        Includes error-tolerance handling: batches with failure rate above
        `error_tolerance_pct` will raise and halt the stream.
        """
        sink_name = self.config.name
        error_tolerance = self.config.error_tolerance_pct

        def fn(batch_df: DataFrame, batch_id: int) -> None:
            try:
                result = self.write_batch(batch_df, batch_id)
                self.metrics.emit_sink_metrics(
                    sink_name=result.sink_name,
                    records_written=result.records_written,
                    records_failed=result.records_failed,
                    duration_ms=result.duration_ms,
                )

                if result.failure_rate > error_tolerance:
                    raise RuntimeError(
                        f"Sink {sink_name} batch {batch_id} failure rate "
                        f"{result.failure_rate:.2%} exceeds tolerance "
                        f"{error_tolerance:.2%}"
                    )

                log.info(
                    "sink_batch_done",
                    sink=sink_name,
                    batch_id=batch_id,
                    written=result.records_written,
                    failed=result.records_failed,
                    duration_ms=result.duration_ms,
                )
            except Exception as exc:
                log.exception(
                    "sink_batch_failed",
                    sink=sink_name,
                    batch_id=batch_id,
                    error=str(exc),
                )
                raise

        return fn


def extract_idempotency_token(record: dict[str, Any]) -> str:
    """Build a stable idempotency token for a record.

    Strategy: prefer CDC LSN; fall back to event_id; finally to a composite
    of topic + partition + offset.
    """
    if "lsn" in record and record["lsn"]:
        return f"lsn:{record['lsn']}"
    if "event_id" in record and record["event_id"]:
        return f"eid:{record['event_id']}"
    topic = record.get("raw_topic", "?")
    partition = record.get("raw_partition", "?")
    offset = record.get("raw_offset", "?")
    return f"koffset:{topic}:{partition}:{offset}"
