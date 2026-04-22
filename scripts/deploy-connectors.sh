#!/usr/bin/env bash
# Deploy MSK Connect connectors in a given AWS environment.
# Usage: bash scripts/deploy-connectors.sh <env>

set -euo pipefail

ENV="${1:-}"
if [[ -z "$ENV" ]]; then
    echo "Usage: $0 <dev|staging|prod>"
    exit 1
fi

echo "=== Validating configs ==="
python scripts/validate_connect_configs.py mskconnect/

cd infra/terraform
PLUGIN_DEBEZIUM_PG=$(terraform output -raw -module=msk_connect plugin_debezium_pg_arn 2>/dev/null || echo "")
PLUGIN_S3_SINK=$(terraform output -raw -module=msk_connect plugin_s3_sink_arn 2>/dev/null || echo "")
WORKER_CONFIG=$(terraform output -raw -module=msk_connect worker_config_arn 2>/dev/null || echo "")
LOG_GROUP=$(terraform output -raw -module=msk_connect log_group_name 2>/dev/null || echo "")
cd -

if [[ -z "$PLUGIN_DEBEZIUM_PG" ]]; then
    echo "Plugins not deployed yet. Run: terraform apply"
    exit 1
fi

echo "=== Rendering config files with env vars ==="
mkdir -p dist/connectors
for properties_file in mskconnect/debezium/*.properties mskconnect/s3sink/*.properties; do
    rendered="dist/connectors/$(basename $properties_file)"
    envsubst < "$properties_file" > "$rendered"
done

echo "=== Creating / updating connectors via AWS MSK Connect ==="
# Note: AWS CLI v2 supports `kafkaconnect create-connector`
for properties_file in dist/connectors/*.properties; do
    echo "Deploying: $properties_file"
    # Convert .properties to JSON key-value map
    # (implementation left as TODO - use kafkaconnect create-connector)
    echo "  (Placeholder - use kafkaconnect create-connector AWS CLI)"
done

echo "Done."
