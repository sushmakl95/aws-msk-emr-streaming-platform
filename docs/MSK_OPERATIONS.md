# MSK Operations Guide

## Cluster sizing

### Baseline (< 50K events/sec, < 1TB/day)

```hcl
msk_broker_count         = 3
msk_broker_instance_type = "kafka.m5.xlarge"  # 4 vCPU, 16 GB RAM
msk_ebs_volume_size_gb   = 500                 # 1.5 TB cluster, 7-day retention
```
Cost: ~$400/month.

### Medium (50-200K events/sec, 1-10 TB/day)

```hcl
msk_broker_count         = 6
msk_broker_instance_type = "kafka.m5.2xlarge"  # 8 vCPU, 32 GB RAM
msk_ebs_volume_size_gb   = 1000
```
Cost: ~$1,200/month.

### Large (> 200K events/sec, > 10 TB/day)

Consider **MSK Provisioned with tiered storage** or **MSK Serverless**:
- Tiered storage: old data (> 24h) moves to S3 automatically
- Serverless: pay per GB, scales brokers transparently

## Topic design

### Naming convention

```
<source>.<domain>.<table>    e.g., cdc.public.orders
<source>.<purpose>           e.g., app.clickstream, app.transactions
__<internal>                 e.g., __debezium-heartbeat, __s3-sink-dlq
```

### Partition count

Rule of thumb:
- Start with `6 × broker_count` partitions per high-volume topic
- Each partition = 1 consumer's max parallelism
- Don't exceed 4,000 partitions per broker (MSK soft limit)

```bash
kafka-topics --create \
  --topic cdc.public.orders \
  --partitions 18 \
  --replication-factor 3 \
  --config min.insync.replicas=2 \
  --config compression.type=lz4
```

### Retention

| Topic type | Retention | Reason |
|---|---|---|
| CDC topics | 7 days | Survive a mid-week outage + backfill |
| Clickstream / high-volume | 3 days | Cost-sensitive; archive to S3 for long-term |
| Transactional app events | 7 days | Buffer for downstream consumers |
| Internal (`__*`) topics | 1 day | Schema history, DLQs - keep short |
| `ws-broadcast` | 1 hour | Broadcast is ephemeral by nature |

### Compression

Always enable `lz4` compression. Trade-off: ~2-3% CPU overhead for 4-5× smaller on-disk footprint and faster network transfer.

## Day-to-day operations

### Checking cluster health

```bash
# Via AWS CLI
aws kafka describe-cluster-v2 --cluster-arn <arn> \
  --query 'ClusterInfo.{State:State,BrokerCount:NumberOfBrokerNodes}'

# Via kafka-topics
kafka-topics --bootstrap-server $MSK_BROKERS \
  --command-config iam.properties \
  --describe --topic __consumer_offsets \
  | grep -i under-replicated
```

Key CloudWatch metrics:
- `UnderReplicatedPartitions` — should be 0; > 0 means a broker is struggling
- `ActiveControllerCount` — should be exactly 1 per cluster
- `KafkaDataLogsDiskUsed` — stay below 70% to have headroom

### Rebalancing after broker addition

When you add brokers, existing partitions don't auto-move. Use the reassignment tool:

```bash
# 1. Describe current state
kafka-topics --bootstrap-server $MSK_BROKERS --command-config iam.properties \
  --describe > topics.txt

# 2. Generate reassignment JSON (use kafka-reassign-partitions)
cat > topics-to-move.json <<EOF
{"topics": [{"topic": "cdc.public.orders"}], "version": 1}
EOF

kafka-reassign-partitions --bootstrap-server $MSK_BROKERS \
  --topics-to-move-json-file topics-to-move.json \
  --broker-list "1,2,3,4,5,6" \
  --generate > reassignment.json

# 3. Execute (throttle to avoid saturating the network)
kafka-reassign-partitions --bootstrap-server $MSK_BROKERS \
  --reassignment-json-file reassignment.json \
  --execute \
  --throttle 50000000  # 50 MB/s per broker
```

