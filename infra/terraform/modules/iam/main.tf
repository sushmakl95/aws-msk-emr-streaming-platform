variable "name_prefix" { type = string }
variable "s3_bucket_arns" { type = list(string) }
variable "msk_cluster_arn" { type = string }
variable "kms_key_arns" { type = list(string) }
variable "connect_plugin_bucket_arn" { type = string }
variable "iceberg_warehouse_arn" { type = string }

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  msk_resource_prefix = "arn:aws:kafka:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}"
}

# -----------------------------------------------------------------------------
# Lambda execution role
# -----------------------------------------------------------------------------
resource "aws_iam_role" "lambda" {
  name = "${var.name_prefix}-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "lambda_msk_and_ddb" {
  name = "${var.name_prefix}-lambda-access"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kafka-cluster:Connect",
          "kafka-cluster:ReadData",
          "kafka-cluster:WriteData",
          "kafka-cluster:DescribeTopic",
          "kafka-cluster:CreateTopic",
          "kafka-cluster:AlterTopic",
          "kafka-cluster:AlterCluster",
          "kafka-cluster:DescribeCluster",
          "kafka-cluster:DescribeGroup",
          "kafka-cluster:AlterGroup",
        ]
        Resource = [
          var.msk_cluster_arn,
          "${local.msk_resource_prefix}:topic/${var.name_prefix}/*/*",
          "${local.msk_resource_prefix}:group/${var.name_prefix}/*/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem",
          "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:Scan",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "execute-api:ManageConnections",
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = var.kms_key_arns
      },
    ]
  })
}

# -----------------------------------------------------------------------------
# EMR execution role
# -----------------------------------------------------------------------------
resource "aws_iam_role" "emr_execution" {
  name = "${var.name_prefix}-emr-execution-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = ["emr-containers.amazonaws.com", "emr-serverless.amazonaws.com"]
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "emr_access" {
  name = "${var.name_prefix}-emr-access"
  role = aws_iam_role.emr_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject", "s3:PutObject", "s3:ListBucket",
          "s3:DeleteObject", "s3:GetBucketLocation",
        ]
        Resource = concat(
          var.s3_bucket_arns,
          [for arn in var.s3_bucket_arns : "${arn}/*"],
        )
      },
      {
        Effect = "Allow"
        Action = [
          "kafka-cluster:Connect", "kafka-cluster:ReadData",
          "kafka-cluster:WriteData", "kafka-cluster:DescribeTopic",
          "kafka-cluster:DescribeCluster", "kafka-cluster:DescribeGroup",
          "kafka-cluster:AlterGroup",
        ]
        Resource = [
          var.msk_cluster_arn,
          "${local.msk_resource_prefix}:topic/${var.name_prefix}/*/*",
          "${local.msk_resource_prefix}:group/${var.name_prefix}/*/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["glue:*"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = var.kms_key_arns
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "*"
      },
    ]
  })
}

# -----------------------------------------------------------------------------
# MSK Connect service role
# -----------------------------------------------------------------------------
resource "aws_iam_role" "msk_connect" {
  name = "${var.name_prefix}-connect-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "kafkaconnect.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "msk_connect" {
  role = aws_iam_role.msk_connect.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kafka-cluster:Connect", "kafka-cluster:DescribeCluster",
          "kafka-cluster:ReadData", "kafka-cluster:WriteData",
          "kafka-cluster:CreateTopic", "kafka-cluster:DescribeTopic",
          "kafka-cluster:AlterTopic", "kafka-cluster:DescribeGroup",
          "kafka-cluster:AlterGroup",
        ]
        Resource = [
          var.msk_cluster_arn,
          "${local.msk_resource_prefix}:topic/${var.name_prefix}/*/*",
          "${local.msk_resource_prefix}:group/${var.name_prefix}/*/*",
        ]
      },
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          var.connect_plugin_bucket_arn,
          "${var.connect_plugin_bucket_arn}/*",
        ]
      },
      {
        Effect = "Allow"
        Action = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
        Resource = concat(var.s3_bucket_arns, [for arn in var.s3_bucket_arns : "${arn}/*"])
      },
      {
        Effect   = "Allow"
        Action   = ["glue:GetSchema*", "glue:RegisterSchemaVersion", "glue:PutSchemaVersionMetadata", "glue:CreateSchema"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "*"
      },
    ]
  })
}

# -----------------------------------------------------------------------------
# Flink / KDA service role
# -----------------------------------------------------------------------------
resource "aws_iam_role" "flink" {
  name = "${var.name_prefix}-flink-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "kinesisanalytics.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "flink" {
  role = aws_iam_role.flink.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = concat(var.s3_bucket_arns, [for arn in var.s3_bucket_arns : "${arn}/*"])
      },
      {
        Effect = "Allow"
        Action = [
          "kafka-cluster:Connect", "kafka-cluster:ReadData",
          "kafka-cluster:DescribeTopic", "kafka-cluster:DescribeGroup",
          "kafka-cluster:AlterGroup",
        ]
        Resource = [
          var.msk_cluster_arn,
          "${local.msk_resource_prefix}:topic/${var.name_prefix}/*/*",
          "${local.msk_resource_prefix}:group/${var.name_prefix}/*/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogGroups"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
      },
    ]
  })
}

# -----------------------------------------------------------------------------
# Databricks instance profile (used by Databricks comparison clusters)
# -----------------------------------------------------------------------------
resource "aws_iam_role" "databricks" {
  name = "${var.name_prefix}-databricks-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = "arn:aws:iam::414351767826:root" } # Databricks account
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "sts:ExternalId" = var.name_prefix }
      }
    }]
  })
}

resource "aws_iam_role_policy" "databricks" {
  role = aws_iam_role.databricks.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject",
        ]
        Resource = [var.iceberg_warehouse_arn, "${var.iceberg_warehouse_arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["kafka-cluster:Connect", "kafka-cluster:ReadData", "kafka-cluster:DescribeTopic"]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_instance_profile" "databricks" {
  name = "${var.name_prefix}-databricks-profile"
  role = aws_iam_role.databricks.name
}

output "lambda_role_arn" { value = aws_iam_role.lambda.arn }
output "emr_execution_role_arn" { value = aws_iam_role.emr_execution.arn }
output "msk_connect_role_arn" { value = aws_iam_role.msk_connect.arn }
output "flink_role_arn" { value = aws_iam_role.flink.arn }
output "databricks_instance_profile_arn" { value = aws_iam_instance_profile.databricks.arn }
