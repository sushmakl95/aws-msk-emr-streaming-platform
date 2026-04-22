variable "name_prefix" { type = string }
variable "subnet_ids" { type = list(string) }
variable "security_group_id" { type = string }
variable "plugins_bucket" { type = string }
variable "bootstrap_servers" { type = string }
variable "service_role_arn" { type = string }
variable "enable_debezium_pg" { type = bool }
variable "enable_s3_sink" { type = bool }
variable "cold_archive_bucket" { type = string }
variable "postgres_host" { type = string }

resource "aws_cloudwatch_log_group" "connect" {
  name              = "/aws/mskconnect/${var.name_prefix}"
  retention_in_days = 30
}

# -----------------------------------------------------------------------------
# Debezium Postgres plugin
# -----------------------------------------------------------------------------
resource "aws_mskconnect_custom_plugin" "debezium_pg" {
  count        = var.enable_debezium_pg ? 1 : 0
  name         = "${var.name_prefix}-debezium-pg"
  content_type = "ZIP"

  location {
    s3 {
      bucket_arn = "arn:aws:s3:::${var.plugins_bucket}"
      file_key   = "debezium-connector-postgres-2.5.0.zip"
    }
  }
}

# -----------------------------------------------------------------------------
# S3 sink plugin
# -----------------------------------------------------------------------------
resource "aws_mskconnect_custom_plugin" "s3_sink" {
  count        = var.enable_s3_sink ? 1 : 0
  name         = "${var.name_prefix}-s3-sink"
  content_type = "ZIP"

  location {
    s3 {
      bucket_arn = "arn:aws:s3:::${var.plugins_bucket}"
      file_key   = "confluentinc-kafka-connect-s3-10.5.13.zip"
    }
  }
}

# -----------------------------------------------------------------------------
# Worker configuration
# -----------------------------------------------------------------------------
resource "aws_mskconnect_worker_configuration" "default" {
  name = "${var.name_prefix}-worker-config"

  properties_file_content = <<EOT
key.converter=org.apache.kafka.connect.storage.StringConverter
value.converter=org.apache.kafka.connect.storage.StringConverter
key.converter.schemas.enable=false
value.converter.schemas.enable=false
EOT
}

# -----------------------------------------------------------------------------
# Debezium Postgres connector
# Note: connector configs are deployed post-infra via scripts/deploy-connectors.sh
# to avoid Terraform drift on frequently-updated source DB credentials.
# This module only creates the plugin + the service-role wiring.
# -----------------------------------------------------------------------------

output "plugin_debezium_pg_arn" {
  value = var.enable_debezium_pg ? aws_mskconnect_custom_plugin.debezium_pg[0].arn : ""
}
output "plugin_s3_sink_arn" {
  value = var.enable_s3_sink ? aws_mskconnect_custom_plugin.s3_sink[0].arn : ""
}
output "worker_config_arn" { value = aws_mskconnect_worker_configuration.default.arn }
output "log_group_name" { value = aws_cloudwatch_log_group.connect.name }
