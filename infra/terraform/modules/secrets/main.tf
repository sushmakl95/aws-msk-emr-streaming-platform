variable "name_prefix" { type = string }
variable "kms_key_arn" { type = string }
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
variable "clickhouse_password" {
  type      = string
  sensitive = true
  default   = ""
}
variable "opensearch_password" {
  type      = string
  sensitive = true
  default   = ""
}
variable "databricks_token" {
  type      = string
  sensitive = true
  default   = ""
}

locals {
  credentials = {
    postgres   = { value = var.postgres_password, enabled = var.postgres_password != "" }
    mysql      = { value = var.mysql_password, enabled = var.mysql_password != "" }
    mongo      = { value = var.mongo_connection, enabled = var.mongo_connection != "" }
    clickhouse = { value = var.clickhouse_password, enabled = var.clickhouse_password != "" }
    opensearch = { value = var.opensearch_password, enabled = var.opensearch_password != "" }
    databricks = { value = var.databricks_token, enabled = var.databricks_token != "" }
  }
  enabled_credentials = { for k, v in local.credentials : k => v if v.enabled }
}

resource "aws_secretsmanager_secret" "credentials" {
  for_each    = nonsensitive(toset(keys(local.enabled_credentials)))
  name        = "${var.name_prefix}/${each.value}"
  kms_key_id  = var.kms_key_arn
  description = "${each.value} credentials for streaming platform"
}

resource "aws_secretsmanager_secret_version" "credentials" {
  for_each      = nonsensitive(toset(keys(local.enabled_credentials)))
  secret_id     = aws_secretsmanager_secret.credentials[each.value].id
  secret_string = local.enabled_credentials[each.value].value
}

output "credential_secret_ids" {
  value = { for k, s in aws_secretsmanager_secret.credentials : k => s.id }
}
