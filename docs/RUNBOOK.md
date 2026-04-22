# Operations Runbook

## On-call severity matrix

| Severity | Trigger | SLA to ack | Action |
|---|---|---|---|
| P0 | MSK cluster unavailable; all streaming jobs failing | 5 min | Page |
| P0 | Consumer lag > 30 min AND growing | 5 min | Page |
| P1 | One job failing; others healthy | 30 min | Slack |
| P1 | MSK UnderReplicatedPartitions > 0 > 10 min | 30 min | Slack |
| P2 | Lambda errors, single sink slow | Next business day | Backlog |

## Common scenarios

### 1. Consumer lag is growing — streaming job can't keep up

**Symptoms:** `EstimatedMaxTimeLag` CloudWatch alarm fires. Users see stale data.

**Diagnosis:**
```bash
# Check the source rate
aws cloudwatch get-metric-statistics \
  --namespace AWS/Kafka \
  --metric-name BytesInPerSec \
  --dimensions Name="Cluster Name",Value=<cluster> Name=Topic,Value=cdc.public.orders \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 --statistics Average

# Check processing rate in Spark UI
# (SSH to driver pod or open Spark UI)

# Check backpressure in Flink UI for Flink path
```

**Common causes:**
1. **Sudden traffic spike**: scale up consumers or add partitions
2. **Slow downstream sink**: check sink's own health (Redis latency, OpenSearch heap, etc.)
3. **Schema registry lag**: schema changes can choke deserialization briefly
4. **Checkpoint size growing**: state store slowness; reduce state retention or compact

**Fix:**
```bash
# Scale out — EMR on EKS
kubectl scale deployment streaming-orders-enrichment -n emr-streaming --replicas=4

# Scale out — Flink (change parallelism via KDA UpdateApplication)
aws kinesisanalyticsv2 update-application \
  --application-name streaming-platform-prod-orders-enrichment \
  --application-configuration-update ParallelismConfigurationUpdate={ParallelismUpdate=8}
```

### 2. MSK broker storage filling up

**Symptoms:** `KafkaDataLogsDiskUsed` > 75% alarm.

**Diagnosis:**
```bash
# Identify biggest topics
aws kafka describe-cluster-v2 --cluster-arn <arn>
# Then via kafka-log-dirs (requires client pod)
kafka-log-dirs --bootstrap-server $MSK_BROKERS \
  --command-config iam.properties \
  --broker-list "1,2,3" --describe | jq '.[0].brokers[0].logDirs[0].partitions[] | {partition: .partition, size: .size}' | sort -k2 -n
```

**Fix:**
1. **Shorten retention on hot topics**:
   ```bash
   kafka-configs --bootstrap-server $MSK_BROKERS \
     --command-config iam.properties \
     --alter --entity-type topics --entity-name cdc.public.orders \
     --add-config retention.ms=259200000  # 3 days
   ```
2. **Expand broker storage** (scaled update, no downtime):
   ```bash
   aws kafka update-broker-storage --cluster-arn <arn> \
     --target-broker-ebs-volume-info BrokerCount=3,VolumeSizeGB=1000
   ```
   Takes ~30 min per broker.

3. **Enable tiered storage** (requires MSK 3.6+):
   Update the MSK configuration to add `remote.log.storage.system.enable=true`. Only available on MSK Provisioned.

### 3. Debezium replication slot stuck

**Symptoms:** CDC events stop flowing. Connector log shows "WAL overflow" or "replication slot too far behind".

**Diagnosis:**
```sql
-- In Postgres
SELECT slot_name, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn))
  AS replication_lag
FROM pg_replication_slots;
```

If `replication_lag` is > 100GB, the slot is seriously stuck.

**Fix:**
```bash
# Delete the Debezium connector
curl -X DELETE \
  "https://<mskconnect-endpoint>/v1/kafkaconnect/connectors/postgres-orders-cdc"

# Drop the slot in Postgres
psql -c "SELECT pg_drop_replication_slot('debezium_orders_slot');"

# Recreate connector
bash scripts/deploy-connectors.sh

# ⚠️ This triggers a full snapshot. Plan for hours of catch-up.
```

### 4. Flink job in "FAILED" state after savepoint

**Symptoms:** KDA app status = FAILED. CloudWatch shows "Failed to restore from savepoint."

**Common causes:**
- Savepoint is from an incompatible Flink version
- Savepoint's state schema doesn't match current code (you changed a stateful operator)
- Savepoint S3 file is corrupt or missing

