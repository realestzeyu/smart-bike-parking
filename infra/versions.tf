terraform {
  required_version = ">= 1.5"

  # Local state (terraform.tfstate in this folder). Gitignored: it contains secrets.
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile

  default_tags {
    tags = {
      Project   = "smart-bike-parking"
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  prefix     = "sbp"
  account_id = data.aws_caller_identity.current.account_id
  region     = var.region
}
