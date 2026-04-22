terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
    databricks = {
      source                = "databricks/databricks"
      version               = "~> 1.40"
      configuration_aliases = [databricks.workspace]
    }
  }

  backend "s3" {
    # Configured via -backend-config
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
      Repo        = "aws-msk-emr-streaming-platform"
      CostCenter  = var.cost_center
    }
  }
}

provider "databricks" {
  alias = "workspace"
  host  = var.databricks_workspace_url
  token = var.databricks_token
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

# -----------------------------------------------------------------------------
# Foundation
# -----------------------------------------------------------------------------
module "vpc" {
  source             = "./modules/vpc"
  name_prefix        = local.name_prefix
  vpc_cidr_block     = var.vpc_cidr_block
  availability_zones = var.availability_zones
}

module "kms" {
  source      = "./modules/kms"
  name_prefix = local.name_prefix
}

module "s3" {
  source      = "./modules/s3"
  name_prefix = local.name_prefix
  kms_key_arn = module.kms.s3_key_arn
}

module "secrets" {
  source                = "./modules/secrets"
  name_prefix           = local.name_prefix
  kms_key_arn           = module.kms.secrets_key_arn
  postgres_password     = var.postgres_password
  mysql_password        = var.mysql_password
  mongo_connection      = var.mongo_connection
  clickhouse_password   = var.clickhouse_password
  opensearch_password   = var.opensearch_password
  databricks_token      = var.databricks_token
}

module "iam" {
  source                     = "./modules/iam"
  name_prefix                = local.name_prefix
  s3_bucket_arns             = module.s3.all_bucket_arns
  msk_cluster_arn            = module.msk.cluster_arn
  kms_key_arns               = module.kms.all_key_arns
  connect_plugin_bucket_arn  = module.s3.plugins_bucket_arn
  iceberg_warehouse_arn      = module.s3.iceberg_warehouse_arn
}

# -----------------------------------------------------------------------------
# Event bus
# -----------------------------------------------------------------------------
module "msk" {
  source              = "./modules/msk"
  name_prefix         = local.name_prefix
  vpc_id              = module.vpc.vpc_id
  subnet_ids          = module.vpc.private_subnet_ids
  kms_key_arn         = module.kms.msk_key_arn
  broker_count        = var.msk_broker_count
  broker_instance_type = var.msk_broker_instance_type
  ebs_volume_size_gb  = var.msk_ebs_volume_size_gb
  kafka_version       = var.msk_kafka_version
}

module "msk_connect" {
  source                = "./modules/msk_connect"
  name_prefix           = local.name_prefix
  subnet_ids            = module.vpc.private_subnet_ids
  security_group_id     = module.msk.client_security_group_id
  plugins_bucket        = module.s3.plugins_bucket_name
  bootstrap_servers     = module.msk.bootstrap_brokers_sasl_iam
  service_role_arn      = module.iam.msk_connect_role_arn
  enable_debezium_pg    = var.enable_debezium_pg
  enable_s3_sink        = var.enable_s3_sink
  cold_archive_bucket   = module.s3.cold_archive_bucket_name
  postgres_host         = var.postgres_host
}

# -----------------------------------------------------------------------------
# Streaming compute
# -----------------------------------------------------------------------------
module "emr_eks" {
  source                = "./modules/emr_eks"
  name_prefix           = local.name_prefix
  subnet_ids            = module.vpc.private_subnet_ids
  vpc_id                = module.vpc.vpc_id
  kms_key_arn           = module.kms.eks_key_arn
  execution_role_arn    = module.iam.emr_execution_role_arn
  cluster_version       = var.eks_cluster_version
}

module "emr_serverless" {
  source              = "./modules/emr_serverless"
  name_prefix         = local.name_prefix
  subnet_ids          = module.vpc.private_subnet_ids
  security_group_id   = module.msk.client_security_group_id
  release_label       = var.emr_serverless_release_label
}

module "kinesis" {
  source         = "./modules/kinesis"
  name_prefix    = local.name_prefix
  kms_key_arn    = module.kms.kinesis_key_arn
  shard_count    = var.kinesis_shard_count
}

module "flink" {
  source                = "./modules/flink"
  name_prefix           = local.name_prefix
  subnet_ids            = module.vpc.private_subnet_ids
  security_group_id     = module.msk.client_security_group_id
  service_role_arn      = module.iam.flink_role_arn
  application_code_s3   = module.s3.flink_apps_bucket_name
}

# -----------------------------------------------------------------------------
# Sinks
# -----------------------------------------------------------------------------
module "elasticache" {
  source           = "./modules/elasticache"
  name_prefix      = local.name_prefix
  vpc_id           = module.vpc.vpc_id
  subnet_ids       = module.vpc.private_subnet_ids
  kms_key_arn      = module.kms.elasticache_key_arn
  node_type        = var.redis_node_type
}

module "opensearch" {
  source           = "./modules/opensearch"
  name_prefix      = local.name_prefix
  vpc_id           = module.vpc.vpc_id
  subnet_ids       = slice(module.vpc.private_subnet_ids, 0, 2)
  kms_key_arn      = module.kms.opensearch_key_arn
  instance_type    = var.opensearch_instance_type
  instance_count   = var.opensearch_instance_count
  master_password  = var.opensearch_password
}

module "ecs_clickhouse" {
  source              = "./modules/ecs_clickhouse"
  name_prefix         = local.name_prefix
  vpc_id              = module.vpc.vpc_id
  subnet_ids          = module.vpc.private_subnet_ids
  clickhouse_password = var.clickhouse_password
  task_cpu            = var.clickhouse_task_cpu
  task_memory         = var.clickhouse_task_memory
  desired_count       = var.clickhouse_desired_count
}

# -----------------------------------------------------------------------------
# Client-facing
# -----------------------------------------------------------------------------
module "apigw_websocket" {
  source                = "./modules/apigw_websocket"
  name_prefix           = local.name_prefix
  connect_lambda_arn    = module.lambda.ws_connect_arn
  disconnect_lambda_arn = module.lambda.ws_disconnect_arn
}

module "lambda" {
  source                 = "./modules/lambda"
  name_prefix            = local.name_prefix
  subnet_ids             = module.vpc.private_subnet_ids
  security_group_id      = module.msk.client_security_group_id
  connections_table_name = module.dynamodb.connections_table_name
  connections_table_arn  = module.dynamodb.connections_table_arn
  msk_cluster_arn        = module.msk.cluster_arn
  ws_broadcast_topic     = "ws-broadcast"
  execution_role_arn     = module.iam.lambda_role_arn
  ws_endpoint            = module.apigw_websocket.ws_management_endpoint
}

module "dynamodb" {
  source      = "./modules/dynamodb"
  name_prefix = local.name_prefix
  kms_key_arn = module.kms.dynamodb_key_arn
}

# -----------------------------------------------------------------------------
# Databricks comparison track
# -----------------------------------------------------------------------------
module "databricks" {
  source = "./modules/databricks"
  providers = {
    databricks = databricks.workspace
  }

  name_prefix             = local.name_prefix
  iceberg_warehouse_s3    = module.s3.iceberg_warehouse_name
  msk_bootstrap_servers   = module.msk.bootstrap_brokers_sasl_iam
  execution_instance_profile_arn = module.iam.databricks_instance_profile_arn
}

# -----------------------------------------------------------------------------
# Observability
# -----------------------------------------------------------------------------
module "monitoring" {
  source                 = "./modules/monitoring"
  name_prefix            = local.name_prefix
  msk_cluster_name       = module.msk.cluster_name
  emr_application_id     = module.emr_serverless.application_id
  kda_application_name   = module.flink.application_name
  lambda_function_names  = module.lambda.all_function_names
  alarm_email_recipients = var.alarm_email_recipients
  monthly_budget_usd     = var.monthly_budget_usd
  log_retention_days     = var.log_retention_days
}
