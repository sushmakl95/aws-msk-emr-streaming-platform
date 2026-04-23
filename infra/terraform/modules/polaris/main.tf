# Apache Polaris — Iceberg REST Catalog on ECS Fargate.
#
# Polaris is the open-source Unity-Catalog analogue that speaks the Iceberg
# REST catalog API. Flink, Spark, Trino, and PyIceberg all plug in as native
# REST clients, giving us one governance surface for every engine.

variable "name_prefix" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "security_group_ids" { type = list(string) }
variable "warehouse_bucket_arn" { type = string }

resource "aws_cloudwatch_log_group" "polaris" {
  name              = "/aws/ecs/${var.name_prefix}-polaris"
  retention_in_days = 30
}

resource "aws_ecs_cluster" "polaris" {
  name = "${var.name_prefix}-polaris"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_task_definition" "polaris" {
  family                   = "${var.name_prefix}-polaris"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024"
  memory                   = "2048"
  execution_role_arn       = aws_iam_role.polaris_exec.arn
  task_role_arn            = aws_iam_role.polaris_task.arn

  container_definitions = jsonencode([
    {
      name      = "polaris"
      image     = "apache/polaris:latest"
      essential = true
      portMappings = [{
        containerPort = 8181
        protocol      = "tcp"
      }]
      environment = [
        { name = "POLARIS_PERSISTENCE_TYPE", value = "eclipse-link" },
        { name = "POLARIS_BOOTSTRAP_CREDENTIALS", value = "root,rootsecret" },
        { name = "AWS_REGION", value = data.aws_region.current.name },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.polaris.name
          awslogs-region        = data.aws_region.current.name
          awslogs-stream-prefix = "polaris"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "polaris" {
  name            = "${var.name_prefix}-polaris"
  cluster         = aws_ecs_cluster.polaris.id
  task_definition = aws_ecs_task_definition.polaris.arn
  launch_type     = "FARGATE"
  desired_count   = 1

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = false
  }
}

resource "aws_iam_role" "polaris_exec" {
  name = "${var.name_prefix}-polaris-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "polaris_exec" {
  role       = aws_iam_role.polaris_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "polaris_task" {
  name = "${var.name_prefix}-polaris-task"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "polaris_warehouse" {
  name = "polaris-warehouse"
  role = aws_iam_role.polaris_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket",
      ]
      Resource = [
        var.warehouse_bucket_arn,
        "${var.warehouse_bucket_arn}/*",
      ]
    }]
  })
}

data "aws_region" "current" {}

output "rest_catalog_url" {
  description = "Private endpoint Flink/Spark/Trino use for Iceberg REST catalog."
  value       = "http://${aws_ecs_service.polaris.name}.${aws_ecs_cluster.polaris.name}:8181/api/catalog"
}