Takes hours for large topics. Monitor with `--verify`.

### IAM auth debugging

Most "can't connect to MSK" issues are IAM:

```bash
# Verify the role has these actions:
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::...:role/my-role \
  --action-names kafka-cluster:Connect kafka-cluster:ReadData \
  --resource-arns arn:aws:kafka:us-east-1:...:topic/cluster/<uuid>/cdc.public.orders
```

Common gotchas:
- Role trust policy missing `Condition.StringEquals.aws:SourceAccount`
- Topic ARN includes cluster UUID (not just name)
- Security group doesn't allow port 9098 from the client SG

## MSK Connect (Debezium) operations

### Rotating Debezium DB credentials

MSK Connect stores connector configs statically. Rotation steps:

1. Create new DB user with replication grants
2. Update the connector config (create a new connector with new creds, keep old running)
3. Drain old connector
4. Delete old connector
5. Drop old DB user

**Do NOT** edit the connector in place while it's running — restart picks up the config but mid-flight transactions are interrupted.

### Handling schema drift

Debezium handles schema evolution by writing the new schema to the `__debezium-schema-history` topic. This topic MUST persist (don't shorten retention) and MUST be readable by the connector on restart.

If schema history is lost:
1. Delete the replication slot in Postgres (`SELECT pg_drop_replication_slot(...)`)
2. Delete the connector
3. Recreate the connector with `snapshot.mode=initial`
4. Wait for full re-snapshot (can be hours for large tables)

### Debezium connector failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Connector fails on startup with "replication slot in use" | Old process hasn't released | Restart Postgres or manually drop slot |
| "WAL overflow" errors | Slot hasn't been read in too long | Increase Postgres `wal_keep_size`, or drop+recreate slot |
| Events missing | Snapshot didn't complete | Check connector log for snapshot completion marker |
| Heartbeats missing | Connector is stuck | Force restart via MSK Connect API |

## Backup + disaster recovery

### MSK cluster backup

MSK doesn't have native snapshot/restore (unlike RDS). Options:
1. **MirrorMaker 2 to secondary MSK cluster in another region** — real-time replica
2. **MSK Connect S3 sink on all critical topics** — point-in-time archival to S3

Recommended: combine both. MirrorMaker for fast recovery, S3 for long-term audit.

### Disaster recovery procedure

If primary MSK goes down:
1. Cut over consumers to secondary region's MSK endpoint
2. Cut over producers last (so consumers catch up on secondary first)
3. When primary recovers, mirror back from secondary
4. Cut producers + consumers back

Full procedure in `docs/RUNBOOK.md`.

## Cost optimization

Biggest levers, in order of impact:

1. **Right-size brokers.** m5.large is fine for up to ~30K events/sec. Don't pay m5.2xlarge prices if you don't need them.
2. **Use compression.** LZ4 saves ~60% of storage + network cost.
3. **Shorter retention on low-value topics.** 1-day retention on clickstream instead of 7 can save 6× disk.
4. **Enable tiered storage** on prod (if MSK version supports). 3× cheaper than hot tier for data > 24h.
5. **Don't over-partition.** More partitions = more memory overhead per broker, and there are diminishing returns past `6 × broker_count`.

## Known limitations

- **MSK IAM auth latency**: ~5-10ms overhead per new connection vs plain SASL. Negligible for long-lived consumers.
- **No native dead-letter queues**: errors flow to `__*-dlq` topics we create manually per connector.
- **No cluster-level ACLs via IAM**: IAM controls topic-level access; finer-grained ACLs (record-level) require switching to mTLS or Kafka SASL/SCRAM.
- **MSK Serverless doesn't support compaction**: avoid compaction-dependent topic designs (e.g., Kafka-as-state-store patterns) on Serverless.
