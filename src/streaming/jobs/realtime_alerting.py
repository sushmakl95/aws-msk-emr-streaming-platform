"""Spark Structured Streaming: anomaly detection → WebSocket push.

Detects anomalous transaction amounts in real-time using stateful aggregation:
  - Track per-user rolling 1-hour transaction stats
  - Flag transactions > 3 std devs above user's recent mean
  - Push flagged transactions to WebSocket topic for live dashboards

Real-world analog: fraud detection, ops dashboards, real-time business alerting.
"""

from __future__ import annotations

import argparse

from pyspark.sql import functions as F
from pyspark.sql.types import (
    DoubleType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from streaming.sinks import WebSocketSink, WebSocketSinkConfig
from streaming.sources import KafkaSource, KafkaSourceConfig
from streaming.utils import get_logger, get_streaming_spark_session

log = get_logger(__name__, job="realtime-alerting")


TXN_SCHEMA = StructType([
    StructField("txn_id", StringType(), True),
    StructField("user_id", StringType(), True),
    StructField("amount", DoubleType(), True),
    StructField("merchant", StringType(), True),
    StructField("event_time", TimestampType(), True),
])


def run(args: argparse.Namespace) -> None:
    spark = get_streaming_spark_session(
        app_name="realtime-alerting",
        checkpoint_location=args.checkpoint_location,
    )

    kafka = KafkaSource(
        spark,
        KafkaSourceConfig(
            bootstrap_servers=args.bootstrap_servers,
            topics=["app.transactions"],
            starting_offsets="latest",
            use_iam_auth=not args.local,
        ),
    )

    txns = (
        kafka.read_stream()
        .select(F.from_json(F.col("value").cast("string"), TXN_SCHEMA).alias("t"))
        .select("t.*")
        .filter(F.col("event_time").isNotNull())
        .withWatermark("event_time", "5 minutes")
    )

    # Build per-user rolling stats in a 1-hour sliding window
    user_stats = (
        txns.groupBy(
            F.window(F.col("event_time"), "1 hour", "5 minutes").alias("window"),
            F.col("user_id"),
        )
        .agg(
            F.avg("amount").alias("avg_amount"),
            F.stddev("amount").alias("std_amount"),
            F.count("*").alias("txn_count"),
        )
        .select(
            F.col("user_id"),
            F.col("window.end").alias("window_end"),
            F.col("avg_amount"),
            F.col("std_amount"),
            F.col("txn_count"),
        )
    )

    # Stream-stream join: flag txns > 3 std devs above user's recent mean
    # Note: for production, the stats would come from a reference sink read
    # with broadcast or a state store. This is simplified for the portfolio.
    enriched_txns = txns.join(
        user_stats,
        on="user_id",
        how="left",
    )

    anomalies = (
        enriched_txns
        .filter(F.col("std_amount").isNotNull() & (F.col("std_amount") > 0))
        .filter(F.col("txn_count") >= 5)  # need enough history
        .withColumn(
            "z_score",
            (F.col("amount") - F.col("avg_amount")) / F.col("std_amount"),
        )
        .filter(F.abs(F.col("z_score")) > 3.0)
        .withColumn("alert_type", F.lit("anomalous_amount"))
        .withColumn("severity", F.lit("WARNING"))
        .withColumn(
            "user_targets",
            F.array(F.col("user_id"), F.lit("ops-team")),
        )
    )

    # Push to WebSocket broadcast topic
    ws_sink = WebSocketSink(WebSocketSinkConfig(
        name="websocket-alerts",
        bootstrap_servers=args.bootstrap_servers,
        broadcast_topic="ws-broadcast",
        use_iam_auth=not args.local,
    ))

    (anomalies.writeStream
     .foreachBatch(ws_sink.make_foreach_batch_fn())
     .option("checkpointLocation", f"{args.checkpoint_location}/alerts")
     .outputMode("append")
     .trigger(processingTime="10 seconds")
     .start())

    log.info("realtime_alerting_started")
    spark.streams.awaitAnyTermination()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap-servers", required=True)
    parser.add_argument("--checkpoint-location", required=True)
    parser.add_argument("--local", action="store_true")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
