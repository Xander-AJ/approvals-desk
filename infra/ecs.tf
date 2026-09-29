resource "aws_ecr_repository" "api" {
  name                 = "${var.name}/api"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
}
resource "aws_ecr_repository" "sandbox" {
  name                 = "${var.name}/sandbox"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecs_cluster" "main" {
  name = var.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.name}"
  retention_in_days = 30
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}
resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
resource "aws_iam_role_policy" "read_secrets" {
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [for s in aws_secretsmanager_secret.app : s.arn] }]
  })
}
resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

locals {
  secret_arn = { for k, s in aws_secretsmanager_secret.app : k => s.arn }

  common_env = [
    { name = "AD_REDIS_URL", value = local.redis_url },
    { name = "AD_SANDBOX_URL", value = "http://sandbox.${var.name}.local:8001" },
    { name = "AD_JWT_ISSUER", value = var.jwt_issuer },
    { name = "AD_JWT_JWKS_URL", value = var.jwt_jwks_url },
    { name = "AD_DEV_AUTH", value = "false" },
    { name = "AD_LLM_PROVIDER", value = var.llm_provider },
    { name = "AD_ASYNC_RESUME", value = "true" },
    { name = "AD_WEBHOOK_URL", value = var.webhook_url },
    { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = var.otlp_endpoint },
  ]
  common_secrets = [
    { name = "AD_DATABASE_URL", valueFrom = local.secret_arn["database_url"] },
    { name = "AD_CHECKPOINT_DSN", valueFrom = local.secret_arn["checkpoint_dsn"] },
    { name = "AD_WEBHOOK_SECRET", valueFrom = local.secret_arn["webhook_secret"] },
    { name = "AD_SANDBOX_API_KEY", valueFrom = local.secret_arn["sandbox_api_key"] },
    { name = "ANTHROPIC_API_KEY", valueFrom = local.secret_arn["anthropic_api_key"] },
  ]
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name         = "api"
    image        = var.api_image
    essential    = true
    portMappings = [{ containerPort = 8000 }]
    environment  = concat(local.common_env, [{ name = "OTEL_SERVICE_NAME", value = "approvals-api" }])
    secrets      = local.common_secrets
    logConfiguration = { logDriver = "awslogs", options = {
    awslogs-group = aws_cloudwatch_log_group.app.name, awslogs-region = var.region, awslogs-stream-prefix = "api" } }
  }])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name        = "worker"
    image       = var.api_image
    essential   = true
    command     = ["arq", "app.worker.WorkerSettings"]
    environment = concat(local.common_env, [{ name = "OTEL_SERVICE_NAME", value = "approvals-worker" }])
    secrets     = local.common_secrets
    logConfiguration = { logDriver = "awslogs", options = {
    awslogs-group = aws_cloudwatch_log_group.app.name, awslogs-region = var.region, awslogs-stream-prefix = "worker" } }
  }])
}

# One-off: `aws ecs run-task --task-definition approvals-desk-migrate ...` before each deploy.
resource "aws_ecs_task_definition" "migrate" {
  family                   = "${var.name}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name      = "migrate"
    image     = var.api_image
    essential = true
    command   = ["alembic", "upgrade", "head"]
    secrets = [
      { name = "MIGRATION_DATABASE_URL", valueFrom = local.secret_arn["migration_url"] },
      { name = "APP_DB_PASSWORD", valueFrom = local.secret_arn["app_db_password"] },
    ]
    logConfiguration = { logDriver = "awslogs", options = {
    awslogs-group = aws_cloudwatch_log_group.app.name, awslogs-region = var.region, awslogs-stream-prefix = "migrate" } }
  }])
}

resource "aws_ecs_task_definition" "sandbox" {
  family                   = "${var.name}-sandbox"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name         = "sandbox"
    image        = var.sandbox_image
    essential    = true
    portMappings = [{ containerPort = 8001 }]
    environment  = [{ name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = var.otlp_endpoint }]
    secrets = [
      { name = "SANDBOX_DATABASE_URL", valueFrom = local.secret_arn["sandbox_database_url"] },
      { name = "SANDBOX_API_KEY", valueFrom = local.secret_arn["sandbox_api_key"] },
    ]
    logConfiguration = { logDriver = "awslogs", options = {
    awslogs-group = aws_cloudwatch_log_group.app.name, awslogs-region = var.region, awslogs-stream-prefix = "sandbox" } }
  }])
}

resource "aws_service_discovery_private_dns_namespace" "local" {
  name = "${var.name}.local"
  vpc  = aws_vpc.main.id
}
resource "aws_service_discovery_service" "sandbox" {
  name = "sandbox"
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.local.id
    dns_records {
      ttl  = 10
      type = "A"
    }
  }
  health_check_custom_config { failure_threshold = 1 }
}

resource "aws_lb" "api" {
  name               = var.name
  load_balancer_type = "application"
  subnets            = aws_subnet.public[*].id
  security_groups    = [aws_security_group.alb.id]
}
resource "aws_lb_target_group" "api" {
  name        = "${var.name}-api"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check { path = "/healthz" }
}
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = var.certificate_arn == "" ? "forward" : "redirect"
    target_group_arn = var.certificate_arn == "" ? aws_lb_target_group.api.arn : null
    dynamic "redirect" {
      for_each = var.certificate_arn == "" ? [] : [1]
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}
resource "aws_lb_listener" "https" {
  count             = var.certificate_arn == "" ? 0 : 1
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.certificate_arn
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_ecs_service" "api" {
  name            = "api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.tasks.id]
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }
  depends_on = [aws_lb_listener.http]
}

resource "aws_ecs_service" "worker" {
  name            = "worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.tasks.id]
  }
}

resource "aws_ecs_service" "sandbox" {
  name            = "sandbox"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.sandbox.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.tasks.id]
  }
  service_registries { registry_arn = aws_service_discovery_service.sandbox.arn }
}
