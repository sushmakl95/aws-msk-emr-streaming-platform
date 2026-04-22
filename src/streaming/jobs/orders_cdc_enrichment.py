"""Spark Structured Streaming job: orders CDC → enriched → sinks.

Flow:
    MSK topic (cdc.public.orders)
      → parse Debezium envelope
      → broadcast-join with product catalog
      → fan-out to Redis (hot) + OpenSearch (warm) + S3 Iceberg (cold)

Submit to EMR on EKS:
    spark-submit \\
      --master k8s://<emr-eks-endpoint> \\
      --name orders-cdc-enrichment \\
      --conf spark.kubernetes.container.image=<ecr-uri>:latest \\
      src/streaming/jobs/orders_cdc_enrichment.py \\
      --bootstrap-servers <msk-brokers> \\
      --checkpoint-location s3://.../checkpoints/orders-cdc-enrichment/ \\
      --redis-host <elasticache-endpoint> \\
      --opensearch-endpoint <os-endpoint> \\
      --iceberg-table glue_catalog.streaming.orders_events
"""

from __future__ import annotations

import argparse
from typing import Any

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from streaming.sinks import (
    OpenSearchSink,
    OpenSearchSinkConfig,
    RedisSink,
    RedisSinkConfig,
    S3IcebergSink,
    S3IcebergSinkConfig,
)
from streaming.sources import KafkaSource, KafkaSourceConfig, parse_debezium_stream
from streaming.transforms import broadcast_enrich
from streaming.utils import get_logger, get_streaming_spark_session

log = get_logger(__name__, job="orders-cdc-enrichment")


ORDER_PAYLOAD_SCHEMA = StructType([
    StructField("order_id", StringType(), True),
    StructField("customer_id", StringType(), True),
    StructField("product_id", StringType(), True),
    StructField("qty", LongType(), True),
    StructField("total_amount", DoubleType(), True),
    StructField("currency", StringType(), True),
    StructField("order_ts", TimestampType(), True),
])


def run(args: argparse.Namespace) -> None:
    spark = get_streaming_spark_session(
        app_name="orders-cdc-enrichment",
        checkpoint_location=args.checkpoint_location,
    )

    # 1) Read CDC from MSK
    kafka_source = KafkaSource(
        spark,
        KafkaSourceConfig(
            bootstrap_servers=args.bootstrap_servers,
            topics=["cdc.public.orders"],
            starting_offsets="latest",
            use_iam_auth=not args.local,
            max_offsets_per_trigger=50_000,
        ),
    )
    raw_stream = kafka_source.read_stream()

    # 2) Parse Debezium envelope
    cdc_stream = parse_debezium_stream(raw_stream, ORDER_PAYLOAD_SCHEMA)

    # 3) Filter to create/update ops, flatten `after` payload
    orders_stream = (
        cdc_stream
        .filter(F.col("cdc_op").isin("c", "u", "r"))
        .select(
            F.col("event_id"),
            F.col("event_time"),
            F.col("cdc_op"),
            F.col("after.order_id").alias("order_id"),
            F.col("after.customer_id").alias("customer_id"),
            F.col("after.product_id").alias("product_id"),
            F.col("after.qty").alias("qty"),
            F.col("after.total_amount").alias("total_amount"),
            F.col("after.currency").alias("currency"),
            F.col("after.order_ts").alias("order_ts"),
            F.col("raw_topic"),
            F.col("raw_partition"),
            F.col("raw_offset"),
        )
    )

    # 4) Broadcast-enrich with product catalog (refreshed at job startup)
    product_dim = spark.read.format("delta").load(args.product_dim_path)
    enriched = broadcast_enrich(
        stream_df=orders_stream,
        dim_df=product_dim,
        join_key="product_id",
        dim_cols=["product_name", "category", "brand", "unit_cost"],
        join_type="left",
    )

    # Add margin calculation
    final = enriched.withColumn(
        "margin_amount",
        F.col("total_amount") - (F.col("qty") * F.col("unit_cost")),
    )

    # 5) Fan out to sinks
    _start_sink(
        final, "redis",
        RedisSink(RedisSinkConfig(
            name="redis-orders-hot",
            host=args.redis_host,
            port=args.redis_port,
            key_prefix="order:",
            key_field="order_id",
            ttl_seconds=3600,
            ssl=not args.local,
        )),
        args.checkpoint_location,
    )

    _start_sink(
        final, "opensearch",
        OpenSearchSink(OpenSearchSinkConfig(
            name="opensearch-orders",
            endpoint=args.opensearch_endpoint,
            aws_region=args.region,
            index_pattern="orders-{yyyy_mm_dd}",
            timestamp_field="order_ts",
        )),
        args.checkpoint_location,
    )

    _start_sink(
        final, "s3-iceberg",
        S3IcebergSink(S3IcebergSinkConfig(
            name="s3-orders-cold",
            database="streaming",
            table="orders_events",
            s3_warehouse=args.iceberg_warehouse,
            partition_by=["event_date"],
        )),
        args.checkpoint_location,
    )

    log.info("orders_cdc_enrichment_started")
    spark.streams.awaitAnyTermination()


def _start_sink(
    df: DataFrame,
    sink_id: str,
    sink: Any,
    base_checkpoint: str,
) -> None:
    (
        df.writeStream
        .foreachBatch(sink.make_foreach_batch_fn())
        .option("checkpointLocation", f"{base_checkpoint}/{sink_id}")
        .outputMode("append")
        .trigger(processingTime="5 seconds")
        .start()
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap-servers", required=True)
    parser.add_argument("--checkpoint-location", required=True)
    parser.add_argument("--product-dim-path", required=True)
    parser.add_argument("--redis-host", required=True)
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--opensearch-endpoint", required=True)
    parser.add_argument("--iceberg-warehouse", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--local", action="store_true", help="Skip IAM auth for local dev")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
