output "nlb_dns_name" {
  description = "Open http://<this> in a browser"
  value       = aws_lb.main.dns_name
}

output "redis_primary_endpoint" {
  value = aws_elasticache_replication_group.main.primary_endpoint_address
}

output "rds_endpoint" {
  value = aws_db_instance.main.endpoint
}

output "efs_id" {
  value = aws_efs_file_system.main.id
}

output "db_password" {
  description = "Show with: terraform output db_password"
  value       = random_password.db.result
  sensitive   = true
}
