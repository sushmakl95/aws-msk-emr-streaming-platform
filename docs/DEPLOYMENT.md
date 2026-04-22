# Deployment Guide

## Prerequisites

- AWS account with admin for bootstrap
- Terraform >= 1.5
- `kubectl` (for EMR on EKS post-config)
- Databricks workspace (optional, for comparison track)

## Bootstrap (once per account)

```bash
aws s3 mb s3://streaming-platform-tfstate-<suffix>
aws dynamodb create-table \
  --table-name streaming-platform-tfstate-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

## Per-environment deploy

### 1. Configure

```bash
cp infra/terraform/envs/dev.tfvars.example infra/terraform/envs/dev.tfvars
cp infra/terraform/envs/dev.backend.hcl.example infra/terraform/envs/dev.backend.hcl
```

Edit both: fill in Databricks token, source DB credentials, alarm emails, etc.

### 2. Build Lambda zip + upload plugins

Before Terraform apply, MSK Connect needs plugin ZIPs in S3 (bootstrap chicken-and-egg — create the S3 bucket first, upload, then wire up the rest):

```bash
# Stage 1: create just the S3 buckets
cd infra/terraform
terraform init -backend-config=envs/dev.backend.hcl
terraform apply -var-file=envs/dev.tfvars -target=module.s3

# Upload plugins to the plugins bucket
bash scripts/upload-connect-plugins.sh dev

# Stage 2: full apply
terraform apply -var-file=envs/dev.tfvars
```

Takes ~25-35 min on a fresh account. MSK cluster provisioning is the slowest step.

### 3. Register connectors

```bash
bash scripts/deploy-connectors.sh dev
```

### 4. Create topics

```bash
streaming create-topics \
  --bootstrap-servers $(terraform output -raw msk_bootstrap_brokers_iam) \
  --config-file config/topics.yaml
```

### 5. Deploy Flink app

```bash
# Zip the Flink code
cd src/flink && zip ../../dist/flink-orders.zip . && cd -

# Upload
aws s3 cp dist/flink-orders.zip s3://$(terraform output -raw flink_apps_bucket)/flink/

# Start
streaming submit-flink --application-name streaming-platform-dev-orders-enrichment
```

### 6. Submit first Spark job to EMR

```bash
# Upload job code to S3
aws s3 cp src/streaming/jobs/orders_cdc_enrichment.py \
  s3://$(terraform output -raw checkpoints_bucket)/jobs/

# Submit
streaming submit-emr \
  --runtime serverless \
  --application-id $(terraform output -raw emr_serverless_application_id) \
  --role-arn $(terraform output -raw emr_execution_role_arn) \
  --job-name orders-cdc-enrichment-1 \
  --entry-point s3://.../orders_cdc_enrichment.py \
  --entry-args --bootstrap-servers=... \
  --entry-args --checkpoint-location=s3://...
```

## Verifying the deployment

```bash
# Check MSK
aws kafka describe-cluster-v2 \
  --cluster-arn $(terraform output -raw msk_cluster_arn) \
  --query 'ClusterInfo.State'
# Should be ACTIVE

# Check Flink
aws kinesisanalyticsv2 describe-application \
  --application-name $(terraform output -raw flink_application_name) \
  --query 'ApplicationDetail.ApplicationStatus'

# Check EMR
aws emr-serverless get-application \
  --application-id $(terraform output -raw emr_serverless_application_id) \
  --query 'application.state'

# Check Redis
redis-cli -h $(terraform output -raw redis_endpoint) --tls ping
# Should return PONG

# Open dashboard
echo "Dashboard: https://us-east-1.console.aws.amazon.com/cloudwatch/home?dashboard=..."
```

## CI/CD

`.github/workflows/ci.yml` runs on every push:
1. Ruff lint
2. mypy typecheck (non-blocking)
3. Bandit security scan
4. Validate MSK Connect configs
5. Terraform validate
6. Unit test notes

For automatic deployment:
- `deploy-dev.yml` on merge to main → `terraform apply` to dev
- `deploy-staging.yml` on tag `v*-rc*`
- `deploy-prod.yml` on tag `v*` (non-RC) after 24h in staging

## Disaster recovery

See `docs/MSK_OPERATIONS.md` for MSK DR procedure. Short version:
- Primary cluster down → cut consumers + producers to secondary
- MirrorMaker 2 replicates primary → secondary every 30s
- On primary recovery: MM2 replicates secondary → primary
- Cut producers + consumers back

Runs quarterly in a game-day exercise.

## Teardown

```bash
terraform destroy -var-file=envs/dev.tfvars
```

**Data loss warnings:**
- MSK topics + broker logs are gone
- Iceberg warehouse data preserved in S3 (but can't read without glue catalog)
- Secrets Manager entries have a 7-day recovery window
- CloudWatch logs retained per retention period

For prod: **never run destroy.** Decommission selectively with documented change management.
