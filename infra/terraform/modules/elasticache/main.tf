variable "name_prefix" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "kms_key_arn" { type = string }
variable "node_type" { type = string }

resource "aws_security_group" "redis" {
  name        = "${var.name_prefix}-redis-sg"
  description = "Redis SG"
  vpc_id      = var.vpc_id

  ingress {
    description = "Redis port"
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.name_prefix}-redis-subnet-group"
  subnet_ids = var.subnet_ids
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id       = "${var.name_prefix}-redis"
  description                = "Hot state store for streaming platform"
  node_type                  = var.node_type
  engine_version             = "7.1"
  port                       = 6379

  num_cache_clusters         = 2
  automatic_failover_enabled = true
  multi_az_enabled           = true

  parameter_group_name       = "default.redis7"
  subnet_group_name          = aws_elasticache_subnet_group.this.name
  security_group_ids         = [aws_security_group.redis.id]

  at_rest_encryption_enabled = true
  kms_key_id                 = var.kms_key_arn
  transit_encryption_enabled = true

  snapshot_retention_limit   = 5
  snapshot_window            = "03:00-05:00"

  apply_immediately          = true
}

output "primary_endpoint" { value = aws_elasticache_replication_group.this.primary_endpoint_address }
output "reader_endpoint" { value = aws_elasticache_replication_group.this.reader_endpoint_address }
output "security_group_id" { value = aws_security_group.redis.id }
