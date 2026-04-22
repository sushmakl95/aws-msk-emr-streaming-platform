"""WebSocket sink — publishes broadcast events to a Kafka topic.

Architecture: the streaming job doesn't directly call API Gateway. It writes
to a Kafka topic (`ws-broadcast`) which triggers a Lambda via MSK-to-Lambda
event source mapping. The Lambda handles the actual API Gateway postToConnection
fan-out — see src/lambdas/ws_broadcast.py.

This decoupling:
  - Keeps streaming jobs stateless about connected clients
  - Scales broadcast independent of processing
  - Survives API Gateway throttling (Kafka buffers)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from confluent_kafka import Producer
from pyspark.sql import DataFrame

from streaming.core.types import SinkConfig
from streaming.sinks.base import BaseSink, SinkBatchResult
from streaming.utils.logging_config import get_logger

log = get_logger(__name__, component="sink.websocket")


@dataclass
class WebSocketSinkConfig(SinkConfig):
    """WebSocket sink configuration (writes to Kafka topic for Lambda fan-out)."""
    bootstrap_servers: str = ""
    broadcast_topic: str = "ws-broadcast"
    use_iam_auth: bool = True
    user_targets_field: str = "user_targets"
    """Field in the record that contains a list of user_ids to push to.
    Can be '*' for broadcast-to-all."""
    sink_type: str = "websocket"
    properties: dict = field(default_factory=dict)


class WebSocketSink(BaseSink):
    def __init__(self, config: WebSocketSinkConfig):
        super().__init__(config)
        self.config: WebSocketSinkConfig = config
        self._producer: Producer | None = None

    def _get_producer(self) -> Producer:
        if self._producer is None:
            producer_config = {
                "bootstrap.servers": self.config.bootstrap_servers,
                "acks": "all",
                "enable.idempotence": True,
                "linger.ms": 20,
                "batch.size": 32 * 1024,
                "compression.type": "lz4",
            }
            if self.config.use_iam_auth:
                producer_config.update({
                    "security.protocol": "SASL_SSL",
                    "sasl.mechanisms": "OAUTHBEARER",
                    "sasl.oauthbearer.config": "aws_msk_iam",
                })
            self._producer = Producer(producer_config)
        return self._producer

    def write_batch(self, batch_df: DataFrame, batch_id: int) -> SinkBatchResult:
        t0 = time.perf_counter()
        records = batch_df.toJSON().collect()
        written = 0
        failed = 0

        producer = self._get_producer()
        for record_json in records:
            try:
                record = json.loads(record_json)
                user_targets = record.get(self.config.user_targets_field, "*")
                msg = {
                    "user_targets": user_targets,
                    "payload": record,
                    "batch_id": batch_id,
                }
                producer.produce(
                    topic=self.config.broadcast_topic,
                    value=json.dumps(msg).encode("utf-8"),
                )
                written += 1
            except Exception as exc:
                log.warning("ws_produce_failed", error=str(exc))
                failed += 1

        producer.flush(timeout=10)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        return SinkBatchResult(
            sink_name=self.config.name,
            batch_id=batch_id,
            records_written=written,
            records_failed=failed,
            duration_ms=duration_ms,
        )
