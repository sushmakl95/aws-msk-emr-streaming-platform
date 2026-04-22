variable "name_prefix" { type = string }
variable "subnet_ids" { type = list(string) }
variable "security_group_id" { type = string }
variable "connections_table_name" { type = string }
variable "connections_table_arn" { type = string }
variable "msk_cluster_arn" { type = string }
variable "ws_broadcast_topic" { type = string }
variable "execution_role_arn" { type = string }
variable "ws_endpoint" { type = string }

data "archive_file" "lambdas" {
  type        = "zip"
  source_dir  = "${path.module}/../../../../src"
  output_path = "${path.module}/lambdas.zip"
  excludes    = ["**/__pycache__/**", "**/*.pyc"]
}

# -----------------------------------------------------------------------------
# WebSocket $connect
# -----------------------------------------------------------------------------
resource "aws_lambda_function" "ws_connect" {
  function_name    = "${var.name_prefix}-ws-connect"
  role             = var.execution_role_arn
  runtime          = "python3.11"
  handler          = "lambdas.ws_connect.handler"
  filename         = data.archive_file.lambdas.output_path
  source_code_hash = data.archive_file.lambdas.output_base64sha256
  timeout          = 10
  memory_size      = 256

  environment {
    variables = {
      CONNECTIONS_TABLE = var.connections_table_name
    }
  }
}

# -----------------------------------------------------------------------------
# WebSocket $disconnect
# -----------------------------------------------------------------------------
resource "aws_lambda_function" "ws_disconnect" {
  function_name    = "${var.name_prefix}-ws-disconnect"
  role             = var.execution_role_arn
  runtime          = "python3.11"
  handler          = "lambdas.ws_disconnect.handler"
  filename         = data.archive_file.lambdas.output_path
  source_code_hash = data.archive_file.lambdas.output_base64sha256
  timeout          = 10
  memory_size      = 256

  environment {
    variables = {
      CONNECTIONS_TABLE = var.connections_table_name
    }
  }
}

# -----------------------------------------------------------------------------
# WebSocket broadcast (triggered by MSK topic ws-broadcast)
# -----------------------------------------------------------------------------
resource "aws_lambda_function" "ws_broadcast" {
  function_name    = "${var.name_prefix}-ws-broadcast"
  role             = var.execution_role_arn
  runtime          = "python3.11"
  handler          = "lambdas.ws_broadcast.handler"
  filename         = data.archive_file.lambdas.output_path
  source_code_hash = data.archive_file.lambdas.output_base64sha256
  timeout          = 60
  memory_size      = 512

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [var.security_group_id]
  }

  environment {
    variables = {
      CONNECTIONS_TABLE = var.connections_table_name
      WS_ENDPOINT       = var.ws_endpoint
    }
  }
}

resource "aws_lambda_event_source_mapping" "msk_to_broadcast" {
  event_source_arn  = var.msk_cluster_arn
  function_name     = aws_lambda_function.ws_broadcast.arn
  topics            = [var.ws_broadcast_topic]
  starting_position = "LATEST"
  batch_size        = 100

  amazon_managed_kafka_event_source_config {
    consumer_group_id = "${var.name_prefix}-ws-broadcaster"
  }
}

# -----------------------------------------------------------------------------
# Topic creator (invoked by Terraform)
# -----------------------------------------------------------------------------
resource "aws_lambda_function" "topic_creator" {
  function_name    = "${var.name_prefix}-topic-creator"
  role             = var.execution_role_arn
  runtime          = "python3.11"
  handler          = "lambdas.topic_creator.handler"
  filename         = data.archive_file.lambdas.output_path
  source_code_hash = data.archive_file.lambdas.output_base64sha256
  timeout          = 60
  memory_size      = 512

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [var.security_group_id]
  }
}

output "ws_connect_arn" { value = aws_lambda_function.ws_connect.arn }
output "ws_disconnect_arn" { value = aws_lambda_function.ws_disconnect.arn }
output "ws_broadcast_arn" { value = aws_lambda_function.ws_broadcast.arn }
output "topic_creator_arn" { value = aws_lambda_function.topic_creator.arn }
output "all_function_names" {
  value = [
    aws_lambda_function.ws_connect.function_name,
    aws_lambda_function.ws_disconnect.function_name,
    aws_lambda_function.ws_broadcast.function_name,
    aws_lambda_function.topic_creator.function_name,
  ]
}
