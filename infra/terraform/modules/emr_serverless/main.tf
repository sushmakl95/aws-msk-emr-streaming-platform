variable "name_prefix" { type = string }
variable "subnet_ids" { type = list(string) }
variable "security_group_id" { type = string }
variable "release_label" { type = string }

resource "aws_emrserverless_application" "spark" {
  name          = "${var.name_prefix}-emr-serverless-spark"
  release_label = var.release_label
  type          = "Spark"

  initial_capacity {
    initial_capacity_type = "DRIVER"
    initial_capacity_config {
      worker_count = 1
      worker_configuration {
        cpu    = "2 vCPU"
        memory = "8 GB"
      }
    }
  }

  initial_capacity {
    initial_capacity_type = "EXECUTOR"
    initial_capacity_config {
      worker_count = 2
      worker_configuration {
        cpu    = "4 vCPU"
        memory = "16 GB"
      }
    }
  }

  maximum_capacity {
    cpu    = "100 vCPU"
    memory = "400 GB"
  }

  auto_start_configuration {
    enabled = true
  }

  auto_stop_configuration {
    enabled              = true
    idle_timeout_minutes = 15
  }

  network_configuration {
    subnet_ids         = var.subnet_ids
    security_group_ids = [var.security_group_id]
  }
}

output "application_id" { value = aws_emrserverless_application.spark.id }
output "application_arn" { value = aws_emrserverless_application.spark.arn }
