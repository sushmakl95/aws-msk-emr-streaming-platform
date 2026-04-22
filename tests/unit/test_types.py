"""Tests for core streaming types."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from streaming.core.types import (
    CdcOp,
    DeliverySemantic,
    SinkConfig,
    SourceType,
    StreamEvent,
)

pytestmark = pytest.mark.unit


def test_stream_event_lag_ms_computed_from_event_and_ingestion_time():
    now = datetime.now(UTC)
    event_time = now - timedelta(milliseconds=500)
    evt = StreamEvent(
        event_id="evt-1",
        source_type=SourceType.KAFKA,
        source_topic="test",
        partition=0,
        offset=100,
        event_time=event_time,
        ingestion_time=now,
    )
    assert 450 <= evt.lag_ms <= 550  # allow some clock skew


def test_stream_event_is_cdc_true_for_debezium_source():
    evt = StreamEvent(
        event_id="evt-1",
        source_type=SourceType.CDC_DEBEZIUM,
        source_topic="cdc.public.orders",
        partition=0,
        offset=100,
        event_time=datetime.now(UTC),
        cdc_op=CdcOp.UPDATE,
    )
    assert evt.is_cdc


def test_stream_event_is_cdc_false_for_kafka_source():
    evt = StreamEvent(
        event_id="evt-1",
        source_type=SourceType.KAFKA,
        source_topic="app.events",
        partition=0,
        offset=100,
        event_time=datetime.now(UTC),
    )
    assert not evt.is_cdc


def test_cdc_op_values_match_debezium():
    """Debezium uses these exact values in the envelope."""
    assert CdcOp.CREATE.value == "c"
    assert CdcOp.UPDATE.value == "u"
    assert CdcOp.DELETE.value == "d"
    assert CdcOp.READ.value == "r"
    assert CdcOp.TRUNCATE.value == "t"


def test_sink_config_defaults():
    cfg = SinkConfig(name="test-sink", sink_type="redis")
    assert cfg.delivery_semantic == DeliverySemantic.AT_LEAST_ONCE
    assert cfg.batch_size == 1000
    assert cfg.error_tolerance_pct == 0.0
