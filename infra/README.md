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

## What "it works" looks like (acceptance checklist)

The application itself is verified: 153 backend tests, 11 Playwright tests, evals and CI are green, and the same images
run on Railway. The AWS deployment is the one thing **not verified**, because the maintainer had no AWS account. If you
run it with your own account, this is the outcome to expect. Any deviation is a bug in the Terraform, and we'd like a
report (open an issue with the command, the error, and `terraform version`).

| # | Step | Expected outcome |
|---|---|---|
| 1 | `infra/scripts/setup.sh` bootstrap | Creates 1 S3 bucket, 1 DynamoDB table, 1 OIDC provider, 1 IAM role; writes `backend.hcl`; sets `AWS_ROLE_ARN` |
| 2 | `terraform plan` | About 65 resources to add (VPC, RDS, ElastiCache, ECS, ALB, ECR, secrets, logs), 0 to change, 0 to destroy |
| 3 | `terraform apply` | Completes without error (RDS takes 10-15 min). Outputs `alb_dns_name`, `ecr_*_repository`, `migrate_task_definition` |
| 4 | Run the `migrate` task once (`aws ecs run-task`, see `outputs.tf`) | Task exits with code 0; the schema, forced RLS and the `app_user` role exist |
| 5 | Point DNS at the ALB, then `curl https://<your-api-domain>/healthz` | HTTP 200. ECS shows `api`, `worker`, `sandbox` each with running count == desired |
| 6 | `curl` any API route without a token | HTTP 401 (JWT required; there is no dev auth in this mode) |
| 7 | Deploy the web app with `API_URL` set to your API, sign in, run the 60-second demo (README) | Proposal lands in the inbox; after approval the state becomes `executed` |
| 8 | Check the sandbox ledger | **Exactly one** refund for that proposal; the audit timeline shows proposed, pending review, approved, executed |
| 9 | Stop the `worker` task during step 7 (`aws ecs stop-task`), approve, let ECS restart it | Still exactly one refund (durable resume) |
| 10 | `infra/scripts/teardown.sh` | Stack destroyed; no billable resources remain except cents of state storage |

Known gaps to expect (documented, not bugs): the Pesa Sandbox is a fake payments provider with shared-key auth, it shares
the RDS instance, and no tracing backend is provisioned (set `otlp_endpoint` to ship traces).
