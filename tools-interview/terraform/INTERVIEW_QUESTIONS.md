# 🏗️ Terraform — Staff-Level Interview Questions

> *8 questions covering Terraform state management, resource graph, modules, providers, CI/CD integration, HCL advanced patterns, and security — every question expects principal engineer-level depth with production patterns.*

---

## Table of Contents

1. [State Management: Local vs Remote, Locking, Migration](#1-state-management-local-vs-remote-locking-migration)
2. [Resource Graph & Dependency Resolution](#2-resource-graph-dependency-resolution)
3. [Modules: Composition, Versioning, Registry](#3-modules-composition-versioning-registry)
4. [Workspaces & Multi-Environment Strategy](#4-workspaces-multi-environment-strategy)
5. [Providers: Architecture, CRUD, Custom Providers](#5-providers-architecture-crud-custom-providers)
6. [CI/CD Integration: Terraform Cloud, Atlantis](#6-cicd-integration-terraform-cloud-atlantis)
7. [Advanced HCL: Functions, Dynamic Blocks, Expressions](#7-advanced-hcl-functions-dynamic-blocks-expressions)
8. [Security: Secrets Management, IAM, Policy as Code](#8-security-secrets-management-iam-policy-as-code)

---

## 1. State Management: Local vs Remote, Locking, Migration

**Q:** "Your team of 10 engineers is managing AWS infrastructure with Terraform. Two engineers ran `terraform apply` simultaneously and caused a resource conflict. Design a remote state strategy with locking. How does Terraform state work? How do you migrate state from local to S3 without downtime?"

**What They're Really Testing:** Whether you understand Terraform state as the source of truth for resource mapping — the difference between local and remote state, state locking mechanisms, and state migration procedures.

### Answer

**Terraform State Mechanics:**

```yaml
# Terraform state: JSON file mapping logical resources to real-world resources
# terraform.tfstate contains:

{
  "version": 4,
  "terraform_version": "1.7.0",
  "serial": 42,
  "lineage": "abc-123-def",
  "outputs": {},
  "resources": [
    {
      "module": "root",
      "mode": "managed",
      "type": "aws_instance",
      "name": "web_server",
      "provider": "provider[\"registry.terraform.io/hashicorp/aws\"]",
      "instances": [
        {
          "schema_version": 1,
          "attributes": {
            "id": "i-0abcd1234efgh5678",
            "ami": "ami-0c55b159cbfafe1f0",
            "instance_type": "t3.micro",
            "private_ip": "10.0.1.42",
            "subnet_id": "subnet-abc123",
            "tags": {
              "Name": "web-server-prod"
            }
          },
          "dependencies": [
            "aws_subnet.main",
            "aws_security_group.web"
          ]
        }
      ]
    }
  ]
}

# What state contains:
# - Resource metadata: type, name, provider
# - Resource attributes: all current attribute values
# - Dependencies: what this resource depends on
# - Private data: sensitive values (sometimes encrypted)
# - Serial number: monotonic counter for state versioning
```

**Remote State with Locking:**

```yaml
# S3 backend with DynamoDB locking:

terraform {
  backend "s3" {
    bucket         = "my-infra-terraform-state"
    key            = "prod/network/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "terraform-state-locks"
  }
}

# DynamoDB table for state locking:
# - Table: terraform-state-locks
# - Partition key: LockID (string)
# - When terraform apply runs:
#   1. Create item: LockID = "my-infra-terraform-state/prod/network/terraform.tfstate.md5"
#   2. If item exists → lock acquisition fails → TERRAFORM EXITS WITH ERROR
#   3. When apply completes → delete item (release lock)
#   4. If apply crashes → lock held for ~15 min (then released via S3 eventual consistency)
#   5. Force unlock (if needed): terraform force-unlock <LOCK_ID>

# Multiple backends comparison:
Backend      | Locking | Encryption | History | Complexity
-------------|---------|------------|---------|-----------
local        | ❌     | ❌         | ❌     | None
S3 + DynamoDB| ✅     | ✅ (SSE)   | ✅ (versioning) | Low
Terraform Cloud| ✅   | ✅         | ✅     | Medium
Consul       | ✅     | ❌ (optional) | ❌   | High (run Consul)
pg (Postgres)| ✅     | ✅ (TLS)   | ❌     | Medium

# State versioning (S3):
# Enable S3 versioning on the state bucket
# If state is corrupted: restore previous version
# If state is deleted: restore from version history
# Audit trail: who modified state and when (CloudTrail)
```

**State Migration:**

```yaml
# Migrating from local to remote state:

# Step 1: Initialize remote backend (without state)
terraform init -migrate-state
# Terraform detects: current backend = local, new backend = s3
# Prompt: "Do you want to copy existing state to the new backend?"
# Answer: yes
# Terraform: copies terraform.tfstate → s3://bucket/prod/network/terraform.tfstate
#           renames local terraform.tfstate → terraform.tfstate.backup

# Step 2: Verify remote state
terraform state list
# Should show all resources (confirm state was copied)

# Step 3: Remove local state (after verification)
rm terraform.tfstate.backup

# State recovery (if state is corrupted):
# 1. Restore from S3 versioning
aws s3api get-object-version \
  --bucket my-infra-terraform-state \
  --key prod/network/terraform.tfstate \
  --version-id <PREVIOUS_VERSION_ID> \
  terraform.tfstate.recovered

# 2. Import resources (if no backup)
# terraform import aws_instance.web_server i-0abcd1234efgh5678
# Problem: must know every resource's ID
# Better: use terraform state rm + terraform import for each resource

# State operations:
  terraform state list                # List all resources in state
  terraform state show aws_instance.web  # Show resource attributes
  terraform state mv aws_instance.web aws_instance.web_v2  # Rename resource
  terraform state rm aws_instance.old   # Remove resource from state (not destroy!)
  terraform import aws_instance.new i-123456  # Add existing resource to state
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **State mechanics** | Understands state as JSON mapping with serial number for versioning |
| **Locking mechanism** | Knows DynamoDB item-based lock with Force-Unlock for crash recovery |
| **Backend selection** | Can compare S3+DynamoDB vs Terraform Cloud vs Consul for different team sizes |
| **State recovery** | Has recovery plan: S3 versioning restore → import fallback |

---

## 2. Resource Graph & Dependency Resolution

**Q:** "You have 100 Terraform resources with complex interdependencies. `terraform plan` takes 5 minutes to compute. How does Terraform's dependency graph work? How do implicit and explicit dependencies differ? How do you optimize plan time and avoid dependency cycles?"

**What They're Really Testing:** Whether you understand Terraform's core execution model — the DAG (Directed Acyclic Graph) that determines resource creation, update, and destruction order.

### Answer

**Dependency Graph Mechanics:**

```yaml
# Terraform builds a DAG (Directed Acyclic Graph) from resource references

# Implicit dependencies (auto-detected by Terraform):
resource "aws_instance" "web" {
  ami           = data.aws_ami.ubuntu.id       # ← implicit dependency on data.aws_ami
  instance_type = "t3.micro"
  subnet_id     = aws_subnet.main.id            # ← implicit dependency on aws_subnet.main
  security_groups = [aws_security_group.web.name] # ← implicit dependency on aws_sg.web
}

# Terraform infers: web depends on (data.aws_ami, aws_subnet.main, aws_security_group.web)
# Graph: data.aws_ami → aws_instance.web ← aws_subnet.main
#                                         ← aws_security_group.web

# Explicit dependencies (when Terraform can't auto-detect):
resource "aws_s3_bucket" "data" {
  bucket = "my-data-lake"
}

resource "aws_s3_bucket_object" "config" {
  bucket = aws_s3_bucket.data.bucket
  key    = "config.json"
  source = "config.json"
  
  # Even though no reference to aws_lambda_function.processor
  # This object must be created BEFORE the Lambda function
  depends_on = [aws_lambda_function.processor]
}

# Use depends_on when:
# 1. Provisioner dependencies (Terraform can't see into the script)
# 2. Side-effect dependencies (e.g., DNS propagation before cert validation)
# 3. Module-level dependencies (Terraform doesn't inspect module internals for depends_on)
```

**Plan Time Optimization:**

```yaml
# Why plan takes 5 minutes for 100 resources:

# Serial operations:
# Terraform must refresh state for EACH resource
# Each refresh = API call to AWS
# 100 resources × 500ms avg API latency = 50 seconds
# But: depends_on creates chains: one resource must complete before next starts

# Parallelism:
terraform plan -parallelism=20  # Default: 10
# Higher parallelism = faster plan (but more API rate limit risk)

# Optimization strategies:

# 1. Target specific resources (for quick plans)
terraform plan -target=aws_instance.web
# Only plans the targeted resource + its dependencies
# RISK: can create partial plans that miss dependency updates!

# 2. Use data sources sparingly
# Data sources are REFRESHED every plan/apply
# data "aws_secretsmanager_secret" "db_pass"  # API call every plan!
# Solution: use static values or SSM Parameter Store with caching

# 3. Split into multiple state files
# Instead of 1 state with 100 resources:
# - state-1: network (10 resources)
# - state-2: database (20 resources)
# - state-3: application (70 resources)
# Each plans independently (faster!)
# Data exchange: terraform_remote_state data source

# 4. Use -refresh-only for independent refresh
terraform plan -refresh-only  # Refresh state without changing resources
terraform apply -refresh-only  # Update state to match real world (no resource changes)

# 5. Parallelism tuning:
# Small infra (< 50 resources): parallelism = 10 (default)
# Medium infra (50-200): parallelism = 20
# Large infra (200+): parallelism = 30-50 (watch API rate limits)
```

**Dependency Cycles & Resolution:**

```yaml
# Dependency cycle example (DAG cycle):
resource "aws_security_group" "web" {
  name = "web-sg"
  ingress {
    security_groups = [aws_security_group.lb.id]  # → depends on lb
  }
}

resource "aws_security_group" "lb" {
  name = "lb-sg"
  ingress {
    security_groups = [aws_security_group.web.id]  # → depends on web
  }
}
# Cycle: web → lb → web (CIRCULAR DEPENDENCY!)
# Error: "Cycle: aws_security_group.web, aws_security_group.lb"

# Solutions:
# 1. Use self-referencing ingress (avoid mutual SG references)
# 2. Break the cycle by using IP-based ingress instead of SG IDs
# 3. Use separate state files (import one SG ID as data source)
# 4. Use "lifecycle" to create one SG with known CIDR, then update

# Good practice: tiered security groups
# Tier 1: ALB SG (allow 0.0.0.0/0:443)
# Tier 2: App SG (allow ALB SG → no cycle!)
# Tier 3: DB SG (allow App SG → no cycle!)
```

**Graph Visualization:**

```bash
# Visualize the dependency graph:
terraform graph | dot -Tpng > graph.png
# Install Graphviz: brew install graphviz
# Output: PNG file showing all resources and their dependencies
# Red edges: dependencies
# Blue nodes: resources
# Green nodes: data sources
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Implicit vs explicit** | Knows Terraform auto-detects references, depends_on for provisioners/side-effects |
| **Plan optimization** | Can tune parallelism, split state, and use -target correctly |
| **Cycle resolution** | Can break circular dependencies with IP-based references or tiered structure |
| **Graph visualization** | Uses terraform graph + Graphviz to debug complex dependency chains |

---

## 3. Modules: Composition, Versioning, Registry

**Q:** "Your team manages 50 infrastructure components using Terraform modules. Design a module strategy for reusability across 3 environments (dev, staging, prod). How do you version modules? How do you publish to a private registry? When should you NOT use a module?"

**What They're Really Testing:** Whether you understand Terraform modules as the unit of composition — input/output contracts, versioning strategies, and the trade-offs between abstraction and flexibility.

### Answer

**Module Design Principles:**

```yaml
# Module structure:
modules/
  ├── networking/
  │   ├── main.tf          # VPC, subnets, NAT gateway, route tables
  │   ├── variables.tf     # Input variables with type constraints
  │   ├── outputs.tf       # Outputs for consuming modules
  │   └── README.md        # Documentation
  ├── compute/
  │   ├── main.tf          # ASG, launch template, ALB
  │   ├── variables.tf
  │   ├── outputs.tf
  │   └── README.md
  ├── database/
  │   ├── main.tf          # RDS, replica, security group
  │   ├── variables.tf
  │   ├── outputs.tf
  │   └── README.md
  └── kubernetes/
      ├── main.tf          # EKS cluster, node groups, add-ons
      ├── variables.tf
      ├── outputs.tf
      └── README.md

# Module interface (variables.tf):
variable "environment" {
  type        = string
  description = "Environment name (dev, staging, prod)"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be dev, staging, or prod."
  }
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC"
  default     = "10.0.0.0/16"
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to all resources"
  default     = {}
}

# Module outputs (outputs.tf):
output "vpc_id" {
  description = "ID of the created VPC"
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "IDs of private subnets"
  value       = aws_subnet.private[*].id
}
```

**Module Versioning Strategy:**

```yaml
# Source: git tags, registry versions, or local paths

# Option 1: Git tags (recommended for internal)
module "networking" {
  source = "git::https://github.com/my-org/tf-modules.git//networking?ref=v1.2.0"
  # ref: branch (main), tag (v1.2.0), or commit (abc123)
  environment = var.environment
  vpc_cidr    = "10.0.0.0/16"
}

# Option 2: Terraform Registry (public or private)
module "networking" {
  source  = "my-org/network/aws"
  version = "~> 1.2"  # >= 1.2, < 2.0
  # version constraints:
  #   >= 1.2.0        = at least 1.2.0
  #   ~> 1.2.0        = >= 1.2.0, < 1.3.0 (pessimistic)
  #   ~> 1.2          = >= 1.2.0, < 2.0.0
  #   >= 1.0, < 2.0   = range
  environment = var.environment
}

# Option 3: Local path (for development)
module "networking" {
  source      = "../../modules/networking"
  environment = var.environment
}

# Versioning workflow:
# 1. Develop module: source = "./modules/networking" (local)
# 2. Test: run terraform plan/apply in dev environment
# 3. Tag: git tag v1.2.0 && git push --tags
# 4. Publish: push to private registry (Terraform Cloud / JFrog)
# 5. Consume: source = "my-org/network/aws", version = "~> 1.2"
# 6. Major change: bump to v2.0.0 (breaking change alert!)
```

**Private Module Registry (Terraform Cloud):**

```yaml
# Terraform Cloud private registry:
# 1. Connect VCS provider (GitHub, GitLab, Bitbucket)
# 2. Define module repository naming:
#    terraform-<PROVIDER>-<NAME>
#    Example: terraform-aws-networking, terraform-aws-compute
# 3. Tag a release: git tag v1.0.0
# 4. Registry auto-imports the tag
# 5. Team can browse module docs in Terraform Cloud UI

# Requirements for module registry:
# - README.md required (auto-displayed in registry)
# - variables.tf with descriptions (auto-generated inputs)
# - outputs.tf with descriptions (auto-generated outputs)
# - Semantic versioning: vMAJOR.MINOR.PATCH

# Without Terraform Cloud: use git source with ref:
# source = "git::https://github.com/my-org/terraform-aws-networking?ref=v1.2.0"
```

**When NOT to Use Modules:**

```yaml
# Over-abstracting is a common anti-pattern:

# DON'T use a module for:
# 1. Unique or one-off resources
#    - A module with one resource and 20 variables is over-engineering
#    - Just write the resource directly

# 2. Resources that change frequently
#    - If you update the module every week, consumers can't keep up
#    - Prefer direct resource definitions for frequently changing infra

# 3. Simple wrappers (passthrough anti-pattern):
# BAD: Module that just passes variables through
module "s3_bucket" {
  source     = "./modules/s3"
  bucket     = var.bucket      # ← Just passes through!
  acl        = var.acl         # ← No logic!
  tags       = var.tags        # ← No value added!
  versioning = var.versioning
}
# Instead: use the resource directly! (less indirection)

# 4. Cross-cutting concerns that need coordination
# Module can't share state between instances
# Example: VPC module should not also create subnets (separate module or resource)

# Good module candidates:
# - Resources that always appear together (VPC + subnets + route tables + NAT GW)
# - Resources with complex setup that should be consistently configured
# - Standardized patterns used across 10+ environments
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Module interface** | Designs clear input variables with types/validation, outputs with descriptions |
| **Version constraints** | Uses semantic versioning with pessimistic constraint (~> 1.2) |
| **Private registry** | Knows Terraform Cloud registry or git tag ref pattern for internal modules |
| **When NOT to module** | Identifies passthrough modules and one-off resources as bad candidates |

---

## 4. Workspaces & Multi-Environment Strategy

**Q:** "Design a Terraform directory structure for 3 environments (dev, staging, prod) with shared modules. Compare workspaces vs directory layouts. How do you manage environment-specific variables? How do you prevent a staging change from affecting production?"

**What They're Really Testing:** Whether you understand workspace mechanics — the difference between Terraform Cloud workspaces and CLI workspaces — and can design a safe multi-environment deployment strategy.

### Answer

**Workspaces vs Directory Layout:**

```yaml
# Option 1: Terraform CLI Workspaces (single directory, multiple states)

environments/
  └── network/
      ├── main.tf
      ├── variables.tf
      └── outputs.tf

# Same Terraform code, different state files:
# terraform workspace new dev      → state: env:/dev/network
# terraform workspace new staging  → state: env:/staging/network  
# terraform workspace new prod     → state: env:/prod/network

# Variables: use terraform.tfvars per workspace
terraform workspace select dev
terraform apply -var-file=dev.tfvars

# Pros: single codebase, no duplication
# Cons: easy to forget which workspace you're in!
#       can accidentally: `terraform apply` in prod while thinking you're in dev

# Option 2: Directory Layout (recommended for teams)

environments/
  ├── dev/
  │   ├── network/
  │   │   ├── main.tf
  │   │   └── terraform.tfvars     # Environment-specific values
  │   └── database/
  │       ├── main.tf
  │       └── terraform.tfvars
  ├── staging/
  │   ├── network/
  │   │   ├── main.tf
  │   │   └── terraform.tfvars
  │   └── database/
  │       └── main.tf
  └── prod/
      ├── network/
      │   ├── main.tf
      │   └── terraform.tfvars
      └── database/
          └── main.tf

modules/
  ├── networking/
  │   ├── main.tf
  │   ├── variables.tf
  │   └── outputs.tf
  └── database/
      ├── main.tf
      ├── variables.tf
      └── outputs.tf

# Each environment directory has its OWN state file (S3 key: env/network/dev)
# Separation: physical directory prevents cross-environment mistakes
# CI/CD: each environment has its own pipeline step
# Required: CI checks that prod apply only happens after staging verification
```

**Variable Management Strategy:**

```yaml
# Environment-specific variables using YAML or terraform.tfvars:

# environments/prod/network/terraform.tfvars:
environment     = "prod"
vpc_cidr        = "10.0.0.0/16"
private_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
public_subnets  = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]
instance_type   = "t3.large"
min_size        = 3
max_size        = 20

# environments/staging/network/terraform.tfvars:
environment     = "staging"
vpc_cidr        = "10.1.0.0/16"
private_subnets = ["10.1.1.0/24", "10.1.2.0/24"]
public_subnets  = ["10.1.101.0/24", "10.1.102.0/24"]
instance_type   = "t3.medium"
min_size        = 1
max_size        = 5

# environments/dev/network/terraform.tfvars:
environment     = "dev"
vpc_cidr        = "10.2.0.0/16"
private_subnets = ["10.2.1.0/24"]
public_subnets  = ["10.2.101.0/24"]
instance_type   = "t3.micro"
min_size        = 1
max_size        = 2

# Shared variables (for all environments):
# environments/shared/common.tfvars:
region          = "us-east-1"
tags            = { Owner = "platform-team", ManagedBy = "terraform" }
```

**Terraform Cloud Workspaces:**

```yaml
# Terraform Cloud: remote workspaces with RBAC

# Each environment = separate workspace in TFC:
Workspaces:
  - net-dev      → AWS dev account, us-east-1
  - net-staging  → AWS staging account, us-east-1
  - net-prod     → AWS prod account, us-east-1

# Variables scoped to workspace:
# Terraform variables: vpc_cidr, instance_type, ...
# Environment variables: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (sensitive)

# Run workflow:
# 1. PR to environments/dev → plan (auto) → apply (manual)
# 2. PR to environments/staging → plan (auto) → apply (manual)
# 3. PR to environments/prod → plan (manual) → apply (manual, requires approval)

# Teams & permissions:
# - dev: developers can plan + apply
# - staging: developers can plan, senior can apply
# - prod: only platform team can plan + apply (requires approval gate)
```

**Preventing Cross-Environment Mistakes:**

```yaml
# Safety mechanisms:

# 1. Environment-specific AWS profiles/roles
# ~/.aws/config:
[profile dev]
role_arn = arn:aws:iam::DEV_ACCOUNT:role/TerraformRole

[profile prod]
role_arn = arn:aws:iam::PROD_ACCOUNT:role/TerraformRole

# Provider config:
provider "aws" {
  profile = "dev"  # Can't accidentally use prod creds
}

# 2. Directory structure: CI/CD only runs apply for the changed directory
# No: manual terraform apply in environments/prod
# Yes: CI pipeline applies prod after PR merge + staging verification

# 3. terraform plan validation:
# Run plan for ALL environments on every PR
# Visual diff shows what changes in each environment
# Prevents: "I thought this was staging but it changed prod"

# 4. State file separate per environment:
# S3 key: dev/network/terraform.tfstate
# S3 key: staging/network/terraform.tfstate
# S3 key: prod/network/terraform.tfstate
# Different DynamoDB lock items → no cross-environment lock conflicts

# 5. CI gating:
# - Auto-plan on PR (all environments)
# - Auto-apply for dev (fast feedback)
# - Manual approval for staging
# - Manual approval + 2 reviewers for prod
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Workspace vs directory** | Recommends directory layout for teams (safer, clearer ownership) |
| **Variable separation** | Uses per-environment tfvars files with shared common vars |
| **CI/CD gating** | Designs approval gates per environment (auto dev → manual staging → gated prod) |
| **Safety** | Uses separate AWS profiles, separate state files, and CI/CD to prevent cross-env mistakes |

---

## 5. Providers: Architecture, CRUD, Custom Providers

**Q:** "You need to manage a third-party SaaS API (e.g., Datadog, PagerDuty) with Terraform. How does a Terraform provider work? Walk through the CRUD lifecycle. How would you build a custom provider for an internal API?"

**What They're Really Testing:** Whether you understand Terraform's provider model — the gRPC-based provider protocol, the resource lifecycle (CRUD), and the abstraction between provider implementation and user-facing HCL.

### Answer

**Provider Architecture:**

```yaml
# Terraform provider architecture:

┌─────────────────────────────────────────────────────────────┐
│  Terraform Core (HCL parser, graph, state engine)           │
│                                                              │
│  gRPC connection to provider process                         │
│  Provider runs as SEPARATE BINARY (not embedded in TF)       │
│  Communication: protocol buffers over gRPC                   │
│  Provider binary: terraform-provider-<NAME>_vX.Y.Z           │
└────────────────────┬────────────────────────────────────────┘
                     │ gRPC
┌────────────────────▼────────────────────────────────────────┐
│  Provider Plugin                                            │
│                                                              │
│  ├── Provider Config (authentication, region, endpoints)    │
│  │                                                           │
│  ├── Resources (CRUD operations)                             │
│  │   ├── Create: POST /api/v1/resources                    │
│  │   ├── Read:   GET  /api/v1/resources/{id}               │
│  │   ├── Update: PUT  /api/v1/resources/{id}               │
│  │   └── Delete: DELETE /api/v1/resources/{id}             │
│  │                                                           │
│  └── Data Sources (read-only queries)                       │
│      └── Read: GET /api/v1/resources                        │
└─────────────────────────────────────────────────────────────┘

# Provider lifecycle:
# 1. Core starts provider process (separate binary)
# 2. Core calls: ConfigureProvider (auth, region)
# 3. Core calls: ValidateResourceConfig, PlanResourceChange, ApplyResourceChange
# 4. On completion: Kill provider process
```

**Resource CRUD Lifecycle:**

```go
// Go example (Terraform Plugin Framework):

func (r *resourceService) Create(ctx context.Context,
    req tfsdk.CreateResourceRequest, resp *tfsdk.CreateResourceResponse,
) {
    var plan ServiceModel
    req.Plan.Get(ctx, &plan)
    
    // 1. Build API request from plan attributes
    apiReq := api.CreateServiceRequest{
        Name:     plan.Name.ValueString(),
        Team:     plan.Team.ValueString(),
        Enabled:  plan.Enabled.ValueBool(),
    }
    
    // 2. Call API
    apiResp, err := r.client.CreateService(ctx, apiReq)
    if err != nil {
        resp.Diagnostics.AddError("Failed to create service", err.Error())
        return
    }
    
    // 3. Set ID from API response
    plan.ID = types.StringValue(apiResp.ID)
    
    // 4. Set computed attributes (from API, not from config)
    plan.CreatedAt = types.StringValue(apiResp.CreatedAt)
    plan.UpdatedAt = types.StringValue(apiResp.UpdatedAt)
    
    // 5. Save to state
    resp.State.Set(ctx, &plan)
}

func (r *resourceService) Read(ctx context.Context,
    req tfsdk.ReadResourceRequest, resp *tfsdk.ReadResourceResponse,
) {
    var state ServiceModel
    req.State.Get(ctx, &state)
    
    // 1. Get resource by ID from API
    apiResp, err := r.client.GetService(ctx, state.ID.ValueString())
    if err != nil {
        // Handle 404 → remove from state (resource deleted outside Terraform)
        if errors.Is(err, api.ErrNotFound) {
            resp.State.RemoveResource(ctx)
            return
        }
        resp.Diagnostics.AddError("Failed to read service", err.Error())
        return
    }
    
    // 2. Refresh state with latest API values
    state.Name      = types.StringValue(apiResp.Name)
    state.Team      = types.StringValue(apiResp.Team)
    state.Enabled   = types.BoolValue(apiResp.Enabled)
    state.UpdatedAt = types.StringValue(apiResp.UpdatedAt)
    
    // 3. Save refreshed state
    resp.State.Set(ctx, &state)
}

func (r *resourceService) Update(ctx context.Context,
    req tfsdk.UpdateResourceRequest, resp *tfsdk.UpdateResourceResponse,
) {
    var plan, state ServiceModel
    req.Plan.Get(ctx, &plan)   // Desired state
    req.State.Get(ctx, &state) // Current state
    
    // 1. Only call API if something changed
    if plan.Name != state.Name || plan.Team != state.Team {
        apiReq := api.UpdateServiceRequest{
            ID:       state.ID.ValueString(),
            Name:     plan.Name.ValueString(),
            Team:     plan.Team.ValueString(),
        }
        _, err := r.client.UpdateService(ctx, apiReq)
        if err != nil {
            resp.Diagnostics.AddError("Failed to update service", err.Error())
            return
        }
    }
    
    // 2. Read back updated state
    apiResp, _ := r.client.GetService(ctx, state.ID.ValueString())
    plan.UpdatedAt = types.StringValue(apiResp.UpdatedAt)
    
    resp.State.Set(ctx, &plan)
}

func (r *resourceService) Delete(ctx context.Context,
    req tfsdk.DeleteResourceRequest, resp *tfsdk.DeleteResourceResponse,
) {
    var state ServiceModel
    req.State.Get(ctx, &state)
    
    // 1. Call API to delete
    err := r.client.DeleteService(ctx, state.ID.ValueString())
    if err != nil {
        // If already deleted (404), just remove from state
        if !errors.Is(err, api.ErrNotFound) {
            resp.Diagnostics.AddError("Failed to delete service", err.Error())
            return
        }
    }
    
    // 2. State is automatically removed
}
```

**When to Build a Custom Provider:**

```yaml
# Custom provider thresholds:

# < 5 API calls: use null_resource + local-exec with curl/API calls
resource "null_resource" "register_service" {
  triggers = {
    name = var.service_name
  }
  provisioner "local-exec" {
    command = "curl -X POST https://api.internal.com/services -d '{\"name\": \"${var.service_name}\"}'"
  }
}

# 5-20 API calls: use Terraform provider (hashicorp/random, http data source)
# data "http" "api_response" { ... }
# resource "random_id" "name" { ... }

# 20+ API calls: build custom provider
# Benefits:
# - Type safety: HCL validation catches errors before API calls
# - State management: CRUD lifecycle automatically handles drift
# - Documentation: terraform docs output from schema
# - Team adoption: standard Terraform workflow

# Building a custom provider:
# 1. Use Terraform Plugin Framework (recommended)
# 2. Define provider schema (auth, endpoints)
# 3. Define resource/data source schemas
# 4. Implement CRUD handlers
# 5. Compile: go build -o terraform-provider-myapi_v1.0.0
# 6. Install: copy to ~/.terraform.d/plugins/...
# 7. Publish: upload to Terraform Registry
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **gRPC provider model** | Understands provider runs as separate process, communicates via gRPC |
| **CRUD lifecycle** | Knows the 4 operations and how state is saved/read after each |
| **Computed attributes** | Distinguishes config attributes (from HCL) from computed (from API response) |
| **Custom provider threshold** | Can articulate when to build a provider vs use null_resource (20+ API calls) |

---

## 6. CI/CD Integration: Terraform Cloud, Atlantis

**Q:** "Design a CI/CD pipeline for Terraform infrastructure changes. How does Atlantis automate terraform plan/apply on pull requests? Compare Terraform Cloud vs Atlantis vs GitHub Actions. How do you handle concurrent PRs that modify the same resources?"

**What They're Really Testing:** Whether you understand the operational challenges of infrastructure CI/CD — plan output in PR comments, concurrent change management, and the state locking problem.

### Answer

**Atlantis Workflow:**

```yaml
# Atlantis: PR-driven Terraform automation
# Architecture:

┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  GitHub PR   │────►│  Atlantis    │────►│  Terraform   │
│  (terraform  │     │  (Webhook)   │     │  (State in   │
│   plan/apply)│     │              │     │   S3)        │
└─────────────┘     └──────┬───────┘     └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Pull        │
                    │  Request     │
                    │  Comment     │
                    │  (plan/apply │
                    │   output)    │
                    └─────────────┘

# Workflow:
# 1. Developer creates PR with Terraform changes
# 2. GitHub webhook → Atlantis
# 3. Atlantis runs: terraform plan
# 4. Atlantis comments on PR: plan output
# 5. Reviewer checks plan, approves PR
# 6. Developer comments: "atlantis apply"
# 7. Atlantis runs: terraform apply
# 8. PR merges (apply was already done!)
```

**Atlantis Configuration:**

```yaml
# atlantis.yaml (repo-level config):
version: 3
projects:
  - name: dev-network
    dir: environments/dev/network
    terraform_version: v1.7.0
    workflow: default
    autoplan:
      enabled: true
      when_modified: ["*.tf", "*.tfvars"]
    
  - name: staging-network
    dir: environments/staging/network
    terraform_version: v1.7.0
    workflow: default
    autoplan:
      enabled: true
      when_modified: ["*.tf", "*.tfvars"]
    apply_requirements: ["approved"]  # Require PR approval before apply

  - name: prod-network
    dir: environments/prod/network
    terraform_version: v1.7.0
    workflow: production
    autoplan:
      enabled: true
      when_modified: ["*.tf", "*.tfvars"]
    apply_requirements: ["approved", "mergeable"]  # Require approval + mergeable

workflows:
  production:
    plan:
      steps:
        - init
        - plan:
            extra_args: ["-lock-timeout=300s"]  # Wait 5 min for lock
    apply:
      steps:
        - apply:
            extra_args: ["-lock-timeout=300s"]

# Server config (server-side):
repos:
  - id: /.*/
    branch: /main/
    plan_requirements: [approved]
    apply_requirements: [approved, mergeable]
```

**GitHub Actions for Terraform:**

```yaml
# .github/workflows/terraform.yml
name: Terraform

on:
  pull_request:
    paths:
      - 'environments/**/*.tf'
      - 'modules/**/*.tf'
  push:
    branches: [main]
    paths:
      - 'environments/**/*.tf'
      - 'modules/**/*.tf'

env:
  TF_VERSION: '1.7.0'

jobs:
  plan:
    name: Terraform Plan
    runs-on: ubuntu-latest
    
    strategy:
      matrix:
        environment: [dev, staging, prod]
    
    steps:
      - uses: actions/checkout@v4
      
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: ${{ env.TF_VERSION }}
      
      - name: Terraform Init
        working-directory: environments/${{ matrix.environment }}/network
        run: terraform init
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
      
      - name: Terraform Plan
        id: plan
        working-directory: environments/${{ matrix.environment }}/network
        run: terraform plan -no-color -detailed-exitcode
        continue-on-error: true
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
      
      - name: Post Plan Comment
        uses: actions/github-script@v7
        if: github.event_name == 'pull_request'
        with:
          script: |
            const output = `## Terraform Plan (${{ matrix.environment }})
            \`\`\`\n${{ steps.plan.outputs.stdout }}\n\`\`\``;
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: output
            });
  
  apply:
    name: Terraform Apply
    needs: [plan]
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    
    environment: production  # Requires manual approval in GitHub Environments
    
    strategy:
      matrix:
        environment: [dev, staging, prod]
    
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
      
      - name: Terraform Apply
        working-directory: environments/${{ matrix.environment }}/network
        run: terraform apply -auto-approve
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
```

**Concurrent PRs & State Locking:**

```yaml
# Problem: Two PRs modify the same Terraform resources
# PR1: change VPC CIDR (environments/prod/network/main.tf)
# PR2: add subnet (environments/prod/network/main.tf)

# Scenario:
# 1. PR1's plan runs: shows VPC CIDR change
# 2. PR2's plan runs: uses OLD state (PR1 not applied yet!)
#    Plan shows: add subnet to OLD VPC CIDR
# 3. PR1 merges: apply succeeds, VPC CIDR changes
# 4. PR2 merges: apply FAILS!
#    State serial mismatch: state was updated by PR1
#    terraform detects drift: "planned state doesn't match current state"

# Solutions:
# 1. Locking (DynamoDB): prevents concurrent applies
#    - PR1 acquires lock → applies → releases lock
#    - PR2 tries to acquire lock → WAITS for lock-timeout (e.g., 5 min)
#    - Lock timeout: PR2 fails with timeout (not corrupt!)
#    - PR2 must re-run plan against latest state

# 2. Plan in isolation + Apply sequentially
#    Each PR's plan is valid ONLY for the state at plan time
#    If another PR applied, plan is stale → re-plan required
#    Atlantis: auto-detects stale plan and rejects apply

# 3. Branch isolation (Terraform Cloud):
#    Each branch gets a temporary workspace
#    Plan runs in isolation (no interference)
#    Apply merges to main workspace

# 4. State locking with DynamoDB:
#    Lock timeout: terraform plan -lock-timeout=5m
#    If lock held: wait up to 5 minutes
#    After 5 min: fail with error (not silent failure!)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Atlantis workflow** | Explains webhook → plan comment → apply comment flow |
| **CI/CD gating** | Designs environment-specific approval requirements (auto dev → gated prod) |
| **Concurrency handling** | Explains state locking and stale plan detection for concurrent PRs |
| **Tool comparison** | Can compare Atlantis (PR-native) vs GitHub Actions (customizable) vs TFC (managed) |

---

## 7. Advanced HCL: Functions, Dynamic Blocks, Expressions

**Q:** "You need to create 50 security group rules from a list of ports and protocols. Using HCL functions and dynamic blocks, write a Terraform configuration that creates these rules without repeating code. How do for_each, count, and dynamic blocks differ?"

**What They're Really Testing:** Whether you understand Terraform's configuration language deeply — the meta-arguments for repetition (count, for_each), dynamic blocks for nested schemas, and HCL functions for data transformation.

### Answer

**Dynamic Blocks:**

```yaml
# Problem: Create 50 security group rules without repeating code

# Data: List of ingress rules
variable "ingress_rules" {
  type = list(object({
    port        = number
    protocol    = string
    cidr_blocks = list(string)
    description = optional(string)
  }))
  default = [
    { port = 80,  protocol = "tcp", cidr_blocks = ["10.0.0.0/8"], description = "HTTP" },
    { port = 443, protocol = "tcp", cidr_blocks = ["10.0.0.0/8"], description = "HTTPS" },
    { port = 22,  protocol = "tcp", cidr_blocks = ["10.10.0.0/16"], description = "SSH" },
    { port = 5432, protocol = "tcp", cidr_blocks = ["10.20.0.0/16"], description = "PostgreSQL" },
    # ... 46 more rules
  ]
}

# Solution: dynamic block
resource "aws_security_group" "app" {
  name        = "app-sg"
  description = "Application security group"
  vpc_id      = aws_vpc.main.id

  dynamic "ingress" {
    for_each = var.ingress_rules  # Iterates over the list

    content {
      from_port   = ingress.value.port
      to_port     = ingress.value.port
      protocol    = ingress.value.protocol
      cidr_blocks = ingress.value.cidr_blocks
      description = try(ingress.value.description, "Managed by Terraform")
    }
  }

  dynamic "egress" {
    for_each = var.egress_rules
    content {
      from_port   = 0
      to_port     = 0
      protocol    = "-1"
      cidr_blocks = ["0.0.0.0/0"]
    }
  }

  tags = {
    Name = "app-sg"
  }
}

# Dynamic blocks are useful for:
# - Security group rules
# - Load balancer listener rules
# - Auto-scaling tag specifications
# - IAM policy statements
# Any nested block that repeats with similar structure
```

**count vs for_each:**

```yaml
# count: create N instances of a resource (when N is small and stable)

# Create 3 IAM users
variable "user_names" {
  type    = list(string)
  default = ["alice", "bob", "charlie"]
}

resource "aws_iam_user" "this" {
  count = length(var.user_names)
  name  = var.user_names[count.index]  # 0, 1, 2
}

# Problem with count:
# If you insert a user at index 1: alice(0), bob(1), charlie(2)
# → The list shifts: alice(0), NEW_USER(1), bob(2), charlie(3)
# Terraform sees: user[1] changed from bob → NEW_USER
#                 user[2] changed from charlie → bob
#                 user[3] created (charlie)
# This DESTROYS and RECREATES existing users!
# count.index is positional → fragile!

# for_each: create resources with stable keys

resource "aws_iam_user" "this" {
  for_each = toset(var.user_names)  # Create a set (deduplicates)
  name     = each.key               # "alice", "bob", "charlie"
}

# With map (more attributes):
variable "users" {
  type = map(object({
    groups   = list(string)
    tags     = map(string)
  }))
  default = {
    alice = { groups = ["engineering"], tags = { role = "senior" }}
    bob   = { groups = ["sre"], tags = {} }
  }
}

resource "aws_iam_user" "this" {
  for_each = var.users
  name     = each.key                  # "alice", "bob"
  tags     = each.value.tags
}

resource "aws_iam_user_group_membership" "this" {
  for_each = var.users
  user     = aws_iam_user.this[each.key].name
  groups   = each.value.groups
}

# Inserting "dave" to the map: only dave is created (no recreation!)
# Removing "bob": only bob is destroyed (no cascading!)
# for_each uses stable keys → safe for production
```

**HCL Functions for Data Transformation:**

```yaml
# Common HCL functions for infrastructure transformation:

# 1. Merge tags from multiple sources
locals {
  default_tags = {
    Environment = var.environment
    ManagedBy   = "Terraform"
    Project     = "interview-prep"
  }
  extra_tags = {
    CostCenter = var.cost_center
    Team       = var.team
  }
  all_tags = merge(local.default_tags, local.extra_tags, var.custom_tags)
  # merge: later maps override earlier ones for duplicate keys
}

# 2. CIDR manipulation
locals {
  vpc_cidr    = "10.0.0.0/16"
  subnet_bits = 8  # /16 + 8 = /24 subnets
  az_count    = 3
  
  # Generate subnet CIDRs:
  # cidrsubnet("10.0.0.0/16", 8, 0) → "10.0.0.0/24"
  # cidrsubnet("10.0.0.0/16", 8, 1) → "10.0.1.0/24"
  # cidrsubnet("10.0.0.0/16", 8, 2) → "10.0.2.0/24"
  subnet_cidrs = [
    for i in range(local.az_count) :
    cidrsubnet(local.vpc_cidr, local.subnet_bits, i)
  ]
}

# 3. Flatten nested structures
locals {
  # Convert a list of maps into a flat list for for_each
  ingress_rules = flatten([
    for sg_name, sg in var.security_groups : [
      for rule in sg.ingress_rules : {
        sg_name   = sg_name
        port      = rule.port
        protocol  = rule.protocol
        cidr      = rule.cidr
      }
    ]
  ])
  # flat list: [{sg_name="web", port=80}, {sg_name="web", port=443}, ...]
}

# 4. String formatting
locals {
  name_prefix = "${var.environment}-${var.service_name}"
  
  # formatlist
  instance_names = formatlist("%s-instance-%02d", [local.name_prefix], range(3))
  # ["prod-web-instance-00", "prod-web-instance-01", "prod-web-instance-02"]
}

# 5. Conditional expressions
locals {
  instance_type = var.environment == "prod" ? "t3.large" : "t3.micro"
  
  # Advanced: conditional with coalesce
  description = coalesce(var.description, "Managed by Terraform")
  # Returns first non-null/non-empty value
  
  # try/catch (safe attribute access)
  # Instead of: var.config.endpoint (may fail)
  # Use: try(var.config.endpoint, "default-endpoint")
}
```

**Best Practices for HCL Complexity:**

```yaml
# 1. Use locals for complex expressions (don't inline in resources)
# BAD:
resource "aws_instance" "web" {
  tags = merge(
    { Name = format("%s-%s", var.environment, "web") },
    var.common_tags,
    var.environment == "prod" ? { Backup = "true" } : {}
  )
}

# GOOD:
locals {
  instance_name = "${var.environment}-web"
  backup_tag    = var.environment == "prod" ? { Backup = "true" } : {}
  instance_tags = merge({ Name = local.instance_name }, var.common_tags, local.backup_tag)
}

resource "aws_instance" "web" {
  tags = local.instance_tags
}

# 2. Prefer for_each over count for lists that may change
# 3. Use dynamic blocks only for genuinely repeated nested blocks
# 4. Keep HCL expressions simple — move complex logic to external data sources
# 5. Test HCL expressions with terraform console:
terraform console
> var.environment == "prod" ? "t3.large" : "t3.micro"
"t3.micro"
> merge({a=1}, {b=2})
{ "a" = 1, "b" = 2 }
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Dynamic blocks** | Uses for repeated nested blocks (SG rules, LB listeners) |
| **for_each vs count** | Knows for_each uses stable keys, count uses fragile indices |
| **HCL functions** | Uses merge, flatten, cidrsubnet, format, try for safe data transformation |
| **locals organization** | Moves complex expressions from resources to locals for readability |

---

## 8. Security: Secrets Management, IAM, Policy as Code

**Q:** "Design a secure Terraform workflow for managing secrets across environments. How do you avoid storing secrets in state files? Compare Vault, AWS Secrets Manager, and SOPS for secrets management. How do you enforce policies like 'no public S3 buckets' using Sentinel or OPA?"

**What They're Really Testing:** Whether you understand the security challenges of IaC — secrets in state files, sensitive output handling, and policy enforcement as part of the CI/CD pipeline.

### Answer

**Secrets in State Files:**

```yaml
# Problem: Terraform state contains ALL resource attributes
# Including: database passwords, API keys, private keys

# Example state (vulnerable):
{
  "resources": [
    {
      "type": "aws_db_instance",
      "instances": [{
        "attributes": {
          "password": "SuperSecretP@ssw0rd!",  # PLAINTEXT!
          "username": "admin"
        }
      }]
    }
  ]
}

# Anyone with S3 read access to the state file can see all secrets!
# State bucket permissions = secret access permissions!

# Solutions:

# 1. State encryption at rest (S3 SSE)
terraform {
  backend "s3" {
    encrypt = true  # AES-256 server-side encryption
    # BUT: Terraform decrypts during operations (still visible in process memory)
  }
}

# 2. Use Secrets Manager (reference, don't store)
resource "aws_db_instance" "main" {
  username = "admin"
  password = data.aws_secretsmanager_secret_version.db_pass.secret_string
  # Password is fetched at runtime (not stored in state as plaintext)
  # BUT: state still stores the password! (terraform reads it and writes to state)
}

# 3. Use dynamic secrets (Vault)
resource "aws_db_instance" "main" {
  username = "admin"
  # Vault generates temporary password
  password = vault_dynamic_secret.db.password
  # Password changes on every apply!
  # State stores different password each time (but it's short-lived)
}

# 4. Mark as sensitive (HCL only, not state!)
output "db_password" {
  value     = aws_db_instance.main.password
  sensitive = true  # Hides from CLI output
  # BUT: state still stores the password!
  # sensitive just prevents display in terraform output
}
```

**Secrets Management Integration:**

```yaml
# Option 1: AWS Secrets Manager (for AWS-native)
data "aws_secretsmanager_secret" "db" {
  name = "prod/db/credentials"
}

data "aws_secretsmanager_secret_version" "db" {
  secret_id = data.aws_secretsmanager_secret.db.id
}

resource "aws_db_instance" "main" {
  username = jsondecode(data.aws_secretsmanager_secret_version.db.secret_string).username
  password = jsondecode(data.aws_secretsmanager_secret_version.db.secret_string).password
}

# Option 2: HashiCorp Vault (multi-cloud)
provider "vault" {
  address = "https://vault.internal.com:8200"
  token   = var.vault_token  # From environment variable!
}

data "vault_kv_secret_v2" "db" {
  mount = "kv-v2"
  name  = "environments/prod/database"
}

resource "aws_db_instance" "main" {
  username = data.vault_kv_secret_v2.db.data["username"]
  password = data.vault_kv_secret_v2.db.data["password"]
}

# Option 3: SOPS (Mozilla SOPS) + git
# Encrypt secrets file with age/gpg:
# sops --encrypt prod.enc.tfvars → prod.tfvars (encrypted)
# Decrypt at plan time:
# sops --decrypt prod.tfvars > prod.decrypted.tfvars
# terraform plan -var-file=prod.decrypted.tfvars
# rm prod.decrypted.tfvars  # Clean up!

# Option 4: Terraform Cloud variable sets
# Variables marked "sensitive" in TFC:
# - Encrypted at rest and in transit
# - Not visible in UI
# - Not logged in run output
# - Injected as environment variables to Terraform runs
```

**Policy as Code (Sentinel / OPA):**

```yaml
# Sentinel (HashiCorp's policy language, requires Terraform Cloud/Enterprise):

# Policy: No public S3 buckets
import "tfplan/v2" as tfplan

# Find all aws_s3_bucket_public_access_block resources
public_access_blocks = filter tfplan.resource_changes as _, rc {
  rc.type is "aws_s3_bucket_public_access_block"
}

# Check that block_public_acls is true for all
main = rule {
  all public_access_blocks as _, block {
    block.change.after.block_public_acls is true
  }
}

# Policy: Restrict instance types
allowed_types = ["t3.micro", "t3.small", "t3.medium", "t3.large", "m5.large"]

aws_instances = filter tfplan.resource_changes as _, rc {
  rc.type is "aws_instance"
}

main = rule {
  all aws_instances as _, instance {
    instance.change.after.instance_type in allowed_types
  }
}

# Policy: Mandatory tags
main = rule {
  all tfplan.resource_changes as _, rc {
    # Skip resources that don't support tagging
    rc.mode is "data" or
    # Check required tags exist
    "Environment" in rc.change.after.tags and
    "Owner" in rc.change.after.tags and
    "CostCenter" in rc.change.after.tags
  }
}

# Enforcement levels:
# - advisory: warn only
# - soft mandatory: warn + requires override
# - mandatory: BLOCK the apply
```

**OPA (Open Policy Agent) for Terraform:**

```yaml
# OPA: CNCF policy engine, works with ANY Terraform (not just TFC)

# Step 1: Generate plan JSON
terraform plan -out=plan.tfplan
terraform show -json plan.tfplan > plan.json

# Step 2: Evaluate with OPA
opa eval --data policy/s3.rego --input plan.json "data.terraform.deny"

# Step 3: Rego policy (s3.rego):
package terraform

# Deny public S3 buckets
deny[msg] {
  resource := input.resource_changes[_]
  resource.type == "aws_s3_bucket_public_access_block"
  resource.change.after.block_public_acls == false
  msg := sprintf("S3 bucket %v must block public ACLs", [resource.change.after.bucket])
}

deny[msg] {
  resource := input.resource_changes[_]
  resource.type == "aws_s3_bucket_public_access_block"
  resource.change.after.block_public_policy == false
  msg := sprintf("S3 bucket %v must block public policies", [resource.change.after.bucket])
}

# Deny instances without encryption
deny[msg] {
  resource := input.resource_changes[_]
  resource.type == "aws_db_instance"
  resource.change.after.storage_encrypted == false
  msg := sprintf("RDS instance %v must be encrypted", [resource.change.after.identifier])
}

# Step 4: Add to CI/CD pipeline
# - plan → plan.json → OPA evaluation → block apply if policy violations

# OPA advantages over Sentinel:
# - Works with ANY Terraform (OSS, Cloud, Enterprise)
# - Open source (no licensing costs)
# - Can use same policies for Kubernetes, APIs, etc.
```

**IAM Least Privilege for Terraform:**

```yaml
# Principle: Terraform should use the MINIMUM permissions needed

# BAD: Terraform using AdministratorAccess
# If terraform credentials leaked → attacker has full AWS access

# GOOD: Scoped IAM policy for Terraform
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "ec2:CreateSecurityGroup",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:DeleteSecurityGroup",
        "ec2:RunInstances",
        "ec2:TerminateInstances",
        "ec2:CreateTags"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::my-terraform-state/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:DeleteItem"
      ],
      "Resource": "arn:aws:dynamodb:*:*:table/terraform-state-locks"
    }
  ]
}

# Use IAM permission boundaries:
# Set a boundary on the Terraform role:
# "PermissionsBoundary": "arn:aws:iam::xxx:policy/TerraformBoundary"
# Even if terraform creates a role with Admin permissions,
# the boundary limits it to the boundary's maximum
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Secrets in state** | Knows state stores all attributes including secrets, proposes Vault or dynamic secrets |
| **Sentinel vs OPA** | Can compare: Sentinel (TFC-only) vs OPA (open, works with any Terraform) |
| **Policy enforcement** | Designs CI/CD pipeline to evaluate OPA policies before terraform apply |
| **IAM least privilege** | Creates scoped IAM roles for Terraform with permission boundaries |

---

> *All 8 questions cover the full breadth of Terraform — from state mechanics and dependency graphs to custom providers, Atlantis CI/CD, and security policy enforcement.*
