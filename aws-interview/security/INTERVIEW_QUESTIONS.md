# ☁️ AWS Security — Staff-Level Interview Questions

> *8 questions covering IAM, KMS, Cognito, WAF, Secrets Manager, Security Hub, GuardDuty, and security architecture — every question expects principal engineer-level depth with production patterns.*

---

## Table of Contents

1. [IAM: Policies, Roles, Permission Boundaries](#1-iam-policies-roles-permission-boundaries)
2. [IAM: Least Privilege at Scale](#2-iam-least-privilege-at-scale)
3. [KMS: Key Management, Encryption at Rest](#3-kms-key-management-encryption-at-rest)
4. [AWS Cognito: AuthN/AuthZ for Applications](#4-aws-cognito-authnauthz-for-applications)
5. [AWS WAF & Managed Rules](#5-aws-waf-managed-rules)
6. [Secrets Manager: Rotation & Vault Architecture](#6-secrets-manager-rotation-vault-architecture)
7. [GuardDuty & Security Hub: Threat Detection](#7-guardduty-security-hub-threat-detection)
8. [AWS Security Reference Architecture](#8-aws-security-reference-architecture)

---

## 1. IAM: Policies, Roles, Permission Boundaries

**Q:** "Design an IAM architecture for a multi-account AWS organization with 50 AWS accounts, 500 developers, and 10 CI/CD pipelines. How do IAM permission boundaries prevent privilege escalation? How does SCP differ from IAM policies? Walk through a cross-account role assumption flow."

**What They're Really Testing:** Whether you understand IAM's delegation model — the relationship between SCPs, IAM policies, and permission boundaries — and can design for least privilege at organizational scale.

### Answer

**IAM Policy Evaluation Chain:**

```yaml
# IAM policy evaluation (DENY always wins):

User → Groups → Roles → Permission Boundary → SCP → Resource Policy
  │        │        │           │               │          │
  └────────┴────────┴───────────┴───────────────┴──────────┘
                        │
                    Effective
                    Permissions
                        │
                 ALLOW/ACCESS GRANTED
                 (unless any DENY)

# Evaluation order:
# 1. Identity-based policies (User, Group, Role) → ALLOW by default
# 2. Permission boundary → sets MAX allowed permissions
# 3. SCP (Service Control Policy) → sets MAX at OU/account level
# 4. Resource-based policies → ALLOW specific access
# 5. Session policies (STS assume-role) → further restricts

# DENY always overrides ALLOW — no matter where it's set
```

**Permission Boundaries:**

```yaml
# Permission Boundary = Maximum permissions a role can have
# Even if IAM policy allows more, boundary limits it

# Example boundary: Developer can only use EC2 and S3
PermissionBoundary:
  Version: "2012-10-17"
  Statement:
    - Effect: Allow
      Action:
        - ec2:*
        - s3:*
      Resource: "*"

# Role with this boundary:
Role:
  AssumeRolePolicy: (allow dev to assume)
  PermissionsBoundary: arn:aws:iam::123456789:policy/developer-boundary
  
  # Even if role policy says:
  ManagedPolicy: AdministratorAccess  # Allows ALL services
  # The permission boundary restricts to EC2 + S3 only!

# Use cases:
# - Developers: can create roles but bounded (no IAM admin)
# - Service teams: bounded to their service scope
# - CI/CD pipelines: bounded to deployment permissions
```

**Cross-Account Role Assumption:**

```yaml
# Developer in Account A needs to access resources in Account B:

Account A (Security)              Account B (Production)
┌─────────────────────┐          ┌─────────────────────┐
│ Developer            │          │                     │
│  IAM User/Dev Role  │          │  ProductionRole     │
│                     │          │  Trust Policy:       │
│                     │          │   Principal:         │
│  AssumeRole →       │─────────►│     AWS: Account-A   │
│                     │          │   Action:            │
│                     │          │     sts:AssumeRole   │
│  Temporary          │◄─────────│   Condition:         │
│  Credentials        │          │     MFA: true        │
└─────────────────────┘          └─────────────────────┘

# Trust policy in Account B:
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "AWS": "arn:aws:iam::ACCOUNT_A:root"
    },
    "Action": "sts:AssumeRole",
    "Condition": {
      "Bool": {
        "aws:MultiFactorAuthPresent": "true"
      }
    }
  }]
}

# Assume role command:
aws sts assume-role \
  --role-arn "arn:aws:iam::ACCOUNT_B:role/ProductionRole" \
  --role-session-name "dev-session" \
  --serial-number "arn:aws:iam::ACCOUNT_A:mfa/dev-user" \
  --token-code 123456

# Temporary credentials (1 hour):
# - AccessKeyId
# - SecretAccessKey
# - SessionToken
# - Expiration
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Evaluation chain** | Explains DENY overrides ALLOW, SCPs bound all accounts in OU |
| **Permission boundaries** | Uses boundaries to delegate role creation without privilege escalation |
| **Cross-account access** | Designs trust policies with conditions (MFA, source IP, VPC endpoint) |
| **STS assume-role** | Understands temporary credentials, session duration limits |

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-iam-permission-boundary.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated IAM Permission Boundary Flow — policy evaluation chain: DENY always wins, boundaries cap max permissions — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 2. IAM: Least Privilege at Scale

**Q:** "Your team manages 200 microservices, each needing different IAM permissions. How do you implement least privilege without managing hundreds of individual IAM roles? Design a CI/CD pipeline that dynamically generates IAM roles per service. How do you audit and detect over-privileged roles?"

**What They're Really Testing:** Whether you understand IAM automation at scale — using IAM Roles Anywhere, service-linked roles, and policy simulation for auditing.

### Answer

**IAM Role per Microservice:**

```yaml
# Pattern: One IAM role per microservice, auto-generated by CI/CD

# CI/CD pipeline (Terraform/CloudFormation):
Service: order-service
  IAM Role: order-service-role
    Trust: ECS/EKS/Lambda
    Policies:
      - service-specific-policy (auto-generated)
      - managed policies (shared):
        - CloudWatchLogsFullAccess
        - X-RayWriteOnlyAccess

# Auto-generated policy from code analysis:
# CI/CD scans source code for AWS SDK calls:
# Scan results:
#   - dynamodb:GetItem
#   - dynamodb:PutItem
#   - sqs:SendMessage
#   - sns:Publish

Generated Policy:
  Effect: Allow
  Action:
    - dynamodb:GetItem
    - dynamodb:PutItem
    - sqs:SendMessage
    - sns:Publish
  Resource:
    - arn:aws:dynamodb:us-east-1:123456789:table/orders
    - arn:aws:dynamodb:us-east-1:123456789:table/orders-index
    - arn:aws:sqs:us-east-1:123456789:order-queue
    - arn:aws:sns:us-east-1:123456789:order-events
```

**IAM Access Analyzer:**

```yaml
# IAM Access Analyzer finds over-privileged policies:

# 1. Policy validation:
# Checks for: too permissive, incorrect ARNs, missing conditions
# Score: PASS/WARNING/ERROR/FATAL

# 2. Unused access analysis:
# Identifies: roles/users with unused permissions
# Reports:
#   Role: order-service-role
#   Unused: s3:ListAllMyBuckets (not used in 90 days)
#   Unused: ec2:DescribeInstances (not used in 180 days)
#   Recommendation: remove unused actions

# 3. External access analysis:
# Finds: roles that can be assumed by external entities
# Critical: cross-account roles with too-permissive trust policies

# 4. Automated remediation:
# - Generate least-privilege policy from CloudTrail logs
# - IAM Access Analyzer → policy generation

# Generate policy from CloudTrail:
aws accessanalyzer start-policy-generation \
  --policy-generation-details '{"principalArn": "arn:aws:iam::123456789:role/order-service-role"}' \
  --cloud-trail-details '{"trailArns": ["arn:aws:cloudtrail:us-east-1:..."], "startTime": "...", "endTime": "..."}'

# Result: compressed policy with ONLY actions actually used
# This is the gold standard for least privilege!
```

**IAM Roles Anywhere (Hybrid):**

```yaml
# IAM Roles Anywhere: on-premises servers get IAM credentials
# Uses X.509 certificates for authentication

# 1. Create trust anchor (CA certificate):
aws rolesanywhere create-trust-anchor \
  --name "corporate-ca" \
  --type "CERTIFICATE_BUNDLE" \
  --source '{"sourceData": {"x509CertificateData": "-----BEGIN CERTIFICATE-----..."}}'

# 2. Create profile (maps certificate to IAM role):
aws rolesanywhere create-profile \
  --name "on-prem-app" \
  --role-arns "arn:aws:iam::123456789:role/on-prem-app-role" \
  --session-policy "..." \
  --duration-seconds 3600

# 3. On-prem server requests credentials:
# Install rolesanywhere-credential-helper
# Runs: AWS_RolesAnywhere_get_credentials
# Returns: temporary AWS credentials!
# On-prem server gets IAM role w/out long-term access keys!

# Use: on-prem databases, legacy servers, hybrid deployments
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Per-service roles** | Generates IAM roles from code analysis, attaches least-privilege policies |
| **Access Analyzer** | Uses CloudTrail analysis to generate least-privilege policies |
| **Unused permissions** | Audits and removes unused permissions regularly |
| **Roles Anywhere** | Extends IAM to on-premises with certificate-based auth |

---

## 3. KMS: Key Management, Encryption at Rest

**Q:** "Design a KMS key hierarchy for a PCI-DSS compliant application. You need envelope encryption for data at rest in S3, EBS, and RDS. How does KMS key rotation work? How do you manage cross-account access to KMS keys? What is the difference between AWS managed keys and customer managed keys?"

**What They're Really Testing:** Whether you understand KMS's key hierarchy — CMK, DEK, envelope encryption — and the operational aspects of key management for compliance.

### Answer

**KMS Key Hierarchy:**

```yaml
# AWS KMS uses envelope encryption:

┌─────────────────────────────────────┐
│  Customer Master Key (CMK)           │
│  - 256-bit AES symmetric            │
│  - Stored in HSM (hardware)         │
│  - Never leaves AWS KMS             │
│  - Key rotation: annual (or auto)   │
└──────────────────┬──────────────────┘
                   │
       ┌───────────┴───────────┐
       │                       │
       ▼                       ▼
┌─────────────────┐   ┌─────────────────┐
│ Data Encryption  │   │ Data Encryption  │
│ Key (DEK)        │   │ Key (DEK)        │
│ - 256-bit AES    │   │ - 256-bit AES    │
│ - Generated per  │   │ - Generated per  │
│   operation      │   │   operation      │
│ - Encrypted by   │   │ - Encrypted by   │
│   CMK            │   │   CMK            │
│ (encrypted DEK   │   │ (encrypted DEK   │
│  stored with     │   │  stored with     │
│  data)           │   │  data)           │
└─────────────────┘   └─────────────────┘

# More detailed architecture for PCI-DSS:

# Key hierarchy for PCI-DSS:
# 1. Root KMS Key (CMK)
# 2. Region-specific KMS keys (one per region)
# 3. Service-specific keys (S3, EBS, RDS)
# 4. Application-specific keys (per microservice)

# Encrypt S3 object:

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-kms-envelope-encryption.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated KMS Envelope Encryption — CMK encrypts DEK, DEK encrypts data, encrypted DEK stored alongside ciphertext — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---
kms_key = 'arn:aws:kms:us-east-1:123456789:key/abc-123'
response = kms.generate_data_key(KeyId=kms_key, KeySpec='AES_256')
plaintext_dek = response['Plaintext']      # Use for encryption, then discard!
encrypted_dek = response['CiphertextBlob']  # Store with object

# Decrypt:
plaintext_dek = kms.decrypt(CiphertextBlob=stored_encrypted_dek)
# Now use plaintext DEK to decrypt the data
```

**Key Rotation:**

```yaml
# KMS key rotation:

# Automatic rotation (once per year):
# - Creates new backing key (new cryptographic material)
# - Old backing key retained (for decryption of old data)
# - Key ID stays the same (automatic for users)
# - Annual rotation: enabled for customer managed keys
# - Cannot: rotate keys more than once per year automatically

# Manual rotation (recommended for PCI-DSS):
# - Create new KMS key (new ID)
# - Update applications to use new key
# - Re-encrypt data with new key
# - Old key retained for decryption only
# - Can rotate monthly or quarterly

# Key rotation strategy:
# 1. Enable automatic annual rotation
# 2. For PCI-DSS: manual rotation every 6 months
# 3. Re-encrypt S3 objects with new key:
#    - Use S3 Batch Operation with KMS re-encrypt
#    - Or: read → kms:decrypt → kms:encrypt → write

# Key deletion:
# - Schedule deletion (7-30 day waiting period)
# - During waiting period: key is "pending deletion"
# - Can cancel deletion during waiting period
# - After deletion: ALL encrypted data becomes UNREADABLE

# Best practice:
# - NEVER delete a key that may have encrypted data
# - Use key aliases (not key IDs) in application config
# - Rotate alias to new key: all apps automatically use new key
```

**Cross-Account Key Access:**

```yaml
# Cross-account KMS access:

# Account A (key owner): KMS key with cross-account policy
KMS Key Policy:
  Version: "2012-10-17"
  Statement:
    - Effect: Allow
      Principal:
        AWS: "arn:aws:iam::ACCOUNT_B:root"
      Action:
        - kms:Decrypt
        - kms:GenerateDataKey
      Resource: "*"
    
    - Effect: Allow
      Principal:
        AWS: "arn:aws:iam::ACCOUNT_B:role/app-role"
      Action:
        - kms:Decrypt
      Resource: "*"
      Condition:
        StringEquals:
          kms:EncryptionContext: {"service": "payment"}

# Account B (user):
IAM Policy for app-role:
  Effect: Allow
  Action:
    - kms:Decrypt
    - kms:GenerateDataKey
  Resource: "arn:aws:kms:us-east-1:ACCOUNT_A:key/abc-123"

# Encryption context (audit trail):
# - Tied to each encryption operation
# - Logged in CloudTrail
# - Acts as additional authentication
{
  "service": "payment",
  "environment": "production",
  "data_type": "pci"
}
```

**AWS Managed vs Customer Managed Keys:**

```yaml
AWS Managed Keys:
  - Created automatically (e.g., aws/s3, aws/ebs, aws/rds)
  - Cannot: view key policy, rotate manually, disable
  - Automatic rotation: every 3 years (default)
  - Cost: free (no $1/month per key)
  - Use: compliance-only encryption, non-critical data

Customer Managed Keys:
  - Created by you
  - Full control: key policy, rotation, enable/disable
  - Automatic rotation: configurable (annual)
  - Cost: $1/month per key + $0.03/10,000 API requests
  - Use: PCI-DSS, HIPAA, sensitive customer data

# For PCI-DSS:
# - Use customer managed keys (control over rotation and access)
# - Separate keys per environment (dev/staging/prod)
# - Separate keys per data classification
# - Enable key rotation (automatic + manual)
# - Monitor key usage in CloudTrail
# - Key deletion: never for prod (schedule for key retirement)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Envelope encryption** | Explains CMK encrypts DEK, DEK encrypts data, DEK stored with data |
| **Key rotation** | Uses aliases for zero-downtime rotation, schedules deletion carefully |
| **Cross-account** | Configures key policies with encryption context for audit |
| **Managed vs customer** | Chooses customer managed for compliance (full control, rotation) |

---

## 4. AWS Cognito: AuthN/AuthZ for Applications

**Q:** "Design an authentication system for a B2B SaaS platform with multi-tenancy. Users belong to organizations, each with role-based access. How does Cognito User Pools handle user registration, MFA, and federation? How do you map Cognito groups to IAM roles for fine-grained authorization?"

**What They're Really Testing:** Whether you understand Cognito's architecture — user pools vs identity pools, group-based authorization, and federation with external identity providers.

### Answer

**Cognito User Pools vs Identity Pools:**

```yaml
Cognito User Pools (CUP):
  - User directory (sign-up, sign-in)
  - MFA (TOTP, SMS)
  - Federation (Google, Apple, SAML, OIDC)
  - JWT tokens (ID token, Access token, Refresh token)
  - Groups and roles (within the app)
  - Custom attributes (tenant_id, role)
  - Lambda triggers (pre-signup, post-auth, etc.)
  - Hosted UI (customizable login page)

Cognito Identity Pools (CIP):
  - AWS credential exchange (get AWS STS credentials)
  - Map federated identities to IAM roles
  - Guest/unauthenticated access
  - Fine-grained IAM policies per user/group
  - Used WITH User Pools (not instead of)

# Typical flow:

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-cognito-auth-flow.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Cognito Authentication & Authorization Flow — User Pool → JWT → Identity Pool → AWS credentials → Resources — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---
# User → User Pool (authenticate) → JWT tokens
# JWT → Identity Pool (exchange for AWS credentials)
# AWS credentials → access S3, DynamoDB, API Gateway
```

**Multi-Tenant Configuration:**

```yaml
# Option 1: Pool-per-tenant
# - Separate User Pool for each organization
# - Complete isolation between tenants
# - Max: 1000 User Pools per account
# - Use: enterprise customers needing isolation
# - Cost: higher (each pool has cost)
# - Management overhead: complex

# Option 2: Group-based (recommended)
# - Single User Pool, groups per tenant
# - Group: tenant-{id}-{role}
# - Custom attribute: custom:tenant_id
# - Use: most B2B SaaS applications
# - Isolation: app-level (Cognito is shared)

Cognito User Pool:
  Schema:
    - Name: custom:tenant_id
      AttributeDataType: String
      Mutable: true
      Required: true

  Groups:
    - Name: tenant-123-admin
      Description: "Admin for org 123"
      Precedence: 10
    
    - Name: tenant-123-user
      Description: "User for org 123"
      Precedence: 20
    
    - Name: tenant-456-admin
      ...
  
  # Each user is member of ONE group (tenant+role)

# Authorization check:
def authorize(user, requested_tenant_id):
    # Extract tenant from JWT
    token_tenant = user['custom:tenant_id']
    
    if token_tenant != requested_tenant_id:
        return 403  # Cross-tenant access denied!
    
    # Extract role
    groups = user['cognito:groups']
    # e.g., ['tenant-123-admin']
    
    return 200  # Authorized
```

**Federation with SAML/OIDC:**

```yaml
# Enterprise federation with SAML:
# User's company uses their own IdP (Okta, Azure AD, etc.)

Cognito User Pool → SAML IdP → Okta/Azure AD

# User flow:
# 1. User clicks "Sign in with Company SSO"
# 2. Cognito redirects to company's SAML IdP
# 3. User authenticates with company credentials
# 4. SAML assertion returned to Cognito
# 5. Cognito creates/finds user and returns JWT
# 6. JWT contains: name, email, groups, tenant_id

# SAML attribute mapping:
SAML Attribute:
  - Name: "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"
    Maps to: email
  
  - Name: "memberOf"
    Maps to: cognito:groups
    # AD groups → Cognito groups

  - Name: "department"
    Maps to: custom:tenant_id

# OIDC federation (Google, Apple, etc.):
Cognito User Pool → Google → Google token → Cognito JWT
# Simpler than SAML, uses JSON web tokens
```

**Lambda Triggers for Custom Logic:**

```python
def lambda_handler(event, context):
    """
    Pre sign-up Lambda trigger.
    Auto-assigns tenant_id and group on registration.
    """
    if event['triggerSource'] == 'PreSignUp_SignUp':
        # Extract tenant from email domain
        email = event['request']['userAttributes']['email']
        domain = email.split('@')[1]
        
        # Look up tenant by domain
        tenant_id = tenant_table.get(domain)
        if not tenant_id:
            raise Exception("Unknown organization domain")
        
        # Auto-verify email (trusted domain)
        event['response']['autoConfirmUser'] = True
        event['response']['autoVerifyEmail'] = True
        
        # Add tenant_id to user attributes
        event['response']['claimsOverrideDetails'] = {
            'claimsToAddOrOverride': {
                'custom:tenant_id': str(tenant_id),
            }
        }
    
    # Post-confirmation: add user to group
    if event['triggerSource'] == 'PostConfirmation_ConfirmSignUp':
        cognito.admin_add_user_to_group(
            UserPoolId=event['userPoolId'],
            Username=event['userName'],
            GroupName=f"tenant-{tenant_id}-user"
        )
    
    return event
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Pool vs identity** | Distinguishes user directory (CUP) from AWS credential exchange (CIP) |
| **Multi-tenancy** | Uses group-based approach with tenant_id attribute for isolation |
| **SAML federation** | Maps enterprise SAML assertions to Cognito attributes and groups |
| **Lambda triggers** | Uses pre/post hooks for auto-verification, group assignment |

---

## 5. AWS WAF & Managed Rules

**Q:** "Design a WAF strategy for a global web application. Compare the AWS WAF managed rule groups (Core rule set, SQL injection, XSS, etc.). How do you tune WAF rules to minimize false positives? How do you use WAF logs for security analytics?"

**What They're Really Testing:** Whether you understand WAF rule evaluation, managed rule group tuning, and the operational challenge of balancing security with user experience.

### Answer

**WAF Rule Groups:**

```yaml
# Managed rule groups (provided by AWS):

AWSManagedRulesCommonRuleSet (CRS):
  - Generic web application protection
  - 15+ rules: SQLi, XSS, LFI/RFI, SSRF, RFI
  - Covers OWASP Top 10
  - Rate: 0.001% false positive rate (well-tuned)

AWSManagedRulesSQLiRuleSet:
  - SQL injection specific
  - Detects: UNION, OR 1=1, comments, hex encoding
  - Body, query string, URI path

AWSManagedRulesKnownBadInputsRuleSet:
  - Known attack patterns
  - Log4j RCE, command injection
  - Vendor-specific CVEs

AWSManagedRulesWindowsRuleSet:
  - Windows-specific: PowerShell, cmd.exe
  - ASP.NET specific attacks

AWSManagedRulesPHPRuleSet:
  - PHP-specific: object injection, file inclusion

AWSManagedRulesLinuxRuleSet:
  - Linux-specific: /etc/passwd, /proc/self

AWSManagedRulesBotControlRuleSet:
  - Bot detection and mitigation
  - Levels: COMMON (basic), TARGETED (advanced)
  - Categories: verified (Googlebot), unverified, malicious

AWSManagedRulesATPRuleSet (Account Takeover):
  - Login brute force detection
  - Stolen credential detection
  - Requires integration with Cognito/ALB
```

**WAF Rule Tuning:**

```yaml
# Rule tuning methodology:

# Phase 1: Count mode (ALLOW, monitor for 2 weeks)
WAF WebACL:
  Rules:
    - Name: AWS-AWSManagedRulesCommonRuleSet
      OverrideAction:
        Count: {}          # Count only (don't block!)
      VisibilityConfig:
        SampledRequestsEnabled: true
        CloudWatchMetricsEnabled: true

# Phase 2: Analyze false positives
# Query WAF logs in Athena:
SELECT 
  rule_name,
  action,
  COUNT(*) as matches,
  COUNT(DISTINCT client_ip) as unique_ips
FROM waf_logs
WHERE action = 'COUNT'
  AND rule_name LIKE 'AWS-AWSManagedRules%'
GROUP BY rule_name, action
ORDER BY matches DESC;

# Phase 3: Create exceptions for false positives
# If CRS blocks legitimate API calls:
WAF WebACL:
  Rules:
    - Name: skip-path-api-exceptions
      Statement:
        NotStatement:
          Statement:
            ByteMatchStatement:
              FieldToMatch:
                UriPath: {}
              SearchString: "/api/"    # API paths
              TextTransformations: [{"Priority": 0, "Type": "NONE"}]
      # CRS doesn't apply to /api/ paths (exempted)

# Phase 4: Switch to BLOCK mode (gradually)
# Enable blocking per rule group
# Start with: KnownBadInputs (low false positive)
# Then: CRS (after 2 weeks of tuning)
# Then: SQLi, XSS (if applicable)
```

**WAF Security Analytics:**

```yaml
# WAF logs → S3 → Athena → QuickSight dashboard:

# 1. Enable WAF logging to S3:
waf.put_logging_configuration(
    ResourceArn='arn:aws:wafv2:us-east-1:123456789:webacl/my-acl',
    LogDestinationConfigs=['arn:aws:firehose:us-east-1:123456789:deliverystream/waf-logs'],
    RedactedFields=[{'SingleHeader': {'Name': 'authorization'}}]  # Mask sensitive data
)

# 2. Top attack sources:
SELECT 
  http_source_ip,
  COUNT(*) as requests,
  COUNT(DISTINCT rule_name) as rules_triggered
FROM waf_logs
WHERE action IN ('BLOCK', 'COUNT')
GROUP BY http_source_ip
ORDER BY requests DESC
LIMIT 100;

# 3. Attack patterns over time:
SELECT 
  date_trunc('hour', timestamp) as hour,
  rule_name,
  COUNT(*) as matches
FROM waf_logs
WHERE action = 'BLOCK'
GROUP BY 1, 2
ORDER BY 1;

# 4. False positive monitoring:
SELECT 
  rule_name,
  COUNT(*) as blocks,
  COUNT(DISTINCT http_source_ip) as unique_ips,
  COUNT(*) FILTER (WHERE http_request_uri LIKE '/api/') as api_hits
FROM waf_logs
WHERE action = 'BLOCK'
  AND rule_vendor = 'AWS'
GROUP BY rule_name
ORDER BY blocks DESC;

# 5. Bot analysis:
SELECT 
  rule_name,
  http_user_agent,
  COUNT(*) as requests
FROM waf_logs
WHERE rule_name LIKE 'AWSBotControl%'
GROUP BY rule_name, http_user_agent
ORDER BY requests DESC;
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Rule groups** | Knows which AWS managed rule groups to enable and in what order |
| **Tuning methodology** | Phases from COUNT → analyze exceptions → BLOCK |
| **False positives** | Creates path-based exemptions, analyzes logs for regressions |
| **Security analytics** | Uses Athena for WAF log analysis and attack pattern detection |

---

## 6. Secrets Manager: Rotation & Vault Architecture

**Q:** "Design a secrets management strategy for 500 microservices. Each service needs database credentials, API keys, and TLS certificates. How does AWS Secrets Manager handle automatic rotation? Compare Secrets Manager vs Parameter Store vs Vault. How do you audit secret access?"

**What They're Really Testing:** Whether you understand secrets management at scale — rotation strategies, caching vs direct access, and integration with IAM for access control.

### Answer

**Secrets Manager Architecture:**

```yaml
# Secrets Manager architecture for 500 microservices:

# Key features:
# - Encryption at rest (KMS CMK)
# - Automatic rotation (Lambda-based)
# - Cross-region replication
# - Fine-grained IAM access
# - Secret versioning
# - CloudTrail audit logging

Secret: production/my-app/db-creds
  Type: RDS Credentials
  Value:
    {
      "username": "app_user",
      "password": "auto-generated-rotated",
      "engine": "postgres",
      "host": "my-db.xyz.us-east-1.rds.amazonaws.com",
      "port": 5432,
      "dbInstanceIdentifier": "my-db"
    }
  
  Rotation:
    Enabled: true
    RotationInterval: 30 days
    RotationLambdaARN: arn:aws:lambda:...:rds-rotation-function
    
  VersionIds:
    - v1: current
    - v2: previous (still valid during rotation)
    - v3: pending (being created)
```

**Automatic Rotation (Lambda):**

```python
import boto3
import json
import secrets

def lambda_handler(event, context):
    """Rotate RDS credentials."""
    arn = event['SecretId']
    token = event['ClientRequestToken']
    step = event['Step']  # createSecret, setSecret, testSecret, finishSecret
    
    client = secretsmanager.client()
    
    if step == 'createSecret':
        # Generate new password
        password = secrets.token_urlsafe(32)
        client.put_secret_value(
            SecretId=arn,
            ClientRequestToken=token,
            SecretString=json.dumps({
                'username': 'app_user',
                'password': password,
                # ... other fields
            }),
            VersionStages=['AWSPENDING']
        )
    
    elif step == 'setSecret':
        # Update database with new password
        pending = json.loads(client.get_secret_value(
            SecretId=arn,
            VersionStage='AWSPENDING'
        )['SecretString'])
        
        # Update RDS password
        rds = boto3.client('rds')
        rds.modify_db_instance(
            DBInstanceIdentifier='my-db',
            MasterUserPassword=pending['password']
        )
    
    elif step == 'testSecret':
        # Test new credentials work
        pending = json.loads(client.get_secret_value(
            SecretId=arn,
            VersionStage='AWSPENDING'
        )['SecretString'])
        
        # Test connection
        # psycopg2.connect(...)
    
    elif step == 'finishSecret':
        # Mark pending as current
        client.update_secret_version_stage(
            SecretId=arn,
            VersionStage='AWSPENDING',
            RemoveVersionStage='AWSCURRENT'
        )
        client.update_secret_version_stage(
            SecretId=arn,
            VersionStage='AWSCURRENT',
            MoveToVersionId=token
        )
```

**Secrets Manager vs Parameter Store vs Vault:**

```yaml
AWS Secrets Manager:
  - Automatic rotation: ✅ (Lambda-based, 30+ services)
  - Cross-region replication: ✅
  - Encryption: KMS (always)
  - Cost: $0.40/secret/month + $0.05/10K API calls
  - Max secret size: 64KB
  - Use: DB credentials, API keys, rotation required

AWS Parameter Store:
  - Tiers: Standard (free, 10K params), Advanced ($0.05/param/month)
  - Rotation: ❌ (manual only)
  - Encryption: Optional (KMS)
  - Cost: FREE (standard), $0.05/param (advanced)
  - Max size: 8KB (standard), 8KB (advanced)
  - Use: config, feature flags, non-sensitive parameters

HashiCorp Vault:
  - Dynamic secrets: ✅ (generate on-demand)
  - Rotation: ✅ (automatic)
  - Encryption: ✅
  - Replication: ✅ (enterprise)
  - Cost: free (OSS) or enterprise licensing
  - Complexity: higher (separate infrastructure to manage)
  - Use: dynamic secrets, multi-cloud, existing Vault investment

# Recommendation:
# Secrets Manager for: database credentials, API keys (need rotation)
# Parameter Store for: configuration, feature flags (no rotation)
# Vault: only if already using Vault elsewhere (don't add complexity)
```

**Secret Access Patterns:**

```python
# Best practice: cache secrets in memory, don't fetch on every request

class SecretCache:
    def __init__(self):
        self.cache = {}
        self.ttl = 3600  # 1 hour cache (rotation takes effect)
    
    def get_secret(self, secret_name):
        now = time.time()
        
        # Check cache
        if secret_name in self.cache:
            cached = self.cache[secret_name]
            if now < cached['expires_at']:
                return cached['value']
        
        # Fetch from Secrets Manager
        response = secretsmanager.get_secret_value(
            SecretId=secret_name
        )
        
        value = json.loads(response['SecretString'])
        
        # Cache for 1 hour
        # If rotation happens, application will get new secret
        # within 1 hour (acceptable for most apps)
        self.cache[secret_name] = {
            'value': value,
            'expires_at': now + self.ttl
        }
        
        return value
    
    def force_refresh(self, secret_name):
        """Force refresh (called if auth fails)."""
        if secret_name in self.cache:
            del self.cache[secret_name]
        return self.get_secret(secret_name)

# SecretManager is called ONCE per hour (not 1000× per request)
# 500 services × 1 call/hour = 12K calls/day = $0.60/day in API costs
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Rotation mechanism** | Explains Lambda-based rotation with create/set/test/finish stages |
| **Service comparison** | Compares Secrets Manager ($0.40/secret) vs Parameter Store (free) vs Vault (complexity) |
| **Caching** | Caches secrets in memory to reduce API costs (10x reduction) |
| **Monitoring** | Uses CloudTrail to audit secret access (who, when, which application) |

---

## 7. GuardDuty & Security Hub: Threat Detection

**Q:** "Your CISO wants a centralized security monitoring platform across 50 AWS accounts. Design a multi-account GuardDuty and Security Hub architecture. How does GuardDuty detect threats? How do you prioritize and automate remediation of security findings?"

**What They're Really Testing:** Whether you understand AWS security services at organizational scale — delegated administrators, cross-account aggregation, and automated remediation workflows.

### Answer

**Multi-Account Architecture:**

```yaml
# Security account (delegated administrator):

Security Account (111111111111) ← Delegated Admin
├── GuardDuty (aggregated findings)
├── Security Hub (cross-region aggregation)
├── Detective (investigation)
├── IAM Access Analyzer
└── S3: centralized security logs

Member Accounts (50 accounts, 3 regions each):
├── GuardDuty (local, findings sent to admin)
├── Security Hub (local, findings sent to admin)
└── CloudTrail → S3 (centralized to security account)

# Setup:
# GuardDuty:
#   - Enable in security account
#   - Add member accounts (automated via Organizations)
#   - Findings: aggregated in security account

# Security Hub:
#   - Enable in security account (delegated admin)
#   - Enable cross-region aggregation
#   - Enable CIS, PCI-DSS, AWS Foundational Best Practices standards

# Centralized view:

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-guardduty-multi-account.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated GuardDuty Multi-Account Threat Detection — 50 member accounts report to delegated admin with auto-remediation — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---
# Security Hub → EventBridge → Auto-remediation
```

**GuardDuty Threat Detection:**

```yaml
# GuardDuty detection types:

1. Reconnaissance:
   - Unusual port scans from EC2 (Recon:EC2/Portscan)
   - Unusual API calls from known bad IPs (Recon:IAMUser/TorIPCaller)
   - DNS query for known malicious domains

2. Compromised Instance:
   - Crypto mining (CryptoCurrency:EC2/BitcoinTool.B)
   - Outbound traffic to C2 servers (Backdoor:EC2/C2Activity.B)
   - Unusual network traffic (Behavior:EC2/NetworkPortUnusual)

3. Privilege Escalation:
   - Disabling CloudTrail (Stealth:IAMUser/CloudTrailLoggingDisabled)
   - Creating access keys (Persistence:IAMUser/UserWithKey)
   - Unusual IAM role assumption (UnauthorizedAccess:IAMUser/RoleAssumption)

4. Data Exfiltration:
   - Large data upload (Exfiltration:S3/ObjectRead)
   - Unusual S3 access patterns (Policy:IAMUser/RootCredentialUsage)
   - S3 ACL modifications

# Detection methods:
# - Threat intelligence feeds (known bad IPs/domains)
# - ML-based anomaly detection (unusual API patterns)
# - Behavioral analysis (baseline of normal activity)
```

**Automated Remediation:**

```yaml
# Security Hub → EventBridge → Lambda (auto-remediation)

# EventBridge rule:
Security Hub Finding → EventBridge → Lambda

# Finding: GuardDuty finds crypto mining on EC2 instance
{
  "source": ["aws.securityhub"],
  "detail": {
    "findings": [{
      "Id": "arn:aws:guardduty:...",
      "Title": "CryptoCurrency:EC2/BitcoinTool.B",
      "Severity": {
        "Label": "HIGH",
        "Normalized": 70
      },
      "Resources": [{
        "Type": "AwsEc2Instance",
        "Id": "i-1234567890abcdef"
      }],
      "ProductFields": {
        "aws/guardduty/service/action/networkConnectionAction/remoteIpDetails/ipAddressV4": "1.2.3.4"
      }
    }]
  }
}

# Auto-remediation Lambda:
def lambda_handler(event, context):
    finding = event['detail']['findings'][0]
    
    if 'CryptoCurrency' in finding['Title']:
        instance_id = finding['Resources'][0]['Id']
        
        # Isolate the instance
        ec2 = boto3.client('ec2')
        
        # Create security group that denies all egress
        sg = ec2.create_security_group(
            GroupName=f"isolate-{instance_id}",
            Description=f"Isolated {instance_id} for crypto mining"
        )
        
        ec2.revoke_security_group_egress(
            GroupId=sg['GroupId'],
            IpPermissions=[{
                'IpProtocol': '-1',
                'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
            }]
        )
        
        # Attach isolation SG to instance
        ec2.modify_instance_attribute(
            InstanceId=instance_id,
            Groups=[sg['GroupId']]
        )
        
        # Capture forensic snapshot
        ec2.create_snapshots(
            InstanceSpecification={
                'InstanceId': instance_id,
                'ExcludeBootVolume': False
            },
            TagSpecifications=[{
                'ResourceType': 'snapshot',
                'Tags': [{'Key': 'Forensic', 'Value': finding['Id']}]
            }]
        )
        
        # Notify security team
        sns.publish(
            TopicArn='arn:aws:sns:...:security-alerts',
            Message=f"Isolated {instance_id} for crypto mining"
        )
```

**Finding Prioritization:**

```yaml
# Severity levels:
# CRITICAL (90-100): active compromise, data exfiltration
# HIGH (70-89): confirmed malicious activity
# MEDIUM (40-69): suspicious activity needs investigation
# LOW (1-39): informational, configuration issues

# Prioritization criteria:
# 1. Severity (HIGH+ → immediate)
# 2. Resource criticality (prod vs dev)
# 3. Data sensitivity (PII, PCI → higher priority)
# 4. Attack chain position (initial access vs exfiltration)
# 5. Time since first detected

# Finding workflow:
# 1. NEW → triage (auto-remediate where possible)
# 2. IN_PROGRESS → investigate (GuardDuty + Detective)
# 3. RESOLVED → confirmed fixed
# 4. SUPPRESSED → false positive (add suppression rule)

# Suppression rules (reduce noise):
SuppressionRule:
  - Criteria:
      ResourceType: "AccessKey"
      FindingType: "UnauthorizedAccess:IAMUser/RootCredentialUsage"
    # Suppress: root credential usage if it's from known automation
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Multi-account architecture** | Uses delegated admin in security account for centralized management |
| **Threat detection** | Explains ML-based anomaly detection, threat intelligence, behavioral analysis |
| **Auto-remediation** | Automatically isolates compromised instances, triggers incident response |
| **Prioritization** | Triages findings by severity, resource criticality, and attack chain position |

---

## 8. AWS Security Reference Architecture

**Q:** "Design a complete security architecture for a new AWS organization with 10 accounts. Cover: identity management, network security, data protection, monitoring, and incident response. How do you implement the principle of least privilege at the organizational level?"

**What They're Really Testing:** Whether you can design a comprehensive security architecture covering all aspects of AWS security — from governance (SCPs) to detective controls (GuardDuty) to data protection (KMS).

### Answer

**AWS Organization Structure:**

```yaml
AWS Organization: my-org

Root OU:
├── Security OU:
│   ├── Security Account (111111111111)
│   │   ├── GuardDuty (delegated admin)
│   │   ├── Security Hub
│   │   ├── Detective
│   │   ├── Macie
│   │   └── CloudTrail (org trail)
│   │
│   ├── Log Archive Account
│   │   ├── S3: Centralized logs
│   │   └── Glacier: Long-term archive
│   │
│   └── Shared Services Account
│       ├── IAM Identity Center (SSO)
│       ├── Active Directory (or Managed AD)
│       └── DNS (Route53 Resolver)
│
├── Infrastructure OU:
│   ├── Network Account
│   │   ├── Transit Gateway
│   │   ├── Direct Connect
│   │   └── VPN
│   │
│   └── Compute Account
│       ├── EC2 (spot, reserved)
│       └── ECS/EKS (container orchestration)
│
├── Application OU:
│   ├── Dev Account
│   ├── Staging Account
│   └── Prod Account
│       ├── Application services
│       ├── RDS, DynamoDB, ElastiCache
│       └── ALB, CloudFront
│
└── Sandbox OU:
    └── Developer Accounts (1 per developer)
```

**Service Control Policies:**

```yaml
# SCPs at OU level enforce guardrails:

# Root SCP: Deny sensitive actions at organization level
DenyHighRiskActions:
  Effect: Deny
  Action:
    - iam:CreateAccessKey
    - iam:CreateUser
    - iam:DeleteRolePermissionsBoundary
    - cloudtrail:StopLogging
    - cloudtrail:DeleteTrail
    - ec2:DeleteFlowLogs
    - config:DeleteConfigRule
    - guardduty:DeleteDetector
    - guardduty:DisassociateFromMasterAccount
    - s3:PutBucketPublicAccessBlock
    - s3:PutBucketAcl (with condition: public = true)
  Resource: "*"

# Infrastructure OU SCP: Only allow approved services
DenyNonInfrastructureServices:
  Effect: Deny
  Action:
    - ec2:*
    - ecs:*
    - eks:*
    - autoscaling:*
    - ebs:*
    - vpc:*
  Resource: "*"
  # All other services denied

# Production SCP: MFA must be enabled
RequireMFADeny:
  Effect: Deny
  Action: "*"
  Resource: "*"
  Condition:
    BoolIfExists:
      "aws:MultiFactorAuthPresent": "false"
  # All actions require MFA (except console login)

# Sandbox SCP: Budget limit
BudgetLimit:
  Effect: Deny
  Action:
    - ec2:RunInstances
  Resource: "arn:aws:ec2:*:*:instance/*"
  Condition:
    NumericGreaterThan:
      "aws:RequestTag/cost-center": "developer-*"
```

**Network Security Architecture:**

```yaml
# Network security across accounts:

# One VPC per account, connected via Transit Gateway:
┌─────────────────────────────────────────────────┐
│                 Transit Gateway                  │
│                                                   │
│  Spoke VPCs:                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Dev VPC  │  │ Stg VPC  │  │ Prod VPC │       │
│  │ 10.0.0/16│  │ 10.1.0/16│  │ 10.2.0/16│       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
│       │              │              │            │
│       └──────────────┼──────────────┘            │
│                      │                           │
│  ┌───────────────────▼───────────────────┐      │
│  │          Inspection VPC                │      │
│  │  ┌─────────────┐  ┌─────────────┐     │      │
│  │  │ Firewall    │  │ IDS/IPS     │     │      │
│  │  │ (Palo Alto) │  │ (GuardDuty) │     │      │
│  │  └─────────────┘  └─────────────┘     │      │
│  └───────────────────────────────────────┘      │
└─────────────────────────────────────────────────┘

# Security groups: least privilege per microservice
# Network ACLs: subnet-level deny lists
# VPC Endpoints: private access to AWS services
# VPC Flow Logs: published to Security account S3
```

**Monitoring & Incident Response:**

```yaml
# Centralized monitoring:

1. CloudTrail (Organization Trail):
   - All accounts, all regions
   - Management events + data events (S3, Lambda)
   - Insights (unusual API activity)
   - Logs → S3 (Log Archive account)

2. GuardDuty:
   - All accounts (delegated admin in Security)
   - Threat detection: compromised instances, crypto mining
   - Findings → Security Hub

3. Security Hub:
   - All accounts (delegated admin)
   - Standards: CIS, PCI-DSS, AWS Foundational
   - Cross-region aggregation
   - Findings → EventBridge → Auto-remediation

4. Config:
   - All accounts, all regions
   - Rules: S3 public access, security group changes
   - Conformance packs: compliance frameworks

5. Incident Response Plan:
   # Tier 1 (automated):
   - Crypto mining: isolate instance
   - S3 public access: block automatically
   - Root user activity: notify security team
   
   # Tier 2 (playbook):
   - Compromised IAM key: rotate key, review activity
   - EC2 backdoor: snapshot forensic, terminate instance
   - Ransomware: restore from backup, isolate affected resources
   
   # Tier 3 (escalation):
   - Data exfiltration: full incident investigation
   - Compliance breach: legal notification
   - Cross-account compromise: emergency access revocation
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Organization structure** | Separates duties via OU structure (security, infrastructure, application) |
| **SCP guardrails** | Enforces organization-wide policies (deny high-risk actions, require MFA) |
| **Defense in depth** | Applies controls at every layer: network, identity, data, monitoring |
| **Incident response** | Designs tiered response (automated → playbook → escalation) |

---

> *All 8 questions cover the full breadth of AWS security — from IAM architecture and KMS key management to multi-account threat detection and automated remediation.*
