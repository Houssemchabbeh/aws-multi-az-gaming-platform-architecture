# PostgreSQL for persistent game data. Multi-AZ keeps a standby copy in the
# other AZ and fails over to it automatically.
resource "aws_db_subnet_group" "main" {
  name       = "${var.name_prefix}-db-subnets"
  subnet_ids = local.subnet_ids
}

resource "random_password" "db" {
  length  = 20
  special = false # avoids characters RDS does not allow in passwords
}

resource "aws_db_instance" "main" {
  identifier        = "${var.name_prefix}-db"
  engine            = "postgres"
  engine_version    = "18"
  instance_class    = "db.t3.micro"
  allocated_storage = 20
  storage_type      = "gp3"

  db_name  = "gamedb"
  username = "gameadmin"
  password = random_password.db.result

  multi_az               = true
  publicly_accessible    = false
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]

  # Learner Lab: no Enhanced Monitoring / Performance Insights.
  monitoring_interval          = 0
  performance_insights_enabled = false

  skip_final_snapshot = true
}
