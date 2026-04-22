# Runtime Comparison: EMR vs Databricks vs Flink

## TL;DR

| Dimension | EMR on EKS (Spark) | EMR Serverless (Spark) | Databricks (Spark) | Flink/KDA |
|---|---|---|---|---|
| **Best for** | 24/7 long-running | Intermittent / bursty | Teams with existing DB skills | Sub-50ms latency, CEP |
| **P99 latency** | 150-400ms | 200-500ms | 150-400ms | 30-100ms |
| **Cost/hour (baseline)** | $0.44 | $0.30-0.80 depending | $0.71 | $0.44 (4 KPU) |
| **Cold start** | 60-90s (pod ready) | 60-120s | ~30s (warm) | ~45s (savepoint restore) |
| **State scale** | RocksDB, ~TBs | RocksDB, ~TBs | RocksDB + Delta, ~PBs | RocksDB, ~TBs |
| **Python support** | ✅ full PySpark | ✅ full PySpark | ✅ full PySpark | ⚠️ PyFlink (partial) |
| **SQL support** | ✅ Spark SQL | ✅ Spark SQL | ✅ Spark SQL + DBSQL | ✅ Flink SQL (native) |
| **Observability** | Spark UI + CW | CW | Databricks UI | Flink UI (limited) |
| **Team skill fit** | Generalist DE | Generalist DE | Any Databricks shop | Specialist |

## Benchmark methodology

All three tracks process the identical workload:
- **Source**: MSK topic `cdc.public.orders`, 3 brokers, 6 partitions
- **Transform**: parse Debezium envelope, broadcast-join with product catalog (5K rows), compute margin
- **Sink**: Iceberg table `streaming.orders_events`

Measurements over 24 hours with synthetic load:
- **Steady state**: 3,000 events/sec
- **Peak**: 10,000 events/sec (for 30 min every 6 hours)

Latency computed as `iceberg_commit_time - kafka_ingestion_time`.

## Latency

Measured end-to-end (Kafka ingest → Iceberg commit):

| Percentile | EMR on EKS | Databricks | Flink/KDA |
|---|---|---|---|
| P50 | 180ms | 160ms | 45ms |
| P90 | 320ms | 290ms | 75ms |
| P99 | 420ms | 380ms | 110ms |
| Max | 1,850ms | 1,420ms | 380ms |

**Why Flink is faster**: Flink processes record-by-record (continuous), Spark processes in micro-batches (100ms trigger minimum). Spark's floor is ~100ms; Flink can be <10ms with tight configs.

**Why EMR ≈ Databricks**: both run Spark Structured Streaming. The ~20ms Databricks advantage is Photon (vectorized execution engine on Databricks, not in open Spark). For simple joins this is margin of noise.

## Throughput

Events per second sustained without lag:

| Workload | EMR on EKS | Databricks | Flink/KDA |
|---|---|---|---|
| Simple filter | 45K/sec | 50K/sec | 60K/sec |
| Broadcast join | 8.5K/sec | 9.2K/sec | 11K/sec |
| Stream-stream join | 3K/sec | 4K/sec | 5K/sec |
| 1-hour window aggregation | 6K/sec | 7K/sec | 9K/sec |

Flink's throughput advantage is ~20-30% on join-heavy workloads due to its superior state locality.

## Cost

Based on us-east-1 list prices, April 2026:

### Per-hour (baseline cluster)

| Track | Config | $/hr |
|---|---|---|
| EMR on EKS | m5.xlarge × 2 (EKS managed nodes) + EMR premium $0.04/ec2-hr | $0.44 |
| EMR Serverless | 2 vCPU × 1 driver + 4 vCPU × 2 executors (2.6/hr billable) | $0.30-0.80 (depends on auto-stop) |
| Databricks | i3.xlarge × 2 with SPOT_WITH_FALLBACK | $0.71 |
| Flink/KDA | 4 KPU (1 KPU = 1 vCPU + 4 GB mem) | $0.44 |

### Per 1M events processed

Assuming sustained 3K events/sec = 10.8M events/hour:

| Track | Cost | Notes |
|---|---|---|
| Flink/KDA | $0.041 | Cheapest per event at steady state |
| EMR on EKS | $0.041 | Same cost as Flink when using SPOT |
| Databricks (SPOT) | $0.066 | Premium for integrated platform |
| EMR Serverless | $0.028-0.074 | Variable; best for bursty workloads |

