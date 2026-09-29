output "alb_dns_name" { value = aws_lb.api.dns_name }
output "ecr_api_repository" { value = aws_ecr_repository.api.repository_url }
output "ecr_sandbox_repository" { value = aws_ecr_repository.sandbox.repository_url }
output "migrate_task_definition" { value = aws_ecs_task_definition.migrate.family }
output "private_subnet_ids" { value = aws_subnet.private[*].id }
output "tasks_security_group_id" { value = aws_security_group.tasks.id }
