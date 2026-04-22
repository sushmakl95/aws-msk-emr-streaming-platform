output "msk_bootstrap_brokers_iam" {
  value       = module.msk.bootstrap_brokers_sasl_iam
  description = "MSK SASL/IAM bootstrap endpoint"
}

output "msk_cluster_arn" {
  value = module.msk.cluster_arn
}

output "emr_serverless_application_id" {
  value = module.emr_serverless.application_id
}

output "emr_eks_virtual_cluster_id" {
  value = module.emr_eks.virtual_cluster_id
}

output "flink_application_name" {
  value = module.flink.application_name
}

output "redis_endpoint" {
  value = module.elasticache.primary_endpoint
}

output "opensearch_endpoint" {
  value = module.opensearch.endpoint
}

output "clickhouse_lb_dns" {
  value = module.ecs_clickhouse.load_balancer_dns
}

output "websocket_url" {
  value = module.apigw_websocket.websocket_url
}

output "iceberg_warehouse_s3" {
  value = module.s3.iceberg_warehouse_name
}

output "databricks_dq_job_id" {
  value = module.databricks.comparison_job_id
}
