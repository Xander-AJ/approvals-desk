terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.70" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  # Configure a remote backend (S3 + DynamoDB lock) per environment before `apply`.
}

provider "aws" {
  region = var.region
  default_tags { tags = { Project = var.name, ManagedBy = "terraform" } }
}

variable "region" {
  type    = string
  default = "eu-west-1"
}
variable "name" {
  type    = string
  default = "approvals-desk"
}
variable "api_image" {
  type        = string
  description = "ECR image URI for the API/worker/migrate image (backend/Dockerfile)"
}
variable "sandbox_image" {
  type        = string
  description = "ECR image URI for Pesa Sandbox (sandbox/Dockerfile)"
}
variable "llm_provider" {
  type        = string
  default     = "anthropic"
  description = "anthropic (real Claude; requires anthropic_api_key) or fake (demo only, rule-based)"
  validation {
    condition     = contains(["anthropic", "fake"], var.llm_provider)
    error_message = "llm_provider must be anthropic or fake."
  }
}
variable "anthropic_api_key" {
  type      = string
  sensitive = true
  default   = ""
}
variable "jwt_issuer" { type = string }
variable "jwt_jwks_url" {
  type        = string
  description = "OIDC provider JWKS URL; tokens are verified with RS256. dev_auth is never enabled here."
}
variable "certificate_arn" {
  type        = string
  default     = ""
  description = "ACM certificate for HTTPS. Empty = HTTP only (not for production)."
}
variable "otlp_endpoint" {
  type        = string
  default     = ""
  description = "OTLP gRPC endpoint (e.g. Grafana Tempo / ADOT collector). Empty disables export."
}
variable "webhook_url" {
  type    = string
  default = ""
}
variable "db_instance_class" {
  type    = string
  default = "db.t4g.small"
}
variable "api_desired_count" {
  type    = number
  default = 2
}

data "aws_availability_zones" "available" { state = "available" }
locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
}
