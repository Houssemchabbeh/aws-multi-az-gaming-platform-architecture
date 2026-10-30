# Internet-facing Network Load Balancer spread across both AZs.
resource "aws_lb" "main" {
  name                             = "${var.name_prefix}-nlb"
  load_balancer_type               = "network"
  internal                         = false
  subnets                          = local.subnet_ids
  security_groups                  = [aws_security_group.nlb.id]
  enable_cross_zone_load_balancing = true
}

# Target group for web traffic (TCP 80).
resource "aws_lb_target_group" "tcp80" {
  name     = "${var.name_prefix}-tg-tcp80"
  port     = 80
  protocol = "TCP"
  vpc_id   = aws_vpc.main.id

  health_check {
    protocol = "TCP"
    port     = "80"
  }
}

# Target group for game traffic (UDP 3478). UDP can't be health-checked
# directly, so it checks the instance on TCP 80 instead.
resource "aws_lb_target_group" "udp3478" {
  name     = "${var.name_prefix}-tg-udp3478"
  port     = 3478
  protocol = "UDP"
  vpc_id   = aws_vpc.main.id

  health_check {
    protocol = "TCP"
    port     = "80"
  }
}

resource "aws_lb_listener" "tcp80" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.tcp80.arn
  }
}

resource "aws_lb_listener" "udp3478" {
  load_balancer_arn = aws_lb.main.arn
  port              = 3478
  protocol          = "UDP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.udp3478.arn
  }
}
