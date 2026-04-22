# AWS MSK + EMR Streaming Platform

> Production-grade real-time data platform built on **AWS MSK** (Managed Kafka) as the backbone, with **MSK Connect / Debezium** for database CDC, **EMR on EKS** + **EMR Serverless** running Spark Structured Streaming, **Kinesis Data Analytics for Apache Flink** for SQL-native streaming, and a hot/warm/cold sink fan-out (ElastiCache Redis / OpenSearch / ClickHouse / S3). Includes a parallel **Databricks Streaming** comparison path so teams can evaluate both runtimes on identical workloads.

[![CI](https://github.com/sushmakl95/aws-msk-emr-streaming-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/sushmakl95/aws-msk-emr-streaming-platform/actions/workflows/ci.yml)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![PySpark 3.5](https://img.shields.io/badge/pyspark-3.5-E25A1C.svg)](https://spark.apache.org/)
[![Flink 1.18](https://img.shields.io/badge/flink-1.18-darkcyan.svg)](https://flink.apache.org/)
[![AWS MSK](https://img.shields.io/badge/aws-msk%20%7C%20emr%20%7C%20kinesis-FF9900.svg)](https://aws.amazon.com/)
[![Databricks](https://img.shields.io/badge/databricks-structured_streaming-FF3621.svg)](https://www.databricks.com/)
[![Terraform](https://img.shields.io/badge/terraform-17_modules-7B42BC.svg)](https://www.terraform.io/)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

---

## Author

**Sushma K L** — Senior Data Engineer
📍 Bengaluru, India
💼 [LinkedIn](https://www.linkedin.com/in/sushmakl1995/) • 🐙 [GitHub](https://github.com/sushmakl95) • ✉️ sushmakl95@gmail.com

---

## What this platform does

You have an operational database (Postgres, MySQL, or MongoDB) and need:
1. **Sub-second propagation** of every row change to downstream systems
2. **Multiple sinks** with different access patterns — hot lookups, full-text search, columnar analytics, cold archive
3. **At-least-once guarantees** with **end-to-end backpressure handling**
4. **Choice of processing runtime** — Spark Structured Streaming, Flink SQL, or both
5. **Real-time push to clients** via WebSocket

This repo is the opinionated AWS-native implementation of all five, with a `Databricks Streaming` track showing the same pipeline on that runtime for TCO/operational comparison.

## Comparison at a glance

| Capability | AWS-native (this platform) | Databricks alternative |
|---|---|---|
| Event bus | Amazon MSK | Databricks managed Kafka (AWS MSK under the hood) |
| Streaming compute | EMR on EKS + EMR Serverless + Flink | Databricks Structured Streaming |
| State store | RocksDB on EMR / Flink state backend | Delta Lake (bronze) + Databricks state store |
| Exactly-once | Kafka transactions + Flink 2PC + Spark checkpoints | DLT + Delta ACID |
| CDC ingest | MSK Connect + Debezium | Delta Lake CDC + Auto Loader |
| Monitoring | CloudWatch + Grafana | Databricks observability |
| Monthly cost (baseline) | ~$1,800/month | ~$2,400/month |

Both tracks produce identical output semantics; choose based on your team's skills + existing tooling.

---

## System Architecture

### High-level architecture

```mermaid
flowchart TB
    subgraph Sources["🟢 Data Sources"]
        Postgres[("Postgres OLTP")]
        MySQL[("MySQL OLTP")]
        Mongo[("MongoDB")]
        Apps["Application events<br/>(REST API → Lambda)"]
    end

    subgraph Ingest["🟡 CDC + Ingest Layer"]
        Debezium["MSK Connect<br/>Debezium Connectors"]
        Lambda["Lambda<br/>(app events to Kafka)"]
    end

    subgraph Bus["🟠 Event Bus"]
        MSK[("Amazon MSK<br/>3 brokers × m5.xlarge<br/>Multi-AZ")]
        KinesisAlt[("Kinesis Data Streams<br/>(alternate path)")]
    end

    subgraph Compute["🔴 Streaming Compute"]
        EMREKS["EMR on EKS<br/>Spark Structured Streaming<br/>(long-running)"]
        EMRServerless["EMR Serverless<br/>Spark Streaming<br/>(on-demand)"]
        KDA["Kinesis Data Analytics<br/>Apache Flink"]
        DBStream["Databricks Streaming<br/>(comparison track)"]
    end

    subgraph State["🟣 State + Schema"]
        SchemaRegistry["Glue Schema Registry"]
        RocksDB["RocksDB<br/>(EMR state backend)"]
        FlinkState["Flink State Backend<br/>(S3 + RocksDB)"]
        DeltaState[("Delta Lake<br/>state snapshots<br/>(Databricks track)")]
    end

    subgraph Sinks["🔵 Sinks (Hot / Warm / Cold)"]
        Redis[("ElastiCache Redis<br/>microsec lookups<br/>hot state")]
        OS[("OpenSearch<br/>full-text search<br/>aggregations")]
        CH[("ClickHouse on ECS<br/>columnar analytical<br/>OLAP queries")]
        S3Cold[("S3 + Iceberg<br/>historical archive<br/>cold queries via Athena")]
    end

    subgraph Egress["🟢 Client-facing"]
        WSAPI["API Gateway<br/>WebSocket API"]
        Clients["Connected Clients<br/>(browser, mobile)"]
    end

    subgraph Obs["📊 Observability"]
        CW["CloudWatch<br/>Logs + Metrics"]
        Grafana["Managed Grafana<br/>streaming dashboards"]
        Prom["Managed Prometheus<br/>(EMR on EKS metrics)"]
    end

    Postgres -.binlog.-> Debezium
    MySQL -.binlog.-> Debezium
    Mongo -.oplog.-> Debezium
    Apps --> Lambda
    Lambda --> MSK
    Debezium --> MSK
    MSK -.optional bridge.-> KinesisAlt

    MSK --> EMREKS
    MSK --> EMRServerless
    MSK --> KDA
    MSK --> DBStream

    EMREKS --- RocksDB
    KDA --- FlinkState
    DBStream --- DeltaState
    EMREKS --- SchemaRegistry
    KDA --- SchemaRegistry

    EMREKS --> Redis
    EMREKS --> OS
    EMREKS --> S3Cold
    EMRServerless --> S3Cold
    KDA --> CH
    KDA --> WSAPI
    DBStream --> Redis
    DBStream --> S3Cold

    WSAPI --> Clients

    EMREKS -.metrics.-> Prom
    EMRServerless -.logs.-> CW
    KDA -.logs.-> CW
    MSK -.metrics.-> CW
    CW --> Grafana
    Prom --> Grafana

    classDef src fill:#22C55E,stroke:#166534,color:#fff
    classDef ingest fill:#fbbf24
    classDef bus fill:#FF9900,color:#000
    classDef compute fill:#EF4444,color:#fff
    classDef state fill:#a855f7,color:#fff
    classDef sink fill:#3b82f6,color:#fff
    classDef egress fill:#10b981,color:#fff
    classDef obs fill:#0ea5e9,color:#fff
    class Postgres,MySQL,Mongo,Apps src
    class Debezium,Lambda ingest
    class MSK,KinesisAlt bus
    class EMREKS,EMRServerless,KDA,DBStream compute
    class SchemaRegistry,RocksDB,FlinkState,DeltaState state
    class Redis,OS,CH,S3Cold sink
    class WSAPI,Clients egress
    class CW,Grafana,Prom obs
```

### CDC ingestion flow (Postgres → MSK)

```mermaid
sequenceDiagram
    autonumber
    participant PG as Postgres
    participant WAL as WAL / logical replication slot
    participant Debezium as Debezium<br/>Connector
    participant SR as Schema Registry
    participant MSK as MSK Topic<br/>(cdc.public.orders)
    participant Consumer as Spark/Flink<br/>Consumer

    Note over PG,WAL: Enable logical replication<br/>wal_level = logical

    Debezium->>PG: Open replication slot
    PG-->>Debezium: Snapshot current state
    Debezium->>SR: Register Avro schema
    Debezium->>MSK: Produce snapshot events<br/>(op=r, "read")

    loop Continuous CDC
        PG->>WAL: INSERT/UPDATE/DELETE
        WAL->>Debezium: Logical replication stream
        Debezium->>Debezium: Transform to CloudEvents format
        Debezium->>SR: Check schema compatibility
        Debezium->>MSK: Produce (op=c/u/d, before, after)
    end

    Consumer->>MSK: Subscribe cdc.public.orders
    MSK-->>Consumer: Avro-encoded events
    Consumer->>SR: Deserialize via schema
```

### Dual-runtime streaming comparison

```mermaid
flowchart LR
    subgraph Source["Single Source of Truth"]
        MSK[("MSK Topic<br/>cdc.public.orders")]
    end

    subgraph AWS_Track["🟠 AWS Native Track"]
        direction TB
        EMR["EMR on EKS<br/>Spark Structured Streaming"]
        EMR_State["RocksDB<br/>state backend"]
        EMR_CP["S3 Checkpoint"]
        EMR --- EMR_State
        EMR --- EMR_CP
    end

    subgraph DB_Track["🔴 Databricks Track"]
        direction TB
        DBR["Databricks<br/>Structured Streaming"]
        DLT["DLT Pipeline<br/>+ Auto Loader"]
        Delta[("Delta Lake<br/>bronze/silver/gold")]
        DBR --- DLT
        DLT --- Delta
    end

    subgraph Sinks["Shared Output Sinks"]
        Redis[(Redis)]
        OS[(OpenSearch)]
        S3[(S3 Archive)]
    end

    MSK --> EMR
    MSK --> DBR

    EMR --> Redis
    EMR --> OS
    EMR --> S3
    DBR --> Redis
    DBR --> OS
    DBR --> S3

    subgraph Compare["Comparison metrics"]
        M1["P99 end-to-end latency"]
        M2["Cost per event processed"]
        M3["Operational burden"]
        M4["Backpressure behavior"]
        M5["Recovery time after crash"]
    end

    EMR -.measure.-> Compare
    DBR -.measure.-> Compare
```

### Exactly-once semantics — Spark Structured Streaming path

```mermaid
sequenceDiagram
    autonumber
    participant MSK as MSK Topic
    participant Spark as Spark Streaming<br/>(EMR on EKS)
    participant CP as S3 Checkpoint
    participant State as RocksDB state
    participant Sink as Redis Sink

    loop Each micro-batch (100ms trigger)
        Spark->>MSK: Request offsets [batch-id]
        MSK-->>Spark: Messages + offsets
        Spark->>CP: Write planned offsets<br/>(before processing)
        Note over Spark,CP: Crash-safe: if crash now,<br/>restart re-reads SAME offsets
        Spark->>Spark: Process records
        Spark->>State: Update state (aggregation counters)
        Spark->>Sink: Write with idempotent key<br/>(order_id + batch_id)
        Sink-->>Spark: Confirm write
        Spark->>CP: Commit completed offsets
        Note over Spark,CP: Crash-safe: if crash now,<br/>restart skips this batch
    end
```

### MSK Connect deployment model

```mermaid
flowchart TB
    subgraph Config["Config in Git"]
        DebeziumConfig["mskconnect/debezium/<br/>orders.properties"]
        S3SinkConfig["mskconnect/s3sink/<br/>archive.properties"]
        CustomPlugin["Custom SMT plugins<br/>(optional, uber JAR)"]
    end

    subgraph S3Plugin["S3 plugin bucket"]
        ZipPlugin["debezium-postgres-2.5.zip"]
        ZipSink["confluent-s3-sink-10.5.zip"]
    end

    subgraph MSK_Connect["MSK Connect (managed)"]
        direction TB
        Worker1["Connect worker 1<br/>MCU: 2"]
        Worker2["Connect worker 2<br/>MCU: 2"]
        Connector_A["Debezium connector<br/>'orders-cdc'"]
        Connector_B["S3 sink connector<br/>'archive-s3'"]
        Worker1 --- Connector_A
        Worker2 --- Connector_B
    end

    subgraph Targets["Sources / Sinks"]
        Postgres[("Postgres")]
        MSK[("MSK Cluster")]
        S3Archive[("S3 Archive Bucket")]
    end

    DebeziumConfig -.create-connector API.-> Connector_A
    S3SinkConfig -.create-connector API.-> Connector_B
    ZipPlugin --> Worker1
    ZipSink --> Worker2
    CustomPlugin -.optional.-> Worker1

    Postgres -.WAL stream.-> Connector_A
    Connector_A --> MSK
    MSK --> Connector_B
    Connector_B --> S3Archive

    classDef cfg fill:#fbbf24
    classDef plugin fill:#a855f7,color:#fff
    classDef mc fill:#FF9900,color:#000
    classDef target fill:#22C55E,color:#fff
    class DebeziumConfig,S3SinkConfig,CustomPlugin cfg
    class ZipPlugin,ZipSink plugin
    class Worker1,Worker2,Connector_A,Connector_B mc
    class Postgres,MSK,S3Archive target
```

### Hot / Warm / Cold sink fan-out

```mermaid
flowchart LR
    subgraph Stream["Stream Processing Output"]
        Enriched["Enriched Event<br/>(joined + denormalized)"]
    end

    subgraph Hot["🔥 Hot Sink (microsec reads)"]
        Redis[("ElastiCache Redis<br/>TTL: 1h")]
        RedisUse["Application lookups<br/>'user 123's current cart'"]
    end

    subgraph Warm["☀️ Warm Sink (ms reads, complex queries)"]
        OS[("OpenSearch<br/>30-day retention")]
        CH[("ClickHouse on ECS<br/>90-day retention")]
        OSUse["Full-text search<br/>dashboards"]
        CHUse["OLAP aggregations<br/>real-time funnels"]
    end

    subgraph Cold["❄️ Cold Sink (s reads, unbounded retention)"]
        S3[("S3 + Iceberg<br/>partitioned by date")]
        Athena["Athena queries"]
        S3Use["Historical analysis<br/>ML training datasets"]
    end

    Enriched --> Redis
    Enriched --> OS
    Enriched --> CH
    Enriched --> S3

    Redis --- RedisUse
    OS --- OSUse
    CH --- CHUse
    S3 --- Athena
    Athena --- S3Use

    classDef hot fill:#dc2626,color:#fff
    classDef warm fill:#f59e0b
    classDef cold fill:#3b82f6,color:#fff
    class Redis,RedisUse hot
    class OS,CH,OSUse,CHUse warm
    class S3,Athena,S3Use cold
```

### WebSocket push architecture

```mermaid
sequenceDiagram
    autonumber
    participant Client as Client<br/>(browser / mobile)
    participant WSAPI as API Gateway<br/>WebSocket
    participant ConnectLambda as Lambda<br/>$connect handler
    participant ConnDDB as DynamoDB<br/>connection registry
    participant Stream as Flink Stream<br/>Processor
    participant Push as Lambda<br/>broadcast handler
    participant MSK as MSK Topic<br/>ws-broadcast

    Client->>WSAPI: wss:// connect
    WSAPI->>ConnectLambda: $connect event
    ConnectLambda->>ConnDDB: Store {conn_id, user_id, subscribed_topics}
    ConnectLambda-->>WSAPI: 200 OK
    WSAPI-->>Client: Connection open

    Note over Client,MSK: Live data flow begins

    Stream->>MSK: Produce broadcast event<br/>(topic, payload, user_targets)
    MSK->>Push: Triggered by Lambda ESM
    Push->>ConnDDB: Query connections<br/>matching user_targets
    ConnDDB-->>Push: [conn_id_1, conn_id_2, ...]

    loop For each active connection
        Push->>WSAPI: postToConnection(conn_id, payload)
        WSAPI->>Client: Push message
    end

    Note over Client,WSAPI: Client disconnects (eventually)
    Client->>WSAPI: wss:// close
    WSAPI->>ConnectLambda: $disconnect event
    ConnectLambda->>ConnDDB: Delete conn_id
```

### Deployment + CI/CD topology

```mermaid
flowchart LR
    subgraph Git["GitHub"]
        PR["PR branches"]
        Main["main branch"]
        Tags["release tags v*"]
    end

    subgraph CI["GitHub Actions"]
        Lint["ruff + mypy + bandit"]
        TFValidate["TF validate"]
        UnitTests["PySpark unit tests<br/>(Java 17)"]
        Build["Build Flink JAR<br/>Build Spark uber-JAR"]
    end

    subgraph ECR["ECR"]
        EMRImg["emr-eks-streaming:tag"]
        FlinkImg["flink-app:tag"]
    end

    subgraph S3Artifacts["S3 Artifacts"]
        SparkJar["Spark streaming JAR"]
        FlinkSQL["Flink SQL scripts"]
        PluginZip["MSK Connect plugins"]
    end

    subgraph Deploy["AWS deploy"]
        Dev["Dev env"]
        Stg["Staging env"]
        Prod["Prod env"]
    end

    PR --> Lint
    PR --> TFValidate
    PR --> UnitTests
    Main --> Build
    Build --> EMRImg
    Build --> FlinkImg
    Build --> SparkJar
    Build --> FlinkSQL
    Build --> PluginZip

    Tags --> Dev
    Tags -.RC only.-> Stg
    Tags -.stable only.-> Prod

    Dev --> EMRImg
    Stg --> EMRImg
    Prod --> EMRImg
    Dev --> FlinkImg
    Stg --> FlinkImg
    Prod --> FlinkImg
```

---

## Repository Structure

```
aws-msk-emr-streaming-platform/
├── .github/workflows/          # CI: lint + TF validate + build + unit tests
├── src/
│   ├── streaming/
│   │   ├── core/               # StreamEvent, Checkpoint, Watermark types
│   │   ├── sources/            # Kafka, Kinesis source builders
│   │   ├── sinks/              # Redis, OpenSearch, ClickHouse, S3 sinks
│   │   ├── transforms/         # Windowing, joins, enrichment UDFs
│   │   ├── jobs/               # Spark Structured Streaming jobs
│   │   ├── state/              # State store helpers, RocksDB config
│   │   ├── orchestration/      # EMR job submission + lifecycle
│   │   └── utils/              # Logging, metrics, secrets
│   ├── flink/                  # Flink SQL + DataStream jobs (Python + SQL)
│   └── lambdas/                # WebSocket handlers, broadcast Lambda
├── mskconnect/                 # Debezium + S3 sink connector configs
├── notebooks/                  # Databricks Streaming comparison notebooks
├── infra/terraform/
│   ├── modules/                # 17 modules
│   └── envs/                   # dev/staging/prod
├── dashboards/                 # Grafana + CloudWatch JSON
├── scripts/                    # Deploy, submit jobs, scale brokers
├── tests/                      # Unit + integration
├── config/                     # Topic configs, sink configs
└── docs/
    ├── ARCHITECTURE.md
    ├── EXACTLY_ONCE.md
    ├── BACKPRESSURE.md
    ├── RUNTIME_COMPARISON.md
    ├── MSK_OPERATIONS.md
    ├── LOCAL_DEVELOPMENT.md
    ├── COST_ANALYSIS.md
    └── RUNBOOK.md
```

## Quick Start (Local Dev)

```bash
git clone https://github.com/sushmakl95/aws-msk-emr-streaming-platform.git
cd aws-msk-emr-streaming-platform
make install-dev

# Start local Kafka + Postgres + Debezium stack
make compose-up

# Produce some test events
make demo-seed-data

# Run a Spark Streaming job locally
make demo-spark-job

# Run a Flink SQL job locally
make demo-flink-job
```

## ⚠️ Cloud Cost Warning

Full production deployment costs approximately **$1,800/month** at moderate throughput (10k events/sec baseline). See [docs/COST_ANALYSIS.md](docs/COST_ANALYSIS.md). For evaluation, use the local Docker Compose stack (free).

## Resume Alignment

Directly maps to these responsibilities from my roles:

- **Talent 500**: "Designed and delivered real-time CDC ingestion using Kafka + Debezium + AWS EMR for cross-platform data replication"
- **Publicis Sapient / Goldman Sachs**: "Engineered and maintained Databricks-based lakehouse pipelines with Spark Structured Streaming"
- **Current (JLP)**: "Real-time clickstream processing with Adobe Analytics feed integration"

## License

MIT — see [LICENSE](LICENSE).
