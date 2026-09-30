#!/usr/bin/env bash
# Guided AWS setup: checks tools and credentials, bootstraps remote state + GitHub OIDC role, prepares tfvars,
# builds/pushes images, then plans. It never applies the main stack without an explicit "yes".
set -euo pipefail
cd "$(dirname "$0")/.."
say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
need() { command -v "$1" >/dev/null || { echo "Missing '$1'. Install: $2"; exit 1; }; }

say "1/6 Tools"
need terraform "brew install hashicorp/tap/terraform"
need aws "brew install awscli"
need docker "https://docs.docker.com/get-docker/"

say "2/6 AWS credentials"
if ! aws sts get-caller-identity >/dev/null 2>&1; then
  cat <<MSG
No working AWS credentials. Pick ONE, then re-run this script:
  a) IAM Identity Center (recommended):  aws configure sso   &&   aws sso login   &&   export AWS_PROFILE=<name>
  b) Access keys for a non-root IAM user: aws configure
Create the account at https://aws.amazon.com/ first if you do not have one. Do not use root keys.
MSG
  exit 1
fi
aws sts get-caller-identity --query '[Account,Arn]' --output text
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region || true)}}"
REGION="${REGION:-eu-west-1}"
read -r -p "Region [$REGION]: " r; REGION="${r:-$REGION}"
export AWS_REGION="$REGION"

say "3/6 Bootstrap: state bucket, lock table, GitHub OIDC role (local state in infra/bootstrap)"
( cd bootstrap && terraform init -input=false >/dev/null && terraform plan -input=false -var "region=$REGION" -out=tfplan | tail -5 )
read -r -p "Create these resources? [yes/no]: " a; [ "$a" = yes ] || { echo "Stopped."; exit 0; }
( cd bootstrap && terraform apply -input=false tfplan )
out() { ( cd bootstrap && terraform output -raw "$1" ); }
cat > backend.hcl <<HCL
bucket         = "$(out state_bucket)"
key            = "approvals-desk/terraform.tfstate"
region         = "$REGION"
dynamodb_table = "$(out lock_table)"
encrypt        = true
HCL
ROLE="$(out ci_role_arn)"
if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  gh secret set AWS_ROLE_ARN --body "$ROLE" && echo "GitHub secret AWS_ROLE_ARN set."
else
  echo "Add this GitHub secret manually: AWS_ROLE_ARN=$ROLE"
fi

say "4/6 terraform.tfvars"
[ -f terraform.tfvars ] || { sed "s/eu-west-1/$REGION/g" terraform.tfvars.example > terraform.tfvars; }
echo "Edit infra/terraform.tfvars now (certificate_arn is required), then press Enter."; read -r _

say "5/6 Init, create ECR, push images"
terraform init -input=false -reconfigure -backend-config=backend.hcl
terraform apply -input=false -target=aws_ecr_repository.api -target=aws_ecr_repository.sandbox \
  -var "api_image=placeholder" -var "sandbox_image=placeholder" -auto-approve
API_REPO="$(terraform output -raw ecr_api_repository)"; SBX_REPO="$(terraform output -raw ecr_sandbox_repository)"
aws ecr get-login-password | docker login --username AWS --password-stdin "${API_REPO%%/*}"
TAG="$(git rev-parse --short HEAD)"
docker build --platform linux/amd64 -f ../backend/Dockerfile -t "$API_REPO:$TAG" .. && docker push "$API_REPO:$TAG"
docker build --platform linux/amd64 -f ../sandbox/Dockerfile -t "$SBX_REPO:$TAG" .. && docker push "$SBX_REPO:$TAG"
sed -i.bak -E "s|^api_image.*|api_image     = \"$API_REPO:$TAG\"|; s|^sandbox_image.*|sandbox_image = \"$SBX_REPO:$TAG\"|" terraform.tfvars && rm terraform.tfvars.bak

say "6/6 Plan"
terraform plan -input=false -out=tfplan
read -r -p "Apply this plan (creates billable resources: RDS, NAT, ALB...)? [yes/no]: " a
[ "$a" = yes ] && terraform apply -input=false tfplan || echo "Not applied. Run 'terraform apply tfplan' in infra/ when ready."
