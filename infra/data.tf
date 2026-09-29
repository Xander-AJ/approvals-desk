resource "random_password" "db_owner" {
  length  = 32
  special = false
}
resource "random_password" "app_user" {
  length  = 32
  special = false
}

resource "aws_db_subnet_group" "main" {
  name       = var.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_instance" "main" {
  identifier                 = var.name
  engine                     = "postgres"
  engine_version             = "16"
  instance_class             = var.db_instance_class
  allocated_storage          = 20
  max_allocated_storage      = 100
  storage_encrypted          = true
  db_name                    = "approvals"
  username                   = "owner"
  password                   = random_password.db_owner.result
  db_subnet_group_name       = aws_db_subnet_group.main.name
  vpc_security_group_ids     = [aws_security_group.data.id]
  multi_az                   = true
  backup_retention_period    = 7
  deletion_protection        = true
  skip_final_snapshot        = false
  final_snapshot_identifier  = "${var.name}-final"
  auto_minor_version_upgrade = true
  publicly_accessible        = false
}

resource "aws_elasticache_subnet_group" "main" {
  name       = var.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = var.name
  description                = "arq job queue"
  engine                     = "redis"
  node_type                  = "cache.t4g.small"
  num_cache_clusters         = 1
  subnet_group_name          = aws_elasticache_subnet_group.main.name
  security_group_ids         = [aws_security_group.data.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = false # arq's redis DSN below is plain; enable + rediss:// for production
}

locals {
  db_host = aws_db_instance.main.address
  # app_user is the RLS-bound runtime role (NOBYPASSRLS); owner is used only for migrations, the
  # LangGraph checkpointer, and the sandbox.
  secret_values = {
    database_url         = "postgresql+asyncpg://app_user:${random_password.app_user.result}@${local.db_host}:5432/approvals"
    checkpoint_dsn       = "postgresql://owner:${random_password.db_owner.result}@${local.db_host}:5432/approvals"
    migration_url        = "postgresql+asyncpg://owner:${random_password.db_owner.result}@${local.db_host}:5432/approvals"
    sandbox_database_url = "postgresql+asyncpg://owner:${random_password.db_owner.result}@${local.db_host}:5432/approvals"
    app_db_password      = random_password.app_user.result
    webhook_secret       = random_password.webhook.result
    sandbox_api_key      = random_password.sandbox_key.result
    anthropic_api_key    = var.anthropic_api_key == "" ? "unset" : var.anthropic_api_key
  }
  redis_url = "redis://${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379"
}

resource "random_password" "sandbox_key" {
  length  = 40
  special = false
}

resource "random_password" "webhook" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret" "app" {
  for_each                = local.secret_values
  name                    = "${var.name}/${each.key}"
  recovery_window_in_days = 7
}
resource "aws_secretsmanager_secret_version" "app" {
  for_each      = local.secret_values
  secret_id     = aws_secretsmanager_secret.app[each.key].id
  secret_string = each.value
}
