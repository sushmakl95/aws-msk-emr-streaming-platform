# Databricks notebook source
# MAGIC %md
# MAGIC # DLT Pipeline: Orders CDC Bronze → Silver → Gold
# MAGIC
# MAGIC Delta Live Tables implementation of the same orders CDC workload, using
# MAGIC DLT's expectations + Auto-compaction + medallion architecture.
# MAGIC
# MAGIC Compare with the plain Structured Streaming notebook
# MAGIC (`01_orders_cdc_comparison`) to see DLT's auto-tuning + built-in DQ.

# COMMAND ----------

import dlt
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
    StructField("order_id", StringType()),
    StructField("customer_id", StringType()),
    StructField("product_id", StringType()),
    StructField("qty", LongType()),
    StructField("total_amount", DoubleType()),
    StructField("currency", StringType()),
    StructField("order_ts", TimestampType()),
])

DEBEZIUM_SCHEMA = StructType([
    StructField("op", StringType()),
    StructField("ts_ms", LongType()),
    StructField("source", StructType([
        StructField("lsn", LongType()),
    ])),
    StructField("after", ORDER_SCHEMA),
])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Bronze: raw CDC from MSK

# COMMAND ----------

@dlt.table(
    name="orders_cdc_bronze",
    comment="Raw Debezium CDC envelope for orders table",
    table_properties={"quality": "bronze"},
)
def orders_cdc_bronze():
    return (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", spark.conf.get("msk.bootstrap"))
        .option("subscribe", "cdc.public.orders")
        .option("kafka.security.protocol", "SASL_SSL")
        .option("kafka.sasl.mechanism", "AWS_MSK_IAM")
        .option("kafka.sasl.jaas.config",
                "software.amazon.msk.auth.iam.IAMLoginModule required;")
        .option("kafka.sasl.client.callback.handler.class",
                "software.amazon.msk.auth.iam.IAMClientCallbackHandler")
        .load()
        .select(
            F.from_json(F.col("value").cast("string"), DEBEZIUM_SCHEMA).alias("env"),
            F.col("timestamp").alias("kafka_ts"),
        )
    )


# COMMAND ----------

# MAGIC %md
# MAGIC ## Silver: parsed + DQ enforced

# COMMAND ----------

@dlt.table(
    name="orders_cdc_silver",
    comment="Parsed orders with DQ rules enforced",
    table_properties={"quality": "silver"},
)
@dlt.expect_or_drop("valid_op", "env.op IN ('c', 'u', 'r')")
@dlt.expect_or_drop("order_id_not_null", "env.after.order_id IS NOT NULL")
@dlt.expect("amount_positive", "env.after.total_amount > 0")
@dlt.expect("currency_valid", "env.after.currency IN ('USD', 'EUR', 'GBP', 'JPY')")
def orders_cdc_silver():
    return (
        dlt.read_stream("orders_cdc_bronze")
        .filter(F.col("env").isNotNull())
        .select(
            F.col("env.after.order_id").alias("order_id"),
            F.col("env.after.customer_id").alias("customer_id"),
            F.col("env.after.product_id").alias("product_id"),
            F.col("env.after.qty").alias("qty"),
            F.col("env.after.total_amount").alias("total_amount"),
            F.col("env.after.currency").alias("currency"),
            F.col("env.after.order_ts").alias("order_ts"),
            (F.col("env.ts_ms") / 1000).cast("timestamp").alias("event_time"),
        )
    )


# COMMAND ----------

# MAGIC %md
# MAGIC ## Gold: enriched with product catalog

# COMMAND ----------

@dlt.table(
    name="orders_cdc_gold",
    comment="Enriched orders with product margin",
    table_properties={"quality": "gold"},
    partition_cols=["event_date"],
)
def orders_cdc_gold():
    product_dim = spark.read.table("catalog.dims.products")
    return (
        dlt.read_stream("orders_cdc_silver")
        .join(
            F.broadcast(
                product_dim.select("product_id", "product_name", "category", "unit_cost")
            ),
            on="product_id",
            how="left",
        )
        .withColumn(
            "margin_amount",
            F.col("total_amount") - (F.col("qty") * F.col("unit_cost")),
        )
        .withColumn("event_date", F.to_date(F.col("order_ts")))
    )
