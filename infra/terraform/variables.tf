variable "project_name" {
  type    = string
  default = "streaming-platform"
}

variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod"
  }
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "cost_center" {
  type    = string
  default = "data-platform"
}

variable "vpc_cidr_block" {
  type    = string
  default = "10.60.0.0/16"
}

variable "availability_zones" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

# -----------------------------------------------------------------------------
# MSK
# -----------------------------------------------------------------------------
variable "msk_broker_count" {
  type    = number
  default = 3
}

variable "msk_broker_instance_type" {
  type    = string
  default = "kafka.m5.xlarge"
}

variable "msk_ebs_volume_size_gb" {
  type    = number
  default = 500
}

variable "msk_kafka_version" {
  type    = string
  default = "3.6.0"
}

# -----------------------------------------------------------------------------
# MSK Connect
# -----------------------------------------------------------------------------
variable "enable_debezium_pg" {
  type    = bool
  default = true
}

variable "enable_s3_sink" {
  type    = bool
  default = true
}

variable "postgres_host" {
  type    = string
  default = ""
}

variable "postgres_password" {
  type      = string
  sensitive = true
  default   = ""
}

variable "mysql_password" {
  type      = string
  sensitive = true
  default   = ""
}

variable "mongo_connection" {
  type      = string
  sensitive = true
  default   = ""
}

# -----------------------------------------------------------------------------
# EKS / EMR
# -----------------------------------------------------------------------------
variable "eks_cluster_version" {
  type    = string
  default = "1.29"
}

variable "emr_serverless_release_label" {
  type    = string
  default = "emr-7.0.0"
}

# -----------------------------------------------------------------------------
# Kinesis
# -----------------------------------------------------------------------------
variable "kinesis_shard_count" {
  type    = number
  default = 4
}

# -----------------------------------------------------------------------------
# Sinks
# -----------------------------------------------------------------------------
variable "redis_node_type" {
  type    = string
  default = "cache.t4g.medium"
}

variable "opensearch_instance_type" {
  type    = string
  default = "t3.small.search"
}

variable "opensearch_instance_count" {
  type    = number
  default = 2
}

variable "opensearch_password" {
  type      = string
  sensitive = true
  default   = ""
}

variable "clickhouse_password" {
  type      = string
  sensitive = true
  default   = ""
}

variable "clickhouse_task_cpu" {
  type    = number
  default = 2048
}

variable "clickhouse_task_memory" {
  type    = number
  default = 8192
}

variable "clickhouse_desired_count" {
  type    = number
  default = 1
}

# -----------------------------------------------------------------------------
# Databricks
# -----------------------------------------------------------------------------
variable "databricks_workspace_url" {
  type    = string
  default = ""
}

variable "databricks_token" {
  type      = string
  sensitive = true
  default   = ""
}

# -----------------------------------------------------------------------------
# Observability
# -----------------------------------------------------------------------------
variable "alarm_email_recipients" {
  type    = list(string)
  default = []
}

variable "monthly_budget_usd" {
  type    = number
  default = 2000
}

variable "log_retention_days" {
  type    = number
  default = 30
}
