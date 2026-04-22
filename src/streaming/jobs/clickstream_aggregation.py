"""Spark Structured Streaming: clickstream → sliding 5-min window aggregations → ClickHouse.

Demonstrates:
  - Session windowing (30-min gap) for session counts
  - Sliding window (5-min / 1-min) for rolling page-view counts
  - ClickHouse sink for real-time OLAP

Real-world analog: the kind of real-time dashboard backing a marketing attribution tool.
"""

from __future__ import annotations

import argparse

from pyspark.sql import functions as F
from pyspark.sql.types import (
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from streaming.sinks import ClickHouseSink, ClickHouseSinkConfig
from streaming.sources import KafkaSource, KafkaSourceConfig
from streaming.transforms import session_window, sliding_window
from streaming.utils import get_logger, get_streaming_spark_session

log = get_logger(__name__, job="clickstream-aggregation")


CLICK_SCHEMA = StructType([
    StructField("user_id", StringType(), True),
    StructField("session_id", StringType(), True),
    StructField("page_url", StringType(), True),
    StructField("referrer", StringType(), True),
    StructField("device_type", StringType(), True),
    StructField("country", StringType(), True),
    StructField("event_time", TimestampType(), True),
    StructField("page_load_ms", IntegerType(), True),
])


def run(args: argparse.Namespace) -> None:
    spark = get_streaming_spark_session(
        app_name="clickstream-aggregation",
        checkpoint_location=args.checkpoint_location,
    )

    # 1) Source
    kafka = KafkaSource(
        spark,
        KafkaSourceConfig(
            bootstrap_servers=args.bootstrap_servers,
            topics=["app.clickstream"],
            starting_offsets="latest",
            use_iam_auth=not args.local,
            max_offsets_per_trigger=100_000,
        ),
    )

    clicks = (
        kafka.read_stream()
        .select(
            F.from_json(F.col("value").cast("string"), CLICK_SCHEMA).alias("c")
        )
        .select("c.*")
        .filter(F.col("event_time").isNotNull())
    )

    # 2) Sliding window: 5-min rolling page views per country, updated every 1 min
    country_counts = sliding_window(
        df=clicks,
        event_time_col="event_time",
        window_duration="5 minutes",
        slide_duration="1 minute",
        group_cols=["country", "device_type"],
        aggregations={"*": "count", "page_load_ms": "avg"},
        watermark_delay="10 minutes",
    )

    # 3) Session window: per-user session counts (30-min inactivity gap)
    sessions = session_window(
        df=clicks,
        event_time_col="event_time",
        session_gap="30 minutes",
        group_cols=["user_id"],
        aggregations={"page_url": "count"},
        watermark_delay="30 minutes",
    ).withColumn(
        "session_duration_sec",
        (F.unix_timestamp("session_end") - F.unix_timestamp("session_start")),
    )

    # 4) Write to ClickHouse
    ch_windows = ClickHouseSink(ClickHouseSinkConfig(
        name="clickhouse-country-windows",
        host=args.clickhouse_host,
        port=args.clickhouse_port,
        database="analytics",
        target_table="country_page_views_5min",
        username=args.clickhouse_user,
        password=args.clickhouse_password,
    ))

    ch_sessions = ClickHouseSink(ClickHouseSinkConfig(
        name="clickhouse-sessions",
        host=args.clickhouse_host,
        port=args.clickhouse_port,
        database="analytics",
        target_table="user_sessions",
        username=args.clickhouse_user,
        password=args.clickhouse_password,
    ))

    (country_counts.writeStream
     .foreachBatch(ch_windows.make_foreach_batch_fn())
     .option("checkpointLocation", f"{args.checkpoint_location}/country-windows")
     .outputMode("update")
     .trigger(processingTime="30 seconds")
     .start())

    (sessions.writeStream
     .foreachBatch(ch_sessions.make_foreach_batch_fn())
     .option("checkpointLocation", f"{args.checkpoint_location}/sessions")
     .outputMode("append")
     .trigger(processingTime="1 minute")
     .start())

    log.info("clickstream_aggregation_started")
    spark.streams.awaitAnyTermination()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap-servers", required=True)
    parser.add_argument("--checkpoint-location", required=True)
    parser.add_argument("--clickhouse-host", required=True)
    parser.add_argument("--clickhouse-port", type=int, default=8443)
    parser.add_argument("--clickhouse-user", default="default")
    parser.add_argument("--clickhouse-password", default="")
    parser.add_argument("--local", action="store_true")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
