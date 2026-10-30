# Redis for game sessions: primary in us-east-1a, replica in us-east-1b.
# If the primary fails, the replica is promoted automatically.
resource "aws_elasticache_subnet_group" "main" {
  name       = "${var.name_prefix}-cache-subnets"
  subnet_ids = local.subnet_ids
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id = "${var.name_prefix}-redis"
  description          = "Game session cache"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = "cache.t3.micro"
  port                 = 6379

  num_cache_clusters          = 2 # 1 primary + 1 replica
  preferred_cache_cluster_azs = ["us-east-1a", "us-east-1b"]
  automatic_failover_enabled  = true
  multi_az_enabled            = true

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.cache.id]
}
