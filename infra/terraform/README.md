# Infrastructure — Terraform (AWS)

## Prerequisites

| Tool | Version |
|------|---------|
| Terraform | ≥ 1.6.0 |
| AWS CLI | ≥ 2.0 |
| Docker | ≥ 24 |

**AWS permissions required:**
- `AdministratorAccess` (for initial setup) or a scoped policy covering ECS, ECR, RDS, EC2, IAM, CloudWatch, Secrets Manager.

---

## Quick Deployment Steps

### 1. Configure AWS credentials

```bash
aws configure        # or export AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
aws sts get-caller-identity   # verify
```

### 2. Initialise Terraform

```bash
cd infra/terraform
terraform init
```

### 3. Create a `terraform.tfvars` file

```hcl
# infra/terraform/terraform.tfvars
aws_region          = "us-east-1"
environment         = "dev"
db_master_password  = "SuperSecretPassword123!"
tenant_keys_secret  = "acme:key-acme-prod,globex:key-globex-prod"
image_tag           = "latest"
alarm_sns_arn       = ""   # Optional: ARN of an SNS topic for alarms
```

> ⚠️ **Never commit `terraform.tfvars` to source control.** Add it to `.gitignore`.

### 4. Plan and apply

```bash
terraform plan -var-file=terraform.tfvars -out=tfplan
terraform apply tfplan
```

### 5. Build and push the Docker image

```bash
# Get ECR URL from Terraform output
ECR_URL=$(terraform output -raw ecr_repository_url)
AWS_REGION="us-east-1"

# Authenticate Docker with ECR
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin $ECR_URL

# Build and push
cd ../..   # back to project root
docker build -f infra/docker/Dockerfile -t $ECR_URL:latest .
docker push $ECR_URL:latest
```

### 6. Update the ECS service

```bash
CLUSTER=$(terraform -chdir=infra/terraform output -raw ecs_cluster_name)
aws ecs update-service \
  --cluster $CLUSTER \
  --service kip-dev-svc \
  --force-new-deployment \
  --region us-east-1
```

### 7. Verify deployment

```bash
ALB_URL=$(terraform -chdir=infra/terraform output -raw alb_dns_name)
curl http://$ALB_URL/api/v1/health
```

---

## Blue/Green Deployment Strategy

The ECS service uses a `CODE_DEPLOY` deployment controller. AWS CodeDeploy manages the traffic shift between the `blue` (current) and `green` (new) target groups.

### Traffic shift policy (configured in CodeDeploy)

1. Deploy new task set to the **green** target group
2. Run health checks — CodeDeploy waits until green tasks pass
3. Shift **10%** of traffic to green (canary)
4. Bake for **5 minutes** monitoring the CloudWatch alarms:
   - `kip-{env}-alb-5xx` — error rate alarm
   - `kip-{env}-alb-p99-latency` — latency alarm
5. If alarms are OK, shift **100%** of traffic to green
6. Terminate old (blue) tasks

**Automatic rollback:** If either alarm fires during the bake window, CodeDeploy automatically shifts traffic back to blue within 60 seconds.

### Manual rollback

```bash
aws deploy stop-deployment \
  --deployment-id d-XXXXXXXXX \
  --auto-rollback-enabled \
  --region us-east-1
```

---

## Scaling Strategy

| Metric | Scale Out Threshold | Scale In Threshold | Cooldown |
|--------|--------------------|--------------------|---------|
| CPU Utilization | > 60% | < 40% | Out: 60s / In: 300s |
| Memory Utilization | > 70% | < 50% | Out: 60s / In: 300s |

- **Minimum tasks:** 1 (dev) / 2 (prod)
- **Maximum tasks:** 20

Aurora Serverless v2 scales automatically between 0.5 and 8 ACUs based on load, with no downtime during scaling.

---

## Destroy (cleanup)

```bash
cd infra/terraform
terraform destroy -var-file=terraform.tfvars
```

> ⚠️ In production (`environment = "prod"`), `deletion_protection = true` on Aurora and `force_delete` is disabled. You must manually disable deletion protection before destroying.
