#!/usr/bin/env bash
# Register Debezium Postgres connector against the local kafka-connect container.
# Run after `make compose-up` once Postgres + Kafka Connect are healthy.

set -euo pipefail

echo "Waiting for Kafka Connect..."
until curl -sf http://localhost:8083/ > /dev/null; do
    sleep 2
done

echo "Registering Debezium Postgres connector..."

curl -X POST http://localhost:8083/connectors \
    -H "Content-Type: application/json" \
    -d '{
        "name": "postgres-orders-cdc-local",
        "config": {
            "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
            "tasks.max": "1",
            "database.hostname": "postgres",
            "database.port": "5432",
            "database.user": "debezium_user",
            "database.password": "debezium",
            "database.dbname": "analytics",
            "database.server.name": "pg-local",
            "plugin.name": "pgoutput",
            "slot.name": "debezium_orders_slot",
            "publication.name": "debezium_orders_pub",
            "table.include.list": "public.orders,public.order_items,public.customers",
            "topic.prefix": "cdc",
            "snapshot.mode": "initial",
            "tombstones.on.delete": "false",
            "include.schema.changes": "false",
            "schema.history.internal.kafka.topic": "__debezium-schema-history",
            "schema.history.internal.kafka.bootstrap.servers": "kafka:29092"
        }
    }'

echo
echo "Connector registered. Check status:"
echo "  curl http://localhost:8083/connectors/postgres-orders-cdc-local/status"
