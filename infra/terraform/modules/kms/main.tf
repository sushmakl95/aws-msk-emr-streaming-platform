variable "name_prefix" { type = string }

resource "aws_kms_key" "s3" {
  description             = "${var.name_prefix} S3"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}
resource "aws_kms_alias" "s3" {
  name          = "alias/${var.name_prefix}-s3"
  target_key_id = aws_kms_key.s3.key_id
}

resource "aws_kms_key" "secrets" {
  description             = "${var.name_prefix} secrets"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}
resource "aws_kms_alias" "secrets" {
  name          = "alias/${var.name_prefix}-secrets"
  target_key_id = aws_kms_key.secrets.key_id
}

resource "aws_kms_key" "msk" {
  description             = "${var.name_prefix} msk"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}
resource "aws_kms_alias" "msk" {
  name          = "alias/${var.name_prefix}-msk"
  target_key_id = aws_kms_key.msk.key_id
}

resource "aws_kms_key" "eks" {
  description             = "${var.name_prefix} eks"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}
resource "aws_kms_alias" "eks" {
  name          = "alias/${var.name_prefix}-eks"
  target_key_id = aws_kms_key.eks.key_id
}

resource "aws_kms_key" "kinesis" {
  description             = "${var.name_prefix} kinesis"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}
resource "aws_kms_alias" "kinesis" {
  name          = "alias/${var.name_prefix}-kinesis"
  target_key_id = aws_kms_key.kinesis.key_id
}

resource "aws_kms_key" "elasticache" {
  description             = "${var.name_prefix} elasticache"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}
resource "aws_kms_alias" "elasticache" {
  name          = "alias/${var.name_prefix}-elasticache"
  target_key_id = aws_kms_key.elasticache.key_id
}

resource "aws_kms_key" "opensearch" {
  description             = "${var.name_prefix} opensearch"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}
resource "aws_kms_alias" "opensearch" {
  name          = "alias/${var.name_prefix}-opensearch"
  target_key_id = aws_kms_key.opensearch.key_id
}

resource "aws_kms_key" "dynamodb" {
  description             = "${var.name_prefix} dynamodb"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}
resource "aws_kms_alias" "dynamodb" {
  name          = "alias/${var.name_prefix}-dynamodb"
  target_key_id = aws_kms_key.dynamodb.key_id
}

output "s3_key_arn" { value = aws_kms_key.s3.arn }
output "secrets_key_arn" { value = aws_kms_key.secrets.arn }
output "msk_key_arn" { value = aws_kms_key.msk.arn }
output "eks_key_arn" { value = aws_kms_key.eks.arn }
output "kinesis_key_arn" { value = aws_kms_key.kinesis.arn }
output "elasticache_key_arn" { value = aws_kms_key.elasticache.arn }
output "opensearch_key_arn" { value = aws_kms_key.opensearch.arn }
output "dynamodb_key_arn" { value = aws_kms_key.dynamodb.arn }
output "all_key_arns" {
  value = [
    aws_kms_key.s3.arn,
    aws_kms_key.secrets.arn,
    aws_kms_key.msk.arn,
    aws_kms_key.eks.arn,
    aws_kms_key.kinesis.arn,
    aws_kms_key.elasticache.arn,
    aws_kms_key.opensearch.arn,
    aws_kms_key.dynamodb.arn,
  ]
}