**Fix:**
```bash
# Option 1: Start without savepoint (lose state, resume from latest offsets)
aws kinesisanalyticsv2 start-application \
  --application-name <name> \
  --run-configuration '{"FlinkRunConfiguration":{"AllowNonRestoredState":true}}'

# Option 2: Restore from an older savepoint
aws kinesisanalyticsv2 start-application \
  --application-name <name> \
  --run-configuration '{"ApplicationRestoreConfiguration":{"ApplicationRestoreType":"RESTORE_FROM_CUSTOM_SNAPSHOT","SnapshotName":"older-snapshot-id"}}'

# Option 3: Reset to earliest offsets (full replay)
# Requires deleting the consumer group in MSK first
```

### 5. Lambda WebSocket broadcaster timing out

**Symptoms:** `ws_broadcast` Lambda duration approaching 60s timeout. Pushed events lagging.

**Common causes:**
1. **Too many active connections**: scan-all-connections for a `*` broadcast is O(N). For > 10K connections, this breaks.
2. **DynamoDB throttling**: check `ThrottledRequests` metric.
3. **API Gateway postToConnection rate limit**: ~500/sec per endpoint.

**Fix:**
1. Maintain a separate index of "active broadcast subscribers" with capped size.
2. Batch postToConnection via the `batchPostToConnection` API (preview).
3. For very fan-out-heavy workloads, use SNS mobile push instead of WebSocket.

### 6. OpenSearch cluster yellow/red

**Symptoms:** `ClusterStatus.yellow` or `.red` CloudWatch alarm.

**Diagnosis:**
```bash
curl -X GET "https://<os-endpoint>/_cluster/allocation/explain?pretty"
```

**Common causes + fixes:**
- **Disk watermark exceeded**: delete old indices
  ```bash
  curl -X DELETE "https://<os-endpoint>/orders-2026.01.*"
  ```
- **Master election deadlock**: usually self-resolves; if not, reboot nodes one at a time
- **Shard too large**: split with reindex to a new index with more primaries

### 7. ClickHouse cluster behind ALB returning 502s

**Symptoms:** Health check failing. OLAP queries hang.

**Diagnosis:**
```bash
aws ecs list-tasks --cluster <cluster> --service-name <service>
aws ecs describe-tasks --cluster <cluster> --tasks <task-arn>

# Check logs
aws logs tail /ecs/streaming-platform-prod-clickhouse --since 30m
```

**Common causes:**
- Task OOM killed (memory sizing too small)
- Buffer table overflow (writes faster than flush)
- ZooKeeper connection loss (if using ClickHouse Keeper)

**Fix:** scale up task memory; increase buffer flush frequency:
```sql
ALTER TABLE events_buffer MODIFY SETTING max_rows = 5000000, max_time = 10;
```

### 8. Secret rotation broke connections

**Symptoms:** After rotating MSK password or DB password in Secrets Manager, connectors start failing.

**Fix:** force a refresh:
```bash
# MSK Connect connector - delete + recreate picks up new creds
# (MSK Connect doesn't auto-refresh from Secrets Manager)

# EMR/Flink jobs - restart reads the new cred
aws emr-serverless stop-application --application-id <id>
aws emr-serverless start-application --application-id <id>
```

## Scaling operations

### Adding MSK brokers

Zero-downtime:
```bash
aws kafka update-broker-count --cluster-arn <arn> --target-number-of-broker-nodes 6
```

Takes ~20 min. Then rebalance partitions (see `docs/MSK_OPERATIONS.md`).

### Adding partitions to a hot topic

```bash
kafka-topics --alter \
  --bootstrap-server $MSK_BROKERS \
  --command-config iam.properties \
  --topic cdc.public.orders \
  --partitions 24  # was 12
```

**Warning:** can't reduce partition count later without recreating the topic. Be careful.

### Scaling Kinesis

```bash
aws kinesis update-shard-count --stream-name <name> --target-shard-count 8 \
  --scaling-type UNIFORM_SCALING
```

Takes ~5 min, costs 2× during the scaling window.

## CLI cheat sheet

```bash
# Tail MSK broker logs
aws logs tail /aws/msk/streaming-platform-prod --follow

# Tail Lambda logs
aws logs tail /aws/lambda/streaming-platform-prod-ws-broadcast --follow

# Check Flink app status
aws kinesisanalyticsv2 describe-application --application-name <name>

# List active consumer groups
kafka-consumer-groups --bootstrap-server $MSK_BROKERS \
  --command-config iam.properties --list

# Check Redis connectivity
redis-cli -h <endpoint> --tls ping

# Check ClickHouse
curl "https://<ch-lb>/ping"
```

## Post-incident review

Every P0 deserves a review within 5 business days. Template:
- Timeline (first symptom → ack → mitigation → resolution → RCA)
- Root cause (the actual failure, not the symptom)
- Impact (events lost, customer impact, financial)
- Detection (how did we find out? could we have found out faster?)
- Prevention (action items with owners + deadlines)

Track to completion in team's issue tracker.
