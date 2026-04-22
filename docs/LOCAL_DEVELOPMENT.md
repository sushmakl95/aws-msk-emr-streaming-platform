# Local Development

Run the platform end-to-end locally without any AWS account.

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.11 | Runtime |
| Java | 17 | Spark 3.5, Flink 1.18 |
| Docker | 24+ | Kafka, Postgres, Redis, Debezium |
| Make | any | Convenience |

## Setup (first time)

```bash
git clone https://github.com/sushmakl95/aws-msk-emr-streaming-platform.git
cd aws-msk-emr-streaming-platform
make install-dev

# Start local Kafka + Postgres + Debezium + Redis + OpenSearch + ClickHouse
make compose-up

# Wait for services (takes 30-60 seconds)
docker compose -f compose/docker-compose.yml ps

# Register Debezium connector for Postgres
bash scripts/register-local-debezium.sh

# Seed test data
make seed-sample-data

# Watch events flow
docker compose -f compose/docker-compose.yml logs -f kafka-connect
```

## Run a Spark Streaming job locally

```bash
# Use local Kafka instead of MSK
export LOCAL_DEV=true

# Run orders CDC enrichment
python -m streaming.jobs.orders_cdc_enrichment \
  --bootstrap-servers localhost:9092 \
  --checkpoint-location /tmp/checkpoints/orders \
  --product-dim-path /tmp/dims/products \
  --redis-host localhost \
  --redis-port 6379 \
  --opensearch-endpoint localhost \
  --iceberg-warehouse /tmp/iceberg-warehouse \
  --local
```

You should see events flowing from Postgres → Kafka → Spark → Redis/OpenSearch/local Parquet.

## Run a Flink SQL job locally

Install the Flink SQL Client in a container:

```bash
docker run --rm -it --network compose_default \
  flink:1.18-scala_2.12 \
  bin/sql-client.sh
```

Inside the SQL client:
```sql
-- Paste src/flink/orders_enrichment.sql, substituting ${MSK_BOOTSTRAP_SERVERS}
-- with kafka:9092 (the compose service name)
```

## Develop interactively

### Using PySpark shell

```bash
pyspark --packages \
  org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0,\
  io.delta:delta-spark_2.12:3.2.0
```

Then inside:
```python
from streaming.sources import KafkaSource, KafkaSourceConfig
cfg = KafkaSourceConfig(
    bootstrap_servers="localhost:9092",
    topics=["cdc.public.orders"],
    use_iam_auth=False,
)
source = KafkaSource(spark, cfg)
stream = source.read_stream()
stream.printSchema()

query = stream.selectExpr("CAST(value AS STRING)").writeStream.format("console").start()
# Watch events print
query.stop()
```

### Using a Jupyter notebook

```bash
pip install jupyter
jupyter notebook notebooks/
```

The Databricks notebooks are in Databricks source format but also load in Jupyter.

## Testing

### Unit tests

```bash
make test-unit
```

Runs in ~10 seconds. Uses a local SparkSession + stub Kafka via `kafka-python-ng`.

### Integration tests

```bash
make test-integration
```

Requires `make compose-up` first. Takes ~5 minutes.

### Exactly-once regression test

Validates that crash+restart doesn't duplicate:

```bash
pytest tests/integration/test_exactly_once.py -v
```

## Local Docker Compose architecture

The `compose/docker-compose.yml` spins up:

- **zookeeper** (port 2181)
- **kafka** (port 9092, single broker for local)
- **schema-registry** (port 8081, Confluent)
- **postgres** (port 5432, logical replication enabled)
- **kafka-connect** (port 8083, with Debezium + S3 sink plugins pre-installed)
- **redis** (port 6379)
- **opensearch** (port 9200)
- **clickhouse** (ports 8123, 9000)

All on a single bridge network. Service names double as hostnames.

## Turning it off

```bash
make compose-down
```

This removes containers + volumes. Data is gone.

## Troubleshooting

**Kafka connection refused**: wait 30-60s after `compose-up` — Kafka takes time to elect a controller.

**Debezium slot exists**: previous run didn't clean up. `make compose-down -v` to remove volumes.

**Port conflict on 9092/5432**: something else is running. Edit `docker-compose.yml` to remap ports.

**OpenSearch "max virtual memory too low"**: run `sudo sysctl -w vm.max_map_count=262144` (Linux) or increase Docker Desktop's memory to 8 GB.

**Spark can't find Kafka package**: run `make install-dev` to ensure PySpark deps are installed, then `python -m streaming.jobs.orders_cdc_enrichment ...`

**ClickHouse rejects connection**: first-run setup takes 30s; wait for health check to pass.

## What doesn't work locally

- **EMR job submission** (`streaming submit-emr`) requires real AWS
- **MSK Connect custom plugin upload** — only relevant in AWS
- **PyFlink native execution** — requires a Flink cluster; SQL Client in Docker works as a substitute
- **WebSocket API Gateway** — use `wscat` to test the compose-based mock server at ws://localhost:8765

## IDE setup

**VS Code**: install Python + Ruff + HashiCorp Terraform extensions. The repo's `pyproject.toml` is detected automatically.

**PyCharm**: mark `src/` as Sources Root. Use the venv created by `make install-dev`.

## Environment variables

`.env.example` → `.env` (gitignored) and set:

```bash
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
STREAMING_LOG_LEVEL=INFO
STREAMING_LOG_FORMAT=console  # or 'json'
LOCAL_DEV=true
KAFKA_BOOTSTRAP=localhost:9092
```
