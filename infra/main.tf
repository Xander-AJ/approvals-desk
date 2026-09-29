terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.70" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  # Partial config: terraform init -backend-config="bucket=..." -backend-config="key=approvals-desk/terraform.tfstate" \
  #   -backend-config="region=..." -backend-config="dynamodb_table=..." -backend-config="encrypt=true"
  backend "s3" {}
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
  description = "ACM certificate for the ALB HTTPS listener. Required: there is no HTTP-only mode."
}
variable "nat_gateway_count" {
  type        = number
  default     = 2
  description = "1 saves cost; 2 (one per AZ) survives an AZ outage."
  validation {
    condition     = contains([1, 2], var.nat_gateway_count)
    error_message = "nat_gateway_count must be 1 or 2."
  }
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
