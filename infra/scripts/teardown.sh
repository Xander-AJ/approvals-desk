#!/usr/bin/env bash
# Destroys the main stack (RDS, NAT, ALB, ECS...) so it stops billing. Leaves the state bucket and OIDC role.
set -euo pipefail
cd "$(dirname "$0")/.."
aws sts get-caller-identity >/dev/null || { echo "Not signed in to AWS."; exit 1; }
read -r -p "Destroy the approvals-desk AWS stack? Type 'destroy': " a; [ "$a" = destroy ] || exit 0
terraform init -input=false -reconfigure -backend-config=backend.hcl
terraform destroy -input=false
