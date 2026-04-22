# Exactly-Once Semantics

## The problem

Without care, a streaming pipeline gives at-least-once — meaning the same record can be written to a sink multiple times after a crash. For aggregations (counts, sums) this inflates results. For derived events (alerts, notifications) this duplicates downstream actions.

## Three delivery semantics

| Semantic | Guarantee | Use when |
|---|---|---|
| At-most-once | Each record delivered 0 or 1 times | Cannot tolerate duplicates, can tolerate loss (rare in practice) |
| At-least-once | Each record delivered 1 or more times | Duplicates OK (or sink is idempotent), loss NOT OK |
| Exactly-once | Each record effectively delivered exactly 1 time | Accuracy critical (financial, dashboards, alerts) |

The word "effectively" matters: at the wire level, packets can be retransmitted; what matters is the observable effect on the sink.

## How we achieve exactly-once

### Path 1: Spark Structured Streaming → idempotent sink

**Offsets committed AFTER sink write completes**: Spark's `checkpointLocation` stores the input offsets. The sequence is:
1. Start batch N: read planned offsets for [startOffset, endOffset)
2. Write planned offsets to checkpoint (before processing)
3. Process records via `foreachBatch`
4. Sink writes complete
5. Commit endOffset to checkpoint
6. Start batch N+1

If crash occurs **after step 2, before step 5**: restart reads the SAME offsets and re-processes. The sink must be idempotent for this to be exactly-once.

**Idempotent sinks via token-based keys**: each record carries a stable `idempotency_token` (CDC LSN, if available, or composite of topic+partition+offset). Sinks use this as the primary key:

```python
# Redis: HSET uses the composite key
key = f"order:{record['order_id']}"  # stable per record
client.hset(key, mapping=flat_record)

# OpenSearch: doc _id is the token
bulk_ops.append({"index": {"_index": idx, "_id": idempotency_token}})

# Iceberg: UPSERT via MERGE + source LSN comparison
MERGE INTO target t USING updates u ON t.order_id = u.order_id
  AND u.source_lsn > t.source_lsn
WHEN MATCHED THEN UPDATE SET ...
WHEN NOT MATCHED THEN INSERT ...
```

Replay writes the same data under the same key, producing no observable change.

### Path 2: Flink with Kafka transactions

Flink has native exactly-once via two-phase commit (2PC):
1. **Pre-commit**: write data to sink in a transaction
2. **Checkpoint barrier**: Flink checkpoints include transaction handles
3. **Commit**: on checkpoint complete, commit the sink transactions

Source offsets and sink transactions commit atomically with the Flink checkpoint. If crash: re-read from last checkpoint, re-open aborted transactions.

Enabled by default in our Flink SQL jobs via:
```sql
'properties.transactional.id.prefix' = 'streaming-orders',
'sink.semantic' = 'exactly-once'
```

### Path 3: Databricks + Delta Lake ACID

Delta provides ACID transactions. Structured Streaming writes to Delta with `foreachBatch` using `MERGE`:
```python
def upsert(batch_df, batch_id):
  (spark.sql(f"""
    MERGE INTO target t USING batch_df u
      ON t.order_id = u.order_id AND u.source_lsn > t.source_lsn
    WHEN MATCHED THEN UPDATE SET ...
    WHEN NOT MATCHED THEN INSERT ...
  """))
batch_df.writeStream.foreachBatch(upsert).start()
```

The transaction log (_delta_log) is the source of truth; duplicate `batch_id` replays are no-ops.

## What breaks exactly-once

**1. Non-deterministic transformations.** If a UDF uses `rand()` or `now()` inside a map, replay produces different records. Solution: push non-determinism to sink (use `current_timestamp()` at ingestion, store + replay).

**2. External side effects during processing.** If your processing step calls an external HTTP API (e.g., payment gateway), replay calls it again. Solution: side effects belong AFTER the stream, triggered by the sink; use Outbox pattern if you must emit from a stream.

**3. Manual offset commits.** If a downstream consumer commits its own Kafka offsets (not Spark checkpoints), that's a separate failure domain. Don't mix Spark structured streaming offsets with Kafka consumer-group offsets for the same workload.

**4. Changing keys across restarts.** If your `idempotency_token` depends on runtime context (container ID, hostname), replay produces a different key → duplicate at sink. Solution: derive tokens from data, not runtime.

**5. Non-idempotent aggregations in an intermediate store.** If you aggregate to a stateful sink (e.g., HBase counter), a naive `INCRBY` doubles on replay. Use versioned updates (ReplacingMergeTree in ClickHouse, MERGE in Delta).

## Validation: how we measure

Nightly integration test (`tests/integration/test_exactly_once.py`):
1. Produce 1M uniquely-ID'd events to a test MSK topic
2. Start the streaming job
3. Kill the driver mid-way
4. Restart
5. Query the sink: count distinct keys should equal 1M exactly

We keep regression tests for all three paths.

## When at-least-once is acceptable

If the downstream sink is naturally idempotent (e.g., a KV store where you just overwrite), at-least-once is effectively exactly-once at the sink layer. Many systems can live with this. Don't pay the exactly-once overhead if you don't need it — it costs ~15-25% throughput in Flink 2PC mode due to transaction coordination.
