# Cost Analysis

Production deployment at moderate throughput (10K events/sec peak, 3K sustained) costs approximately **$1,800/month**. For local evaluation, use Docker Compose (free).

## Breakdown (us-east-1, April 2026)

| Resource | Config | $/month |
|---|---|---|
| **MSK cluster** | 3 × kafka.m5.xlarge + 500 GB EBS × 3 brokers | $430 |
| **MSK Connect** | 2 workers × 2 MCU + 2 workers × 2 MCU (S3 sink) | $145 |
| **EMR on EKS** | EKS cluster + managed node group (m5.xlarge × 2, spot) | $180 |
| **EMR Serverless** | ~4h/day at 4 vCPU + 16 GB mem | $60 |
| **Kinesis Data Streams** | 4 shards provisioned | $45 |
| **Flink / KDA** | 1 app × 4 KPU, 24/7 | $320 |
| **ElastiCache Redis** | cache.r7g.large × 2 (Multi-AZ) | $210 |
| **OpenSearch** | r6g.large × 3 + 100 GB EBS × 3 | $240 |
| **ECS ClickHouse** | 2 Fargate tasks × 4 vCPU / 16 GB + ALB | $155 |
| **DynamoDB** | PAY_PER_REQUEST for connections table (~10M requests/mo) | $12 |
| **Lambda** | 4 functions, ~2M invocations total | $8 |
| **API Gateway WebSocket** | 500K connections × 1 hr avg + 50M messages | $25 |
| **S3** | 5 buckets total ~2 TB (iceberg + cold archive + checkpoints) | $46 |
| **Secrets Manager** | 6 secrets × $0.40 | $3 |
| **KMS** | 8 CMKs + ~500K API calls | $12 |
| **SNS + CloudWatch** | logs 30d + 50 metrics + dashboard | $65 |
| **VPC** | 3 NAT Gateways (1 per AZ) | $96 |
| **Databricks (comparison workspace)** | i3.xlarge × 2, SPOT, ~4h/day | $55 |
| **Inter-AZ data transfer** | ~5 TB/month inter-AZ (MSK replication + cross-AZ reads) | $120 |

**Total: ~$1,825/month**

Most real deployments land $1,400-2,400 depending on throughput + retention.

## Cost drivers

**1. NAT Gateways (5%).** 3 NATs × $32/month + data transfer. Kept for high availability — not deployed per-AZ = outages during AZ failure. S3 + DynamoDB gateway endpoints save ~60% of NAT traffic.

**2. MSK broker storage (25%).** 500 GB × 3 brokers × $0.10/GB-month + inter-AZ replication = ~$180. Reducing retention is the cheapest lever — 3-day retention instead of 7 saves $100/month.

**3. Flink/KDA (18%).** 4 KPU × 24/7 × $0.11/KPU-hour = $320. KDA is priced like "always-on compute" — pauseable if workload is bursty.

**4. OpenSearch (13%).** 3 × r6g.large + 300 GB = $240. Switching to UltraWarm for anything > 30 days is 80% cheaper.

**5. Inter-AZ data transfer (7%).** MSK replication + cross-AZ reads. Each GB transferred between AZs costs $0.02. Keep producers + consumers in the same AZ when possible.

## Optimization playbook (20-30% reduction possible)

### Low-effort

- **Shorten retention on high-volume topics** (~$80/mo saved). Clickstream at 3-day retention instead of 7 halves the storage footprint.
- **LZ4 compression on all topics** (~$60/mo saved). 3-4× smaller on disk + wire.
- **Redis smaller nodes** (~$80/mo saved). `cache.r7g.large` may be overkill — start with `cache.r6g.medium` and scale up if memory pressure.
- **Shorter CloudWatch log retention in non-prod** (~$30/mo saved). 7 days in dev, 30 in staging, 90 in prod.
- **S3 Intelligent-Tiering on cold archive** (~$15/mo saved). Marginal but free.

### Medium-effort

- **Single NAT Gateway in dev/staging** (~$64/mo saved). High availability only matters in prod.
- **Use EMR Serverless instead of EMR on EKS for non-24/7 workloads** (~$100/mo saved). Bursty workloads benefit from auto-scale + auto-stop.
- **ClickHouse with SPOT Fargate** (~$40/mo saved). Requires handling restart gracefully.
- **Share MSK cluster across envs** (~$200/mo saved). Use separate topics per env; one cluster with resource quotas.

### High-effort

- **Right-size brokers** after 3 months of observation. Most teams start oversized.
- **Migrate cold archive to Glacier IR after 90 days** (~$20/mo saved). Lifecycle rules already deployed.
- **MSK Serverless** for bursty production workloads (~$100/mo saved). Pay per GB not per broker-hour. But no compaction support.
- **OpenSearch UltraWarm tier for old indices** (~$60/mo saved). Great for search-over-archive with 5-second query latency.

## What you must NOT skimp on

1. **MSK replication factor = 3, min.insync.replicas = 2.** Anything lower means you lose data on broker failure.
2. **Multi-AZ for Redis and MSK.** Single-AZ saves $50/month and costs you $50,000 in an outage.
3. **KMS CMKs per data layer.** $1/month each, blast-radius insurance.
4. **CloudWatch log retention on MSK + KDA.** 30 days is the minimum for forensic debugging of a production incident.

## Cost monitoring

Deployed automatically via `modules/monitoring`:
- **AWS Budget** with 80%/100% actual + 100% forecasted alerts
- **Cost anomaly detection** emails daily
- **Tagging** on every resource: `Project=streaming-platform`, `Environment`, `CostCenter`

Review via Cost Explorer monthly; filter by `tag:Project = streaming-platform`.

## Comparison: DIY vs managed streaming alternatives

| Option | $/month @ same scale | Trade-off |
|---|---|---|
| This platform (MSK + EMR + Flink) | $1,800 | Full control + both runtimes |
| Confluent Cloud + ksqlDB | ~$3,500 | Simpler ops, 2× cost |
| Redpanda Cloud + BYO compute | ~$2,400 | Kafka-compatible, fewer managed services |
| Databricks-only (using their managed Kafka) | ~$2,400 | One platform, vendor lock-in |
| AWS Kinesis-only (simpler AWS-native) | ~$1,100 | Shard limits force workarounds past 200K events/sec |

At our scale, this platform is 25-50% cheaper than managed streaming platforms while giving more flexibility. Break-even with Confluent Cloud is around 5K events/sec — below that, Confluent is simpler + cheaper.

## When NOT to deploy this

- **< 1K events/sec sustained**: Kinesis Data Streams (2 shards, $22/mo) handles it cheaper.
- **No real-time SLA** (batch every hour is fine): Glue or EMR batch jobs are 10× cheaper.
- **Single source, single sink, no CDC**: Kafka Connect on a single EC2 instance with native Kafka consumers is $20/month.

If any of the above, reconsider whether you need streaming at all — "real-time" dashboards that use data > 15 min old don't need streaming.
