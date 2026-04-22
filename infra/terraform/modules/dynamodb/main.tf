variable "name_prefix" { type = string }
variable "kms_key_arn" { type = string }

resource "aws_dynamodb_table" "connections" {
  name         = "${var.name_prefix}-ws-connections"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "connection_id"

  attribute {
    name = "connection_id"
    type = "S"
  }

  attribute {
    name = "user_id"
    type = "S"
  }

  global_secondary_index {
    name            = "user_id_index"
    hash_key        = "user_id"
    projection_type = "KEYS_ONLY"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  point_in_time_recovery {
    enabled = false
  }

  tags = {
    Name    = "${var.name_prefix}-ws-connections"
    Purpose = "websocket-connection-registry"
  }
}

output "connections_table_name" { value = aws_dynamodb_table.connections.name }
output "connections_table_arn" { value = aws_dynamodb_table.connections.arn }
