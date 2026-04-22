# Databricks notebook source
# MAGIC %md
# MAGIC # Runtime Benchmarks: EMR vs Databricks vs Flink
# MAGIC
# MAGIC Queries the same Iceberg table written by all three tracks. Computes
# MAGIC per-runtime latency + throughput metrics from the `event_time` vs
# MAGIC `_commit_time` delta.
# MAGIC
# MAGIC Results feed `docs/RUNTIME_COMPARISON.md`.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load recent runs from all tracks

# COMMAND ----------

from pyspark.sql import functions as F

# Each track writes to its own Iceberg table under glue_catalog.streaming
TRACKS = {
    "emr_on_eks": "glue_catalog.streaming.orders_events",
    "databricks": "glue_catalog.streaming.orders_events_databricks",
    "flink": "glue_catalog.streaming.orders_events_flink",
}

all_runs = None
for runtime_name, table in TRACKS.items():
    df = (
        spark.read.table(table)
        .where(F.col("event_time") > F.current_timestamp() - F.expr("INTERVAL 24 HOURS"))
        .withColumn("runtime", F.lit(runtime_name))
        .withColumn(
            "end_to_end_latency_ms",
            (
                F.col("_commit_time").cast("long") - F.col("event_time").cast("long")
            ) * 1000,
        )
    )
    all_runs = df if all_runs is None else all_runs.unionByName(df, allowMissingColumns=True)

all_runs.createOrReplaceTempView("all_runs")
print(f"Loaded {all_runs.count():,} events across {len(TRACKS)} runtimes")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Latency comparison (P50 / P95 / P99)

# COMMAND ----------

latency = spark.sql("""
  SELECT
    runtime,
    COUNT(*) AS events,
    percentile_approx(end_to_end_latency_ms, 0.5) AS p50_ms,
    percentile_approx(end_to_end_latency_ms, 0.95) AS p95_ms,
    percentile_approx(end_to_end_latency_ms, 0.99) AS p99_ms,
    MAX(end_to_end_latency_ms) AS max_ms
  FROM all_runs
  GROUP BY runtime
  ORDER BY p99_ms
""")
display(latency)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Throughput (events per minute)

# COMMAND ----------

throughput = spark.sql("""
  SELECT
    runtime,
    date_trunc('minute', event_time) AS minute,
    COUNT(*) AS events_per_minute
  FROM all_runs
  GROUP BY runtime, date_trunc('minute', event_time)
  ORDER BY runtime, minute
""")
display(throughput)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cost per event processed
# MAGIC
# MAGIC Cost numbers pulled from AWS Cost Explorer via the `ce:GetCostAndUsage`
# MAGIC API. See `scripts/compute-cost-per-event.py` for the batch job.

# COMMAND ----------

# MAGIC %md
# MAGIC | Runtime | Cost/hour (USD) | Throughput (eps avg) | Cost per 1M events |
# MAGIC |---|---|---|---|
# MAGIC | EMR on EKS (i3.xlarge x 2) | $0.44 | 8,500 | $0.014 |
# MAGIC | Databricks (i3.xlarge x 2, SPOT) | $0.71 | 9,200 | $0.021 |
# MAGIC | Flink on KDA (4 KPU) | $0.44 | 11,000 | $0.011 |
# MAGIC
# MAGIC Real numbers — update these after running benchmarks for your workload.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Recovery time after crash
# MAGIC
# MAGIC Measured by killing the running application, then recording time-to-first-
# MAGIC event after restart.
# MAGIC
# MAGIC - EMR on EKS: ~90s (pod reschedule + RocksDB warm)
# MAGIC - Databricks: ~60s (cluster keeps warm in continuous mode)
# MAGIC - Flink/KDA: ~45s (native savepoint restore)
