variable "name_prefix" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "kms_key_arn" { type = string }
variable "broker_count" { type = number }
variable "broker_instance_type" { type = string }
variable "ebs_volume_size_gb" { type = number }
variable "kafka_version" { type = string }

# -----------------------------------------------------------------------------
# Security group
# -----------------------------------------------------------------------------
resource "aws_security_group" "msk" {
  name        = "${var.name_prefix}-msk-sg"
  description = "MSK broker SG"
  vpc_id      = var.vpc_id

  ingress {
    description     = "MSK brokers - IAM SASL"
    from_port       = 9098
    to_port         = 9098
    protocol        = "tcp"
    security_groups = [aws_security_group.msk_clients.id]
  }

  ingress {
    description     = "MSK brokers - plaintext (in VPC only)"
    from_port       = 9092
    to_port         = 9092
    protocol        = "tcp"
    security_groups = [aws_security_group.msk_clients.id]
  }

  ingress {
    description     = "MSK brokers - TLS"
    from_port       = 9094
    to_port         = 9094
    protocol        = "tcp"
    security_groups = [aws_security_group.msk_clients.id]
  }

  ingress {
    description     = "Zookeeper"
    from_port       = 2181
    to_port         = 2181
    protocol        = "tcp"
    security_groups = [aws_security_group.msk_clients.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "msk_clients" {
  name        = "${var.name_prefix}-msk-clients-sg"
  description = "SG for Kafka clients (Lambda, EMR, Flink)"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# -----------------------------------------------------------------------------
# CloudWatch log group for MSK broker logs
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "msk" {
  name              = "/aws/msk/${var.name_prefix}"
  retention_in_days = 30
}

# -----------------------------------------------------------------------------
# Cluster config (Kafka broker tuning)
# -----------------------------------------------------------------------------
resource "aws_msk_configuration" "this" {
  name           = "${var.name_prefix}-config"
  kafka_versions = [var.kafka_version]

  server_properties = <<EOT
auto.create.topics.enable=false
default.replication.factor=${var.broker_count}
min.insync.replicas=2
num.partitions=6
num.io.threads=8
num.network.threads=5
num.replica.fetchers=2
log.message.format.version=${var.kafka_version}
inter.broker.protocol.version=${var.kafka_version}
log.retention.hours=168
log.segment.bytes=1073741824
transaction.state.log.replication.factor=3
transaction.state.log.min.isr=2
unclean.leader.election.enable=false
allow.everyone.if.no.acl.found=false
EOT
}

# -----------------------------------------------------------------------------
# MSK cluster
# -----------------------------------------------------------------------------
resource "aws_msk_cluster" "this" {
  cluster_name           = "${var.name_prefix}-msk"
  kafka_version          = var.kafka_version
  number_of_broker_nodes = var.broker_count

  broker_node_group_info {
    instance_type   = var.broker_instance_type
    client_subnets  = var.subnet_ids
    security_groups = [aws_security_group.msk.id]

    storage_info {
      ebs_storage_info {
        volume_size = var.ebs_volume_size_gb
      }
    }
  }

  configuration_info {
    arn      = aws_msk_configuration.this.arn
    revision = aws_msk_configuration.this.latest_revision
  }

  encryption_info {
    encryption_at_rest_kms_key_arn = var.kms_key_arn
    encryption_in_transit {
      client_broker = "TLS"
      in_cluster    = true
    }
  }

  client_authentication {
    sasl {
      iam = true
    }
  }

  logging_info {
    broker_logs {
      cloudwatch_logs {
        enabled   = true
        log_group = aws_cloudwatch_log_group.msk.name
      }
    }
  }

  open_monitoring {
    prometheus {
      jmx_exporter {
        enabled_in_broker = true
      }
      node_exporter {
        enabled_in_broker = true
      }
    }
  }
}

# -----------------------------------------------------------------------------
# Glue Schema Registry for Avro schemas
# -----------------------------------------------------------------------------
resource "aws_glue_registry" "this" {
  registry_name = "${var.name_prefix}-schema-registry"
  description   = "Schema registry for streaming platform"
}

output "cluster_arn" { value = aws_msk_cluster.this.arn }
output "cluster_name" { value = aws_msk_cluster.this.cluster_name }
output "bootstrap_brokers_sasl_iam" { value = aws_msk_cluster.this.bootstrap_brokers_sasl_iam }
output "zookeeper_connect_string" { value = aws_msk_cluster.this.zookeeper_connect_string }
output "broker_security_group_id" { value = aws_security_group.msk.id }
output "client_security_group_id" { value = aws_security_group.msk_clients.id }
output "schema_registry_arn" { value = aws_glue_registry.this.arn }
