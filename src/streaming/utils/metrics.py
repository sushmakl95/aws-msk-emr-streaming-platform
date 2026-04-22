"""CloudWatch metrics emitter for streaming jobs."""

from __future__ import annotations

from typing import Any

import boto3

from streaming.utils.logging_config import get_logger

log = get_logger(__name__, component="metrics")


class StreamingMetricsEmitter:
    """Emit custom streaming metrics to CloudWatch."""

    def __init__(self, namespace: str = "Streaming/Platform", region: str = "us-east-1"):
        self.namespace = namespace
        self.region = region
        self.client = boto3.client("cloudwatch", region_name=region)

    def emit_batch_metrics(
        self,
        job_name: str,
        batch_id: int,
        records_in: int,
        records_out: int,
        duration_ms: int,
        lag_ms: int,
    ) -> None:
        """Emit per-micro-batch metrics."""
        dims = [
            {"Name": "JobName", "Value": job_name},
        ]
        data = [
            {"MetricName": "RecordsIn", "Value": records_in, "Unit": "Count", "Dimensions": dims},
            {"MetricName": "RecordsOut", "Value": records_out, "Unit": "Count", "Dimensions": dims},
            {"MetricName": "BatchDurationMs", "Value": duration_ms,
             "Unit": "Milliseconds", "Dimensions": dims},
            {"MetricName": "LagMs", "Value": lag_ms,
             "Unit": "Milliseconds", "Dimensions": dims},
            {"MetricName": "BatchId", "Value": batch_id, "Unit": "None", "Dimensions": dims},
        ]
        self._put(data)

    def emit_sink_metrics(
        self,
        sink_name: str,
        records_written: int,
        records_failed: int,
        duration_ms: int,
    ) -> None:
        """Emit per-sink metrics."""
        dims = [{"Name": "SinkName", "Value": sink_name}]
        data = [
            {"MetricName": "SinkRecordsWritten", "Value": records_written,
             "Unit": "Count", "Dimensions": dims},
            {"MetricName": "SinkRecordsFailed", "Value": records_failed,
             "Unit": "Count", "Dimensions": dims},
            {"MetricName": "SinkWriteDurationMs", "Value": duration_ms,
             "Unit": "Milliseconds", "Dimensions": dims},
        ]
        self._put(data)

    def _put(self, data: list[dict[str, Any]]) -> None:
        """Send in chunks of 20."""
        try:
            for chunk_start in range(0, len(data), 20):
                chunk = data[chunk_start : chunk_start + 20]
                self.client.put_metric_data(Namespace=self.namespace, MetricData=chunk)
        except Exception as exc:
            log.warning("metric_emit_failed", error=str(exc))
