# Backpressure

## The problem

Producers produce faster than consumers can consume. Without handling, this manifests as:
- Kafka topic partitions filling up → broker disk fills → broker dies
- Consumer memory grows → GC storms → OOM → consumer crashes → cycle repeats
- Stateful operators grow state → checkpoints grow → checkpoint duration balloons → recovery becomes impossible

## How Kafka handles it naturally

Kafka producers don't block on consumers. Messages land in broker log, broker retains them per retention policy. If consumers fall behind, lag grows. That's visible via `kafka-consumer-groups --describe` or CloudWatch `EstimatedMaxTimeLag`.

The key insight: Kafka *buffers* backpressure — it doesn't eliminate it. If consumer is perpetually behind, disk fills. Retention = 7 days means you have 7 days to catch up before data is irrecoverably lost.

## How Spark Structured Streaming handles it

**Micro-batch rate limiting** via `maxOffsetsPerTrigger`:
```python
.option("maxOffsetsPerTrigger", 50_000)
```
Spark never reads more than N messages per micro-batch. Result: batch size is bounded, so batch duration is bounded, so memory is bounded. Downside: if you set this too low and production rate exceeds it, lag grows indefinitely.

**Rule of thumb**: set `maxOffsetsPerTrigger` to 10-50× your processing capacity per batch. Monitor `inputRowsPerSecond` vs `processedRowsPerSecond` in Spark streaming UI.

## How Flink handles it

**Native backpressure** via record buffering between operators:
- Downstream operator's input buffer fills
- Upstream operator blocks on write
- Network task buffer fills
- Kafka consumer slows down reads

This propagates all the way back to Kafka. No configuration needed — it just works.

Visible in the Flink UI's "Backpressure" tab: each operator shows OK / LOW / HIGH.

## How our sinks handle it

Each sink implements `error_tolerance_pct` (default 0%). If more than N% of a batch fails, the sink raises and halts the stream. This prevents silent data loss when a sink is overloaded.

**Redis**: pipeline + `socket_timeout=5s`. If Redis is slow, writes time out, batch fails, stream backs off.

**OpenSearch**: bulk API with `sink.bulk-flush.max-size=5mb`. OpenSearch `429 Too Many Requests` responses are retried 3× with backoff; if still failing, the batch fails.

**ClickHouse**: `send_receive_timeout=30s`. Inserts are async inside ClickHouse's buffer table. If writes exceed the buffer size, we get 500s which fail the batch.

**S3/Iceberg**: Iceberg writer retries transient S3 429/503s internally. Persistent failures propagate up.

## Detecting backpressure

### In CloudWatch

| Metric | Namespace | What it tells you |
|---|---|---|
| `EstimatedMaxTimeLag` | AWS/Kafka (per consumer group) | Oldest unconsumed message age |
| `SumOffsetLag` | AWS/Kafka (per consumer group) | Total lag across all partitions |
| `currentInputWatermark` | AWS/KinesisAnalytics | Flink watermark position |
| `numRecordsInPerSecond` | AWS/KinesisAnalytics | Operator input rate |
| `backPressuredTimeMsPerSecond` | AWS/KinesisAnalytics | ms/sec operator is blocked on downstream |

### In Spark UI

- **Streaming Query Progress**: if `processedRowsPerSecond` < `inputRowsPerSecond` consistently, you're falling behind
- **Batch Duration** > **Trigger Interval**: micro-batches not keeping up
- **State Size** growing without bound: likely a join without time constraint

## Fixing backpressure

### 1. Scale out

Add partitions to hot topics (before adding more consumers — a consumer can only read as many partitions as exist):
```bash
# Check current
kafka-topics --describe --topic cdc.public.orders
# Increase
kafka-topics --alter --topic cdc.public.orders --partitions 24
```

Then scale consumers. For Spark Streaming, increase `--executor-instances`.

### 2. Scale up sink capacity

Hot sink maxed? Split writes:
- **Redis**: add read replicas, or shard by key hash
- **OpenSearch**: increase data nodes (this is expensive — consider pre-aggregating before sending)
- **ClickHouse**: add shards via ReplicatedMergeTree. Buffer tables help spikes but don't change steady-state capacity.

### 3. Drop or downsample

If you truly can't scale, sample or drop:
```python
# Drop 99% of low-value events
df.filter(
    (F.col("severity") == "CRITICAL") | (F.rand() < 0.01)
)
```

Bad behavior, but better than unbounded lag.

### 4. Break into parallel streams

If one slow sink is dragging the pipeline, split:
```python
# Each sink as a separate query with its own checkpoint
hot_query = df.writeStream.foreachBatch(redis_sink).option(cp="/hot").start()
cold_query = df.writeStream.foreachBatch(s3_sink).option(cp="/cold").start()
```

Now Redis slowness doesn't block S3 writes. Each query has independent offsets.

### 5. Use tiered storage (MSK tiered storage)

For very long retention without broker disk pressure:
- Hot tier: broker disk, fast reads
- Cold tier: S3, slower reads

Enable via `kafka.log.tier.enable=true`. Note: this is an MSK-specific feature (not open-source Kafka).

## Graceful degradation pattern

When downstream is fully down, your best option is usually:
1. Stop accepting new work (pause producers where possible)
2. Pipe existing stream to a "parking lot" S3 location
3. Resume processing when downstream recovers

This is what we do on OpenSearch cluster loss — Spark still runs, writes to S3, and a separate recovery job replays from S3 once OpenSearch is back.

## Alert recommendations

```yaml
alerts:
  - name: kafka_consumer_lag_growing
    metric: AWS/Kafka EstimatedMaxTimeLag
    threshold: > 5 minutes
    action: page
  - name: spark_batch_duration_increasing
    metric: SparkStreamingMetrics/batchDuration
    threshold: > 2x trigger interval for 10 min
    action: slack + investigate
  - name: flink_backpressure
    metric: AWS/KinesisAnalytics backPressuredTimeMsPerSecond
    threshold: > 500 for 5 min
    action: slack + scale
```
