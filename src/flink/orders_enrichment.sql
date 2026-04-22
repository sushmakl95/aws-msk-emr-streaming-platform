-- -----------------------------------------------------------------------------
-- Flink SQL: Orders CDC enrichment (parallel to Spark Structured Streaming version)
-- -----------------------------------------------------------------------------
-- Runtime: Amazon Kinesis Data Analytics for Apache Flink (Flink 1.18)
-- Submit via:
--   aws kinesisanalyticsv2 create-application --application-name orders-enrichment
--   ... and upload this SQL + any UDF JARs to the application S3 location.
--
-- Equivalent to src/streaming/jobs/orders_cdc_enrichment.py but implemented in
-- Flink SQL. Use this side-by-side with the Spark version to compare runtime
-- behavior (see docs/RUNTIME_COMPARISON.md).
-- -----------------------------------------------------------------------------

-- Source: MSK CDC topic (Debezium format)
CREATE TABLE orders_cdc (
    order_id STRING,
    customer_id STRING,
    product_id STRING,
    qty BIGINT,
    total_amount DOUBLE,
    currency STRING,
    order_ts TIMESTAMP(3),
    -- CDC metadata columns (Debezium)
    `op` STRING METADATA FROM 'value.debezium-op',
    `source_ts_ms` BIGINT METADATA FROM 'value.source.timestamp',
    -- Event time from the source DB's commit timestamp
    event_time AS TO_TIMESTAMP_LTZ(source_ts_ms, 3),
    WATERMARK FOR event_time AS event_time - INTERVAL '10' SECOND
) WITH (
    'connector' = 'kafka',
    'topic' = 'cdc.public.orders',
    'properties.bootstrap.servers' = '${MSK_BOOTSTRAP_SERVERS}',
    'properties.security.protocol' = 'SASL_SSL',
    'properties.sasl.mechanism' = 'AWS_MSK_IAM',
    'properties.sasl.jaas.config' = 'software.amazon.msk.auth.iam.IAMLoginModule required;',
    'properties.sasl.client.callback.handler.class' = 'software.amazon.msk.auth.iam.IAMClientCallbackHandler',
    'scan.startup.mode' = 'latest-offset',
    'format' = 'debezium-json',
    'debezium-json.schema-include' = 'false'
);

-- Dimension: product catalog (Iceberg table via Glue catalog)
-- Uses temporal (versioned) table join semantics
CREATE TABLE product_catalog (
    product_id STRING,
    product_name STRING,
    category STRING,
    brand STRING,
    unit_cost DOUBLE,
    _updated_at TIMESTAMP(3),
    WATERMARK FOR _updated_at AS _updated_at - INTERVAL '1' HOUR,
    PRIMARY KEY (product_id) NOT ENFORCED
) WITH (
    'connector' = 'iceberg',
    'catalog-name' = 'glue_catalog',
    'catalog-database' = 'streaming',
    'warehouse' = '${ICEBERG_WAREHOUSE}',
    'format-version' = '2'
);

-- Sink 1: OpenSearch (warm)
CREATE TABLE orders_opensearch (
    order_id STRING,
    customer_id STRING,
    product_id STRING,
    product_name STRING,
    category STRING,
    qty BIGINT,
    total_amount DOUBLE,
    unit_cost DOUBLE,
    margin_amount DOUBLE,
    currency STRING,
    order_ts TIMESTAMP(3),
    event_time TIMESTAMP(3),
    PRIMARY KEY (order_id) NOT ENFORCED
) WITH (
    'connector' = 'opensearch-1',
    'hosts' = 'https://${OPENSEARCH_ENDPOINT}:443',
    'index' = 'orders-{order_ts|yyyy.MM.dd}',
    'format' = 'json',
    'sink.bulk-flush.max-actions' = '1000',
    'sink.bulk-flush.max-size' = '5mb',
    'sink.bulk-flush.interval' = '5s'
);

-- Sink 2: S3 Iceberg (cold)
CREATE TABLE orders_iceberg (
    order_id STRING,
    customer_id STRING,
    product_id STRING,
    product_name STRING,
    category STRING,
    qty BIGINT,
    total_amount DOUBLE,
    margin_amount DOUBLE,
    currency STRING,
    order_ts TIMESTAMP(3),
    event_time TIMESTAMP(3),
    event_date DATE
) PARTITIONED BY (event_date) WITH (
    'connector' = 'iceberg',
    'catalog-name' = 'glue_catalog',
    'catalog-database' = 'streaming',
    'catalog-table' = 'orders_events',
    'warehouse' = '${ICEBERG_WAREHOUSE}',
    'format-version' = '2',
    'write.format.default' = 'parquet',
    'write.parquet.compression-codec' = 'zstd'
);

-- Main query: enrich + fan out
-- Uses STATEMENT SET to write to both sinks in a single unified plan
BEGIN STATEMENT SET;

INSERT INTO orders_opensearch
SELECT
    o.order_id,
    o.customer_id,
    o.product_id,
    p.product_name,
    p.category,
    o.qty,
    o.total_amount,
    p.unit_cost,
    o.total_amount - (o.qty * p.unit_cost) AS margin_amount,
    o.currency,
    o.order_ts,
    o.event_time
FROM orders_cdc o
LEFT JOIN product_catalog FOR SYSTEM_TIME AS OF o.event_time AS p
    ON o.product_id = p.product_id
WHERE o.`op` IN ('c', 'u', 'r');

INSERT INTO orders_iceberg
SELECT
    o.order_id,
    o.customer_id,
    o.product_id,
    p.product_name,
    p.category,
    o.qty,
    o.total_amount,
    o.total_amount - (o.qty * p.unit_cost) AS margin_amount,
    o.currency,
    o.order_ts,
    o.event_time,
    CAST(o.order_ts AS DATE) AS event_date
FROM orders_cdc o
LEFT JOIN product_catalog FOR SYSTEM_TIME AS OF o.event_time AS p
    ON o.product_id = p.product_id
WHERE o.`op` IN ('c', 'u', 'r');

END;
