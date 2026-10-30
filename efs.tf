# Shared file system for all game servers, reachable from both AZs.
resource "aws_efs_file_system" "main" {
  encrypted = true

  tags = { Name = "${var.name_prefix}-efs" }
}

# One mount target (network endpoint) per subnet / AZ.
resource "aws_efs_mount_target" "main" {
  for_each = aws_subnet.public

  file_system_id  = aws_efs_file_system.main.id
  subnet_id       = each.value.id
  security_groups = [aws_security_group.efs.id]
}
