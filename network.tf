# One VPC with two public subnets, one per Availability Zone.
locals {
  subnets = {
    a = { cidr = "10.0.0.0/26", az = "us-east-1a" }
    b = { cidr = "10.0.0.64/26", az = "us-east-1b" }
  }
  subnet_ids = [for s in aws_subnet.public : s.id]
}

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/24"
  enable_dns_support   = true
  enable_dns_hostnames = true # needed so EFS DNS names resolve

  tags = { Name = "${var.name_prefix}-vpc" }
}

resource "aws_subnet" "public" {
  for_each = local.subnets

  vpc_id                  = aws_vpc.main.id
  cidr_block              = each.value.cidr
  availability_zone       = each.value.az
  map_public_ip_on_launch = true

  tags = { Name = "${var.name_prefix}-public-${each.key}" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${var.name_prefix}-igw" }
}

# Single route table: all internet traffic goes through the Internet Gateway.
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${var.name_prefix}-public-rt" }
}

resource "aws_route_table_association" "public" {
  for_each = aws_subnet.public

  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}
