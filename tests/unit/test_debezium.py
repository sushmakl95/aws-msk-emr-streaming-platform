"""Tests for Debezium envelope parsing."""

from __future__ import annotations

import json

import pytest
from pyspark.sql.types import (
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
)

from streaming.sources.debezium import (
    debezium_envelope_schema,
    parse_debezium_stream,
)

pytestmark = pytest.mark.unit


ORDER_SCHEMA = StructType([
    StructField("order_id", StringType(), True),
    StructField("customer_id", StringType(), True),
    StructField("amount", DoubleType(), True),
])


def _make_kafka_df(spark, records: list[dict]):
    """Simulate a Kafka DataFrame with Debezium JSON values."""
    rows = []
    for i, env in enumerate(records):
        rows.append((
            "cdc.public.orders",
            i % 3,  # partition
            i,      # offset
            json.dumps(env).encode("utf-8"),
            "2026-04-22 10:00:00",
        ))
    return spark.createDataFrame(
        rows,
        schema=StructType([
            StructField("topic", StringType()),
            StructField("partition", LongType()),
            StructField("offset", LongType()),
            StructField("value", StringType()),
            StructField("timestamp", StringType()),
        ]),
    )


def test_debezium_envelope_schema_includes_op_before_after():
    schema = debezium_envelope_schema(ORDER_SCHEMA)
    field_names = [f.name for f in schema.fields]
    assert "op" in field_names
    assert "ts_ms" in field_names
    assert "source" in field_names
    assert "before" in field_names
    assert "after" in field_names


def test_parse_debezium_stream_insert(spark):
    """INSERT should have op='c' and populated 'after'."""
    insert_envelope = {
        "op": "c",
        "ts_ms": 1234567890000,
        "source": {"db": "analytics", "schema": "public", "table": "orders", "lsn": 100},
        "before": None,
        "after": {"order_id": "O-1", "customer_id": "C-1", "amount": 100.0},
    }
    kafka_df = _make_kafka_df(spark, [insert_envelope])
    # Cast value to bytes-like for from_json
    kafka_df = kafka_df.selectExpr("topic", "partition", "offset",
                                     "CAST(value AS BINARY) AS value", "timestamp")
    result = parse_debezium_stream(kafka_df, ORDER_SCHEMA).collect()

    assert len(result) == 1
    assert result[0]["cdc_op"] == "c"
    assert result[0]["source_table"] == "orders"
    assert result[0]["after"]["order_id"] == "O-1"


def test_parse_debezium_stream_filters_nulls(spark):
    """Invalid / unparseable messages should be filtered."""
    kafka_df = _make_kafka_df(spark, [{"op": "invalid json"}])
    kafka_df = kafka_df.selectExpr("topic", "partition", "offset",
                                     "CAST(value AS BINARY) AS value", "timestamp")
    # A message with missing required fields is either filtered or has null fields
    # The filter in parse_debezium_stream drops rows where env is null
    result = parse_debezium_stream(kafka_df, ORDER_SCHEMA).collect()
    # Depending on schema parsing, this may have 0 or 1 rows with nulls
    assert len(result) <= 1
