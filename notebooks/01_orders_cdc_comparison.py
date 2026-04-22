# Databricks notebook source
# MAGIC %md
# MAGIC # Orders CDC — Databricks Streaming (Comparison Track)
# MAGIC
# MAGIC Identical workload to `src/streaming/jobs/orders_cdc_enrichment.py` running
# MAGIC on the EMR track. Reads the same MSK topic, writes to the same Iceberg
# MAGIC table. Use this to measure the runtime differences documented in
# MAGIC `docs/RUNTIME_COMPARISON.md`.
# MAGIC
# MAGIC Cluster: i3.xlarge x 2 (SPOT_WITH_FALLBACK)
# MAGIC Parameters (from the Databricks Job):
# MAGIC   - `msk_bootstrap_servers`
# MAGIC   - `iceberg_warehouse_s3`

# COMMAND ----------

dbutils.widgets.text("msk_bootstrap_servers", "", "MSK bootstrap servers")
dbutils.widgets.text("iceberg_warehouse_s3", "", "Iceberg warehouse bucket")

bootstrap = dbutils.widgets.get("msk_bootstrap_servers")
warehouse = dbutils.widgets.get("iceberg_warehouse_s3")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read CDC from MSK (via the same IAM auth as EMR path)

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import (
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

ORDER_SCHEMA = StructType([
    StructField("order_id", StringType(), True),
    StructField("customer_id", StringType(), True),
    StructField("product_id", StringType(), True),
    StructField("qty", LongType(), True),
    StructField("total_amount", DoubleType(), True),
    StructField("currency", StringType(), True),
    StructField("order_ts", TimestampType(), True),
])

DEBEZIUM_SCHEMA = StructType([
    StructField("op", StringType()),
    StructField("ts_ms", LongType()),
    StructField("source", StructType([
        StructField("db", StringType()),
        StructField("table", StringType()),
        StructField("lsn", LongType()),
    ])),
    StructField("before", ORDER_SCHEMA),
    StructField("after", ORDER_SCHEMA),
])

raw = (
    spark.readStream
    .format("kafka")
    .option("kafka.bootstrap.servers", bootstrap)
    .option("subscribe", "cdc.public.orders")
    .option("startingOffsets", "latest")
    .option("kafka.security.protocol", "SASL_SSL")
    .option("kafka.sasl.mechanism", "AWS_MSK_IAM")
    .option("kafka.sasl.jaas.config",
            "software.amazon.msk.auth.iam.IAMLoginModule required;")
    .option("kafka.sasl.client.callback.handler.class",
            "software.amazon.msk.auth.iam.IAMClientCallbackHandler")
    .load()
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Parse + filter to creates/updates

# COMMAND ----------

parsed = (
    raw.select(
        F.from_json(F.col("value").cast("string"), DEBEZIUM_SCHEMA).alias("env"),
        F.col("timestamp").alias("kafka_ts"),
    )
    .filter(F.col("env").isNotNull())
    .filter(F.col("env.op").isin("c", "u", "r"))
    .select(
        F.col("env.after.order_id").alias("order_id"),
        F.col("env.after.customer_id").alias("customer_id"),
        F.col("env.after.product_id").alias("product_id"),
        F.col("env.after.qty").alias("qty"),
        F.col("env.after.total_amount").alias("total_amount"),
        F.col("env.after.currency").alias("currency"),
        F.col("env.after.order_ts").alias("order_ts"),
        (F.col("env.ts_ms") / 1000).cast("timestamp").alias("event_time"),
        F.col("env.source.lsn").alias("source_lsn"),
    )
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Enrich with product catalog (Delta) and write to Iceberg

# COMMAND ----------

# Using Delta instead of Iceberg for the dim (native Databricks)
# Iceberg would also work with the `iceberg` catalog configured in the cluster
product_dim = spark.read.format("delta").load(f"s3://{warehouse}/dims/products/")
enriched = parsed.join(
    F.broadcast(product_dim.select("product_id", "product_name", "category", "unit_cost")),
    on="product_id",
    how="left",
).withColumn(
    "margin_amount",
    F.col("total_amount") - (F.col("qty") * F.col("unit_cost")),
).withColumn(
    "event_date", F.to_date(F.col("order_ts"))
)

# Write to Iceberg (shared with EMR track for side-by-side comparison)
(
    enriched.writeStream
    .format("iceberg")
    .option("catalog", "glue_catalog")
    .option("path", "glue_catalog.streaming.orders_events_databricks")
    .option(
        "checkpointLocation",
        f"s3://{warehouse}/checkpoints/databricks/orders_cdc/",
    )
    .outputMode("append")
    .trigger(processingTime="5 seconds")
    .start()
    .awaitTermination()
)
