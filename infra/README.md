# Deploying to AWS

The stack: VPC, RDS Postgres 16, ElastiCache Redis, ECS Fargate (API behind an ALB, worker, sandbox), ECR.
**It costs real money** (roughly US$100-150/month with the defaults: RDS, ALB, NAT gateways). Destroy it when done.

## Two ways in

**A. From your laptop (simplest)**
1. Create an AWS account and an IAM Identity Center user (not root): `aws configure sso && aws sso login`.
2. Request an ACM certificate for your API domain (HTTPS is mandatory) and note its ARN.
3. `infra/scripts/setup.sh`. It asks for the region, bootstraps state + a GitHub OIDC role, builds and pushes images,
   shows the plan, and applies only after you type `yes`.

**B. From GitHub Actions (after step A once, so the OIDC role exists)**
1. Repo variable `TFVARS`: the contents of your `terraform.tfvars` (see `terraform.tfvars.example`).
2. Repo secret `AWS_ROLE_ARN` (setup.sh sets it) and repo variable `AWS_REGION`.
3. Actions -> **aws-deploy** -> Run workflow. `plan` shows the diff; `apply` waits for approval on the
   `production` environment (create it under Settings -> Environments and add yourself as required reviewer).

## Tear down
`infra/scripts/teardown.sh`. The state bucket and OIDC role are kept (they cost cents).

## Status
Validated with `terraform validate` and checkov; **never applied to a real account**. Expect to fix small things on
the first run and please open an issue with the error.
