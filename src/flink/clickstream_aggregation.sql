-- -----------------------------------------------------------------------------
-- Flink SQL: Clickstream real-time aggregations
-- -----------------------------------------------------------------------------
-- Parallel to src/streaming/jobs/clickstream_aggregation.py but in Flink SQL.
-- Demonstrates Flink's native windowing TVFs (TUMBLE, HOP, SESSION).
-- -----------------------------------------------------------------------------

CREATE TABLE clickstream (
    user_id STRING,
    session_id STRING,
    page_url STRING,
    referrer STRING,
    device_type STRING,
    country STRING,
    event_time TIMESTAMP(3),
    page_load_ms INT,
    WATERMARK FOR event_time AS event_time - INTERVAL '10' MINUTE
) WITH (
    'connector' = 'kafka',
    'topic' = 'app.clickstream',
    'properties.bootstrap.servers' = '${MSK_BOOTSTRAP_SERVERS}',
    'properties.security.protocol' = 'SASL_SSL',
    'properties.sasl.mechanism' = 'AWS_MSK_IAM',
    'properties.sasl.jaas.config' = 'software.amazon.msk.auth.iam.IAMLoginModule required;',
    'properties.sasl.client.callback.handler.class' = 'software.amazon.msk.auth.iam.IAMClientCallbackHandler',
    'scan.startup.mode' = 'latest-offset',
    'format' = 'json'
);

-- Sink: ClickHouse (warm OLAP)
CREATE TABLE country_page_views_5min (
    window_start TIMESTAMP(3),
    window_end TIMESTAMP(3),
    country STRING,
    device_type STRING,
    page_view_count BIGINT,
    avg_page_load_ms DOUBLE,
    PRIMARY KEY (window_start, country, device_type) NOT ENFORCED
) WITH (
    'connector' = 'clickhouse',
    'url' = 'jdbc:ch://${CLICKHOUSE_HOST}:8123/analytics',
    'table-name' = 'country_page_views_5min',
    'username' = '${CLICKHOUSE_USER}',
    'password' = '${CLICKHOUSE_PASSWORD}',
    'sink.batch-size' = '2000',
    'sink.flush-interval' = '5000',
    'sink.max-retries' = '3'
);

CREATE TABLE user_sessions (
    user_id STRING,
    session_start TIMESTAMP(3),
    session_end TIMESTAMP(3),
    page_view_count BIGINT,
    session_duration_sec BIGINT,
    PRIMARY KEY (user_id, session_start) NOT ENFORCED
) WITH (
    'connector' = 'clickhouse',
    'url' = 'jdbc:ch://${CLICKHOUSE_HOST}:8123/analytics',
    'table-name' = 'user_sessions',
    'username' = '${CLICKHOUSE_USER}',
    'password' = '${CLICKHOUSE_PASSWORD}'
);

-- Main queries
BEGIN STATEMENT SET;

-- HOP: 5-min window sliding every 1 min
INSERT INTO country_page_views_5min
SELECT
    window_start,
    window_end,
    country,
    device_type,
    COUNT(*) AS page_view_count,
    AVG(page_load_ms) AS avg_page_load_ms
FROM TABLE(
    HOP(
        TABLE clickstream,
        DESCRIPTOR(event_time),
        INTERVAL '1' MINUTE,
        INTERVAL '5' MINUTE
    )
)
GROUP BY window_start, window_end, country, device_type;

-- SESSION: per-user session with 30-min gap
INSERT INTO user_sessions
SELECT
    user_id,
    window_start AS session_start,
    window_end AS session_end,
    COUNT(page_url) AS page_view_count,
    TIMESTAMPDIFF(SECOND, window_start, window_end) AS session_duration_sec
FROM TABLE(
    SESSION(
        TABLE clickstream PARTITION BY user_id,
        DESCRIPTOR(event_time),
        INTERVAL '30' MINUTE
    )
)
GROUP BY user_id, window_start, window_end;

END;
