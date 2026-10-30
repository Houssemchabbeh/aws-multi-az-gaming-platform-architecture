# Each tier only accepts traffic from the tier in front of it:
# internet -> nlb-sg -> app-sg -> cache-sg / db-sg / efs-sg
# Every SG keeps the default "allow all" outbound rule.

resource "aws_security_group" "nlb" {
  name        = "${var.name_prefix}-nlb-sg"
  description = "NLB: web and game traffic from the internet"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Game traffic (UDP)"
    from_port   = 3478
    to_port     = 3478
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.name_prefix}-nlb-sg" }
}

resource "aws_security_group" "app" {
  name        = "${var.name_prefix}-app-sg"
  description = "Game servers: traffic from the NLB, SSH from my IP"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "HTTP from NLB"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.nlb.id]
  }

  ingress {
    description     = "Game traffic from NLB"
    from_port       = 3478
    to_port         = 3478
    protocol        = "udp"
    security_groups = [aws_security_group.nlb.id]
  }

  ingress {
    description = "SSH from my IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.my_ip]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.name_prefix}-app-sg" }
}

resource "aws_security_group" "cache" {
  name        = "${var.name_prefix}-cache-sg"
  description = "Redis: only from game servers"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Redis from app"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.name_prefix}-cache-sg" }
}

resource "aws_security_group" "db" {
  name        = "${var.name_prefix}-db-sg"
  description = "PostgreSQL: only from game servers"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL from app"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.name_prefix}-db-sg" }
}

resource "aws_security_group" "efs" {
  name        = "${var.name_prefix}-efs-sg"
  description = "EFS: NFS only from game servers"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "NFS from app"
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.name_prefix}-efs-sg" }
}
