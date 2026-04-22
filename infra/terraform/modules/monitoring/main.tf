variable "name_prefix" { type = string }
variable "msk_cluster_name" { type = string }
variable "emr_application_id" { type = string }
variable "kda_application_name" { type = string }
variable "lambda_function_names" { type = list(string) }
variable "alarm_email_recipients" { type = list(string) }
variable "monthly_budget_usd" { type = number }
variable "log_retention_days" { type = number }

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# -----------------------------------------------------------------------------
# SNS for alerts
# -----------------------------------------------------------------------------
resource "aws_sns_topic" "alerts" {
  name = "${var.name_prefix}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  for_each  = toset(var.alarm_email_recipients)
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = each.value
}

# -----------------------------------------------------------------------------
# CloudWatch log groups for Lambdas
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "lambdas" {
  for_each          = toset(var.lambda_function_names)
  name              = "/aws/lambda/${each.value}"
  retention_in_days = var.log_retention_days
}

# -----------------------------------------------------------------------------
# MSK broker alarms
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "msk_under_replicated" {
  alarm_name          = "${var.name_prefix}-msk-under-replicated"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "UnderReplicatedPartitions"
  namespace           = "AWS/Kafka"
  period              = 300
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    "Cluster Name" = var.msk_cluster_name
  }

  alarm_description = "MSK has under-replicated partitions — broker at risk"
  alarm_actions     = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "msk_disk_usage" {
  alarm_name          = "${var.name_prefix}-msk-disk-usage"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "KafkaDataLogsDiskUsed"
  namespace           = "AWS/Kafka"
  period              = 300
  statistic           = "Maximum"
  threshold           = 75
  treat_missing_data  = "notBreaching"

  dimensions = {
    "Cluster Name" = var.msk_cluster_name
  }

  alarm_description = "MSK broker disk usage > 75%"
  alarm_actions     = [aws_sns_topic.alerts.arn]
}

# -----------------------------------------------------------------------------
# Lambda error alarms
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each            = toset(var.lambda_function_names)
  alarm_name          = "${var.name_prefix}-lambda-errors-${each.value}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = each.value
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

# -----------------------------------------------------------------------------
# KDA (Flink) downtime
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "kda_downtime" {
  alarm_name          = "${var.name_prefix}-kda-downtime"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "downtime"
  namespace           = "AWS/KinesisAnalytics"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    Application = var.kda_application_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

# -----------------------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_dashboard" "streaming" {
  dashboard_name = "${var.name_prefix}-streaming"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Kafka", "BytesInPerSec", "Cluster Name", var.msk_cluster_name],
            [".", "BytesOutPerSec", ".", "."],
          ]
          period = 60
          stat   = "Average"
          region = data.aws_region.current.name
          title  = "MSK Throughput"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Kafka", "UnderReplicatedPartitions", "Cluster Name", var.msk_cluster_name],
            [".", "OfflinePartitionsCount", ".", "."],
            [".", "ActiveControllerCount", ".", "."],
          ]
          period = 60
          stat   = "Maximum"
          region = data.aws_region.current.name
          title  = "MSK Health"
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/KinesisAnalytics", "lastCheckpointDuration", "Application", var.kda_application_name],
            [".", "fullRestarts", ".", "."],
            [".", "numLateRecordsDropped", ".", "."],
          ]
          period = 300
          stat   = "Sum"
          region = data.aws_region.current.name
          title  = "Flink Pipeline Health"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            for fn in var.lambda_function_names :
            ["AWS/Lambda", "Duration", "FunctionName", fn]
          ]
          period = 300
          stat   = "Average"
          region = data.aws_region.current.name
          title  = "Lambda Duration"
        }
      },
    ]
  })
}

# -----------------------------------------------------------------------------
# Budget + cost anomaly
# -----------------------------------------------------------------------------
resource "aws_budgets_budget" "monthly" {
  name              = "${var.name_prefix}-monthly"
  budget_type       = "COST"
  limit_amount      = tostring(var.monthly_budget_usd)
  limit_unit        = "USD"
  time_unit         = "MONTHLY"
  time_period_start = "2026-01-01_00:00"

  cost_filter {
    name   = "TagKeyValue"
    values = ["Project$${var.name_prefix}"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.alarm_email_recipients
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.alarm_email_recipients
  }
}

output "dashboard_url" {
  value = "https://${data.aws_region.current.name}.console.aws.amazon.com/cloudwatch/home?region=${data.aws_region.current.name}#dashboards:name=${aws_cloudwatch_dashboard.streaming.dashboard_name}"
}
output "alerts_topic_arn" { value = aws_sns_topic.alerts.arn }
