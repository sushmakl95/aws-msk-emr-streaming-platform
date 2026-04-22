variable "name_prefix" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "clickhouse_password" {
  type      = string
  sensitive = true
}
variable "task_cpu" { type = number }
variable "task_memory" { type = number }
variable "desired_count" { type = number }

resource "aws_ecs_cluster" "this" {
  name = "${var.name_prefix}-clickhouse"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_security_group" "clickhouse" {
  name        = "${var.name_prefix}-clickhouse-sg"
  description = "ClickHouse SG"
  vpc_id      = var.vpc_id

  ingress {
    description = "ClickHouse HTTP"
    from_port   = 8123
    to_port     = 8123
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }

  ingress {
    description = "ClickHouse native"
    from_port   = 9000
    to_port     = 9000
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

resource "aws_iam_role" "ecs_task_execution" {
  name = "${var.name_prefix}-ch-task-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_policy" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_cloudwatch_log_group" "clickhouse" {
  name              = "/ecs/${var.name_prefix}-clickhouse"
  retention_in_days = 14
}

resource "aws_ecs_task_definition" "clickhouse" {
  family                   = "${var.name_prefix}-clickhouse"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn

  container_definitions = jsonencode([{
    name      = "clickhouse"
    image     = "clickhouse/clickhouse-server:24.1"
    essential = true
    portMappings = [
      { containerPort = 8123, hostPort = 8123 },
      { containerPort = 9000, hostPort = 9000 },
    ]
    environment = [
      { name = "CLICKHOUSE_DB", value = "streaming" },
      { name = "CLICKHOUSE_USER", value = "default" },
      { name = "CLICKHOUSE_PASSWORD", value = var.clickhouse_password },
      { name = "CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT", value = "1" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.clickhouse.name
        "awslogs-region"        = data.aws_region.current.name
        "awslogs-stream-prefix" = "clickhouse"
      }
    }
    healthCheck = {
      command     = ["CMD-SHELL", "wget -q --spider http://localhost:8123/ping || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
  }])
}

data "aws_region" "current" {}

# Application Load Balancer for ClickHouse
resource "aws_lb" "clickhouse" {
  name               = "${var.name_prefix}-ch"
  internal           = true
  load_balancer_type = "application"
  subnets            = var.subnet_ids
  security_groups    = [aws_security_group.clickhouse.id]
}

resource "aws_lb_target_group" "clickhouse" {
  name        = "${var.name_prefix}-ch-tg"
  port        = 8123
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/ping"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }
}

resource "aws_lb_listener" "clickhouse" {
  load_balancer_arn = aws_lb.clickhouse.arn
  port              = 8123
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.clickhouse.arn
  }
}

resource "aws_ecs_service" "clickhouse" {
  name            = "${var.name_prefix}-clickhouse"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.clickhouse.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.clickhouse.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.clickhouse.arn
    container_name   = "clickhouse"
    container_port   = 8123
  }

  depends_on = [aws_lb_listener.clickhouse]
}

output "load_balancer_dns" { value = aws_lb.clickhouse.dns_name }
output "ecs_cluster_name" { value = aws_ecs_cluster.this.name }
