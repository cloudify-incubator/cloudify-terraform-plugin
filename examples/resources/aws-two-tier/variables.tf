variable "key_name" {
  description = "A name for the key you are importing."
}

variable "public_key" {
  description = <<DESCRIPTION
Public Key Material.
DESCRIPTION
}

variable "aws_region" {
  description = "AWS region to launch servers."
}

# CentOS 7.7.1908 x86_64 with cloud-init (HVM)
variable "aws_amis" {
  default = {
    eu-west-1 = "ami-0eee6eb870dc1cefa"
    us-east-1 = "ami-03248a0341eadb1f1"
    us-west-1 = "ami-01dd5a8ef26e6341d"
    us-west-2 = "ami-024b56adf74074ca6"
  }
}
