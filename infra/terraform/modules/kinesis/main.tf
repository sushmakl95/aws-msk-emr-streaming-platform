variable "name_prefix" { type = string }
variable "kms_key_arn" { type = string }
variable "shard_count" { type = number }

resource "aws_kinesis_stream" "app_events" {
  name             = "${var.name_prefix}-app-events"
  shard_count      = var.shard_count
  retention_period = 168 # 7 days

  encryption_type = "KMS"
  kms_key_id      = var.kms_key_arn

  shard_level_metrics = [
    "IncomingBytes",
    "IncomingRecords",
    "OutgoingBytes",
    "OutgoingRecords",
    "IteratorAgeMilliseconds",
    "ReadProvisionedThroughputExceeded",
    "WriteProvisionedThroughputExceeded",
  ]

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }
}

output "stream_name" { value = aws_kinesis_stream.app_events.name }
output "stream_arn" { value = aws_kinesis_stream.app_events.arn }
