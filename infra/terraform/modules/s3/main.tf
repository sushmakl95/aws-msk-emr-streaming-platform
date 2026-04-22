variable "name_prefix" { type = string }
variable "kms_key_arn" { type = string }

resource "random_id" "suffix" {
  byte_length = 4
}

# -----------------------------------------------------------------------------
# Plugins bucket — MSK Connect plugin ZIPs
# -----------------------------------------------------------------------------
resource "aws_s3_bucket" "plugins" {
  bucket = "${var.name_prefix}-connect-plugins-${random_id.suffix.hex}"
  tags   = { Name = "${var.name_prefix}-connect-plugins" }
}

resource "aws_s3_bucket_versioning" "plugins" {
  bucket = aws_s3_bucket.plugins.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "plugins" {
  bucket = aws_s3_bucket.plugins.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "plugins" {
  bucket                  = aws_s3_bucket.plugins.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# -----------------------------------------------------------------------------
# Iceberg warehouse — cold Iceberg tables (Spark/Flink sink)
# -----------------------------------------------------------------------------
resource "aws_s3_bucket" "iceberg" {
  bucket = "${var.name_prefix}-iceberg-${random_id.suffix.hex}"
  tags   = { Name = "${var.name_prefix}-iceberg" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "iceberg" {
  bucket = aws_s3_bucket.iceberg.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "iceberg" {
  bucket                  = aws_s3_bucket.iceberg.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "iceberg" {
  bucket = aws_s3_bucket.iceberg.id
  rule {
    id     = "glacier-after-90d"
    status = "Enabled"
    filter {}
    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }
  }
}

# -----------------------------------------------------------------------------
# Cold archive — raw Kafka dumps (MSK Connect S3 sink)
# -----------------------------------------------------------------------------
resource "aws_s3_bucket" "cold_archive" {
  bucket = "${var.name_prefix}-cold-archive-${random_id.suffix.hex}"
  tags   = { Name = "${var.name_prefix}-cold-archive" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cold_archive" {
  bucket = aws_s3_bucket.cold_archive.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "cold_archive" {
  bucket                  = aws_s3_bucket.cold_archive.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# -----------------------------------------------------------------------------
# Checkpoints bucket — Spark + Flink state checkpoints
# -----------------------------------------------------------------------------
resource "aws_s3_bucket" "checkpoints" {
  bucket = "${var.name_prefix}-checkpoints-${random_id.suffix.hex}"
  tags   = { Name = "${var.name_prefix}-checkpoints" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "checkpoints" {
  bucket = aws_s3_bucket.checkpoints.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "checkpoints" {
  bucket                  = aws_s3_bucket.checkpoints.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# -----------------------------------------------------------------------------
# Flink apps bucket — KDA application code
# -----------------------------------------------------------------------------
resource "aws_s3_bucket" "flink_apps" {
  bucket = "${var.name_prefix}-flink-apps-${random_id.suffix.hex}"
  tags   = { Name = "${var.name_prefix}-flink-apps" }
}

resource "aws_s3_bucket_versioning" "flink_apps" {
  bucket = aws_s3_bucket.flink_apps.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "flink_apps" {
  bucket = aws_s3_bucket.flink_apps.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "flink_apps" {
  bucket                  = aws_s3_bucket.flink_apps.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

output "plugins_bucket_name" { value = aws_s3_bucket.plugins.id }
output "plugins_bucket_arn" { value = aws_s3_bucket.plugins.arn }
output "iceberg_warehouse_name" { value = aws_s3_bucket.iceberg.id }
output "iceberg_warehouse_arn" { value = aws_s3_bucket.iceberg.arn }
output "cold_archive_bucket_name" { value = aws_s3_bucket.cold_archive.id }
output "cold_archive_bucket_arn" { value = aws_s3_bucket.cold_archive.arn }
output "checkpoints_bucket_name" { value = aws_s3_bucket.checkpoints.id }
output "checkpoints_bucket_arn" { value = aws_s3_bucket.checkpoints.arn }
output "flink_apps_bucket_name" { value = aws_s3_bucket.flink_apps.id }
output "flink_apps_bucket_arn" { value = aws_s3_bucket.flink_apps.arn }
output "all_bucket_arns" {
  value = [
    aws_s3_bucket.plugins.arn,
    aws_s3_bucket.iceberg.arn,
    aws_s3_bucket.cold_archive.arn,
    aws_s3_bucket.checkpoints.arn,
    aws_s3_bucket.flink_apps.arn,
  ]
}
