# Architecture

## Core decisions

**1. MSK as the backbone, not Kinesis.** Kinesis Data Streams is simpler to operate but has per-shard write limits (1 MB/s / 1000 records/s) that become painful at high throughput. MSK with IAM auth gives us open-source Kafka semantics (consumer groups, compaction, transactions) with AWS-managed operations, and cross-region replication via MirrorMaker is well-understood. For the rare cases where Kinesis is genuinely better (tight AWS-native integrations, very low-throughput streams), we keep a Kinesis path as an alternate source — see `src/streaming/sources/kinesis.py`.

**2. Debezium for CDC, not DMS.** AWS Database Migration Service can do CDC but commits are rough (batch-oriented, not truly streaming), schema evolution is limited, and the output format is proprietary. Debezium produces a canonical CDC envelope (`op`, `before`, `after`, `source`) that downstream tools understand. It's battle-tested and extensible via SMTs. Running it under MSK Connect removes operational burden while keeping the open-source format.

**3. EMR on EKS *and* EMR Serverless, side-by-side.** They serve different needs:
   - **EMR on EKS**: long-running streaming jobs with sub-minute latency. Warm clusters. Good for 24/7 workloads.
   - **EMR Serverless**: batch/one-shot streaming jobs, or late-start streams. No cluster lifecycle to manage, but cold start is 60-90s.

You pick per workload. The dispatch layer (`src/streaming/orchestration/emr_submit.py`) abstracts the difference.

**4. Flink AND Spark, not one or the other.** Flink SQL beats Spark Structured Streaming at:
   - Sub-50ms end-to-end latency (Spark micro-batch is ~100ms floor)
   - Event-time windowing with complex late-arrival handling
   - Native CEP (pattern matching)

Spark Structured Streaming beats Flink at:
   - Python/PySpark ecosystem integration
   - Interop with Delta/Iceberg batch tables without serialization gymnastics
   - Familiar SQL + DataFrame API for SQL-first teams

We expose both runtimes on the same MSK backbone so teams use what fits their use case. See `docs/RUNTIME_COMPARISON.md` for real measurements.

**5. Hot/warm/cold sink fan-out, not one sink.** One sink per workload is an anti-pattern at scale. Different access patterns need different storage:
   - **Redis** for microsecond point lookups (user session, feature flags).
   - **OpenSearch** for full-text search + aggregations on the last 30 days.
   - **ClickHouse** for OLAP queries over millions of recent events.
   - **S3 + Iceberg** for unbounded history, accessible by Spark/Athena/Trino.

Streaming jobs fan out to all four simultaneously. Each has its own retention and idempotency.

**6. WebSocket push via Kafka, not direct API Gateway calls.** The streaming job writes to a Kafka topic (`ws-broadcast`); a Lambda reads the topic and handles postToConnection. This decouples processing speed from client connection count and insulates processing from API Gateway throttling.

**7. Databricks comparison track.** Same MSK topics, same Iceberg sinks, same logical transformations — implemented once on the Databricks runtime. Lets teams evaluate the TCO + operational trade-offs honestly on their workload.

## Component interaction

### The CDC path (Postgres → Iceberg)

```
Postgres commit
  → WAL advance
  → Debezium logical replication reader (running in MSK Connect)
  → Avro encoding via Glue Schema Registry
  → Publish to MSK topic cdc.public.orders
  → EMR Spark Streaming job consumes with IAM auth
  → Parse Debezium envelope (src/streaming/sources/debezium.py)
  → Broadcast-join with product catalog dim
  → foreachBatch → RedisSink + OpenSearchSink + S3IcebergSink
  → Commit Kafka offsets via Spark checkpoint
```

End-to-end latency: ~200-400ms P99 under normal load. Budget assumption: Debezium's poll interval (500ms) dominates.

### The state path (exactly-once)

See `docs/EXACTLY_ONCE.md`. In brief:
- Spark writes offsets BEFORE processing the batch.
- Sinks use idempotency tokens (LSN-derived) as keys.
- On crash + restart, Spark re-reads the same offsets; sink idempotency makes the retry a no-op.

### The WebSocket path

```
Client: wss://... connect
  → API Gateway WebSocket
  → $connect Lambda writes {conn_id, user_id, topics} to DynamoDB (TTL 24h)

Streaming job produces broadcast:
  → write to MSK topic ws-broadcast (key: user_id, value: payload)
  → MSK → Lambda event source mapping
  → ws_broadcast Lambda queries DynamoDB for matching connections
  → calls postToConnection for each active connection
  → on GoneException, deletes stale connection from registry

Client: wss:// disconnect
  → $disconnect Lambda removes {conn_id} from DynamoDB
```

## Trade-offs and known limitations

- **MSK cost floor**: ~$400/month for 3 kafka.m5.xlarge brokers. Can't go lower with managed MSK. For dev, use MSK Serverless or a self-hosted Kafka container.
- **MSK Connect IAM complexity**: connector configs contain static connection strings to source DBs — rotation via Secrets Manager is not native to MSK Connect. We document the workaround in `docs/MSK_OPERATIONS.md`.
- **EMR on EKS cold-start**: first job run on a fresh pod takes 60-90s. Mitigated by keeping warm by running a "ping" streaming query.
- **Flink/KDA vendor lock-in**: moving to open-source Flink requires re-deploying on EKS with checkpointing operator. Manageable but non-trivial.
- **ClickHouse on ECS has no auto-replication**: single-node default. Scale via Altinity Operator on EKS for prod multi-node — out of scope for this repo.
- **Watermark coordination across tracks**: EMR + Databricks + Flink all see the same MSK stream but advance watermarks independently. For exactly-once across tracks, use a single track.

## Why Iceberg instead of Delta

For the cold sink, we chose Iceberg because:
- **Athena-native**: Athena reads Iceberg tables directly without a separate catalog sync.
- **Cross-engine compatibility**: Spark, Flink, and Databricks all write to the same Iceberg table with coherent semantics as of Iceberg format-v2.
- **Hidden partitioning**: users don't need to know the partition strategy to write queries.

The one place we use Delta is inside Databricks for dim tables that stay "on Databricks." Everything cross-engine uses Iceberg.

## Capacity planning

See `docs/COST_ANALYSIS.md` for real numbers. The production baseline assumes:
- 10,000 events/second peak, ~3,000/second average
- 100 GB/day produced to MSK (with 7-day retention = ~700 GB broker storage)
- Per-sink retention: Redis 1h, OpenSearch 30 days, ClickHouse 90 days, S3 Iceberg unbounded