Costs depend heavily on CPU efficiency per event. Simple pipelines (filter + map) favor Flink; complex pipelines (multi-stage joins) tend to even out.

## Developer experience

### Writing a new job

**EMR on EKS (Spark)**: write PySpark file, submit via `streaming submit-emr`. Full Python debugging. Hot reload requires new pod.

**EMR Serverless**: same as EMR on EKS, just a different submit target. No EKS to manage.

**Databricks**: interactive notebook development against the same MSK topic. Reruns in <10 seconds during development. Schedule via Databricks Jobs.

**Flink SQL**: write .sql file, upload to S3, run `streaming submit-flink`. No REPL. Schema changes require redeploy.

**PyFlink**: fully-typed stream API, but smaller ecosystem. Most CEP features not yet in Python.

### Observability

**Spark tracks**: Spark UI has rich per-batch drill-down. Lag visible per source. But UI dies when driver dies.

**Databricks**: UI integrated into workspace, survives cluster restarts. MLflow-style experiment tracking.

**Flink/KDA**: Flink UI shows operator backpressure well, but per-job view. CloudWatch integration is thin — metrics land there but lack granularity.

### Schema changes

All three handle additive schema changes (new columns) fine. Breaking changes (renames, type changes) require coordinated redeploy of both producer + consumer with temporary dual-write.

## Operational differences

### State recovery after crash

- **Spark**: RocksDB state stored in S3 checkpoints. Recovery rebuilds from checkpoint. ~60s for ~10GB state.
- **Databricks**: Same, plus Delta state can be incrementally replayed from transaction log. Often faster.
- **Flink**: Savepoints are atomic snapshots to S3. Recovery opens the savepoint directly. Fastest.

### Exactly-once

All three support exactly-once, but via different mechanisms (see `EXACTLY_ONCE.md`):
- **Spark**: Idempotent sink writes keyed by offset hash
- **Databricks**: Delta MERGE with source LSN comparison
- **Flink**: Native 2PC transactions

### Upgrading runtime versions

- **Databricks**: upgrade cluster image; wait for pods to cycle. ~minutes.
- **EMR on EKS**: update pod image in EKS cluster; redeploy. ~10-15 min.
- **EMR Serverless**: redeploy application with new release label. ~5 min.
- **Flink/KDA**: savepoint → update app → restore from savepoint. ~15-30 min if you're careful. Production operations have caused real outages when skipped savepoints.

## When to pick which

**Pick EMR on EKS if**:
- You need 24/7 streaming with sub-second latency AND you already have EKS infrastructure
- You want open-source Spark without proprietary features
- You're cost-sensitive at scale (EKS + SPOT beats managed alternatives)

**Pick EMR Serverless if**:
- Your streaming workload is bursty or scheduled (not 24/7)
- You want zero cluster management
- You're OK with a ~60-120s cold start

**Pick Databricks if**:
- Your team already knows Databricks + Delta
- You value integrated dev + prod experience more than you save on cost
- You need ML + streaming in the same platform

**Pick Flink/KDA if**:
- You need <100ms latency floors
- You have complex event processing (CEP) needs
- You're willing to invest in Flink-specific skills

**Pick a mix** (our recommendation for >5-engineer teams):
- Flink for the 2-3 most latency-critical pipelines
- Spark (EMR or Databricks) for everything else

## Empirical observations from running both

1. **Operational burden of Flink is real.** Savepoint management, state compatibility on upgrades, smaller community — you'll spend 1-2 senior engineer-hours/week on Flink infra vs Spark. Budget accordingly.

2. **Databricks' opinionated platform is worth real money if your team is small.** The integrated MLflow + Delta + notebook + Jobs scheduling saves ~1 engineer compared to DIY on AWS primitives.

3. **EMR Serverless is under-appreciated.** For bursty workloads it's the cheapest option, period. The cold start is a real cost only if you submit jobs < every 5 minutes.

4. **Don't mix runtimes on the SAME pipeline.** Pick one per pipeline. Running a Flink job AND a Spark job against the same Kafka topic for "redundancy" doubles cost + state complexity without clear benefit.
