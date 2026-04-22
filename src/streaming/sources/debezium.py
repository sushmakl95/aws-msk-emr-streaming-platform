"""Debezium CDC payload parser.

Converts raw Kafka messages from Debezium connectors into canonical
StreamEvent records with CDC op + before/after payloads.

Debezium message format (simplified):
  {
    "op": "c" | "u" | "d" | "r" | "t",
    "ts_ms": <epoch>,
    "source": {"db": "...", "schema": "...", "table": "..."},
    "before": {...} | null,
    "after": {...} | null
  }
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    LongType,
    StringType,
    StructField,
    StructType,
)


def debezium_envelope_schema(payload_schema: StructType) -> StructType:
    """Build the outer Debezium envelope schema.

    `payload_schema` is the schema of the actual row (before + after).
    """
    return StructType([
        StructField("op", StringType(), True),
        StructField("ts_ms", LongType(), True),
        StructField("source", StructType([
            StructField("db", StringType(), True),
            StructField("schema", StringType(), True),
            StructField("table", StringType(), True),
            StructField("lsn", LongType(), True),
            StructField("ts_ms", LongType(), True),
        ]), True),
        StructField("before", payload_schema, True),
        StructField("after", payload_schema, True),
    ])


def parse_debezium_stream(
    kafka_df: DataFrame,
    payload_schema: StructType,
) -> DataFrame:
    """Parse a raw Kafka stream (value: bytes) into a flat Debezium CDC stream.

    Output columns:
      - event_id   (source LSN or kafka offset fallback)
      - event_time (timestamp from source ts_ms)
      - cdc_op     (c/u/d/r/t)
      - source_db, source_schema, source_table
      - before     (struct — nullable)
      - after      (struct — nullable)
      - raw_offset, raw_partition, raw_topic
    """
    envelope_schema = debezium_envelope_schema(payload_schema)

    parsed = (
        kafka_df
        .select(
            F.col("topic").alias("raw_topic"),
            F.col("partition").alias("raw_partition"),
            F.col("offset").alias("raw_offset"),
            F.col("timestamp").alias("kafka_ts"),
            F.from_json(F.col("value").cast("string"), envelope_schema).alias("env"),
        )
        .filter(F.col("env").isNotNull())
        .select(
            F.coalesce(
                F.col("env.source.lsn").cast("string"),
                F.concat_ws(
                    ":",
                    F.col("raw_topic"),
                    F.col("raw_partition").cast("string"),
                    F.col("raw_offset").cast("string"),
                ),
            ).alias("event_id"),
            (F.col("env.ts_ms") / 1000).cast("timestamp").alias("event_time"),
            F.col("env.op").alias("cdc_op"),
            F.col("env.source.db").alias("source_db"),
            F.col("env.source.schema").alias("source_schema"),
            F.col("env.source.table").alias("source_table"),
            F.col("env.before").alias("before"),
            F.col("env.after").alias("after"),
            F.col("raw_offset"),
            F.col("raw_partition"),
            F.col("raw_topic"),
            F.col("kafka_ts"),
        )
    )

    return parsed
