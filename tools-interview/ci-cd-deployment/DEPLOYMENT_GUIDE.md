# CI/CD & Deployment — Complete Guide

> **How modern engineering teams ship code to production reliably, repeatably and safely: the pipeline, deployment strategies, per-platform packaging, supply-chain security and progressive delivery. Tool versions are current as of October 2026.**

---

## Table of Contents

1. [Core Concepts](#1-core-concepts)
2. [End-to-End Flow: Repository → Production](#2-end-to-end-flow-repository-production)
3. [Deployment Strategies](#3-deployment-strategies)
4. [Frontend Deployment](#4-frontend-deployment)
5. [Backend Deployment by Language](#5-backend-deployment-by-language)
6. [Mobile Deployment](#6-mobile-deployment)
7. [Monolith Architecture](#7-monolith-architecture)
8. [Microservices Architecture](#8-microservices-architecture)
9. [CI/CD Pipeline by Tool](#9-cicd-pipeline-by-tool)
10. [Production Best Practices](#10-production-best-practices)
11. [Interview Questions](#11-interview-questions)

---

## 1. Core Concepts

!!! tip "30-second answer"
    **CI** merges small changes to a shared trunk often, each verified by an automated build and test. **Continuous delivery** keeps every passing build releasable, with a human deciding when to release; **continuous deployment** removes that human and ships every passing change. The goal is small batches: they're easier to review, test, roll back and debug. You measure the system with the **DORA metrics**, and you make it safe with immutable artifacts, progressive rollout and fast rollback.

### Continuous Integration (CI)

Developers merge into a shared branch at least daily. Each merge triggers an automated build-and-test pipeline, so integration problems surface within minutes rather than at release time.

```
Code push → Lint/format → Unit tests → Build → Integration tests → Versioned artifact
```

### Continuous Delivery vs Continuous Deployment

| | Continuous Delivery | Continuous Deployment |
|---|---|---|
| Every passing change is... | Releasable | Released |
| Production deploy | Manual approval or scheduled | Automatic |
| Prerequisites | Good tests, automated deploy | Plus progressive rollout, automated analysis and rollback, feature flags |

### Pipeline-as-Code

Pipeline definitions live in the repository with the code (`.github/workflows/*.yml`, `.gitlab-ci.yml`, `Jenkinsfile`), so changes to the delivery process are reviewed, versioned and auditable like any other change.

### Measuring delivery: DORA metrics

| Metric | What it measures | Elite-ish target |
|---|---|---|
| Deployment frequency | How often you ship to production | On demand, many times a day |
| Lead time for changes | Commit → running in production | Less than a day |
| Change failure rate | Share of deployments causing a failure needing remediation | Low single digits to ~15% |
| Failed deployment recovery time | Time to restore after a bad deploy | Under an hour |

DORA's research also added **rework rate** (unplanned deployments to fix production issues) in 2024. Speed and stability correlate positively: teams that deploy more often also fail less, because each change is smaller.

---

## 2. End-to-End Flow: Repository → Production

This section traces a change from first commit to running in production, across project types and architectures.

---

### 2.1 The Complete Pipeline (Overview)

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Developer│───▶│   Git    │───▶│    CI    │───▶│ Build &  │───▶│  CD /    │───▶│Production│
│  commit  │    │  repo    │    │  (test)  │    │ package  │    │  deploy  │    │          │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
     │ push / PR      │ webhook       │ tests, lint    │ immutable      │ promote       │ serve,
     │                │               │ scans          │ artifact       │ through envs  │ observe
```

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/cicd-end-to-end-pipeline.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — CI/CD Pipeline — Code → Commit → CI (Test) → Build (Artifact) → CD (Promote) → Production (Serve). Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

| Stage | What Happens | Output |
|-------|-------------|--------|
| **1. Developer commit** | Write code, run pre-commit hooks (format, lint, secret scan) | Clean commit |
| **2. Git repo** | Push to GitHub/GitLab/Bitbucket; webhook triggers CI; branch protection requires checks and reviews | Commit SHA (e.g. `abc1234`) |
| **3. CI (test)** | Install deps → lint → unit tests → integration tests → security scans | Test report, coverage |
| **4. Build & package** | Build once → container image / bundle / app binary → push to registry → sign and attest | Immutable artifact identified by **digest** |
| **5. CD / deploy** | Promote **the same artifact** through environments (dev → staging → canary → prod) | Running application |
| **6. Production** | Serve traffic, watch SLOs, alert, roll back if needed | Live service |

**Build once, deploy many:** never rebuild per environment. The thing you tested in staging must be byte-for-byte the thing in production; only configuration differs.

---

### 2.2 Branch Strategy & Environment Mapping

Two common models:

```
Release branches / tags (GitFlow-like)
Branch                    Environment     Deploy trigger
──────────────────────────────────────────────────────────
feature/xxx               none            CI only
main                      dev / staging   auto on merge
release/v1.2              staging         manual approval
tag v1.2.0                production      tag triggers prod deploy
```

**Trunk-based development** (what the DORA research associates with high performance):

```
Developer                 main                  Production
─────────────────────────────────────────────────────────────
                    ┌──────────┐              ┌──────────┐
short-lived branch ─▶│  main    │──(auto)────▶│  Prod    │
  (PR, < 1-2 days)  │          │              │ (canary) │
                    └──────────┘              └──────────┘
                         │                        │
                Incomplete work hidden      Progressive rollout,
                behind feature flags        automated rollback
```

Long-lived branches create merge pain and big-bang releases; trunk-based development with feature flags keeps batches small.

---

### 2.3 Flow by Project Type

#### Frontend (React / Next.js / Vue)

```
Developer          GitHub              CI (GitHub Actions)                 CDN / hosting
─────────────────────────────────────────────────────────────────────────────────────────
   │-- git push ──▶  │                       │                                 │
   │                 │── webhook ──────────▶ │                                 │
   │                 │                       ├─ npm ci                         │
   │                 │                       ├─ lint, type-check, unit tests   │
   │                 │                       ├─ npm run build (dist/)          │
   │                 │                       ├─ upload hashed assets (long TTL)│
   │                 │                       ├─ upload index.html (no-cache)   │
   │                 │                       ├─ invalidate index.html ────────▶│
   │                 │                       │                                 ├─ users get new HTML,
   │                 │                       │                                 │  which references new assets
```

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/cicd-frontend-pipeline.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — Frontend Deployment — Developer → GitHub → CI → Build → S3/CloudFront CDN. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

**Tracing a commit:**

```
1. git commit -m "feat: add dark mode" && git push origin feat/dark-mode
2. PR #123 opened → CI runs lint + tests + build, and a preview deployment
3. Reviewer approves, PR merges to main
4. CI on main: tests again → production build → upload to S3 → invalidate index.html
5. Users loading the page get the new HTML and the new hashed bundles
```

Upload order matters: assets first, HTML last. Users with the old HTML still fetch old asset names, which must remain available for a while, so don't delete old hashed files on every deploy.

---

#### Backend (Node.js / Python / Go / Java / Rust)

```
Developer     GitHub          CI (GitHub Actions)                Registry           Kubernetes
──────────────────────────────────────────────────────────────────────────────────────────────
   │-- push ──▶ │                  │                                │                   │
   │            │── webhook ──────▶├─ install deps, lint, test      │                   │
   │            │                  ├─ docker build                  │                   │
   │            │                  ├─ push image ──────────────────▶│                   │
   │            │                  ├─ sign + attest (digest)        │                   │
   │            │                  ├─ update desired image ─────────┼─────────────────▶ │
   │            │                  │  (GitOps commit or kubectl)    │                   ├─ rolling / canary
   │            │                  │                                │                   ├─ readiness gates
   │            │                  │                                │                   ├─ serve traffic
```

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/cicd-backend-pipeline.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — Backend Deployment — Dockerized service pipeline from commit to Kubernetes. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

**Tracing a commit:**

```
1. PR merged to main
2. Job "test":   checkout → install → lint (ruff / golangci-lint / eslint) → unit + integration tests
3. Job "build":  needs test → build image → push ghcr.io/acme/myapp:abc1234 → record digest
                 → attest SLSA provenance for that digest
4. Job "deploy": needs build → set desired image to ghcr.io/acme/myapp@sha256:...
                 (commit to the GitOps repo for Argo CD/Flux, or kubectl for simple setups)
5. Kubernetes rolls out: new pods start → readiness probe passes → old pods drained
6. Pipeline (or Argo Rollouts) watches error rate and latency; rolls back on regression
```

---

#### Mobile (iOS / Android)

```
Developer     GitHub          CI (GitHub Actions / Bitrise / Xcode Cloud)      App Store / Play Store
─────────────────────────────────────────────────────────────────────────────────────────────────────
   │-- push ──▶ │                  │                                                │
   │            │── webhook ──────▶├─ install deps, lint, unit tests                │
   │            │                  ├─ build archive / app bundle                    │
   │            │                  ├─ sign (certs/keystore from secure storage)     │
   │            │                  ├─ upload ──────────────────────────────────────▶├─ internal testing
   │            │                  │                                                ├─ closed / open beta
   │            │                  │                                                ├─ store review
   │            │                  │                                                ├─ phased / staged rollout
```

Mobile can't roll back: once installed, an old binary lives on users' devices. Hence staged rollouts, server-driven feature flags, and APIs that support several app versions at once.

---

### 2.4 Monolith Flow

```
┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐
│  Dev   │──▶│  PR    │──▶│  CI    │──▶│ Build  │──▶│ Stage  │──▶│  Prod  │
│ commit │   │ review │   │  test  │   │ image  │   │ deploy │   │ deploy │
└────────┘   └────────┘   └────────┘   └────────┘   └────────┘   └────────┘
                                                        │            │
                                                 smoke/E2E tests  blue-green or canary
```

- One pipeline, one artifact; build and test time grow with the codebase (invest in caching and test selection).
- Rollback reverts everything, including unrelated teams' changes in the same release.
- Database migrations must be backward-compatible (expand-contract, [section 7](#7-monolith-architecture)).

---

### 2.5 Microservices Flow

Each service has its own pipeline and deploys independently:

```
Service A (Python FastAPI):  CI test → build image → push → deploy (K8s) → live
Service B (Go):              CI test → build image → push → deploy (K8s) → live
Service C (Java Spring):     CI test → build image → push → deploy (K8s) → live
```

**Coordinated change across services** (no lockstep deploys):

```
1. Service A adds the new endpoint/field additively (old and new both work) → deploy A
2. Service B starts using it, behind a flag if risky → deploy B
3. After all consumers moved, A removes the old endpoint in a later release
```

Contract tests (Pact) in each pipeline catch a provider change that would break a consumer before it ships.

---

### 2.6 Deployment Pipeline Visualization — Full Detail

```
GitHub repository                    GitHub Actions                       Kubernetes cluster
┌──────────────────────┐        ┌────────────────────────────┐       ┌──────────────────────────┐
│ main branch          │─push──▶│ Job 1: test                │       │ Namespace: prod          │
│  backend/  Dockerfile│        │  ├─ checkout, install      │       │  Service: myapp          │
│                      │        │  ├─ lint, unit tests       │       │  ┌────────────────────┐  │
│ PR #123 (merged)     │        │  └─ upload coverage        │       │  │ Pod (v2) ready     │  │
│  ✓ checks pass       │        │ Job 2: build               │       │  └────────────────────┘  │
│  ✓ 2 approvals       │        │  ├─ docker build + push    │       │  ┌────────────────────┐  │
│                      │        │  └─ attest provenance      │       │  │ Pod (v1) draining  │  │
│                      │        │ Job 3: deploy (env: prod)  │──────▶│  └────────────────────┘  │
│                      │        │  ├─ OIDC → cloud role      │       │  Ingress/Gateway ─▶ users│
│                      │        │  ├─ set image by digest    │       │                          │
│                      │        │  └─ rollout status         │       │                          │
└──────────────────────┘        └────────────────────────────┘       └──────────────────────────┘
```

---

### 2.7 Artifact Promotion Across Environments

```
Commit abc1234 → Build ghcr.io/acme/myapp@sha256:9f2c... (one artifact)
   │
   ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Dev        │────▶│  Staging    │────▶│  Canary     │────▶│  Production │
│ auto-deploy │     │ auto-deploy │     │ 5-10% of    │     │ 100%        │
│ on merge    │     │ smoke + E2E │     │ traffic     │     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
      │                    │                    │                    │
  unit/integration     E2E, performance    automated analysis:   SLO burn-rate
  tests                tests               error rate, latency   alerts
```

Promotion means changing *which digest an environment runs* (a Git commit in a GitOps repo, or a deploy job input), never rebuilding.

---

### 2.8 Key Takeaway

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/cicd-artifact-promotion.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — Artifact Promotion — Dev → Staging → Canary → Production with validation gates. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

> **Code → Commit → CI (Test) → Build (Artifact) → CD (Promote) → Production (Serve)**

Only the tools and artifacts differ:

- Frontend: `npm run build` → `dist/` → object storage + CDN
- Backend: `docker build` → image digest → Kubernetes / ECS / Cloud Run
- Mobile: `xcodebuild` / Gradle → `.ipa` / `.aab` → TestFlight / Play tracks → store

---

## 3. Deployment Strategies

!!! tip "30-second answer"
    **Rolling** replaces instances gradually; cheap, the default in Kubernetes, but old and new versions serve together and rollback is another rollout. **Blue-green** runs a full second environment and flips traffic; instant rollback but double capacity during the switch. **Canary** sends a small, growing share of real traffic to the new version and promotes or aborts based on metrics; the best risk/cost balance and the basis of **progressive delivery** (Argo Rollouts, Flagger). **Feature flags** decouple deploy from release. Every strategy except recreate requires that two versions can run at once, which constrains your database and API changes.

| Strategy | Mechanism | Zero downtime | Rollback | Main cost / risk |
|----------|-----------|:---:|:---:|---|
| **Rolling update** | Replace instances in batches (`maxSurge`/`maxUnavailable`) | ✅ | Minutes (roll back = roll forward to old version) | Mixed versions during rollout; bad version reaches everyone eventually |
| **Blue-green** | Two full environments, switch the router | ✅ | Seconds (flip back) | 2× capacity during switch; shared DB must suit both |
| **Canary** | Small % of traffic to new version, increase on healthy metrics | ✅ | Seconds (route back to stable) | Needs traffic splitting and good metrics; low-traffic services give weak signal |
| **Shadow / mirroring** | Copy live requests to new version, discard its responses | ✅ | Not applicable (no user impact) | **Side effects:** mirrored writes, emails, payments must be stubbed; doubles load |
| **Recreate** | Stop all old, start all new | ❌ | Redeploy | Downtime; only when versions can't coexist |
| **Feature flag** | Deploy code dark, enable per user/segment | ✅ | Instant (flag off) | Flag debt; combinatorial testing; flag service is a dependency |

### Blue-Green Deployment

```
       ┌─────────────┐     ┌─────────────┐
Users ─▶│ Load        │────▶│   Blue      │ (v1 — live)
       │ balancer    │     └─────────────┘
       └─────────────┘     ┌─────────────┐
                           │   Green     │ (v2 — deployed, smoke-tested, idle)
                           └─────────────┘

Switch:   point the LB/DNS/Service selector at Green
Rollback: point it back at Blue (keep Blue running until confident)
```

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/cicd-blue-green-deployment.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — Blue-Green Deployment — Two identical environments with instant switch and rollback. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

Pitfalls: DNS-based switches are slow and uneven because of client caching; long-lived connections (WebSockets, gRPC streams) stay on Blue until they reconnect; and the database is shared, so the switch doesn't roll back schema changes.

### Canary Release

```
Users ─▶ Router ──── 95% ──▶ stable (v1)
                └──── 5% ──▶ canary (v2)

Each step: hold, compare canary vs stable (error rate, p99 latency, saturation, business KPIs).
Healthy → 25% → 50% → 100%.  Degraded → route 100% back to stable automatically.
```

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/cicd-canary-release.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — Canary Release — Progressive traffic shift with metric-based gates. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

**Progressive delivery** automates this loop. With **Argo Rollouts**, a `Rollout` replaces the `Deployment` and an `AnalysisTemplate` defines the metric gate:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: checkout
spec:
  replicas: 10
  selector:
    matchLabels:
      app: checkout
  template:
    metadata:
      labels:
        app: checkout
    spec:
      containers:
        - name: checkout
          image: ghcr.io/acme/checkout:1.4.2
          ports:
            - containerPort: 8080
  strategy:
    canary:
      stableService: checkout-stable
      canaryService: checkout-canary
      trafficRouting:
        istio:
          virtualService:
            name: checkout
            routes:
              - primary
      analysis:                    # background analysis from step 1 onwards
        templates:
          - templateName: success-rate
        startingStep: 1
        args:
          - name: service
            value: checkout-canary
      steps:
        - setWeight: 5
        - pause: { duration: 10m }
        - setWeight: 25
        - pause: { duration: 10m }
        - setWeight: 50
        - pause: { duration: 10m }
---
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: success-rate
spec:
  args:
    - name: service
  metrics:
    - name: success-rate
      interval: 1m
      failureLimit: 2              # abort and roll back after 2 failed measurements
      successCondition: result[0] >= 0.99
      provider:
        prometheus:
          address: http://prometheus.monitoring:9090
          query: |
            sum(rate(http_requests_total{service="{{args.service}}", status!~"5.."}[2m]))
            /
            sum(rate(http_requests_total{service="{{args.service}}"}[2m]))
```

**Flagger** does the same with an operator that watches ordinary Deployments and drives Istio, Linkerd, Gateway API, NGINX or App Mesh-style routing. Pick one; both integrate with Argo CD/Flux.

Canary pitfalls: low-traffic services don't produce statistically meaningful error rates in 10 minutes (use longer steps or synthetic traffic); sticky sessions and caches skew comparisons; and a canary that writes incompatible data has already done damage before it's rolled back.

### Feature Flags (Feature Toggles)

```javascript
// Deployed dark; released by changing the flag, not by deploying
const enabled = await flags.getBooleanValue('new-checkout-flow', false, { targetingKey: user.id });
if (enabled) {
  renderNewCheckout();
} else {
  renderOldCheckout();
}
```

- **Release flags** (temporary; delete after rollout), **ops/kill switches** (long-lived), **experiment flags** (A/B), **permission flags** (entitlements). Treat release flags as debt with an expiry date.
- Evaluate flags locally from a cached ruleset so a flag-service outage doesn't take you down, and define safe defaults.
- **Tools:** LaunchDarkly, Harness FME (formerly Split), Flagsmith, Unleash, GrowthBook, cloud-native options (AWS AppConfig). **OpenFeature** (CNCF) is the vendor-neutral SDK API in front of any of them, as in the snippet above.

---

## 4. Frontend Deployment

### React / Next.js / Vue / Angular

**Typical pipeline:**

```
1. Install          npm ci                      (exact lockfile install)
2. Lint & types     npm run lint && tsc --noEmit
3. Unit tests       npm test -- --coverage
4. Build            npm run build               (dist/ or .next/)
5. E2E              npx playwright test         (against a preview deployment)
6. Upload assets    content-hashed files, Cache-Control: max-age=31536000, immutable
7. Upload HTML      index.html with Cache-Control: no-cache
8. Invalidate       CDN invalidation for HTML paths only
```

| Concern | Solution |
|----------|----------|
| **Cache busting** | Content-hashed filenames (`app.a1b2c3.js`), immutable caching; HTML never long-cached |
| **CDN** | CloudFront, Cloudflare, Fastly, Akamai |
| **SSR (Next.js, Nuxt)** | It's a server: deploy as a container or to a platform (Vercel, Netlify, AWS Amplify, Cloudflare); needs the same rollout care as a backend |
| **Environment config** | Build once; inject runtime config (`/config.json` or server-rendered values) rather than baking per-env builds |
| **Preview deployments** | Per-PR environments (Vercel/Netlify or your own) for review and E2E |
| **SPA routing** | Fall back to `index.html` for unknown paths (CDN custom error response or edge function) |
| **Rollback** | Re-point to the previous build's HTML; keep old hashed assets |

**Example GitHub Actions workflow (static SPA to S3 + CloudFront):**

```yaml
name: frontend
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with:
          node-version: 24
          cache: npm
      - run: npm ci
      - run: npm run lint
      - run: npm test -- --coverage
      - run: npm run build
      - uses: actions/upload-artifact@v7
        with:
          name: dist
          path: dist/

  deploy:
    if: github.event_name == 'push'      # never deploy from pull requests
    needs: build
    runs-on: ubuntu-latest
    environment: production
    permissions:
      contents: read
      id-token: write                    # OIDC: no stored AWS keys
    steps:
      - uses: actions/download-artifact@v8
        with:
          name: dist
          path: dist/
      - uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: ${{ vars.DEPLOY_ROLE_ARN }}
          aws-region: us-east-1
      - name: Upload hashed assets (long cache)
        run: >
          aws s3 sync dist/ "s3://${{ vars.S3_BUCKET }}/"
          --exclude "index.html"
          --cache-control "public,max-age=31536000,immutable"
      - name: Upload HTML last (no cache)
        run: >
          aws s3 cp dist/index.html "s3://${{ vars.S3_BUCKET }}/index.html"
          --cache-control "no-cache"
      - name: Invalidate HTML
        run: >
          aws cloudfront create-invalidation
          --distribution-id "${{ vars.CF_DISTRIBUTION_ID }}"
          --paths "/index.html" "/"
```

---

## 5. Backend Deployment by Language

Common rules for every Dockerfile below: multi-stage builds, pinned base images (by digest in production), dependencies copied before source for layer caching, run as a **non-root** user, and nothing from the build toolchain in the runtime image.

### 5.1 Node.js / TypeScript

```dockerfile
FROM node:24-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev                 # production dependencies only

FROM node:24-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci                            # dev deps needed to compile
COPY . .
RUN npm run build

FROM node:24-slim
ENV NODE_ENV=production
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY package.json ./
USER node
EXPOSE 3000
CMD ["node", "dist/main.js"]
```

**Pipeline:** `npm ci → lint → test (Vitest/Jest) → build (tsc) → docker build → push → deploy`

- Node.js 20 reached end of life in April 2026; use an active LTS (22 or 24).
- `CMD ["node", ...]` (exec form) makes Node PID 1 so it receives SIGTERM; handle it to drain connections.
- Express/Fastify/NestJS all follow the same pattern. Serverless targets (AWS Lambda, Vercel Functions) deploy bundles instead of images.

### 5.2 Python (FastAPI / Django / Flask)

```dockerfile
FROM python:3.14-slim AS build
WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN pip install --no-cache-dir --no-deps .

FROM python:3.14-slim
RUN useradd --create-home --uid 10001 app
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
CMD ["uvicorn", "myapp.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Copying a **virtualenv** carries both packages and their console scripts (`uvicorn`, `gunicorn`); copying only `site-packages` from the system interpreter leaves the entry-point scripts behind and the container fails to start. `uv` (`uv sync --frozen`) is a much faster drop-in for the install steps.

**Pipeline:** `install (uv/pip) → lint (ruff) → type-check (mypy/pyright) → test (pytest) → build wheel → docker build → push → deploy`

- **FastAPI:** Uvicorn workers (or Gunicorn with Uvicorn workers); scale with replicas rather than many workers per pod.
- **Django:** run `python manage.py migrate` as a separate, single-run step before the new pods take traffic (a Kubernetes Job, Helm pre-upgrade hook, or Argo CD PreSync hook), never in every container's entrypoint, where replicas race. `collectstatic` belongs in the image build.
- **Flask:** Gunicorn behind a reverse proxy.

```yaml
# Pre-deploy step in a pipeline (runs once, before traffic shifts)
- name: Run migrations
  run: python manage.py migrate --noinput
```

### 5.3 Go

```dockerfile
FROM golang:1.26 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/server ./cmd/server

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/server /server
EXPOSE 8080
USER nonroot:nonroot
ENTRYPOINT ["/server"]
```

**Pipeline:** `go mod download → lint (golangci-lint) → go vet → go test -race → build → docker build → push → deploy`

- Static binary: no runtime needed, so `distroless/static` or `scratch` images are a few MB. Distroless includes CA certificates and timezone data; `scratch` doesn't.
- Cross-compilation is built in: `GOOS=linux GOARCH=arm64 go build`. Use `docker buildx` for multi-arch images (amd64 + arm64 for Graviton/Ampere nodes).

### 5.4 Java / Spring Boot

```dockerfile
FROM maven:3.9-eclipse-temurin-25 AS build
WORKDIR /app
COPY pom.xml .
RUN mvn -B dependency:go-offline
COPY src ./src
RUN mvn -B package -DskipTests       # tests ran in an earlier CI job

FROM eclipse-temurin:25-jre
RUN useradd --uid 10001 app
WORKDIR /app
COPY --from=build /app/target/*.jar app.jar
USER app
EXPOSE 8080
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "app.jar"]
```

**Pipeline:** `mvn verify (compile + unit + integration tests) → package → docker build → push → deploy`

- **Memory:** the JVM is container-aware; size the heap as a percentage of the container limit (`MaxRAMPercentage`) instead of hard-coding `-Xmx` per environment.
- **Startup time** affects rollout speed and autoscaling: Spring Boot layered jars or Jib for better caching, CDS/AOT cache (Project Leyden features in JDK 24+), or GraalVM Native Image for fast-start services.
- **Health:** Spring Boot Actuator exposes liveness and readiness groups (`/actuator/health/liveness`, `/actuator/health/readiness`); wire them to Kubernetes probes, and enable graceful shutdown (`server.shutdown=graceful`).
- Java 25 is the current LTS (September 2025); 21 is the previous one.

### 5.5 Rust

```dockerfile
FROM rust:1 AS build
WORKDIR /app
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main() {}" > src/main.rs \
    && cargo build --release        # caches compiled dependencies in this layer
COPY src ./src
RUN touch src/main.rs && cargo build --release

FROM debian:trixie-slim
RUN useradd --uid 10001 app
COPY --from=build /app/target/release/myapp /usr/local/bin/myapp
USER app
EXPOSE 8080
CMD ["myapp"]
```

The runtime image must have a glibc at least as new as the build image's; the `rust:1` image tracks current Debian, so pair it with the same Debian release (or build a static musl binary for `scratch`/distroless). `cargo-chef` is a more robust way to cache dependency builds than the dummy-`main.rs` trick.

---

## 6. Mobile Deployment

### iOS (Swift / SwiftUI / UIKit)

```
1. Dependencies       Swift Package Manager resolve (or CocoaPods for legacy projects)
2. Lint               SwiftLint
3. Unit tests         xcodebuild test -scheme App -destination 'platform=iOS Simulator,name=iPhone 16'
4. UI tests           xcodebuild test -scheme AppUITests -destination ...
5. Archive            xcodebuild archive -scheme App -archivePath build/App.xcarchive
6. Export IPA         xcodebuild -exportArchive -exportOptionsPlist ExportOptions.plist
7. Upload             fastlane pilot / App Store Connect API (or Xcode Cloud end to end)
8. TestFlight         internal, then external testers
9. Release            submit for review → phased release
```

- **Code signing:** certificates and provisioning profiles from a secure store (fastlane `match`, or Xcode Cloud's managed signing); authenticate to App Store Connect with an **API key**, not an Apple ID password.
- **Phased release** spreads automatic updates over 7 days and can be paused; users can still update manually.
- **Runners:** macOS runners (GitHub-hosted, Xcode Cloud, Bitrise, or self-hosted Macs).

```ruby
lane :beta do
  app_store_connect_api_key(
    key_id: ENV["ASC_KEY_ID"],
    issuer_id: ENV["ASC_ISSUER_ID"],
    key_content: ENV["ASC_KEY_CONTENT"]
  )
  match(type: "appstore", readonly: true)
  build_app(scheme: "App")
  upload_to_testflight(skip_waiting_for_build_processing: true)
end
```

### Android (Kotlin / Jetpack Compose)

```
1. Lint                  ./gradlew lint
2. Unit tests            ./gradlew testReleaseUnitTest
3. Build bundle          ./gradlew bundleRelease          (.aab, R8 minification on)
4. Sign                  upload key from CI secrets; Play App Signing holds the app signing key
5. Upload                Gradle Play Publisher (publishReleaseBundle) or fastlane supply
6. Tracks                internal → closed → open → production
7. Staged rollout        e.g. 1% → 5% → 20% → 50% → 100%, halt on crash-rate regressions
```

- **Android App Bundles (.aab)** are required for new apps on Google Play; Play generates optimised APKs per device.
- Watch Android vitals (crash and ANR rates) between rollout steps; a staged rollout can be halted but not "undone" for users who already updated, so the fix is a new, higher version code.

---

## 7. Monolith Architecture

### Characteristics

- Single deployable unit (one binary or image), usually one shared database
- Modules coupled in-process; refactoring is easy, independent release isn't

### CI/CD Strategy

```
Pipeline
├── Pre-commit hooks (format, lint, secret scan)
├── CI on every PR
│   ├── lint + type-check
│   ├── unit tests (parallelised, sharded)
│   ├── build image
│   └── integration tests (Testcontainers)
├── Staging (on merge to main)
│   ├── deploy
│   └── smoke + E2E tests
└── Production (on release, or continuously)
    ├── blue-green or canary
    ├── health checks and automated analysis
    └── monitoring and alerts
```

### Database Migrations

!!! tip "30-second answer"
    During any non-recreate rollout, old and new code run against the same database, so every schema change must work with **both**. Use **expand → migrate → contract** across separate releases, run migrations once as their own step (not in every pod), make them online (no long table locks), and remember that you can roll back code but rarely data, so prefer rolling forward.

**Expand-contract example: renaming `users.name` to `users.full_name`:**

```sql
-- Release 1 (expand): add the new column; app writes BOTH columns, reads old
ALTER TABLE users ADD COLUMN full_name TEXT;

-- Background job (migrate): backfill in small batches to avoid long locks
UPDATE users SET full_name = name
WHERE id IN (
  SELECT id FROM users WHERE full_name IS NULL LIMIT 10000
);
-- repeat until no rows remain

-- Release 2: app reads full_name, still writes both (safe to roll back to release 1)

-- Release 3 (contract): app stops writing name; then drop it
ALTER TABLE users DROP COLUMN name;
```

Operational details: in PostgreSQL, create indexes with `CREATE INDEX CONCURRENTLY`, add `NOT NULL` via a `CHECK ... NOT VALID` constraint validated later, and set a short `lock_timeout` so a migration waiting on a lock doesn't queue all traffic behind it. Tools like gh-ost/pt-online-schema-change (MySQL) or pgroll (PostgreSQL) automate online changes.

### Production Concerns

- **Build and test time:** remote build caching (Gradle/Bazel), test sharding, and running only tests affected by the change.
- **Release coordination:** many teams in one artifact → release trains or, better, trunk-based with flags.
- **Rollback scope:** one rollback reverts everyone's changes; feature flags let you disable one feature instead.
- **Scaling:** scale the whole app horizontally behind a load balancer; heavy modules can't scale independently.

---

## 8. Microservices Architecture

### Characteristics

- Independently deployable services, each owning its data
- Communicate via APIs (REST/gRPC) and events (Kafka, SNS/SQS)
- Polyglot where justified; a shared platform (golden paths) keeps 50 pipelines from becoming 50 snowflakes

### CI/CD Strategy

```
Per-service pipeline (independent)
├── CI: lint → test → contract tests (Pact) → build image → sign/attest → push
└── CD:
    ├── preview environment per PR (namespace or vcluster)
    ├── staging via GitOps (Argo CD / Flux)
    └── production via GitOps + progressive delivery (Argo Rollouts / Flagger)

Shared platform pipelines
├── Infrastructure as code (Terraform/OpenTofu, Pulumi, Crossplane)
├── Cluster add-ons and policies (Kyverno/Gatekeeper)
├── Service mesh / Gateway API config
└── Monitoring and alerting rules
```

Reusable pipeline templates (GitHub reusable workflows, GitLab CI components) give every service the same security scanning, provenance and deployment steps; teams supply parameters, not pipelines.

### GitOps with Argo CD

```
            ┌──────────────────────┐
  CI ──────▶│ Git: env manifests   │  (CI commits new image digest, or Argo CD Image Updater does)
            │ (Helm/Kustomize)     │
            └──────────┬───────────┘
                       │ pull, diff, sync
                       ▼
            ┌──────────────────────┐
            │ Argo CD (in cluster) │  detects and reverts drift (self-heal)
            └──────────┬───────────┘
                       │ apply
                       ▼
            ┌──────────────────────┐
            │ Kubernetes cluster   │
            └──────────────────────┘
```

Why GitOps: the cluster pulls desired state, so CI needs no cluster credentials; Git history is the deployment audit log; rollback is `git revert`; drift is visible and corrected. Trade-offs: secrets need a separate solution (External Secrets Operator, Sealed Secrets, SOPS), and "deploy succeeded" now means "Argo CD synced and the app is healthy", which pipelines must wait for if they run post-deploy tests.

### Service Mesh (Istio) for Deployments

```yaml
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata:
  name: user-service
spec:
  host: user-service
  subsets:
    - name: v1
      labels:
        version: v1
    - name: v2
      labels:
        version: v2
---
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata:
  name: user-service
spec:
  hosts:
    - user-service
  http:
    - name: canary-header         # testers opt in with a header
      match:
        - headers:
            x-canary:
              exact: "true"
      route:
        - destination:
            host: user-service
            subset: v2
    - name: primary               # everyone else: weighted split
      route:
        - destination:
            host: user-service
            subset: v1
          weight: 90
        - destination:
            host: user-service
            subset: v2
          weight: 10
```

Hand-editing weights is how you start; in production let Argo Rollouts or Flagger own them. The Kubernetes **Gateway API** `HTTPRoute` supports the same weighted `backendRefs` and header matches without mesh-specific CRDs, and is the direction most ingress and mesh projects are converging on.

### Inter-Service Testing

| Test Type | Tool | Purpose |
|-----------|------|---------|
| **Contract tests** | Pact, Spring Cloud Contract | Consumer expectations verified against the provider in the provider's pipeline |
| **Integration tests** | Testcontainers | Real databases and brokers in CI |
| **E2E tests** | Playwright, Cypress | A few critical user journeys; expensive and flaky at scale |
| **Chaos engineering** | Chaos Mesh, LitmusChaos, AWS FIS | Verify resilience under failure |

### Production Deployment Steps

```
1. Build service A (new version), unit + integration tests
2. Contract tests: A's provider verification against all consumers' pacts ("can-i-deploy")
3. Deploy A to staging via GitOps; smoke + E2E tests
4. Production: canary 5% with automated analysis (error rate, p99, saturation vs stable)
5. Promote 25% → 50% → 100% if healthy; automatic abort and rollback if not
6. Post-deploy: SLO burn-rate alerts watch the full rollout
```

---

## 9. CI/CD Pipeline by Tool

### GitHub Actions

```yaml
name: ci-cd

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:18
        env:
          POSTGRES_DB: test
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.14"
          cache: pip
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: ruff check .
      - run: mypy .
      - run: pytest --cov --cov-report=xml
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/test
      - uses: codecov/codecov-action@v7

  build:
    needs: test
    if: github.event_name == 'push'
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
      id-token: write          # sign the attestation with the workflow's OIDC identity
      attestations: write
      artifact-metadata: write
    outputs:
      digest: ${{ steps.push.outputs.digest }}
    steps:
      - uses: actions/checkout@v7
      - uses: docker/setup-buildx-action@v4
      - uses: docker/login-action@v4
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: push
        uses: docker/build-push-action@v7
        with:
          context: .
          push: true
          tags: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
      - uses: actions/attest@v4          # SLSA build provenance for the image digest
        with:
          subject-name: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          subject-digest: ${{ steps.push.outputs.digest }}
          push-to-registry: true

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment: production              # required reviewers / wait timer live here
    permissions:
      contents: read
      id-token: write                    # OIDC → AWS role, no stored keys
    steps:
      - uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: ${{ vars.EKS_DEPLOY_ROLE_ARN }}
          aws-region: us-east-1
      - uses: azure/setup-kubectl@v5
      - run: aws eks update-kubeconfig --name prod-cluster --region us-east-1
      - name: Deploy by digest and wait
        run: |
          kubectl -n prod set image deployment/myapp \
            myapp=${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}@${{ needs.build.outputs.digest }}
          kubectl -n prod rollout status deployment/myapp --timeout=10m
```

Notes on what makes this production-grade:

- **Least-privilege `GITHUB_TOKEN`**: read-only by default, write scopes granted per job.
- **OIDC to the cloud** (`id-token: write` + `configure-aws-credentials`): the AWS role's trust policy should pin `sub` to `repo:<org>/<repo>:environment:production`, so only this repo's production environment can deploy.
- **Deploy by digest**, not a mutable tag, so what was tested is what runs.
- **Provenance:** `actions/attest` produces a signed SLSA build provenance attestation for the image digest (verifiable with `gh attestation verify`). This meets **SLSA Build Level 2**; building in a reusable workflow that the calling repo can't tamper with gets you to **Level 3**.
- **Pin third-party actions to full commit SHAs** (Dependabot/Renovate keep them updated). The March 2025 `tj-actions/changed-files` compromise retagged versions to leak secrets from thousands of repositories; SHA pins were unaffected. GitHub's allowed-actions policy can now enforce SHA pinning organisation-wide.
- For GitOps, replace the deploy job with a step that commits the new digest to the environment repo, and let Argo CD/Flux apply it.

### GitLab CI

```yaml
stages: [test, build, deploy]

variables:
  IMAGE: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA

test:
  stage: test
  image: python:3.14-slim
  script:
    - pip install -r requirements.txt -r requirements-dev.txt
    - pytest --cov --cov-report=term --cov-report=xml:coverage.xml
  coverage: '/TOTAL.*? (100(?:\.0+)?\%|[1-9]?\d(?:\.\d+)?\%)$/'
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml

build:
  stage: build
  image: docker:29
  services:
    - docker:29-dind
  script:
    - echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
    - docker build -t "$IMAGE" .
    - docker push "$IMAGE"
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy:
  stage: deploy
  image:
    name: bitnami/kubectl:latest
    entrypoint: [""]
  script:
    - kubectl set image deployment/myapp myapp="$IMAGE"
    - kubectl rollout status deployment/myapp --timeout=10m
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual            # continuous delivery: a human presses deploy
```

`only:`/`except:` are legacy; use `rules:`. The cluster connection comes from the GitLab agent for Kubernetes (`KUBECONFIG` context) rather than stored credentials; GitLab also issues OIDC ID tokens (`id_tokens:`) for cloud federation. Reusable **CI/CD components** (catalog) play the role of GitHub reusable workflows. Docker-in-Docker needs privileged runners; Kaniko is no longer maintained, so rootless BuildKit or Buildah are the usual alternatives.

### Jenkins Pipeline (Declarative)

```groovy
pipeline {
    agent { label 'docker' }
    environment {
        IMAGE = "registry.example.com/myapp:${env.GIT_COMMIT}"
    }
    stages {
        stage('Test') {
            steps {
                sh 'npm ci'
                sh 'npm test'
            }
        }
        stage('Build & Push') {
            steps {
                withCredentials([usernamePassword(credentialsId: 'registry',
                                  usernameVariable: 'REG_USER', passwordVariable: 'REG_PASS')]) {
                    sh 'echo "$REG_PASS" | docker login -u "$REG_USER" --password-stdin registry.example.com'
                    sh 'docker build -t "$IMAGE" . && docker push "$IMAGE"'
                }
            }
        }
        stage('Deploy') {
            when { branch 'main' }
            steps {
                input message: 'Deploy to production?'
                sh 'kubectl set image deployment/myapp myapp="$IMAGE"'
                sh 'kubectl rollout status deployment/myapp --timeout=10m'
            }
        }
    }
    post {
        failure {
            slackSend(color: 'danger', message: "Build failed: ${env.JOB_NAME} #${env.BUILD_NUMBER}")
        }
    }
}
```

Jenkins remains common in enterprises; its costs are plugin maintenance, controller security and the lack of ephemeral, isolated runners by default (use Kubernetes agents).

---

## 10. Production Best Practices

### Security and the software supply chain

!!! tip "30-second answer"
    Assume the build system is a target. Use **short-lived OIDC credentials** instead of stored secrets, **pin dependencies and actions** (lockfiles, SHAs), build in **ephemeral isolated runners**, produce an **SBOM** and **signed provenance** (SLSA) for every artifact, and **verify signatures and provenance at deploy time** (admission control), so only artifacts built by your pipeline from your repo can run.

| Practice | Description |
|----------|-------------|
| **Secrets** | OIDC federation to cloud providers; secret scanning (gitleaks, TruffleHog, GitHub push protection) |
| **Dependency scanning** | Dependabot/Renovate updates; SCA (Snyk, Trivy, Grype, OSV-Scanner) |
| **Image scanning** | Trivy/Grype on build and continuously in the registry; fail on fixable criticals |
| **Minimal images** | Distroless, Chainguard/Wolfi, `scratch`, or slim bases; non-root; read-only root filesystem |
| **SBOM** | CycloneDX or SPDX per artifact (Syft, `docker buildx --sbom`), stored as an attestation |
| **Provenance (SLSA)** | Signed statement of what source, builder and steps produced the artifact; GitHub artifact attestations or the SLSA GitHub generator; target Build L3 for critical services |
| **Signing** | Sigstore cosign keyless signing (identity from the CI OIDC token, recorded in the Rekor transparency log) |
| **Verify at deploy** | Kyverno `verifyImages`, Sigstore policy-controller or Ratify reject unsigned images or images without provenance from your builder |
| **Workflow hardening** | Least-privilege tokens, no `pull_request_target` with untrusted checkout, protected environments, CODEOWNERS on pipeline files |

### Observability-driven deploy gates

```
Automated analysis during rollout (canary vs stable, not absolute thresholds alone):
  ├── error ratio not worse than stable by > X%
  ├── p99 latency not worse than stable by > Y ms
  ├── saturation (CPU throttling, memory, pool usage) within limits
  ├── business KPIs (checkout success, sign-ups) not regressing
  └── no SLO burn-rate alert firing
```

Compare canary with stable at the same time rather than with fixed thresholds: it cancels out daily traffic patterns and incidents unrelated to the deploy. Annotate dashboards with every deploy so humans can correlate too.

### Rollback Playbook

```
1. Detect:   automated analysis or burn-rate alert fires
2. Decide:   automation aborts canaries; humans decide for full rollouts (bias towards rollback)
3. Roll back:
     Canary / Argo Rollouts:  abort → traffic returns to stable
     Blue-green:              switch the router back to blue
     Rolling (Kubernetes):    kubectl rollout undo deployment/myapp, or git revert in GitOps
     Feature flag:            turn the flag off
4. Verify:   metrics return to baseline
5. Learn:    blameless review → fix forward → add the missing test, alert or analysis metric
```

Rollback doesn't undo data. If the bad version wrote data in a new format or ran a destructive migration, you're rolling forward with a fix, which is why expand-contract and backward-compatible writes matter.

### Environment Parity

| Aspect | Staging | Production |
|--------|---------|------------|
| **Artifact** | Same image digest | Same image digest |
| **Database** | Same engine and version, smaller instance | Sized for load |
| **Config** | Same structure, different values | Production values |
| **Infrastructure** | Same IaC modules, smaller scale | Full scale, multi-AZ |
| **Data** | Synthetic or anonymised subset | Real data |

Staging never fully matches production (traffic shape, data volume, noisy neighbours), which is why production canaries and feature flags exist.

---

## 11. Interview Questions

### Beginner

1. **Explain the difference between CI and CD.**
2. **What is a deployment strategy? Name three types.**
3. **How does blue-green deployment work?**
4. **What is the purpose of a build artifact?**

### Intermediate

5. **Compare rolling update vs. blue-green deployment. When would you use each?**
6. **How do you handle database migrations in a CI/CD pipeline?**
7. **What is GitOps and how does ArgoCD implement it?**
8. **How would you set up a canary release for a microservice?**
9. **Explain the expand-contract pattern for zero-downtime migrations.**

### Senior / Staff

Each comes with an answer sketch: the points an interviewer expects to hear.

10. **Design a CI/CD pipeline for a 50-microservice system with polyglot services (Go, Python, Java). How do you handle cross-service contract testing?**
    Shared reusable pipeline templates per language (lint, test, build, scan, SBOM, provenance, deploy) so each service only declares parameters; build once and promote by digest via GitOps; consumer-driven contracts (Pact) published to a broker, with the provider pipeline verifying all consumer pacts and a `can-i-deploy` gate before production. Avoid a shared E2E environment as the main gate: it becomes the bottleneck and the flakiest part of the system.

11. **How do you ensure backward compatibility during a multi-service rollout?**
    Additive API changes only (new optional fields, new endpoints), tolerant readers, versioned APIs or schemas for breaking changes (with schema registry compatibility rules for events), expand-contract for data, deploy providers before consumers, and feature flags so the consumer side can be turned off independently of deploys.

12. **Design a deployment system that can handle 1,000+ deployments per day across 200 services.**
    Self-service golden paths; fully automated pipelines with no human gates for low-risk changes; progressive delivery with automated analysis as the safety net instead of approvals; GitOps controllers sharded per cluster; deploy queues or merge queues to serialise per service; strong observability (deploy markers, per-version metrics); and DORA metrics to show change failure rate stays flat as frequency rises.

13. **How do you implement progressive delivery with feature flags and canary releases in a service mesh?**
    Argo Rollouts or Flagger owns the mesh or Gateway API traffic weights and runs metric analysis against Prometheus at each step, aborting automatically. Feature flags then release functionality to user segments independently of the binary rollout. Discuss metric choice, minimum traffic for significance, header-based routing for internal testers, and session affinity.

14. **How would you migrate a monolith to microservices incrementally using CI/CD?**
    Strangler fig: route specific paths to new services at the edge (gateway/mesh), extract by domain boundary, use change data capture or events to sync data during transition, keep the monolith's pipeline healthy (it still ships most changes), and give each extracted service its own pipeline from day one. Measure lead time and change failure rate to show the migration is helping.

15. **How do you handle the "diamond dependency" problem in microservice deployments?**
    When two services depend on different versions of a shared library or a shared downstream contract: keep shared libraries thin and backward-compatible, version them with semver and automate upgrades (Renovate), avoid lockstep releases, and for shared runtime contracts use compatibility rules plus contract tests so each consumer can upgrade on its own schedule.

---

> **Key Takeaway:** CI/CD is a safety system as much as an automation system: build once, prove it, promote the same artifact, roll out progressively with automated analysis, and keep rollback (or roll-forward) cheap. Supply-chain controls (OIDC, pinning, SBOM, signed provenance verified at deploy) are now baseline expectations at senior and staff level.
