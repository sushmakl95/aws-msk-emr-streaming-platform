"""Spark session factory tuned for streaming workloads."""

from __future__ import annotations

import os

from pyspark.sql import SparkSession


def get_streaming_spark_session(
    app_name: str = "streaming-platform",
    master: str = "local[*]",
    checkpoint_location: str | None = None,
    extra_configs: dict | None = None,
) -> SparkSession:
    """Build a Spark session optimized for Structured Streaming.

    Key tunings vs batch:
      - AQE is enabled but NOT skew-join adjustment (expensive for micro-batches)
      - Shuffle partitions lower (8-16) to reduce per-batch overhead
      - Kryo serialization (faster than Java default for streaming)
      - Delta + Kafka packages auto-loaded
      - RocksDB state store (default on Databricks, opt-in elsewhere)
    """
    cores = os.cpu_count() or 4
    configs = {
        "spark.driver.memory": "4g",
        "spark.driver.bindAddress": "127.0.0.1",
        "spark.driver.host": "127.0.0.1",
        "spark.ui.enabled": "false",
        # Streaming-specific tunings
        "spark.sql.shuffle.partitions": str(min(cores * 2, 16)),
        "spark.sql.adaptive.enabled": "true",
        "spark.sql.adaptive.skewJoin.enabled": "false",
        "spark.sql.streaming.minBatchesToRetain": "10",
        "spark.sql.streaming.stateStore.providerClass": (
            "org.apache.spark.sql.execution.streaming.state.RocksDBStateStoreProvider"
        ),
        "spark.sql.streaming.stateStore.rocksdb.compactOnCommit": "true",
        "spark.sql.streaming.forceDeleteTempCheckpointLocation": "false",
        # Kafka + Delta
        "spark.jars.packages": ",".join([
            "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0",
            "io.delta:delta-spark_2.12:3.2.0",
        ]),
        # Serialization
        "spark.serializer": "org.apache.spark.serializer.KryoSerializer",
        "spark.kryoserializer.buffer.max": "512m",
        # Delta
        "spark.sql.extensions": "io.delta.sql.DeltaSparkSessionExtension",
        "spark.sql.catalog.spark_catalog": "org.apache.spark.sql.delta.catalog.DeltaCatalog",
    }
    if checkpoint_location:
        configs["spark.sql.streaming.checkpointLocation"] = checkpoint_location
    if extra_configs:
        configs.update(extra_configs)

    builder = SparkSession.builder.appName(app_name).master(master)
    for k, v in configs.items():
        builder = builder.config(k, str(v))

    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark
