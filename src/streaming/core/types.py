"""Core streaming types: StreamEvent, Checkpoint, Watermark.

These are the shared vocabulary for all streaming jobs across Spark + Flink +
Databricks tracks. Any pipeline in this platform deals in these types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class CdcOp(str, Enum):
    """CDC operation types - matches Debezium's `op` field."""
    CREATE = "c"
    UPDATE = "u"
    DELETE = "d"
    READ = "r"  # Initial snapshot
    TRUNCATE = "t"


class SourceType(str, Enum):
    """Where the event came from."""
    KAFKA = "kafka"
    KINESIS = "kinesis"
    CDC_DEBEZIUM = "cdc_debezium"
    APP_EVENT = "app_event"


class DeliverySemantic(str, Enum):
    """Message delivery guarantee."""
    AT_MOST_ONCE = "at_most_once"
    AT_LEAST_ONCE = "at_least_once"
    EXACTLY_ONCE = "exactly_once"


@dataclass
class StreamEvent:
    """Canonical wrapper for any event flowing through the platform.

    Sources produce these; transforms consume + produce these; sinks persist
    them. Gives us one type system across Kafka + Kinesis + app events.
    """

    event_id: str
    """Unique identifier. For CDC: source LSN or timestamp + pk."""

    source_type: SourceType
    source_topic: str
    """e.g., 'cdc.public.orders' or 'kinesis:app-events'"""

    partition: int
    offset: int
    """For Kafka: offset within partition. For Kinesis: sequence number."""

    event_time: datetime
    """When the event occurred in the source system."""

    ingestion_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    """When the platform received the event."""

    key: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)

    # CDC-specific
    cdc_op: CdcOp | None = None
    cdc_before: dict[str, Any] | None = None
    cdc_after: dict[str, Any] | None = None

    @property
    def is_cdc(self) -> bool:
        return self.source_type == SourceType.CDC_DEBEZIUM

    @property
    def lag_ms(self) -> int:
        """Time between event occurrence and platform ingestion."""
        return int((self.ingestion_time - self.event_time).total_seconds() * 1000)


@dataclass
class Checkpoint:
    """Streaming checkpoint - used for exactly-once + restart."""
    job_id: str
    batch_id: int
    offsets: dict[str, dict[int, int]]
    """{topic: {partition: offset}}"""
    state_snapshot_path: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Watermark:
    """Event-time watermark advance.

    Represents the platform's confidence that no event with event_time <= this
    watermark will arrive in the future.
    """
    timestamp: datetime
    source: str
    """Which stream this watermark is for."""
    allowed_lateness_ms: int = 60_000
    """How late an event can arrive before being considered lost."""


@dataclass
class SinkRecord:
    """Record written to a terminal sink (Redis, OpenSearch, etc.)."""
    sink_name: str
    key: str
    value: dict[str, Any]
    event_time: datetime
    """Used for TTL + retention in the sink."""
    idempotency_token: str
    """Used by the sink to deduplicate on replay."""


@dataclass
class SinkConfig:
    """Abstract sink configuration - concrete subclasses per sink type."""
    name: str
    sink_type: str  # 'redis', 'opensearch', 'clickhouse', 's3', 'websocket'
    delivery_semantic: DeliverySemantic = DeliverySemantic.AT_LEAST_ONCE
    batch_size: int = 1000
    flush_interval_ms: int = 100
    max_in_flight: int = 5
    error_tolerance_pct: float = 0.0
    """Acceptable error rate before halting the stream."""
    properties: dict[str, Any] = field(default_factory=dict)
