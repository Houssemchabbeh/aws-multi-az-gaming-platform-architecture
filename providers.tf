# Credentials come from ~/.aws/credentials (default profile, Learner Lab session).
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project = "ha-gaming-platform"
    }
  }
}
