variable "name_prefix" { type = string }
variable "subnet_ids" { type = list(string) }
variable "security_group_id" { type = string }
variable "service_role_arn" { type = string }
variable "application_code_s3" { type = string }

resource "aws_cloudwatch_log_group" "flink" {
  name              = "/aws/kinesisanalytics/${var.name_prefix}-flink"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_stream" "flink" {
  name           = "flink-log-stream"
  log_group_name = aws_cloudwatch_log_group.flink.name
}

resource "aws_kinesisanalyticsv2_application" "orders_enrichment" {
  name                   = "${var.name_prefix}-orders-enrichment"
  runtime_environment    = "FLINK-1_18"
  service_execution_role = var.service_role_arn

  application_configuration {
    application_code_configuration {
      code_content {
        s3_content_location {
          bucket_arn = "arn:aws:s3:::${var.application_code_s3}"
          file_key   = "flink/orders_enrichment.zip"
        }
      }
      code_content_type = "ZIPFILE"
    }

    environment_properties {
      property_group {
        property_group_id = "kinesis.analytics.flink.run.options"
        property_map = {
          "python"   = "orders_enrichment.py"
          "jarfile"  = "lib/flink-sql-connector-kafka-3.1.0-1.18.jar"
        }
      }
    }

    flink_application_configuration {
      checkpoint_configuration {
        configuration_type = "CUSTOM"
        checkpointing_enabled = true
        checkpoint_interval   = 30000
        min_pause_between_checkpoints = 5000
      }

      monitoring_configuration {
        configuration_type = "CUSTOM"
        log_level          = "INFO"
        metrics_level      = "APPLICATION"
      }

      parallelism_configuration {
        configuration_type   = "CUSTOM"
        auto_scaling_enabled = true
        parallelism          = 2
        parallelism_per_kpu  = 1
      }
    }

    vpc_configuration {
      subnet_ids         = var.subnet_ids
      security_group_ids = [var.security_group_id]
    }
  }

  cloudwatch_logging_options {
    log_stream_arn = aws_cloudwatch_log_stream.flink.arn
  }

  lifecycle {
    ignore_changes = [
      application_configuration[0].application_code_configuration[0].code_content,
    ]
  }
}

output "application_name" { value = aws_kinesisanalyticsv2_application.orders_enrichment.name }
output "application_arn" { value = aws_kinesisanalyticsv2_application.orders_enrichment.arn }
