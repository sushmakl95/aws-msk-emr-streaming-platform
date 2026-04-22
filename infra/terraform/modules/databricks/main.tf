terraform {
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.40"
    }
  }
}

variable "name_prefix" { type = string }
variable "iceberg_warehouse_s3" { type = string }
variable "msk_bootstrap_servers" { type = string }
variable "execution_instance_profile_arn" { type = string }

# -----------------------------------------------------------------------------
# Register instance profile with Databricks
# -----------------------------------------------------------------------------
resource "databricks_instance_profile" "this" {
  instance_profile_arn = var.execution_instance_profile_arn
}

# -----------------------------------------------------------------------------
# Cluster policy for streaming workloads
# -----------------------------------------------------------------------------
resource "databricks_cluster_policy" "streaming" {
  name = "${var.name_prefix}-streaming-policy"
  definition = jsonencode({
    "spark_version" : {
      "type" : "fixed",
      "value" : "14.3.x-scala2.12"
    },
    "node_type_id" : {
      "type" : "allowlist",
      "values" : ["i3.xlarge", "i3.2xlarge", "r5.xlarge"]
    },
    "autotermination_minutes" : {
      "type" : "fixed",
      "value" : 0
    },
    "aws_attributes.instance_profile_arn" : {
      "type" : "fixed",
      "value" : var.execution_instance_profile_arn
    },
    "aws_attributes.availability" : {
      "type" : "fixed",
      "value" : "SPOT_WITH_FALLBACK"
    },
    "custom_tags.Project" : {
      "type" : "fixed",
      "value" : var.name_prefix
    },
  })
}

# -----------------------------------------------------------------------------
# Comparison job — runs the same workload as the EMR track for benchmarking
# -----------------------------------------------------------------------------
resource "databricks_job" "comparison" {
  name = "${var.name_prefix}-streaming-comparison"

  job_cluster {
    job_cluster_key = "streaming-cluster"
    new_cluster {
      policy_id     = databricks_cluster_policy.streaming.id
      spark_version = "14.3.x-scala2.12"
      node_type_id  = "i3.xlarge"
      num_workers   = 2
      aws_attributes {
        first_on_demand        = 1
        availability           = "SPOT_WITH_FALLBACK"
        instance_profile_arn   = var.execution_instance_profile_arn
        spot_bid_price_percent = 100
      }
      custom_tags = {
        Project = var.name_prefix
      }
    }
  }

  task {
    task_key        = "orders_cdc_comparison"
    job_cluster_key = "streaming-cluster"
    max_retries     = 1
    notebook_task {
      notebook_path = "/Shared/streaming-platform/01_orders_cdc_comparison"
      base_parameters = {
        msk_bootstrap_servers = var.msk_bootstrap_servers
        iceberg_warehouse_s3  = var.iceberg_warehouse_s3
      }
    }
  }

  continuous {
    pause_status = "PAUSED"
  }

  timeout_seconds     = 0 # long-running
  max_concurrent_runs = 1
}

output "comparison_job_id" { value = tostring(databricks_job.comparison.id) }
output "cluster_policy_id" { value = databricks_cluster_policy.streaming.id }
