import { SequenceData } from "./SequenceDiagram";

export const AWS_SECURITY_ADDITIONAL_SEQUENCES: SequenceData[] = [
  // ═══════════════════════════════════════════════════════════
  // SECURITY — AWS WAF Managed Rules & Rate Limiting
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-waf-managed-rules",
    title: "AWS WAF — Managed Rules & Rate-Based Protection",
    subtitle:
      "Request → WAF ACL → Managed Rule Groups (Core, SQLi, XSS, RFI) → Rate-Based Rule → Allow/Block — 99%+ bot mitigation",
    actors: [
      "Client\nRequest",
      "AWS WAF\n(Web ACL)",
      "Core Rule\nSet (CRS)",
      "Rate-Based\nRule",
      "ALB / CF\n(Origin)",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "GET /checkout HTTP/1.1",
        detail: "Request arrives: src IP 203.0.113.5",
      },
      {
        from: 1,
        to: 2,
        label: "Core Rule Set evaluation",
        detail: "AWSManagedRulesCommonRuleSet",
      },
      {
        from: 2,
        to: 2,
        label: "CRS: SQLi + XSS + PHP + RFI",
        detail: "Generic threats: standard protection",
      },
      {
        from: 2,
        to: 1,
        label: "No CRS match ✅",
        detail: "Passes common threat rules",
      },
      {
        from: 1,
        to: 3,
        label: "Rate-based rule: 2000 req/5min",
        detail: "Per-IP counter, aggressive threshold",
      },
      {
        from: 3,
        to: 1,
        label: "Src IP: 12 req/5min — OK",
        detail: "Within rate limit, proceed",
      },
      {
        from: 1,
        to: 4,
        label: "Forward request to origin",
        detail: "WAF passes: all checks passed",
      },
      {
        from: 4,
        to: 1,
        label: "200 OK response",
        detail: "Request fulfilled via WAF",
      },
      {
        from: 0,
        to: 1,
        label: "POST /login (SCRIPT tag)",
        detail: "XSS attempt: <script>alert('xss')</script>",
      },
      {
        from: 1,
        to: 2,
        label: "CRS: CrossSiteScripting match!",
        detail: "Rule: XSS evil attributes detected",
      },
      {
        from: 2,
        to: 1,
        label: "WAF blocks with 403 Forbidden",
        detail: "Action: BLOCK, logged to S3",
      },
      {
        from: 1,
        to: 0,
        label: "❌ 403 Forbidden",
        detail: "XSS attack prevented",
      },
      {
        from: 0,
        to: 1,
        label: "GET /api (×10K from one IP)",
        detail: "Rate limit: 10,000 req/5min detected!",
      },
      {
        from: 3,
        to: 1,
        label: "Rate limit exceeded!",
        detail: "IP 203.0.113.5 → BLOCKED for 5 min",
      },
      {
        from: 1,
        to: 0,
        label: "❌ 429 Rate Limited",
        detail: "Retry-After: 300 seconds",
      },
    ],
    durationInFrames: 420,
  },

  // ═══════════════════════════════════════════════════════════
  // SECURITY — Secrets Manager Rotation
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-secrets-manager",
    title: "Secrets Manager — Rotation & Vault Architecture",
    subtitle:
      "Application → Secrets Manager (KMS envelope) → Lambda Rotator → RDS/API — automatic rotation every 30 days, no downtime",
    actors: [
      "Application",
      "Secrets\nManager",
      "Lambda\nRotator",
      "RDS / API\n(Target)",
      "CloudWatch\n(Monitoring)",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "GetSecretValue: db_credentials",
        detail: "SDK call with IAM auth via VPC endpoint",
      },
      {
        from: 1,
        to: 1,
        label: "KMS decrypt: envelope decryption",
        detail: "CMK decrypts DEK, DEK decrypts secret",
      },
      {
        from: 1,
        to: 0,
        label: "Username + Password returned",
        detail: "Cached locally per IAM role",
      },
      {
        from: 0,
        to: 0,
        label: "Connect to RDS with credentials",
        detail: "No hardcoded secrets in code!",
      },
      {
        from: 1,
        to: 2,
        label: "Rotation trigger: day 30",
        detail: "Scheduled: CloudWatch Events → Lambda",
      },
      {
        from: 2,
        to: 2,
        label: "Create new password",
        detail: "Random 64-char alphanumeric via Secrets Mgr SDK",
      },
      {
        from: 2,
        to: 3,
        label: "ALTER USER password = new",
        detail: "Phase 1: create new password (pending)",
      },
      {
        from: 3,
        to: 2,
        label: "Password updated",
        detail: "Old password still valid (dual stage)",
      },
      {
        from: 2,
        to: 1,
        label: "Store new secret version",
        detail: "Version label: AWSCURRENT",
      },
      {
        from: 1,
        to: 2,
        label: "Test new credentials",
        detail: "Lambda validates: connect + query",
      },
      {
        from: 2,
        to: 3,
        label: "Test app connection OK ✅",
        detail: "Phase 2: finalize, deprecate old",
      },
      {
        from: 1,
        to: 4,
        label: "Rotation complete — log event",
        detail: "CloudWatch: secret rotated successfully",
      },
      {
        from: 1,
        to: 0,
        label: "App gets new secret automatically",
        detail: "Secrets cache refresh: < 1 sec",
      },
    ],
    durationInFrames: 390,
  },
];
