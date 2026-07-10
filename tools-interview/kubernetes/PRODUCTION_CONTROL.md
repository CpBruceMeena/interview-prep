# 🚀 Kubernetes Production Control — Staff-Level Deep Dive

> *Deep-dive into production control patterns for Kubernetes: GitOps, admission controllers, deployment strategies, multi-tenancy, service mesh, and cluster governance — every section expects principal engineer-level depth with real production patterns.*

> **Prerequisites:** This file builds on the foundational Kubernetes content in [`INTERVIEW_QUESTIONS.md`](./INTERVIEW_QUESTIONS.md) (scheduler, networking, RBAC, storage, controllers), [`POD_LIFECYCLE_AND_MONITORING.md`](./POD_LIFECYCLE_AND_MONITORING.md) (pod lifecycle, probes, monitoring, eBPF), and Docker fundamentals in [`../docker/INTERVIEW_QUESTIONS.md`](../docker/INTERVIEW_QUESTIONS.md) (container runtime, namespaces, cgroups, images).
>
> **Storage deep-dive** in [Section 12](#12-storage-csi-volume-snapshots-backup-strategies) extends the PV/PVC/CSI/StatefulSet foundations from `INTERVIEW_QUESTIONS.md` Q6.

---

## Table of Contents

1. [GitOps: ArgoCD & Flux](#1-gitops-argocd--flux)
2. [Admission Controllers: Webhooks, OPA/Gatekeeper, Kyverno](#2-admission-controllers-webhooks-opagatekeeper-kyverno)
3. [Deployment Strategies: Rolling, Blue-Green, Canary, A/B](#3-deployment-strategies-rolling-blue-green-canary-ab)
4. [Progressive Delivery: Flagger & Argo Rollouts](#4-progressive-delivery-flagger--argo-rollouts)
5. [Multi-Tenancy: Namespaces, Resource Quotas, Network Policies](#5-multi-tenancy-namespaces-resource-quotas-network-policies)
6. [Service Mesh: Istio, Linkerd & mTLS](#6-service-mesh-istio-linkerd--mtls)
7. [Network Policies: Micro-Segmentation](#7-network-policies-micro-segmentation)
8. [Cluster API & Multi-Cluster Management](#8-cluster-api--multi-cluster-management)
9. [Pod Security: Kyverno Policies for Production](#9-pod-security-kyverno-policies-for-production)
10. [CNI Deep Dive: Calico, Cilium, Flannel](#10-cni-deep-dive-calico-cilium-flannel)
11. [Descheduler & Cluster Autoscaler](#11-descheduler--cluster-autoscaler)
12. [Storage: CSI, Volume Snapshots, Backup Strategies](#12-storage-csi-volume-snapshots-backup-strategies)

---

## 1. GitOps: ArgoCD & Flux

**Q:** "Your team deploys to 5 Kubernetes clusters (dev, staging, prod-us, prod-eu, prod-apac) with 200 microservices. How do you ensure declarative, auditable, and automated deployments? Design a GitOps workflow using ArgoCD or Flux."

**What They're Really Testing:** Whether you understand GitOps principles — Git as the single source of truth, automated drift detection and reconciliation, and pull-based deployment for security.

### Answer

**GitOps Principles:**

```
1. Declarative: Entire system described in Git (manifests, Helm, Kustomize)
2. Versioned: Every change is a Git commit (full audit trail)
3. Pull-based: Agent in cluster pulls desired state from Git (no cluster credentials in CI!)
4. Reconciled: Agent continuously compares cluster state vs Git state
5. Automated: Drift detected and corrected automatically
```

**GitOps Architecture:**

```
┌─────────────────────────────────────────────────────────────┐
│                        Git Repository                        │
│  ┌─────────────────────────────────────────────┐           │
│  │ apps/                                        │           │
│  │ ├── payment-service/                        │           │
│  │ │   ├── base/        (Helm chart or Kustomize)│          │
│  │ │   ├── overlays/                           │           │
│  │ │   │   ├── dev/                            │           │
│  │ │   │   ├── staging/                        │           │
│  │ │   │   └── prod/                           │           │
│  │ ├── user-service/                           │           │
│  │ └── ...                                     │           │
│  │                                             │           │
│  │ clusters/                                   │           │
│  │ ├── prod-us/ (ArgoCD ApplicationSet)        │           │
│  │ ├── prod-eu/                                │           │
│  │ └── ...                                     │           │
│  └─────────────────────────────────────────────┘           │
└─────────────────────────┬───────────────────────────────────┘
                          │ Pull
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                        ArgoCD Operator                      │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Cluster  │  │ Cluster  │  │ Cluster  │  │ Cluster  │   │
│  │ prod-us  │  │ prod-eu  │  │ prod-apac│  │ staging  │   │
│  │          │  │          │  │          │  │          │   │
│  │ ArgoCD   │  │ ArgoCD   │  │ ArgoCD   │  │ ArgoCD   │   │
│  │ Apps     │  │ Apps     │  │ Apps     │  │ Apps     │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     CI Pipeline (GitHub Actions)             │
│  Build → Test → Push image → Update Git (k8s manifest)     │
│  Git commit → ArgoCD detects change → syncs to cluster      │
│  (No kubectl apply in CI! Cluster credentials never leave   │
│   the cluster.)                                             │
└─────────────────────────────────────────────────────────────┘
```

**ArgoCD Application:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: payment-service
  namespace: argocd
spec:
  project: production                  # Logical grouping of applications
  source:
    repoURL: https://github.com/company/k8s-manifests
    targetRevision: main               # Branch to follow
    path: apps/payment-service/overlays/prod
    helm:
      valueFiles:
      - values-prod.yaml
      parameters:
      - name: image.tag
        value: v1.2.3                  # Or use :latest with Image Updater
  destination:
    server: https://kubernetes.default.svc
    namespace: prod-payment
  syncPolicy:
    automated:
      prune: true                      # Remove resources not in Git
      selfHeal: true                    # Auto-fix manual changes (drift)
      allowEmpty: false
    syncOptions:
    - CreateNamespace=true             # Auto-create namespace
    - PruneLast=true                    # Prune after sync (safer)
    - ApplyOutOfSyncOnly=true          # Only apply out-of-sync resources
  retry:
    limit: 5
    backoff:
      duration: 5s
      factor: 2
      maxDuration: 3m
```

**ArgoCD ApplicationSet (Multi-Cluster):**

```yaml
# ApplicationSet: deploy the same app to multiple clusters/environments
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: payment-service
  namespace: argocd
spec:
  generators:
  - clusters:                            # From cluster secrets in argocd
      selector:
        matchLabels:
          environment: prod
  template:
    metadata:
      name: 'payment-service-{{name}}'   # {{name}} = cluster name
      labels:
        app: payment-service
        environment: '{{metadata.labels.environment}}'
    spec:
      project: production
      source:
        repoURL: https://github.com/company/k8s-manifests
        targetRevision: main
        path: 'apps/payment-service/overlays/{{metadata.labels.environment}}'
      destination:
        server: '{{server}}'            # From cluster secret
        namespace: prod-payment
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
```

**GitOps CI/CD Pipeline:**

```yaml
# GitHub Actions workflow (CI only — no cluster credentials!)
name: Build and Deploy (GitOps)

on:
  push:
    branches: [main]
    paths:
    - 'apps/payment-service/**'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - run: make test

  build-and-push:
    needs: test
    runs-on: ubuntu-latest
    outputs:
      image-tag: ${{ steps.meta.outputs.version }}
    steps:
    - name: Login to registry
      uses: docker/login-action@v3
      with:
        registry: registry.example.com
        username: ${{ secrets.REGISTRY_USER }}
        password: ${{ secrets.REGISTRY_PASSWORD }}

    - name: Build and push
      uses: docker/build-push-action@v5
      with:
        push: true
        tags: registry.example.com/payment-service:${{ github.sha }}

  update-manifest:
    needs: build-and-push
    runs-on: ubuntu-latest
    steps:
    - name: Checkout k8s manifests repo
      uses: actions/checkout@v4
      with:
        repository: company/k8s-manifests   # Separate repo!
        token: ${{ secrets.MANIFESTS_TOKEN }}
        ref: main

    - name: Update image tag
      run: |
        cd apps/payment-service/overlays/prod
        kustomize edit set image \
          payment-service=registry.example.com/payment-service:${{ github.sha }}

    - name: Commit and push
      run: |
        git config user.name "CI Bot"
        git config user.email "ci@example.com"
        git add .
        git commit -m "Update payment-service to ${{ github.sha }}"
        git push
    # ArgoCD detects the Git change and auto-syncs!
```

**Flux v2 (Alternative to ArgoCD):**

```yaml
# Flux uses GitRepository and Kustomization resources
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: flux-system
  namespace: flux-system
spec:
  interval: 1m                           # Check Git every 1 minute
  url: https://github.com/company/k8s-manifests
  ref:
    branch: main
  secretRef:
    name: flux-repo-auth

---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: apps
  namespace: flux-system
spec:
  interval: 10m                          # Sync every 10 minutes
  sourceRef:
    kind: GitRepository
    name: flux-system
  path: ./apps/production
  prune: true                            # Remove resources not in Git
  validation: client                      # Client-side validation
  healthChecks:
  - apiVersion: apps/v1
    kind: Deployment
    name: payment-service
    namespace: prod-payment
  postBuild:
    substitute:
      environment: prod
      cluster_region: us-east-1
```

**ArgoCD vs Flux:**

```yaml
Feature               | ArgoCD                    | Flux v2
----------------------|---------------------------|---------------------------
UI                    | Rich web UI + CLI          | CLI only (but good)
Multi-cluster         | Built-in (ApplicationSet) | Via Kustomization per cluster
SSO/RBAC              | Built-in (Dex, Keycloak)  | Kubernetes RBAC
Configuration tool    | Any (Helm, Kustomize, YAML)| Any (Helm, Kustomize, YAML)
Sync strategies       | Manual, automated, phased | Automated with health checks
Image updates         | ArgoCD Image Updater      | Flux Image Automation
Rollback              | Via UI, CLI, or Git revert| Git revert (automatic)
Secret management     | External (Sealed Secrets,  | External (SOPS, Sealed Secrets,
                      | External Secrets)          | External Secrets)
Learning curve        | Moderate                  | Steeper (CRD-based)

# Recommendation:
# ArgoCD: When you need a UI, multi-cluster management, team accessibility
# Flux: When you want Git-native, no-UI, security-first, single-cluster
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Pull vs push** | Understands GitOps uses pull (agent in cluster) not push (CI with kubectl) |
| **Drift detection** | Explains continuous reconciliation: Git is source of truth, cluster converges |
| **Multi-cluster** | Uses ApplicationSet or Flux Kustomization per cluster |
| **CI vs CD separation** | CI builds images, Git commit triggers CD; no cluster creds in CI |

---

## 2. Admission Controllers: Webhooks, OPA/Gatekeeper, Kyverno

**Q:** "Your security team requires that all pods must have resource limits, specific labels, and must not use the `latest` image tag. How do you enforce these policies without modifying every deployment? Design an admission control strategy using Kyverno or OPA/Gatekeeper."

**What They're Really Testing:** Whether you understand Kubernetes admission controllers — how mutating and validating webhooks intercept API requests — and can design policy-as-code enforcement.

### Answer

**Admission Controller Flow:**

```
API Request (kubectl apply, API call)
        │
        ▼
┌─────────────────────────────────────────────┐
│        Authentication & Authorization         │
│  (Who is this? Can they do this?)            │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│         Mutating Admission Webhooks          │
│  (Modify the resource BEFORE validation)     │
│  Examples:                                   │
│  - Inject sidecar (Istio, Linkerd)           │
│  - Add default resource limits               │
│  - Add labels/annotations                    │
│  - Set securityContext defaults              │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│         Validating Admission Webhooks        │
│  (Allow or deny the resource)                │
│  Examples:                                   │
│  - Enforce pod security standards            │
│  - Check image registry is allowed           │
│  - Verify resource limits are set            │
│  - Ensure required labels exist              │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│             Resource Quota                   │
│  (Check namespace quotas)                    │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│              Object Storage (etcd)           │
└─────────────────────────────────────────────┘
```

**Kyverno (Kubernetes-Native Policy Engine):**

```yaml
# Kyverno: policies as Kubernetes resources (no new language!)
# Mutating, validating, and generate policies

# ── 1. MUTATING: Add default resource limits if not set ──
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: add-resource-limits
spec:
  validationFailureAction: Audit           # Audit mode first (don't block)
  # Change to: Enforce after testing
  rules:
  - name: add-default-limits
    match:
      any:
      - resources:
          kinds:
          - Pod
    mutate:
      patchStrategicMerge:
        spec:
          containers:
          - (name): "*"                    # Match ALL containers
            resources:
              limits:
                +(cpu): "500m"             # + means: add if not present
                +(memory): "512Mi"
              requests:
                +(cpu): "100m"
                +(memory): "256Mi"

# ── 2. VALIDATING: Require specific labels ──
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-labels
spec:
  validationFailureAction: Enforce          # Block if invalid
  rules:
  - name: check-team-label
    match:
      any:
      - resources:
          kinds:
          - Pod
          - Deployment
          - Service
    validate:
      message: "Label 'team' is required for all resources"
      pattern:
        metadata:
          labels:
            team: "?*"                      # Must exist and not be empty

# ── 3. VALIDATING: Block latest image tag ──
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: block-latest-tag
spec:
  validationFailureAction: Enforce
  background: false                         # Don't scan existing resources
  rules:
  - name: block-latest
    match:
      any:
      - resources:
          kinds:
          - Pod
    validate:
      message: "Using 'latest' tag is not allowed"
      foreach:
      - list: request.object.spec.containers
        deny:
          conditions:
            any:
            - key: "{{ element.image }}"
              operator: Equals
              value: "*:latest"

# ── 4. GENERATE: Create NetworkPolicy for every namespace ──
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: generate-networkpolicy
spec:
  rules:
  - name: default-deny-ingress
    match:
      any:
      - resources:
          kinds:
          - Namespace
    generate:
      synchronize: true                     # Keep in sync (recreate if deleted)
      generate:
        kind: NetworkPolicy
        name: default-deny-ingress
        namespace: "{{ request.object.metadata.name }}"
        data:
          spec:
            podSelector: {}
            policyTypes:
            - Ingress
```

**OPA/Gatekeeper (Rego-Based Policies):**

```yaml
# OPA/Gatekeeper: uses Rego policy language (more powerful, steeper learning curve)

apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: k8srequiredlabels
spec:
  crd:
    spec:
      names:
        kind: K8sRequiredLabels
      validation:
        openAPIV3Schema:
          type: object
          properties:
            labels:
              type: array
              items:
                type: string
  targets:
  - target: admission.k8s.gatekeeper.sh
    rego: |
      package k8srequiredlabels

      violation[{"msg": msg}] {
        provided := {label | input.review.object.metadata.labels[label]}
        required := {label | label := input.parameters.labels[_]}
        missing := required - provided
        count(missing) > 0
        msg := sprintf("Required labels missing: %v", [missing])
      }

---
# Constraint instance (uses the template)
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sRequiredLabels
metadata:
  name: require-team-label
spec:
  match:
    kinds:
    - apiGroups: [""]
      kinds: ["Pod", "Service", "Deployment"]
    namespaces:
    - "production"
    - "staging"
  parameters:
    labels:
    - "team"
    - "owner"
    - "environment"

# ── Block privileged containers ──
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: k8spspprivilegedcontainer
spec:
  crd:
    spec:
      names:
        kind: K8sPSPPrivilegedContainer
  targets:
  - target: admission.k8s.gatekeeper.sh
    rego: |
      package k8spspprivilegedcontainer

      violation[{"msg": msg}] {
        c := input.review.object.spec.containers[_]
        c.securityContext.privileged
        msg := sprintf("Privileged container %v is not allowed", [c.name])
      }

      violation[{"msg": msg}] {
        input.review.object.spec.containers[_].securityContext.capabilities.add[_] == "SYS_ADMIN"
        msg := "CAP_SYS_ADMIN is not allowed"
      }
```

**Kyverno vs OPA/Gatekeeper:**

```yaml
Feature               | Kyverno                      | OPA/Gatekeeper
----------------------|------------------------------|------------------------------
Policy language       | YAML (Kubernetes-native)     | Rego (new language to learn)
Learning curve        | Low (looks like K8s resources)| High (Rego is different)
Built-in functions    | Rich: image verification,     | Rich: custom Rego logic
                      | auto-gen NetworkPolicy,       |
                      | variable substitution         |
Mutation              | Built-in (mutate rules)      | Requires mutating webhook +
                      |                              | custom Rego logic
Generate resources    | Built-in (generate rules)    | Not natively supported
Performance           | Good (native Go)             | Good (Rego is compiled to bytecode)
Validation            | Patterns, deny conditions    | Full Rego policy
Community             | Nirmata, growing fast        | CNCF graduated, large
Use case              | K8s-specific policies        | General-purpose policy engine
                      |                              | (also covers Terraform, K8s, etc.)

# Recommendation:
# Kyverno: Simpler, K8s-native policies (most teams)
# OPA: Already invested in Rego, need cross-platform policies (K8s + Terraform + Envoy)
```

**Validating Webhook (Manual Implementation):**

```yaml
# For custom validation logic (when Kyverno/OPA is too much overhead)

apiVersion: v1
kind: Service
metadata:
  name: pod-validator
  namespace: admission
spec:
  selector:
    app: pod-validator
  ports:
  - port: 443
    targetPort: 8443

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pod-validator
  namespace: admission
spec:
  replicas: 2
  selector:
    matchLabels:
      app: pod-validator
  template:
    spec:
      containers:
      - name: webhook
        image: registry.example.com/pod-validator:1.0
        args:
        - --tls-cert=/certs/tls.crt
        - --tls-key=/certs/tls.key
        ports:
        - containerPort: 8443
        volumeMounts:
        - name: certs
          mountPath: /certs
          readOnly: true
      volumes:
      - name: certs
        secret:
          secretName: webhook-certs

---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: pod-validator
webhooks:
- name: pod-validator.admission.example.com
  rules:
  - operations: ["CREATE", "UPDATE"]
    apiGroups: [""]
    apiVersions: ["v1"]
    resources: ["pods"]
  clientConfig:
    service:
      name: pod-validator
      namespace: admission
      path: /validate
    caBundle: <base64-encoded-CA-cert>
  admissionReviewVersions: ["v1"]
  sideEffects: None
  timeoutSeconds: 5
  failurePolicy: Fail                     # If webhook is down, reject requests
  # Or: Ignore (allow requests if webhook is down — risk but availability)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Mutating vs Validating** | Understands the order: mutate first, then validate |
| **Kyverno vs OPA** | Can recommend based on team skills and policy complexity |
| **Webhook failure policy** | Knows Fail (block if webhook down) vs Ignore (allow if down) trade-offs |
| **Audit mode** | Uses audit mode before Enforce to prevent breaking existing workloads |

---

## 3. Deployment Strategies: Rolling, Blue-Green, Canary, A/B

**Q:** "Design a deployment strategy for a payment processing service that must have zero downtime, canary testing with 5% traffic, and instant rollback within 10 seconds if errors spike. Compare RollingUpdate, Blue-Green, Canary, and A/B testing deployments."

**What They're Really Testing:** Whether you understand the deployment strategy trade-offs — speed vs safety, cost vs simplicity, and how to implement each with Kubernetes primitives (Deployments, Services, Ingress).

### Answer

**Strategy Comparison:**

```yaml
Strategy        | Downtime | Rollback Speed | Cost       | Traffic Control | Complexity
----------------|----------|----------------|------------|-----------------|-----------
Recreate        | Yes      | Slow           | Low        | None            | Minimal
RollingUpdate   | No       | Medium         | Low        | At pod level    | Low
Blue-Green      | No       | Instant        | High (2×)  | At service      | Medium
Canary          | No       | Fast           | Medium     | % based         | High
A/B Testing     | No       | Fast           | Medium     | Header based    | High

# Recreate: Kill all old, create all new (downtime!)
# RollingUpdate: Incrementally replace pods (no downtime)
# Blue-Green: Two full environments, switch traffic instantly
# Canary: Gradual % traffic shift with rollback
# A/B: Traffic routing by header/cookie (for testing features)
```

**Blue-Green Deployment:**

```yaml
# Blue = current (v1), Green = new (v2)
# Two identical deployments, service points to one at a time

# Step 1: Deploy green (alongside blue)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-service-green
  labels:
    app: payment-service
    version: green                       # Identifies this as green
spec:
  replicas: 5
  selector:
    matchLabels:
      app: payment-service
      version: green
  template:
    metadata:
      labels:
        app: payment-service
        version: green
    spec:
      containers:
      - name: app
        image: registry.example.com/payment-service:v2.0.0
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8080

# Service points to BLUE (current production)
apiVersion: v1
kind: Service
metadata:
  name: payment-service
spec:
  selector:
    app: payment-service
    version: blue                        # Currently blue
  ports:
  - port: 8080

# Step 2: Verify green is healthy
# kubectl get pods -l version=green
# kubectl exec -it payment-service-green-abc -- curl localhost:8080/health

# Step 3: Switch traffic to green (instant!)
kubectl patch service payment-service -p '{"spec":{"selector":{"version":"green"}}}'

# Step 4: Monitor for 10-15 minutes
# If issues: switch back to blue (instant rollback)
# kubectl patch service payment-service -p '{"spec":{"selector":{"version":"blue"}}}'

# Step 5: Scale down blue
# kubectl scale deployment payment-service-blue --replicas=0

# Pros: Instant switch, instant rollback, easy to understand
# Cons: 2× resource cost during deployment, requires full environment
```

**Ingress-Based Canary:**

```yaml
# Canary using Ingress (nginx-ingress, contour, gloo)
# Route % of traffic to canary version based on weight

apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: payment-service
  annotations:
    nginx.ingress.kubernetes.io/canary: "true"
    nginx.ingress.kubernetes.io/canary-weight: "5"     # 5% traffic to canary
    nginx.ingress.kubernetes.io/canary-by-header: "x-canary"  # Or by header
    # nginx.ingress.kubernetes.io/canary-by-cookie: "canary_test"
spec:
  ingressClassName: nginx
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /api/payments
        pathType: Prefix
        backend:
          service:
            name: payment-service-canary
            port:
              number: 8080

# Primary ingress (90% traffic to stable)
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: payment-service-stable
spec:
  ingressClassName: nginx
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /api/payments
        pathType: Prefix
        backend:
          service:
            name: payment-service-stable
            port:
              number: 8080
```

**A/B Testing with Header Routing:**

```yaml
# A/B testing: route specific users to new version based on header/cookie
# Not about gradual rollout — about testing behavior differences

# Nginx Ingress canary by header:
# nginx.ingress.kubernetes.io/canary-by-header: "x-ab-test"
# nginx.ingress.kubernetes.io/canary-by-header-value: "v2"

# Client sends: x-ab-test: v2 → request goes to canary
# Client sends: anything else → request goes to stable

# For more sophisticated A/B with support for multiple experiments:

apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: payment-service
spec:
  hosts:
  - payment-service
  http:
  - match:
    - headers:                              # A/B test group A
        x-ab-test:
          exact: "new-checkout-flow"
    route:
    - destination:
        host: payment-service
        subset: v2          # New checkout flow version
  - route:                                  # Everyone else
    - destination:
        host: payment-service
        subset: v1          # Current version

# A/B best practices:
# 1. Run experiments for statistically significant duration (1-2 weeks)
# 2. Track both business metrics (conversion) and technical metrics (latency, errors)
# 3. Use feature flags for simple feature toggles (LaunchDarkly, Flagsmith)
# 4. A/B = behavioral experiment, Canary = risk mitigation
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Strategy trade-offs** | Can compare Blue-Green (instant rollback, 2× cost) vs Canary (gradual, cheaper) |
| **Rollback speed** | Understands Blue-Green rollback is instant (service label change) |
| **Canary weight progression** | Knows to progressively increase: 1%→5%→10%→25%→50%→100% |
| **A/B vs Canary** | Distinguishes header-based routing (A/B) from weight-based (canary) |

---

## 4. Progressive Delivery: Flagger & Argo Rollouts

**Q:** "Manual canary deployments are error-prone — engineers forget to monitor and rollback takes too long. Design an automated progressive delivery pipeline using Flagger or Argo Rollouts that automatically promotes or rolls back based on metrics."

**What They're Really Testing:** Whether you understand automated canary analysis — how Flagger/Argo Rollouts shift traffic, collect metrics, analyze health, and automatically promote or rollback.

### Answer

**Flagger Automated Canary:**

```yaml
# Flagger: automated canary deployments with metric analysis
# Integrates with: Prometheus, Istio/Linkerd/NGINX/SMI, Slack, Teams

apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: payment-service
  namespace: prod
spec:
  # Target deployment (the thing being deployed)
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: payment-service

  # Service mesh or ingress
  service:
    port: 8080
    targetPort: 8080
    gateways:                             # For Istio
    - istio-system/public-gateway
    hosts:
    - api.example.com
    trafficPolicy:                         # mTLS settings
      tls:
        mode: ISTIO_MUTUAL
    retries:
      attempts: 3
      perTryTimeout: 1s
    headers:
      request:
        add:
          x-canary: "true"                # Mark requests for tracking

  # Canary analysis settings
  analysis:
    interval: 30s                          # Check metrics every 30 seconds
    iterations: 10                         # Run 10 iterations (10 × 30s = 5 min)
    threshold: 5                           # Max 5% error rate
    maxWeight: 50                          # Max 50% traffic to canary
    stepWeight: 5                          # Increase by 5% each iteration
    # Progression: 5% → 10% → 15% → ... → 50%
    # After all iterations pass: promote canary to primary

    metrics:
    - name: request-success-rate           # Built-in metric
      threshold: 99                        # 99% must succeed
      interval: 1m                         # Evaluate over 1-minute window
    - name: request-duration               # Built-in metric
      threshold: 500                       # p99 < 500ms
      interval: 1m
    - name: "database_connections_active"    # Custom Prometheus metric
      templateRef:
        name: database-connections
      threshold: 50
      interval: 1m

    webhooks:
    - name: load-test                      # Run load test during canary
      url: http://flagger-loadtester.prod/
      timeout: 5s
      metadata:
        cmd: "hey -z 2m -q 10 -host api.example.com http://gateway:80/api/payments"
    - name: slack-notification
      url: http://webhook.slack.com/...
      timeout: 5s
    - name: datadog-check                  # Custom metric from Datadog
      url: http://datadog-webhook/api/v1/metrics
      timeout: 10s
```

**Flagger Canary Lifecycle:**

```
1. User updates Deployment (new image tag)
2. Flagger detects change, creates:
   - payment-service-primary (stable, current version)
   - payment-service-canary (new version, starts at 0 replicas)
3. Flagger scales canary to 1 replica
4. Traffic shift: 5% to canary
5. Analysis iteration 1:
   - Check: request-success-rate ≥ 99%
   - Check: request-duration p99 < 500ms
   - Check: custom metrics (database connections)
   - If ALL pass: continue to next step
6. Traffic shift: 10% to canary
7. ... repeat until maxWeight (50%)
8. After all iterations pass:
   - Promote: canary becomes primary
   - Scale down old primary
9. IF ANY iteration fails:
   - Auto-rollback: traffic redirected to primary
   - Canary scaled to 0
   - Alert sent to Slack/PagerDuty
```

**Argo Rollouts (Alternative to Flagger):**

```yaml
# Argo Rollouts: native Kubernetes controller (no service mesh required)
# Works with: Ingress controllers (NGINX, Contour), Service Mesh (Istio, Linkerd, SMI)
# Also supports: Blue-Green, Canary, and Experiment (A/B) strategies

apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: payment-service
spec:
  replicas: 5
  revisionHistoryLimit: 3
  selector:
    matchLabels:
      app: payment-service
  template:
    metadata:
      labels:
        app: payment-service
    spec:
      containers:
      - name: app
        image: registry.example.com/payment-service:v2.0.0
        ports:
        - containerPort: 8080

  strategy:
    canary:
      maxSurge: 1
      maxUnavailable: 0
      steps:
      - setWeight: 10                       # Start at 10% traffic
      - pause:
          duration: 2m                      # Wait 2 minutes
      - setWeight: 25
      - pause:
          duration: 5m
      - setWeight: 50
      - pause:
          duration: 5m
      - setWeight: 75
      - pause:
          duration: 2m
      # After last step → auto-promote to 100%

      analysis:
        templates:
        - templateName: success-rate        # Reference an AnalysisTemplate
        - templateName: latency-check
        startingStep: 1                     # Start analysis after step 1

---
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: success-rate
spec:
  metrics:
  - name: success-rate
    interval: 30s
    successCondition: result[0] >= 0.99     # 99%+ success
    failureLimit: 3                          # 3 failures = rollback
    provider:
      prometheus:
        address: http://prometheus.monitoring:9090
        query: |
          sum(rate(
            http_requests_total{namespace="prod", status=~"2.."}[2m]
          )) /
          sum(rate(
            http_requests_total{namespace="prod"}[2m]
          ))

  - name: latency
    interval: 30s
    successCondition: result[0] <= 0.5       # p99 < 500ms
    failureLimit: 3
    provider:
      prometheus:
        address: http://prometheus.monitoring:9090
        query: |
          histogram_quantile(0.99,
            sum(rate(
              http_request_duration_seconds_bucket{namespace="prod"}[2m]
            )) by (le)
          )
```

**Manual Approval Gates (Argo Rollouts + Argo Workflows):**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: payment-service
spec:
  strategy:
    canary:
      steps:
      - setWeight: 10
      - pause: {}                              # Wait for manual approval
      - setWeight: 25
      - pause: {duration: 10m}                 # Wait 10 minutes
      - setWeight: 50
      - pause: {}                              # Wait for manual approval
      - setWeight: 75
      - pause: {duration: 10m}
      # After last step → promote

# Manual promotion:
kubectl argo rollouts promote payment-service
# Manual rollback:
kubectl argo rollouts abort payment-service
```

**Flagger vs Argo Rollouts:**

```yaml
Feature               | Flagger                      | Argo Rollouts
----------------------|------------------------------|------------------------------
Service mesh required | Yes (Istio, Linkerd, AppMesh)| No (works with NGINX, Contour)
                       | or NGINX Ingress             | or Istio/Linkerd via plugins
Analysis              | Built-in metric templates    | AnalysisTemplate CRD
Webhooks              | Load testing, notifications  | Manual approval gates
Blue-Green            | Yes                          | Yes
Canary                | Yes (weight-based)           | Yes (weight-based, mirroring)
A/B testing           | Via Istio                    | Via Istio plugin
Complexity            | Simpler (CRD-based)          | More flexible but complex
Integration           | Prometheus, Datadog, NewRelic| Prometheus, Datadog, custom
GitOps                | ArgoCD compatible            | ArgoCD native (same project)

# Recommendation:
# Flagger: Service-mesh environment, simple canary, built-in metrics
# Argo Rollouts: Need manual gates, no service mesh, already use ArgoCD
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Automated analysis** | Understands metrics-driven promotion: check health at each step before proceeding |
| **Auto-rollback** | Knows that failed metric check → immediate rollback to primary |
| **Traffic progression** | Can design step progression: 5%→10%→25%→50% (or similar) with appropriate pauses |
| **Load testing** | Understands the need for synthetic load during canary to generate meaningful metrics |

---

## 5. Multi-Tenancy: Namespaces, Resource Quotas, Network Policies

**Q:** "Design a multi-tenant Kubernetes cluster serving 5 teams with 10-50 microservices each. Teams must be isolated (can't access each other's resources), have fair resource allocation, and operate independently. How do you implement this with native Kubernetes primitives?"

**What They're Really Testing:** Whether you understand Kubernetes multi-tenancy — using namespaces, ResourceQuotas, LimitRanges, NetworkPolicies, and RBAC to provide strong isolation between teams running workloads on a shared cluster.

### Answer

**Multi-Tenancy Architecture:**

```
┌─────────────────────────────────────────────────────────────┐
│                     Shared Cluster                           │
│                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐│
│  │  Team A (prod)   │  │  Team B (prod)  │  │  System      ││
│  │                  │  │                  │  │              ││
│  │  namespace:      │  │  namespace:      │  │  ns:         ││
│  │  team-a-prod     │  │  team-b-prod     │  │  kube-system ││
│  │                  │  │                  │  │  monitoring  ││
│  │  Resources:      │  │  Resources:      │  │  ingress-    ││
│  │  20 CPU, 40GB   │  │  30 CPU, 60GB   │  │  nginx       ││
│  │                  │  │                  │  │              ││
│  │  NetworkPolicy:  │  │  NetworkPolicy:  │  │              ││
│  │  deny all except │  │  deny all except │  │              ││
│  │  team-a ingress  │  │  team-b ingress  │  │              ││
│  └─────────────────┘  └─────────────────┘  └──────────────┘│
│                                                              │
│  ┌─────────────────┐  ┌─────────────────┐                   │
│  │  Team A (staging)│  │  Team B (staging)│                   │
│  │  ns: team-a-stg  │  │  ns: team-b-stg  │                   │
│  │  Resources:      │  │  Resources:      │                   │
│  │  10 CPU, 20GB   │  │  15 CPU, 30GB   │                   │
│  └─────────────────┘  └─────────────────┘                   │
└─────────────────────────────────────────────────────────────┘
```

**Namespace Provisioning:**

```yaml
# Each team gets namespaces: team-{name}-prod, team-{name}-staging, team-{name}-dev

apiVersion: v1
kind: Namespace
metadata:
  name: team-payment-prod
  labels:
    name: team-payment-prod
    team: payment
    environment: prod
    pod-security.kubernetes.io/enforce: restricted   # Pod Security Standards
---
apiVersion: v1
kind: Namespace
metadata:
  name: team-payment-staging
  labels:
    name: team-payment-staging
    team: payment
    environment: staging
    pod-security.kubernetes.io/enforce: baseline      # Less strict for staging
```

**Resource Quota:**

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-quota
  namespace: team-payment-prod
spec:
  hard:
    # Compute
    requests.cpu: 20
    requests.memory: 40Gi
    limits.cpu: 40
    limits.memory: 80Gi

    # Storage
    requests.storage: 500Gi
    persistentvolumeclaims: 10

    # Ephemeral storage
    requests.ephemeral-storage: 100Gi
    limits.ephemeral-storage: 200Gi

    # Object counts
    pods: 50
    services: 20
    configmaps: 30
    secrets: 30
    deployments.apps: 20
    statefulsets.apps: 5

    # Other
    count/ingresses.networking.k8s.io: 5
    count/jobs.batch: 20

  scopeSelector:
    matchExpressions:
    - operator: In
      scopeName: PriorityClass
      values:
      - production-critical      # Only count production-critical pods
```

**LimitRange (Namespace Defaults):**

```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: team-limits
  namespace: team-payment-prod
spec:
  limits:
  - type: Container
    default:                                  # Default limits (if not specified)
      cpu: 500m
      memory: 512Mi
    defaultRequest:                           # Default requests (if not specified)
      cpu: 100m
      memory: 256Mi
    max:                                      # Hard max per container
      cpu: 4
      memory: 8Gi
    min:                                      # Hard min per container
      cpu: 50m
      memory: 64Mi
  - type: PersistentVolumeClaim
    max:
      storage: 100Gi
    min:
      storage: 1Gi
```

**Network Policy for Namespace Isolation:**

```yaml
# Default deny ALL ingress (base policy for every namespace)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: team-payment-prod
spec:
  podSelector: {}                           # Apply to ALL pods
  policyTypes:
  - Ingress                                 # Deny ALL incoming traffic

# Allow Ingress controller to route to services
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-ingress-controller
  namespace: team-payment-prod
spec:
  podSelector: {}                           # All pods in namespace
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-nginx  # Only from ingress namespace
    ports:
    - port: 8080
    - port: 8443

# Allow monitoring to scrape metrics
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-monitoring
  namespace: team-payment-prod
spec:
  podSelector:
    matchLabels:
      app: payment-service                  # Only payment-service pods
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
    ports:
    - port: 8080

# Allow inter-service communication within the same namespace
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-within-namespace
  namespace: team-payment-prod
spec:
  podSelector: {}                           # All pods
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: team-payment-prod  # Same namespace
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: team-payment-prod

# Allow DNS (CoreDNS) — required for service discovery
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: team-payment-prod
spec:
  podSelector: {}
  egress:
  - to:
    - namespaceSelector: {}
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
```

**RBAC per Team:**

```yaml
# Team A gets admin access to their own namespace and read-only to others

# Role: full access in team's namespace
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: team-payment-prod
  name: team-admin
rules:
- apiGroups: ["", "apps", "batch", "networking.k8s.io", "autoscaling"]
  resources: ["*"]
  verbs: ["*"]
- apiGroups: [""]
  resources: ["pods/exec", "pods/log", "pods/portforward"]
  verbs: ["get", "list", "create"]

# RoleBinding: bind team's ServiceAccount
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  namespace: team-payment-prod
  name: team-payment-binding
subjects:
- kind: Group
  name: team-payment-engineers
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: team-admin
  apiGroup: rbac.authorization.k8s.io

# ClusterRole: read-only across all namespaces (for SREs)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: read-only-global
rules:
- apiGroups: [""]
  resources: ["pods", "services", "endpoints", "events", "nodes"]
  verbs: ["get", "list", "watch"]
```

**Multi-Tenancy Tools:**

```yaml
# For more advanced multi-tenancy, consider:

# 1. Capsule (projectcapsule.dev)
# Multi-tenant operator that creates Tenant CRD
# Each tenant gets: namespaces, resource quotas, network policies, RBAC
apiVersion: capsule.clastix.io/v1beta2
kind: Tenant
metadata:
  name: payment-team
spec:
  owners:
  - kind: User
    name: alice
  - kind: Group
    name: payment-engineers
  namespaceQuota: 3                         # Max 3 namespaces
  namespacesMetadata:
    labels:
      team: payment
      environment: prod
  resourceQuotas:
    scope: Tenant
    items:
    - hard:
        limits.cpu: 40
        limits.memory: 80Gi
        pods: 50
  networkPolicies:
    items:                                  # Enforce base policies
    - spec:
        ingress:
        - from:
          - namespaceSelector:
              matchLabels:
                capsule.clastix.io/tenant: payment-team
  limitRanges:
    items:                                  # Enforce default limits
    - spec:
        limits:
        - default:
            cpu: 500m

# 2. vCluster (virtual clusters)
# Each team gets a virtual cluster inside the physical cluster
# Full Kubernetes API, CRDs, RBAC — isolated at the API level
# Cost: 1 physical node can run 100+ virtual clusters
# Trade-off: Resource overhead for API server per vCluster
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Namespace isolation** | Uses NetworkPolicy + ResourceQuota + LimitRange + RBAC as layered controls |
| **Resource allocation** | Sets hard quotas per namespace with LimitRange defaults |
| **Network isolation** | Default deny, then selective allow for ingress, DNS, monitoring |
| **Tools awareness** | Knows about Capsule (namespace-based multi-tenancy) and vCluster (virtual clusters) |

---

## 6. Service Mesh: Istio, Linkerd & mTLS

**Q:** "Your 50-microservice platform needs mutual TLS (mTLS) between all services, detailed traffic metrics, canary deployments, and circuit breaking — all without modifying application code. Compare Istio and Linkerd. How do they implement mTLS? What's the overhead?"

**What They're Really Testing:** Whether you understand service mesh architecture — sidecar proxies, mTLS certificate rotation, and the control plane vs data plane separation — and can compare Istio (Envoy-based, feature-rich) vs Linkerd (Rust-based, simpler).

### Answer

**Service Mesh Architecture:**

```
┌─────────────────────────────────────────────────────────────┐
│                     Service Mesh Control Plane                │
│                                                              │
│  Istio: Pilot (service discovery), Citadel (certificates),   │
│         Galley (config), Mixer (telemetry — deprecated)      │
│  Linkerd: Destination (service discovery), Identity (certs), │
│           Proxy Injector                                     │
└──────────┬──────────┬──────────┬──────────┬──────────────────┘
           │          │          │          │
      ┌────▼────┐┌────▼────┐┌────▼────┐┌────▼────┐
      │ Service ││ Service ││ Service ││ Service │
      │   A     ││   B     ││   C     ││   D     │
      │  ┌───┐  ││  ┌───┐  ││  ┌───┐  ││  ┌───┐  │
      │  │Envoy│ ││  │Envoy│ ││  │Envoy│ ││  │Envoy│ │
      │  │/link│ ││  │/link│ ││  │/link│ ││  │/link│ │
      │  │erd-p│ ││  │erd-p│ ││  │erd-p│ ││  │erd-p│ │
      │  │roxy │ ││  │roxy │ ││  │roxy │ ││  │roxy │ │
      │  └───┘  ││  └───┘  ││  └───┘  ││  └───┘  │
      └─────────┘└─────────┘└─────────┘└─────────┘
           │          │          │          │
           │  ALL TRAFFIC FLOWS THROUGH PROXIES  │
           └──────────┴──────────┴──────────┘
                mTLS (encrypted, authenticated)
```

**Istio Implementation:**

```yaml
# Istio installs an Envoy sidecar proxy alongside each pod
# All inbound/outbound traffic goes through Envoy

# Auto-injection of sidecar (namespace-level):
apiVersion: v1
kind: Namespace
metadata:
  name: prod
  labels:
    istio-injection: enabled                # Inject Envoy sidecar to ALL pods

# mTLS configuration (enforce mTLS for all services in namespace):
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: prod
spec:
  mtls:
    mode: STRICT                            # STRICT = mTLS required
    # PERMISSIVE = accept both TLS and plaintext (migration mode)
    # DISABLE = no mTLS

# Istio VirtualService (traffic routing):
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: payment-service
spec:
  hosts:
  - payment-service
  http:
  - match:
    - uri:
        prefix: /api/v2/payments
    rewrite:
      uri: /api/v2/payments
    route:
    - destination:
        host: payment-service
        subset: v2                          # Route to v2 for /api/v2/*
  - route:
    - destination:
        host: payment-service
        subset: v1                          # Everything else goes to v1

# Circuit breaker:
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: payment-service-cb
spec:
  host: payment-service
  trafficPolicy:
    connectionPool:
      tcp:
        maxConnections: 100                 # Max 100 concurrent connections
      http:
        http1MaxPendingRequests: 10
        maxRequestsPerConnection: 10
    outlierDetection:                       # Circuit breaker
      consecutive5xxErrors: 5               # 5 consecutive errors
      interval: 30s
      baseEjectionTime: 30s
      maxEjectionPercent: 50                # Eject max 50% of replicas

# Istio mTLS certificate rotation:
# Istio Citadel (or istiod) manages certificates
# Each Envoy proxy gets a SPIFFE-compliant certificate
# Cert format: spiffe://cluster.local/ns/prod/sa/payment-service
# Certificate valid: 24 hours (auto-rotated by Envoy)
# Rotation: Envoy periodically checks for new cert (configurable)
```

**Linkerd Implementation:**

```yaml
# Linkerd uses a Rust-based proxy (linkerd-proxy) instead of Envoy
# Much smaller (~10MB vs ~50MB for Envoy), lower latency

# Install:
linkerd install | kubectl apply -f -
linkerd inject deployment.yaml | kubectl apply -f -

# Auto-injection:
apiVersion: v1
kind: Namespace
metadata:
  name: prod
  annotations:
    linkerd.io/inject: enabled              # Inject linkerd-proxy sidecar

# mTLS (enabled by default — no config needed!):
# Linkerd automatically enables mTLS for ALL injected pods
# Uses auto-rotated certificates (24h rotation)
# Identity: spiffe://cluster.local/ns/prod/sa/payment-service

# Traffic split (canary):
apiVersion: split.smi-spec.io/v1alpha4
kind: TrafficSplit
metadata:
  name: payment-service-split
spec:
  service: payment-service
  backends:
  - service: payment-service-v1
    weight: 90                              # 90% to v1
  - service: payment-service-v2
    weight: 10                              # 10% to v2

# Observability (Linkerd Viz):
# linkerd viz install
# linkerd viz dashboard                     # Web UI
# linkerd viz stat deploy                   # CLI metrics
# linkerd viz top deploy                    # Top endpoints by latency

# Metrics per service (auto-generated, no config needed):
# request_total, request_duration, tcp_open_connections
# All zero-instrumentation — from sidecar proxy
```

**Istio vs Linkerd:**

```yaml
Feature               | Istio                       | Linkerd
----------------------|-----------------------------|---------------------------
Proxy                 | Envoy (C++, 50MB)           | linkerd-proxy (Rust, 10MB)
Latency overhead      | 2-5ms p99 (Envoy)           | 0.5-1ms p99 (Rust)
CPU overhead          | 10-30% (Envoy)              | 5-10% (Rust)
Memory per proxy      | 50-100MB                    | 10-20MB
mTLS                  | STRICT/PERMISSIVE/DISABLE   | Auto-on (no config needed)
Traffic routing       | VirtualService +            | TrafficSplit (SMI)
                      | DestinationRule             |
Circuit breaking      | Yes (outlierDetection)      | Yes (via ServiceProfile)
Retries/timeouts      | Yes                         | Yes
Fault injection       | Yes                         | No
Envoy filter extens.  | Yes (WASM, Lua)             | No
Authorization policy  | Yes (native K8s NetworkPolicies) | Yes (NetworkPolicies)
Multi-cluster         | Yes (multicluster mesh)     | Yes (linkerd-multicluster)
Ingress gateway       | Yes (Istio Gateway)         | No (use NGINX/Contour)
Learning curve        | Steep                       | Gentle
Community             | Large (Google)              | Growing (Buoyant, CNCF)

# When to choose Istio:
# - Need advanced traffic management (A/B testing, fault injection)
# - Need authorization policies (who can call whom)
# - Multi-cluster mesh
# - Already have Envoy experience

# When to choose Linkerd:
# - Simplicity is priority (mTLS + observability out of the box)
# - Resource-constrained clusters (lower overhead)
# - Teams want "it just works" without configuration
# - Focus on mTLS and observability (not traffic management)
```

**Service Mesh Overhead Considerations:**

```yaml
# CPU overhead:
# Istio/Envoy: 10-30% additional CPU per request
# Linkerd: 5-10% additional CPU per request
#
# Mitigation:
# - Use CPU limits on sidecar proxies
# - Tune proxy resources:
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 256Mi

# Latency overhead:
# Istio: 2-5ms added to p99 latency
# Linkerd: 0.5-1ms added to p99 latency
#
# Actual impact depends on:
# - Request size (larger = less relative overhead)
# - TLS handshake (mTLS adds ~1ms for initial connection)
# - Connection reuse (keepalive reduces overhead)

# Memory overhead:
# - Envoy: 50-100MB per sidecar
# - linkerd-proxy: 10-20MB per sidecar
# For 100 pods: Istio=5-10GB, Linkerd=1-2GB

# When NOT to use service mesh:
# - Batch/offline workloads (no benefit)
# - Very latency-sensitive (HFT, real-time video)
# - Small clusters (< 10 services)
# - Already using application-level mTLS
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **mTLS mechanics** | Understands SPIFFE identities, certificate rotation, and mTLS handshake |
| **Istio vs Linkerd** | Can compare proxy overhead, feature set, and operational complexity |
| **Sidecar injection** | Knows mutating webhook injects proxy, intercepts all traffic via iptables |
| **Overhead awareness** | Understands the CPU, memory, and latency costs of adding a service mesh |

---

## 7. Network Policies: Micro-Segmentation

**Q:** "Your security team wants zero-trust networking — every pod-to-pod connection must be explicitly allowed. Design a network policy strategy for a 3-tier application (web → API → database). How do you implement default deny, then selectively allow traffic?"

**What They're Really Testing:** Whether you understand Kubernetes NetworkPolicy as the foundation for micro-segmentation — pod selectors, namespace selectors, IP blocks, and egress/ingress rules.

### Answer

**Zero-Trust Network Policy Design:**

```
Default posture: DENY ALL (no traffic allowed)

Allow rules:
┌────────────┐     :80      ┌────────────┐     :5432     ┌────────────┐
│  Web Tier  │──────────────►│  API Tier  │──────────────►│  DB Tier   │
│            │               │            │               │            │
│  Ingress:  │               │  Ingress:  │               │  Ingress:  │
│  - Ingress │               │  - Web:80  │               │  - API:5432│
│  controller│               │  - Web:443 │               │            │
│            │               │            │               │  Egress:   │
│  Egress:   │               │  Egress:   │               │  - none    │
│  - API:80  │               │  - DB:5432 │               │            │
│  - DNS:53  │               │  - Redis   │               │            │
│            │               │  - DNS:53  │               │            │
└────────────┘               └────────────┘               └────────────┘
```

**Default Deny Policies:**

```yaml
# Default deny ALL ingress (apply to every namespace)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: prod
spec:
  podSelector: {}                           # ALL pods in namespace
  policyTypes:
  - Ingress

# Default deny ALL egress (apply to every namespace)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-egress
  namespace: prod
spec:
  podSelector: {}
  policyTypes:
  - Egress
```

**Tier-Specific Policies:**

```yaml
# ── WEB TIER ──

# Allow Ingress controller to route to web tier
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: web-allow-ingress
  namespace: prod
spec:
  podSelector:
    matchLabels:
      tier: web
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-nginx
    ports:
    - port: 8080
    - port: 8443

# Allow web tier to call API tier
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: web-egress-to-api
  namespace: prod
spec:
  podSelector:
    matchLabels:
      tier: web
  egress:
  - to:
    - podSelector:
        matchLabels:
          tier: api
    ports:
    - port: 8080

# ── API TIER ──

# Allow web tier to call API
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-allow-from-web
  namespace: prod
spec:
  podSelector:
    matchLabels:
      tier: api
  ingress:
  - from:
    - podSelector:
        matchLabels:
          tier: web
    ports:
    - port: 8080

# Allow API to call database
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-egress-to-db
  namespace: prod
spec:
  podSelector:
    matchLabels:
      tier: api
  egress:
  - to:
    - podSelector:
        matchLabels:
          tier: database
    ports:
    - port: 5432

# ── DATABASE TIER ──

# Allow only API tier to connect to database
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: db-allow-from-api
  namespace: prod
spec:
  podSelector:
    matchLabels:
      tier: database
  ingress:
  - from:
    - podSelector:
        matchLabels:
          tier: api
    ports:
    - port: 5432              # PostgreSQL
```

**Cross-Namespace Policies:**

```yaml
# Service in namespace "prod-payment" needs to reach DB in "prod-db"
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: db-allow-from-payment
  namespace: prod-db
spec:
  podSelector:
    matchLabels:
      app: postgres
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: prod-payment
      podSelector:
        matchLabels:
          app: payment-service
    ports:
    - port: 5432
```

**Monitoring Service with IP Block:**

```yaml
# Allow monitoring to scrape from a specific IP range (e.g., Prometheus)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-monitoring-scrape
  namespace: prod
spec:
  podSelector:
    matchLabels:
      app: payment-service
  ingress:
  - from:
    - ipBlock:
        cidr: 10.0.0.0/16                   # Cluster CIDR (for node-exporter, kubelet)
        except:
        - 10.0.1.0/24                       # Except a specific subnet
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
    ports:
    - port: 8080
```

**Network Policy Best Practices:**

```yaml
# 1. Start with audit mode (if using Cilium or Calico)
# Cilium allows policy audit mode without enforcement:
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: audit-mode
spec:
  endpointSelector:
    matchLabels:
      app: payment-service
  ingress:
  - fromEndpoints:
    - matchLabels:
        app: web
  # No egress rules → traffic is logged, not blocked
  # Enable: k8s:io.cilium.network.policy.audit-mode=true (annotation)

# 2. Use policy tiers (Calico Enterprise):
# - Platform: base policies (deny all, allow monitoring, allow DNS)
# - Team: team-specific policies (allow service-to-service)
# - Application: app-specific policies (allow specific ports)

# 3. Allow DNS (CoreDNS) for service discovery — REQUIRED!
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: prod
spec:
  podSelector: {}
  egress:
  - to:
    - namespaceSelector: {}
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP

# 4. Validate with network policy analyzer:
# https://github.com/alcideio/policy-validator
kubectl np-validator -f policy.yaml         # Check policy validity

# 5. Test policies:
kubectl run test-$RANDOM --rm -it --image=nicolaka/netshoot -- /bin/bash
# Inside: curl -v http://payment-service:8080/health
# Should be BLOCKED if no policy allows it
```

**CNI Network Policy Support:**

```yaml
CNI Plugin    | NetworkPolicy Support | Network Policy Features
--------------|-----------------------|--------------------------
Calico        | Full                  | GlobalNetworkPolicy, policy tiers, DNS policy
Cilium        | Full                  | CiliumNetworkPolicy (L7), HTTP-aware, Kafka-aware
Flannel       | None                  | No policy support (use separate Calico for policies)
Weave Net     | Full                  | Standard K8s NetworkPolicy only
Antrea        | Full                  | Standard + Antrea-native policies
Kube-router   | Full                  | iptables/IPVS-based policies
OVN-Kubernetes| Full                  | Standard policies, ACL-based

# For strict zero-trust: Calico or Cilium are recommended
# For simple deployments: standard K8s NetworkPolicy is enough
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Default deny** | Knows to start with deny-all ingress+egress before allowing specific traffic |
| **Micro-segmentation** | Designs tier-by-tier: ingress → web → api → db with minimum necessary ports |
| **Cross-namespace** | Uses namespaceSelector + podSelector for cross-namespace policies |
| **DNS requirement** | Remembers to allow DNS (CoreDNS) — a common gotcha |

---

## 8. Cluster API & Multi-Cluster Management

**Q:** "Your organization is growing from 3 to 50 Kubernetes clusters across multiple cloud providers and regions. How do you manage cluster lifecycle declaratively? Design a Cluster API strategy for provisioning, upgrading, and operating clusters at scale."

**What They're Really Testing:** Whether you understand Cluster API as a Kubernetes-native way to manage cluster lifecycle — provisioning, upgrading, and operating clusters using Kubernetes-style resources.

### Answer

**Cluster API Architecture:**

```
┌─────────────────────────────────────────────────────────────┐
│                    Management Cluster                        │
│                                                              │
│  Cluster API controllers:                                    │
│  - Cluster (the cluster itself)                              │
│  - MachineDeployment (worker node groups)                   │
│  - Machine (individual nodes)                                │
│  - KubeadmControlPlane (control plane nodes)                 │
│  - ClusterResourceSet (addons: CNI, CSI, CCM)               │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Cluster: prod-us-east-1                              │   │
│  │ KubeadmControlPlane: 3 control plane nodes           │   │
│  │ MachineDeployment: 5 worker nodes (m5.large)         │   │
│  │ ClusterResourceSet: Cilium, AWS EBS CSI, CoreDNS     │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  Provider: AWS Cluster API Provider (CAPA)                   │
│  - Creates: VPC, subnets, security groups, IAM, EC2, ELB    │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  Workload Cluster (prod-us-east-1)            │
│                                                              │
│  3 Control Plane Nodes (t3.large, multi-AZ)                 │
│  5 Worker Nodes (m5.large, multi-AZ)                        │
│                                                              │
│  Pre-installed: Cilium (CNI), AWS EBS CSI (storage),        │
│                CoreDNS, metrics-server, ArgoCD               │
└─────────────────────────────────────────────────────────────┘
```

**Cluster API Resources:**

```yaml
apiVersion: cluster.x-k8s.io/v1beta1
kind: Cluster
metadata:
  name: prod-us-east-1
  namespace: clusters
spec:
  clusterNetwork:
    services:
      cidrBlocks: ["10.96.0.0/12"]
    pods:
      cidrBlocks: ["10.32.0.0/12"]
    serviceDomain: cluster.local
  infrastructureRef:
    apiVersion: infrastructure.cluster.x-k8s.io/v1beta2
    kind: AWSCluster
    name: prod-us-east-1
  controlPlaneRef:
    apiVersion: controlplane.cluster.x-k8s.io/v1beta1
    kind: KubeadmControlPlane
    name: prod-us-east-1-cp

---
# AWS infrastructure (VPC, subnets, etc.)
apiVersion: infrastructure.cluster.x-k8s.io/v1beta2
kind: AWSCluster
metadata:
  name: prod-us-east-1
  namespace: clusters
spec:
  region: us-east-1
  sshKeyName: default
  bastion:
    enabled: true
  network:
    vpc:
      cidrBlock: 10.0.0.0/16
    subnets:
    - availabilityZone: us-east-1a
      cidrBlock: 10.0.1.0/24
      isPublic: true
    - availabilityZone: us-east-1b
      cidrBlock: 10.0.2.0/24
      isPublic: true

---
# Control plane (3 nodes)
apiVersion: controlplane.cluster.x-k8s.io/v1beta1
kind: KubeadmControlPlane
metadata:
  name: prod-us-east-1-cp
  namespace: clusters
spec:
  replicas: 3
  version: v1.29.5
  machineTemplate:
    infrastructureRef:
      apiVersion: infrastructure.cluster.x-k8s.io/v1beta2
      kind: AWSMachineTemplate
      name: prod-us-east-1-cp-template
  kubeadmConfigSpec:
    clusterConfiguration:
      apiServer:
        extraArgs:
          cloud-provider: aws
      controllerManager:
        extraArgs:
          cloud-provider: aws

---
# Worker nodes
apiVersion: cluster.x-k8s.io/v1beta1
kind: MachineDeployment
metadata:
  name: prod-us-east-1-workers
  namespace: clusters
spec:
  clusterName: prod-us-east-1
  replicas: 5
  template:
    spec:
      clusterName: prod-us-east-1
      version: v1.29.5
      bootstrap:
        configRef:
          apiVersion: bootstrap.cluster.x-k8s.io/v1beta1
          kind: KubeadmConfigTemplate
          name: prod-us-east-1-workers-template
      infrastructureRef:
        apiVersion: infrastructure.cluster.x-k8s.io/v1beta2
        kind: AWSMachineTemplate
        name: prod-us-east-1-workers-template

---
# Addons to install in the workload cluster
apiVersion: addons.cluster.x-k8s.io/v1beta1
kind: ClusterResourceSet
metadata:
  name: prod-us-east-1-addons
  namespace: clusters
spec:
  clusterSelector:
    matchLabels:
      cluster: prod-us-east-1
  resources:
  - kind: ConfigMap
    name: cilium-install
  - kind: ConfigMap
    name: aws-ebs-csi-driver
  - kind: ConfigMap
    name: core-dns-config
  strategy: ApplyOnce                               # Install once, not on every sync
```

**Cluster Upgrades with Cluster API:**

```yaml
# To upgrade a cluster from v1.29.x to v1.30.0:

# 1. Update control plane version
apiVersion: controlplane.cluster.x-k8s.io/v1beta1
kind: KubeadmControlPlane
metadata:
  name: prod-us-east-1-cp
spec:
  version: v1.30.0           # Update from v1.29.5
  replicas: 3
  rollingUpdate:
    maxSurge: 1              # Upgrade 1 control plane at a time

# Cluster API rolls control plane:
# 1. Machine 1: create new node with v1.30.0, wait for ready, delete old
# 2. Machine 2: create new node with v1.30.0, wait for ready, delete old
# 3. Machine 3: same
# Zero downtime if rolling strategy is set

# 2. Update worker node version
apiVersion: cluster.x-k8s.io/v1beta1
kind: MachineDeployment
metadata:
  name: prod-us-east-1-workers
spec:
  template:
    spec:
      version: v1.30.0       # Update from v1.29.5
  strategy:
    rollingUpdate:
      maxSurge: 2             # 2 new nodes at a time
      maxUnavailable: 0       # Keep all workers available

# Cluster API creates new Machine (with v1.30.0), waits for ready,
# then deletes old Machine (v1.29.5) → Rolling update of nodes
```

**Multi-Cluster Management Tools:**

```yaml
Tool              | Purpose                  | Key Feature
------------------|--------------------------|---------------------------
Cluster API       | Cluster lifecycle        | Declarative cluster CRDs, multi-cloud
Karmada           | Application scheduling   | Multi-cluster app deployment
Fleet (Rancher)   | Multi-cluster management | GitOps for multi-cluster
ArgoCD            | App deployment           | ApplicationSet for multi-cluster
Istio multi-cluster| Service mesh             | Cross-cluster service discovery
Submariner        | Network connectivity     | Cross-cluster pod-to-pod networking

# Karmada example (multi-cluster app deployment):
apiVersion: policy.karmada.io/v1alpha1
kind: PropagationPolicy
metadata:
  name: payment-service-propagation
spec:
  resourceSelectors:
  - apiVersion: apps/v1
    kind: Deployment
    name: payment-service
  placement:
    clusterAffinity:
      clusterNames:
      - prod-us-east
      - prod-eu-west
      - prod-apac
    replicaScheduling:
      replicaDivisionPreference: Weighted
      replicaScheduling:
        totalReplicas: 15
        preferences:
          prod-us-east: 5        # 5 replicas to us-east
          prod-eu-west: 5        # 5 replicas to eu-west
          prod-apac: 5           # 5 replicas to apac
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Cluster API model** | Understands CRDs for clusters, machines, control planes — Kubernetes all the way down |
| **Cluster upgrades** | Explains rolling updates for control plane + worker nodes with zero downtime |
| **Multi-cloud** | Knows Cluster API has providers for AWS, Azure, GCP, vSphere, etc. |
| **Addon management** | Uses ClusterResourceSet to install CNI, CSI, CoreDNS during cluster creation |

---

## 9. Pod Security: Kyverno Policies for Production

**Q:** "Your platform team manages 20 namespaces across 5 teams. You need to enforce: (a) all pods have resource limits, (b) no privileged containers, (c) no latest image tag, (d) specific labels required, (e) root filesystem is read-only. Design a Kyverno policy set for this."

**What They're Really Testing:** Whether you understand how to use Kyverno's mutate, validate, and generate capabilities to enforce production security standards without blocking developers unnecessarily.

### Answer

**Kyverno Policy Set for Production:**

```yaml
# ── 1. MUTATE: Add default resource limits (don't block, fix automatically) ──
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: add-resource-limits
spec:
  validationFailureAction: Audit
  background: false
  rules:
  - name: add-container-limits
    match:
      any:
      - resources:
          kinds:
          - Pod
    mutate:
      patchStrategicMerge:
        spec:
          containers:
          - (name): "*"
            resources:
              limits:
                +(cpu): "500m"
                +(memory): "512Mi"
              requests:
                +(cpu): "100m"
                +(memory): "256Mi"

# ── 2. VALIDATE: No privileged containers ──
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: disallow-privileged-containers
spec:
  validationFailureAction: Enforce
  background: true
  rules:
  - name: privileged-containers
    match:
      any:
      - resources:
          kinds:
          - Pod
    validate:
      message: "Privileged containers are not allowed"
      pattern:
        spec:
          containers:
          - name: "*"
            securityContext:
              =(privileged): false           # If set, must be false
  - name: privileged-escalation
    match:
      any:
      - resources:
          kinds:
          - Pod
    validate:
      message: "Privilege escalation is not allowed"
      pattern:
        spec:
          containers:
          - name: "*"
            securityContext:
              allowPrivilegeEscalation: false

# ── 3. VALIDATE: No latest image tag ──
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: disallow-latest-tag
spec:
  validationFailureAction: Enforce
  background: false
  rules:
  - name: require-image-tag
    match:
      any:
      - resources:
          kinds:
          - Pod
    validate:
      message: "A image tag is required (no 'latest' allowed)"
      foreach:
      - list: request.object.spec.[initContainers, containers][]
        deny:
          conditions:
            any:
            - key: "{{ element.image }}"
              operator: NotEquals
              value: "*@sha256:*"            # Allow digest references
            - key: "{{ regex_match(':[^:]+$', '{{ element.image }}') }}"
              operator: Equals
              value: false                   # Must have a tag
        preconditions:
          any:
          - key: "{{ regex_match(':', '{{ element.image }}') }}"
            operator: Equals
            value: false                    # Skip if already has a tag

# ── 4. VALIDATE: Required labels ──
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-labels
spec:
  validationFailureAction: Enforce
  rules:
  - name: check-required-labels
    match:
      any:
      - resources:
          kinds:
          - Pod
          - Deployment
          - Service
          - PersistentVolumeClaim
    validate:
      message: "Labels 'app.kubernetes.io/name', 'app.kubernetes.io/component', and 'app.kubernetes.io/part-of' are required"
      pattern:
        metadata:
          labels:
            app.kubernetes.io/name: "?*"
            app.kubernetes.io/component: "?*"
            app.kubernetes.io/part-of: "?*"

# ── 5. MUTATE: Set security context defaults ──
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: add-security-context
spec:
  validationFailureAction: Audit
  rules:
  - name: auto-add-security-context
    match:
      any:
      - resources:
          kinds:
          - Pod
    mutate:
      patchStrategicMerge:
        spec:
          securityContext:
            runAsNonRoot: true
            seccompProfile:
              type: RuntimeDefault
          containers:
          - (name): "*"
            securityContext:
              allowPrivilegeEscalation: false
              readOnlyRootFilesystem: true
              capabilities:
                drop: ["ALL"]
                add: ["NET_BIND_SERVICE"]
      patchesJson6902: |-
        # Also set runAsUser if not specified
        - path: /spec/securityContext/runAsUser
          op: add
          value: 1000
        - path: /spec/securityContext/runAsGroup
          op: add
          value: 3000

# ── 6. GENERATE: NetworkPolicy for every new namespace ──
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: generate-default-network-policy
spec:
  rules:
  - name: generate-deny-all
    match:
      any:
      - resources:
          kinds:
          - Namespace
    generate:
      synchronize: true
      apiVersion: networking.k8s.io/v1
      kind: NetworkPolicy
      name: default-deny-ingress
      namespace: "{{ request.object.metadata.name }}"
      data:
        spec:
          podSelector: {}
          policyTypes:
          - Ingress

# ── 7. VALIDATE: Resource Quota enforcement ──
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-resource-quota
spec:
  validationFailureAction: Audit
  rules:
  - name: check-resource-quota
    match:
      any:
      - resources:
          kinds:
          - Namespace
    preconditions:
      any:
      - key: "{{ request.object.metadata.name }}"
        operator: NotEquals
        value: "kube-system"
    validate:
      message: "Namespaces must have a ResourceQuota before deploying workloads"
      deny:
        conditions:
          any:
          - key: "{{ request.object.metadata.name }}"
            operator: NotIn
            value: "{{ namespaces }}"
      # This uses a context variable — in practice, check via API call
```

**Kyverno Policy Testing Strategy:**

```yaml
# Testing approach:
# 1. Start in Audit mode (validationFailureAction: Audit)
#    - Reports policy violations in PolicyReport CRD
#    - Doesn't block anything
# 2. Review PolicyReport for false positives
# 3. Add exceptions for known valid cases
# 4. Switch to Enforce mode

# View policy reports:
kubectl get policyreports -A
kubectl describe policyreport -n prod polr-ns-prod

# Example exception (Kyverno PolicyException):
apiVersion: kyverno.io/v2
kind: PolicyException
metadata:
  name: allow-istio-sidecar
  namespace: istio-system
spec:
  exceptions:
  - policyName: disallow-privileged-containers
    ruleNames:
    - privileged-containers
  - policyName: add-security-context
    ruleNames:
    - auto-add-security-context
  match:
    any:
    - resources:
        kinds:
        - Pod
        namespaces:
        - istio-system
        names:
        - istio-*

# Background scanning (for existing resources):
# Kyvernor scans existing resources and reports violations
# in PolicyReport CRDs — doesn't modify existing resources
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Mutate before validate** | Mutates (adds defaults) before validating (blocks violations) |
| **Audit-first approach** | Starts in Audit mode to discover existing violations safely |
| **PolicyException** | Knows how to exempt legitimate cases (sidecars, system components) |
| **Comprehensive coverage** | Covers: resources, security, images, labels, networking, storage |

---

## 10. CNI Deep Dive: Calico, Cilium, Flannel

**Q:** "Design a Kubernetes networking architecture for a cluster with 500 nodes across 3 availability zones. Compare Calico (BGP), Cilium (eBPF), and Flannel (VXLAN) for this use case. How does each handle pod-to-pod networking across zones?"

**What They're Really Testing:** Whether you understand CNI plugin architecture — overlay vs routing-based networking, BGP vs eBPF data planes, and how each choice impacts performance, security, and operations.

### Answer

**CNI Comparison:**

```yaml
Feature               | Calico                    | Cilium                  | Flannel
----------------------|---------------------------|-------------------------|-----------------------
Data plane            | eBPF (or iptables)        | eBPF                    | VXLAN (or host-gw)
Mode                  | BGP routing (no overlay)  | eBPF-based              | Overlay (VXLAN)
                      | or VXLAN/IPIP overlay     |                         |
Performance           | Native (BGP: line rate)   | Best (no overhead)      | Good (VXLAN: ~5% loss)
                      | VXLAN: ~5% loss           | eBPF direct routing     |
NetworkPolicy         | Full (L3-L4)              | Full (L3-L7)            | None (not supported)
                      |                           | HTTP, gRPC, Kafka-aware |
Encryption            | WireGuard (node-to-node)  | IPsec/WireGuard         | None
Service mesh          | No                        | Yes (eBPF, no sidecar)  | No
IPv6                  | Yes                       | Yes                     | Yes
eBPF                  | Optional (eBPF data plane)| Required                 | No
Complexity            | Medium                    | High                    | Low
Scaling               | 500+ nodes (BGP)          | 1000+ nodes (eBPF)      | 200+ nodes (VXLAN)

# Recommendation:
# Calico: Best all-around, BGP for performance, policy support
# Cilium: eBPF-native, best for security + observability (Hubble)
# Flannel: Simple, no policy, small clusters only
```

**Calico BGP Mode (No Overlay):**

```yaml
# Calico with BGP routing: pods get routable IPs, no encapsulation
# Traffic flows: pod → host → router → destination host → pod
# Uses BGP to advertise pod CIDRs to the network

# ┌─────────┐      BGP       ┌─────────┐
# │ Node 1  │◄══════════════►│ Node 2  │
# │ Pod CIDR│                │ Pod CIDR│
# │ 10.1.1.0/24             │ 10.1.2.0/24
# │         │                │         │
# │  ┌───┐  │                │  ┌───┐  │
# │  │Pod│  │─ ─ ─ ─ ─ ─ ─►│  │Pod│  │
# │  │A  │  │   Direct      │  │B  │  │
# │  └───┘  │   (no encap)  │  └───┘  │
# └─────────┘                └─────────┘

# Data path:
# 1. Pod A (10.1.1.5) sends to Pod B (10.1.2.10)
# 2. Calico routes out of node 1's interface (no encapsulation)
# 3. Upstream router has route: 10.1.2.0/24 → Node 2's IP (via BGP)
# 4. Packet arrives at Node 2, routes to Pod B
# Latency: near line-rate (no encapsulation overhead)

# Calico BGP configuration:
apiVersion: crd.projectcalico.org/v1
kind: BGPConfiguration
metadata:
  name: default
spec:
  logSeverityScreen: Info
  nodeToNodeMeshEnabled: true              # Full mesh for < 50 nodes
  # For > 50 nodes: use route reflectors (RR)
  # nodeToNodeMeshEnabled: false
  # Route reflector: reduces BGP peering from N² to N

# BGP peer with route reflector for larger clusters:
apiVersion: crd.projectcalico.org/v1
kind: BGPPeer
metadata:
  name: route-reflector
spec:
  peerIP: 10.0.0.100                       # Route reflector IP
  asNumber: 64512
  nodeSelector: all()                       # All nodes peer with RR

# Cross-AZ traffic:
# BGP ensures each node knows the pod CIDR of every other node
# Cross-AZ traffic goes through the underlying network layer
# No overlay overhead → same performance as same-AZ
# AZ-aware network policies can restrict cross-AZ traffic
```

**Cilium eBPF Mode:**

```yaml
# Cilium uses eBPF (extended Berkeley Packet Filter) programs
# Programs run in the kernel, not in user space
# Zero-copy packet processing, programmable data plane

# Cilium eBPF features:
# - Direct routing: no iptables, no overlay
# - NetworkPolicy at L7 (HTTP, gRPC, Kafka)
# - Transparent encryption (IPsec, WireGuard)
# - Hubble: deep network observability
# - Service mesh without sidecars (kube-proxy replacement)

apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: allow-http-to-api
  namespace: prod
spec:
  endpointSelector:
    matchLabels:
      app: api
  ingress:
  - fromEndpoints:
    - matchLabels:
        app: web
    toPorts:
    - ports:
      - port: "8080"
        protocol: TCP
      rules:
        http:
        - method: "GET"
          path: "/api/v1/orders"
        - method: "POST"
          path: "/api/v1/payments"

# Cilium replaces kube-proxy (more efficient):
# cilium install --set kubeProxyReplacement=true

# Cilium Cluster Mesh (multi-cluster networking):
apiVersion: cilium.io/v2
kind: CiliumClusterwideEnvoyConfig
metadata:
  name: cilium-cluster-mesh
spec:
  # Connect clusters across regions
  # Pods in cluster A can reach pods in cluster B
  # Uses: native routing + IPsec encryption across regions

# Cilium WireGuard encryption:
apiVersion: cilium.io/v2
kind: CiliumClusterwideEnvoyConfig
metadata:
  name: enable-wireguard
spec:
  encryption:
    type: wireguard

# Performance: Cilium is fastest CNI (eBPF bypasses iptables)
# Latency: sub-millisecond pod-to-pod
# Throughput: 95%+ of line rate
# TCP connection rate: 10× faster than iptables-based CNIs
```

**Flannel VXLAN Mode (Simple Overlay):**

```yaml
# Flannel: simplest CNI, VXLAN overlay
# Each node gets a /24 subnet from the cluster CIDR
# Traffic is encapsulated in VXLAN (UDP port 8472)

# ┌─────────┐    VXLAN     ┌─────────┐
# │ Node 1  │◄═══tunnel══►│ Node 2  │
# │ Pod CIDR│  UDP 8472   │ Pod CIDR│
# │ 10.1.1.0/24           │ 10.1.2.0/24
# │         │              │         │
# │  ┌───┐  │  ┌────────┐ │  ┌───┐  │
# │  │Pod│  │  │VXLAN   │ │  │Pod│  │
# │  │A  │──┼─►│encap   ├─┼─►│B  │  │
# │  └───┘  │  │+5% loss│ │  └───┘  │
# └─────────┘  └────────┘ └─────────┘

# Data path (VXLAN):
# 1. Pod A sends to Pod B
# 2. Flannel wraps packet in VXLAN header (UDP 8472)
# 3. Outer packet: src=Node1_IP, dst=Node2_IP
# 4. Node 2 receives, strips VXLAN header
# 5. Routes to Pod B
# Overhead: ~50 bytes per packet (~3% for 1500 MTU)

# Flannel backend types:
# - vxlan: default, UDP encapsulation, works everywhere
# - host-gw: direct routing (no overlay), same subnet only
# - wireguard: encrypted overlay
# - ipsec: encrypted overlay

# Flannel configuration:
apiVersion: flannel.k8s.io/v1beta1
kind: FlannelConfig
# Simplest installation:
kubectl apply -f https://raw.githubusercontent.com/flannel-io/flannel/master/Documentation/kube-flannel.yml

# Pro: Dead simple to install and operate
# Con: No NetworkPolicy support
# Con: VXLAN overhead (~5% throughput loss)
# Con: Not suitable for > 200 nodes (VXLAN flood learning)
# Con: Cross-AZ traffic goes through tunnel (higher latency)
```

**CNI Selection Decision Tree:**

```
Do you need NetworkPolicy?
├── YES → Do you need L7 policies (HTTP, gRPC)?
│   ├── YES → Cilium (eBPF-based L7-aware policies)
│   └── NO  → Calico (L3-L4 policies, BGP routing)
│
├── NO → Do you have < 200 nodes?
│   ├── YES → Flannel (simplest, good enough)
│   └── NO  → Calico (VXLAN mode, better scaling)
│
└── Do you need multi-cluster networking?
    ├── YES → Cilium (Cluster Mesh)
    └── NO  → Calico (BGP, mature, stable)

Performance ranking: Cilium (eBPF) > Calico (BGP) > Calico (VXLAN) > Flannel (VXLAN)
Security ranking:    Cilium (L7) > Calico (L3-L4 + WireGuard) > Flannel (none)
Simplicity ranking:  Flannel > Calico (VXLAN) > Cilium > Calico (BGP)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **BGP vs Overlay** | Understands BGP (no overhead, needs network config) vs VXLAN (overhead, works anywhere) |
| **eBPF advantages** | Knows eBPF provides L7 policy, Hubble observability, kube-proxy replacement |
| **CNI trade-offs** | Can recommend based on: size, policy needs, performance requirements, operational complexity |
| **Cross-AZ networking** | Understands AZ-aware routing and how each CNI handles multi-AZ traffic |

---

## 11. Descheduler & Cluster Autoscaler

**Q:** "Your cluster has 50 nodes. Over time, pods become unevenly distributed — some nodes are 90% utilized, others 20%. How do you rebalance pods without manual intervention? Design a descheduler strategy. How does it work with cluster autoscaler?"

**What They're Really Testing:** Whether you understand Kubernetes descheduler as a tool for rebalancing pods across nodes, and how it complements the cluster autoscaler for efficient resource utilization.

### Answer

**Descheduler Strategies:**

```yaml
# Descheduler: evicts pods that violate scheduling policies
# After eviction, pods are re-scheduled by the scheduler
# NOT a scheduler — it's a eviction-trigger for rebalancing

# Install descheduler:
helm repo add descheduler https://kubernetes-sigs.github.io/descheduler/
helm install descheduler descheduler/descheduler -f values.yaml

# Descheduler strategies:

# 1. LowNodeUtilization: rebalance pods from low-utilization to high-utilization nodes
#    Actually: evicts pods from LOW utilization nodes so scheduler redistributes
apiVersion: descheduler/v1alpha2
kind: DeschedulerPolicy
spec:
  strategies:
    LowNodeUtilization:
      enabled: true
      params:
        nodeResourceUtilizationThresholds:
          thresholds:
            cpu: 20                    # Node below 20% CPU → underutilized
            memory: 20
            pods: 20
          targetThresholds:
            cpu: 50                    # Target: fill nodes to 50%
            memory: 50
            pods: 50

# 2. HighNodeUtilization: evict pods from highly-utilized nodes
#    Distributes load across more nodes
    HighNodeUtilization:
      enabled: true
      params:
        nodeResourceUtilizationThresholds:
          thresholds:
            cpu: 80                    # Node above 80% → overutilized
            memory: 80
            pods: 80

# 3. RemoveDuplicates: evict redundant pod replicas on same node
    RemoveDuplicates:
      enabled: true

# 4. RemovePodsViolatingNodeAffinity: evict pods that violate node affinity
    RemovePodsViolatingNodeAffinity:
      enabled: true
      params:
        nodeAffinityType:
        - requiredDuringSchedulingIgnoredDuringExecution

# 5. RemovePodsViolatingTopologySpreadConstraint:
#    Evicts pods that violate topology spread
    RemovePodsViolatingTopologySpreadConstraint:
      enabled: true
      params:
        includeSoftConstraints: true

# 6. RemovePodsViolatingInterPodAntiAffinity:
#    Evicts pods that violate inter-pod anti-affinity
    RemovePodsViolatingInterPodAntiAffinity:
      enabled: true

# 7. RemovePodsHavingTooManyRestarts:
#    Evict pods with excessive restarts
    RemovePodsHavingTooManyRestarts:
      enabled: true
      params:
        podRestartThreshold: 100
        includingInitContainers: false
```

**Descheduler Configuration Best Practices:**

```yaml
# Production descheduler configuration:

apiVersion: "descheduler/v1alpha2"
kind: "DeschedulerPolicy"
spec:
  # Run every 10 minutes (not too frequent)
  schedule: "*/10 * * * *"

  # Node selector: only deschedule on worker nodes
  nodeSelector: "node-role.kubernetes.io/worker"

  # Eviction limits: don't evict too many pods at once
  evictionLimits:
    maxNoOfPodsToEvictPerNode: 5
    maxNoOfPodsToEvictPerNamespace: 10

  # Priority threshold: don't evict critical pods
  priorityThreshold:
    value: 100000                       # Don't evict pods with priority ≥ 100000

  strategies:
    LowNodeUtilization:
      enabled: true
      params:
        nodeResourceUtilizationThresholds:
          thresholds:
            cpu: 20
            memory: 20
            pods: 20
          targetThresholds:
            cpu: 60
            memory: 60
            pods: 60
        evictableNamespaces:
          include:
          - "*"                          # Include all namespaces
          exclude:
          - kube-system
          - monitoring

    RemovePodsViolatingTopologySpreadConstraint:
      enabled: true
      params:
        includeSoftConstraints: true    # Enforce soft constraints
        namespaces:
          exclude:
          - kube-system

    RemoveDuplicates:
      enabled: true

  # Pod eviction filters:
  # - Don't evict pods with PDB (unless PDB allows)
  # - Don't evict critical pods (priority ≥ 100000)
  # - Don't evict DaemonSet pods
  # - Don't eviet mirror pods
  # - Don't evict pods that are part of a statefulset with PDB
```

**Cluster Autoscaler with Descheduler:**

```yaml
# Cluster Autoscaler: adds/removes NODES when pods can't schedule
# Descheduler: rebalances PODS across existing nodes
# Together: efficient resource utilization + automatic scaling

# ┌─────────────────────────────────────────────────────────────┐
# │ Cluster Autoscaler + Descheduler Interaction                 │
# │                                                              │
# │ 1. Traffic spike → some pods pending (no node capacity)      │
# │ 2. Cluster Autoscaler: adds 3 nodes                          │
# │ 3. Pods scheduled on new nodes (spread thin)                 │
# │ 4. Traffic drops → descheduler detects low utilization       │
# │ 5. Descheduler evicts pods from underutilized nodes          │
# │ 6. Scheduler re-distributes pods to fewer nodes              │
# │ 7. Cluster Autoscaler: removes empty nodes (scale down)      │
# │                                                              │
# │ Result: Cost savings + Performance                           │
# └─────────────────────────────────────────────────────────────┘

# Cluster Autoscaler configuration (AWS):
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler
  namespace: kube-system
spec:
  replicas: 1                           # Only one should be active
  selector:
    matchLabels:
      app: cluster-autoscaler
  template:
    spec:
      serviceAccountName: cluster-autoscaler
      containers:
      - image: registry.k8s.io/autoscaling/cluster-autoscaler:v1.29.3
        name: cluster-autoscaler
        command:
        - ./cluster-autoscaler
        - --cloud-provider=aws
        - --node-group-auto-discovery=asg:tag=k8s.io/cluster-autoscaler/enabled
        - --scale-down-delay-after-add=10m    # Wait 10m after scale-up
        - --scale-down-delay-after-delete=10s
        - --scale-down-delay-after-failure=3m
        - --scale-down-unneeded-time=10m      # Node idle for 10m → scale down
        - --scale-down-utilization-threshold=0.5  # 50% utilization threshold
        - --max-node-provision-time=15m       # Max 15m for node creation
        - --balance-similar-node-groups=true  # Balance across AZs
        - --skip-nodes-with-system-pods=false
        - --skip-nodes-with-local-storage=false
        resources:
          requests:
            cpu: 100m
            memory: 300Mi
          limits:
            cpu: 500m
            memory: 1Gi

# Descheduler with Cluster Autoscaler integration:
# 1. Descheduler runs every 10 minutes
# 2. Evicts pods from low-utilization nodes
# 3. Cluster Autoscaler sees empty nodes → scales down
# 4. Cost savings: 20-40% reduction in node count
```

**Descheduler Monitoring:**

```yaml
# Descheduler metrics (Prometheus):
# descheduler_pods_evicted_total{strategy="LowNodeUtilization", node="node-1"}
# descheduler_pods_eviction_failed_total{reason="PDB violation"}
# descheduler_evicted_pods_total{node="node-1"}

# Alert on excessive evictions:
- alert: DeschedulerHighEvictionRate
  expr: |
    rate(descheduler_pods_evicted_total[15m]) > 10
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Descheduler evicted {{ $value }} pods in 15m"
    description: "High eviction rate may indicate scheduling issues"

# Logs: descheduler logs show eviction decisions
# "Evicted pod: payment-service-abc from node: node-1 (reason: LowNodeUtilization)"
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Descheduler vs Scheduler** | Understands scheduler assigns pods initially; descheduler rebalances after placement |
| **Eviction safety** | Knows about priority thresholds, PDBs, and max eviction limits to prevent disruption |
| **CA + Descheduler** | Explains how descheduler consolidates, CA scales down empty nodes |
| **Strategy selection** | Can choose LowNodeUtilization for balancing, TopologySpread for AZ distribution |

---

## 12. Storage: CSI, Volume Snapshots, Backup Strategies

**Q:** "Design a storage strategy for stateful workloads on Kubernetes — databases, message queues, and file storage. How does CSI provisioning work? How do you back up and restore persistent volumes? How do you handle disaster recovery across regions?"

**What They're Really Testing:** Whether you understand the Kubernetes storage ecosystem — CSI drivers, volume snapshots, backup tools (Velero), and disaster recovery patterns for stateful workloads.

### Answer

**CSI Driver Architecture:**

```
CSI (Container Storage Interface):
Standard interface between Kubernetes and storage providers

                        ┌──────────────────┐
                        │  Kubernetes API   │
                        └────────┬─────────┘
                                 │
               ┌─────────────────┼─────────────────┐
               ▼                 ▼                  ▼
┌──────────────────────┐ ┌──────────────────┐ ┌─────────────────┐
│  CSI Controller      │ │  CSI Node         │ │  CSI Identity   │
│  (Deployment)        │ │  (DaemonSet)      │ │  (all components)│
│                      │ │                   │ │                   │
│  CreateVolume        │ │  NodeStageVolume  │ │  GetPluginInfo   │
│  DeleteVolume        │ │  NodePublishVolume│ │  Probe            │
│  CreateSnapshot      │ │  NodeUnpublish    │ │                   │
│  ControllerPublish   │ │  NodeGetVolumeStats│ │                   │
└──────────────────────┘ └──────────────────┘ └─────────────────┘
```

**CSI StorageClass Examples:**

```yaml
# AWS EBS (gp3 — general purpose SSD)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3
provisioner: ebs.csi.aws.com
volumeBindingMode: WaitForFirstConsumer   # Wait for pod to schedule before creating volume
parameters:
  type: gp3
  iops: "3000"                            # Baseline 3000 IOPS
  throughput: "125"                       # 125 MB/s
  encrypted: "true"
  csi.storage.k8s.io/fstype: ext4
allowVolumeExpansion: true                # Can resize PVC later

# AWS EBS (io2 — high performance, for databases)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: io2
provisioner: ebs.csi.aws.com
parameters:
  type: io2
  iops: "16000"
  throughput: "500"
  encrypted: "true"
allowVolumeExpansion: true

# GCP Persistent Disk (pd-ssd)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: pd-ssd
provisioner: pd.csi.storage.gke.io
volumeBindingMode: WaitForFirstConsumer
parameters:
  type: pd-ssd
  replication-type: none                  # Regional: regional-pd
allowVolumeExpansion: true

# Azure Disk (Premium SSD)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: azure-premium
provisioner: disk.csi.azure.com
parameters:
  skuname: Premium_LRS
  cachingMode: ReadOnly
allowVolumeExpansion: true

# NFS (shared filesystem)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: nfs
provisioner: nfs.csi.k8s.io
parameters:
  server: nfs-server.internal
  share: /exported/path
  mountPermissions: "0777"
```

**Volume Snapshots & Clone:**

```yaml
# VolumeSnapshot: point-in-time snapshot of a PVC
# Requires: VolumeSnapshotClass (CSI driver must support it)

# VolumeSnapshotClass:
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: ebs-snapshots
driver: ebs.csi.aws.com
deletionPolicy: Delete                    # Delete snapshot when VolumeSnapshot is deleted
# Or: Retain (keep snapshot even if VolumeSnapshot resource is deleted)
parameters:
  tags: "environment=prod,backup=daily"

# Create a snapshot:
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: postgres-pre-upgrade-snapshot
  namespace: prod
spec:
  volumeSnapshotClassName: ebs-snapshots
  source:
    persistentVolumeClaimName: data-postgres-0   # PVC to snapshot

# Restore from snapshot (create new PVC from snapshot):
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-restored
  namespace: prod
spec:
  storageClassName: gp3
  dataSource:
    name: postgres-pre-upgrade-snapshot
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 100Gi

# VolumeClone: clone a PVC without snapshot
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-clone
  namespace: prod
spec:
  storageClassName: gp3
  dataSource:
    name: data-postgres-0
    kind: PersistentVolumeClaim
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 100Gi
```

**Velero (Backup & Disaster Recovery):**

```yaml
# Velero: backup and restore Kubernetes resources + PV snapshots

# Install:
velero install \
  --provider aws \
  --bucket velero-backups \
  --backup-location-config region=us-east-1 \
  --snapshot-location-config region=us-east-1 \
  --plugins velero/velero-plugin-for-aws:v1.9.0 \
  --use-volume-snapshots=true \
  --features=EnableCSI

# Schedule daily backups:
velero schedule create daily-backup \
  --schedule="0 2 * * *"                    # 2 AM daily
  --ttl=720h                                # Keep for 30 days
  --include-namespaces=prod,staging
  --exclude-resources=events,events.events.k8s.io
  --volume-snapshot-locations=us-east-1a

# On-demand backup:
velero backup create pre-deploy-backup \
  --include-namespaces=prod-payment \
  --ttl=48h

# Restore:
velero restore create --from-backup pre-deploy-backup \
  --namespace-mappings prod-payment:prod-payment-restored

# Disaster Recovery: multi-region backup
# Backup in us-east-1 → restore in us-west-2:
# 1. Set up Velero in us-west-2 with same S3 bucket
# 2. Restore:
velero restore create --from-backup daily-backup-20240115 \
  --namespace-mappings prod:prod-dr

# Velero backup contents:
# backup-<name>/
# ├── resources/         # Kubernetes object YAMLs
# │   ├── pods/
# │   │   └── ...
# │   └── deployments/
# ├── volumes/           # PV snapshots (CSI or native)
# │   └── snapshot-xxxx/
# └── velero-backup.json # Backup metadata
```

**Database Backup Strategies on Kubernetes:**

```yaml
# Strategy 1: Velero CSI Snapshots (crash-consistent)
# Simple, fast, but NOT application-consistent for databases
# Restore: filesystem-level, might need WAL replay

# Strategy 2: Pre/Post Hooks (application-consistent backup)
# Velero hooks: quiesce database before snapshot, unquiesce after
apiVersion: velero.io/v1
kind: Backup
metadata:
  name: postgres-backup
spec:
  includedNamespaces:
  - prod-postgres
  hooks:
    resources:
    - name: postgres-hook
      includedNamespaces:
      - prod-postgres
      pre:
      - exec:
          container: postgres
          command:
          - pg_start_backup
          - velero-backup
          onError: Fail
      post:
      - exec:
          container: postgres
          command:
          - pg_stop_backup
          onError: Fail

# Strategy 3: Application-level backup (pg_dump / WAL archiving)
# For point-in-time recovery
apiVersion: batch/v1
kind: CronJob
metadata:
  name: postgres-backup
  namespace: prod-postgres
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: postgres:16
            command:
            - sh
            - -c
            - |
              pg_dump postgres://$(DB_USER):$(DB_PASS)@postgres:5432/mydb \
                | gzip \
                | aws s3 cp - s3://backups/postgres/$(date +%Y/%m/%d)/dump.sql.gz
            env:
            - name: DB_USER
              valueFrom:
                secretKeyRef:
                  name: postgres-credentials
                  key: username
            - name: DB_PASS
              valueFrom:
                secretKeyRef:
                  name: postgres-credentials
                  key: password

# Strategy 4: WAL archiving (continuous backup, point-in-time recovery)
# pg_wal_directory → S3 via pg_receivewal or WAL-G
apiVersion: apps/v1
kind: Sidecar
# Wal-G sidecar for continuous WAL archiving
```

**StatefulSet Disaster Recovery:**

```yaml
# Disaster recovery for StatefulSets (e.g., PostgreSQL, Kafka, Cassandra)

# Approach: Backup + Restore with proper data consistency

# Test restore regularly (most important step!):
# 1. Restore backup to a different namespace
# 2. Verify data integrity
# 3. Validate application connectivity

# Recovery Time Objective (RTO) strategies:
# 
# RTO < 1 minute: Active-Passive (cross-region replication)
#   - Primary cluster + standby cluster in different region
#   - Continuous replication
#   - Failover: switch DNS to standby
#   - Cost: 2× infrastructure
#
# RTO < 15 minutes: Velero + volume snapshots
#   - Automated nightly backups
#   - Volume snapshots (EBS snapshots)
#   - Restore time: 5-15 minutes for 1TB volume
#   - Data loss: up to 24 hours (or configure more frequent backups)
#
# RTO < 1 hour: Database native backup (pg_dump, mysqldump)
#   - Scheduled dump to S3
#   - Restore: download dump, restore to new instance
#   - No infrastructure dependency (works across regions/providers)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **CSI architecture** | Understands controller (create/delete) vs node (mount/unmount) plugins |
| **Volume snapshot** | Knows VolumeSnapshotClass → VolumeSnapshot → PVC restore flow |
| **Application-consistent backup** | Uses pre/post hooks (pg_start_backup/pg_stop_backup) for database snapshots |
| **Disaster recovery** | Can design RTO-based backup strategies: active-passive, snapshots, or dump/restore |

---

> *All 12 sections cover the full depth of Kubernetes production control — from GitOps and admission controllers to service mesh, multi-tenancy, CNI networking, storage, and disaster recovery — with production-ready configurations, policy patterns, and operational best practices.*
