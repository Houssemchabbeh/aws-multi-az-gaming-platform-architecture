# Latest Amazon Linux 2023 AMI, read from the AWS public SSM parameter.
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# Blueprint for every game server the Auto Scaling group launches.
resource "aws_launch_template" "app" {
  name_prefix            = "${var.name_prefix}-lt-"
  image_id               = data.aws_ssm_parameter.al2023.insecure_value
  instance_type          = "t3.micro"
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.app.id]

  iam_instance_profile {
    name = "LabInstanceProfile" # pre-existing in Learner Lab
  }

  user_data = base64encode(templatefile("${path.module}/user_data.sh.tftpl", {
    efs_id = aws_efs_file_system.main.id
  }))
}

# Keeps 2 game servers running (one per AZ), can grow to 6, and replaces
# any instance the NLB marks unhealthy.
resource "aws_autoscaling_group" "app" {
  name                      = "${var.name_prefix}-asg"
  vpc_zone_identifier       = local.subnet_ids
  min_size                  = 2
  desired_capacity          = 2
  max_size                  = 6
  health_check_type         = "ELB"
  health_check_grace_period = 300

  target_group_arns = [
    aws_lb_target_group.tcp80.arn,
    aws_lb_target_group.udp3478.arn,
  ]

  launch_template {
    id      = aws_launch_template.app.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "${var.name_prefix}-game-server"
    propagate_at_launch = true
  }

  # Instances mount EFS at boot, so the mount targets must exist first.
  depends_on = [aws_efs_mount_target.main]
}
