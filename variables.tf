variable "region" {
  description = "AWS region (Learner Lab only allows us-east-1)"
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Prefix for all resource names"
  type        = string
  default     = "gaming"
}

variable "key_name" {
  description = "Existing EC2 key pair used for SSH"
  type        = string
  default     = "houssy"
}

variable "my_ip" {
  description = "Your public IP in /32 form, allowed to SSH into the game servers"
  type        = string
}
