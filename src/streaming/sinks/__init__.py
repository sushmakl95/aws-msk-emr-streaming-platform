"""Stream sinks — Redis (hot), OpenSearch (search), ClickHouse (OLAP), S3 (cold), WebSocket."""

from streaming.sinks.base import BaseSink, SinkBatchResult, extract_idempotency_token
from streaming.sinks.clickhouse_sink import ClickHouseSink, ClickHouseSinkConfig
from streaming.sinks.opensearch_sink import OpenSearchSink, OpenSearchSinkConfig
from streaming.sinks.redis_sink import RedisSink, RedisSinkConfig
from streaming.sinks.s3_iceberg_sink import S3IcebergSink, S3IcebergSinkConfig
from streaming.sinks.websocket_sink import WebSocketSink, WebSocketSinkConfig

__all__ = [
    "BaseSink",
    "ClickHouseSink",
    "ClickHouseSinkConfig",
    "OpenSearchSink",
    "OpenSearchSinkConfig",
    "RedisSink",
    "RedisSinkConfig",
    "S3IcebergSink",
    "S3IcebergSinkConfig",
    "SinkBatchResult",
    "WebSocketSink",
    "WebSocketSinkConfig",
    "extract_idempotency_token",
]
