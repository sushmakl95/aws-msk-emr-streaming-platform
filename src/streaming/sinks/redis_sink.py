"""ElastiCache Redis sink — hot state lookups.

Each record is written as a Redis hash under a composite key. TTL enforced
per-record for automatic eviction.

Note: called inside `foreachBatch`, so runs on the driver OR mapInPandas on
executors. For large batches, prefer mapInPandas; for simple cases, driver
collect is fine.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import redis
from pyspark.sql import DataFrame

from streaming.core.types import SinkConfig
from streaming.sinks.base import BaseSink, SinkBatchResult, extract_idempotency_token
from streaming.utils.logging_config import get_logger

log = get_logger(__name__, component="sink.redis")


@dataclass
class RedisSinkConfig(SinkConfig):
    """Redis-specific sink configuration."""
    host: str = "localhost"
    port: int = 6379
    password: str | None = None
    db: int = 0
    ssl: bool = True
    key_prefix: str = "streaming:"
    ttl_seconds: int = 3600
    key_field: str = "id"
    """Column name to use as the Redis key."""
    sink_type: str = "redis"
    properties: dict = field(default_factory=dict)


class RedisSink(BaseSink):
    def __init__(self, config: RedisSinkConfig):
        super().__init__(config)
        self.config: RedisSinkConfig = config
        self._client: redis.Redis | None = None

    def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis(
                host=self.config.host,
                port=self.config.port,
                password=self.config.password,
                db=self.config.db,
                ssl=self.config.ssl,
                decode_responses=False,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )
        return self._client

    def write_batch(self, batch_df: DataFrame, batch_id: int) -> SinkBatchResult:
        """Write batch via Redis pipeline for efficiency."""
        t0 = time.perf_counter()
        records = batch_df.toJSON().collect()
        written = 0
        failed = 0

        client = self._get_client()
        # Use pipeline to batch writes
        pipe = client.pipeline(transaction=False)
        for record_json in records:
            try:
                record = json.loads(record_json)
                key = (
                    f"{self.config.key_prefix}"
                    f"{record.get(self.config.key_field, extract_idempotency_token(record))}"
                )
                # Store as Redis hash for field-level access
                flat = {k: str(v) if v is not None else "" for k, v in record.items()}
                pipe.hset(key, mapping=flat)
                pipe.expire(key, self.config.ttl_seconds)
                written += 1
            except Exception as exc:
                log.warning("redis_record_failed", error=str(exc))
                failed += 1

        try:
            pipe.execute()
        except redis.RedisError as exc:
            log.error("redis_pipeline_failed", batch_id=batch_id, error=str(exc))
            failed += written
            written = 0

        duration_ms = int((time.perf_counter() - t0) * 1000)
        return SinkBatchResult(
            sink_name=self.config.name,
            batch_id=batch_id,
            records_written=written,
            records_failed=failed,
            duration_ms=duration_ms,
        )
