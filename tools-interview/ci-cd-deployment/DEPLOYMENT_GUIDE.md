# CI/CD & Deployment — Complete Guide

> **How modern engineering teams ship code to production reliably, repeatably, and safely across different architectures and platforms.**

---

## Table of Contents

1. [Core Concepts](#1-core-concepts)
2. [End-to-End Flow: Repository → Production](#2-end-to-end-flow-repository--production)
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

### Continuous Integration (CI)

Developers merge code into a shared repository multiple times a day. Each merge triggers an automated build-and-test pipeline to catch integration issues early.

**CI Pipeline Stages:**
```
Code Push → Lint → Unit Tests → Build → Integration Tests → Artifact
```

### Continuous Delivery (CDel)

Every change that passes CI is automatically prepared for release. Deployment to production requires a manual approval gate.

### Continuous Deployment (CDep)

Every change that passes all automated tests is automatically deployed to production with no human intervention.

### Pipeline-as-Code

Pipeline definitions are checked into version control alongside application code, ensuring reproducibility, auditability, and versioning of the delivery process itself.

```
.github/workflows/deploy.yml   # GitHub Actions
.gitlab-ci.yml                  # GitLab CI
Jenkinsfile                     # Jenkins
```

---

## 2. End-to-End Flow: Repository → Production

This section traces the complete journey of a code change — from a developer's first commit to running in production — across different project types and architectures.

---

### 2.1 The Complete Pipeline (Overview)

Every deployment follows the same high-level flow regardless of tech stack:

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Developer │───▶│   Git    │───▶│    CI    │───▶│  Build & │───▶│   CD /   │───▶│ Production│
│  Commit   │    │  Repo    │    │  (Test)  │    │  Package  │    │  Deploy  │    │          │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
     │              │              │              │              │              │
     │ push / PR    │ trigger      │ run tests    │ create       │ roll out    │ serve users
     │              │ webhook      │ & lint       │ artifact     │ to env      │
```

**Each stage in detail:**

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
| **1. Developer Commit** | Write code, run pre-commit hooks (lint, format) | Clean commit with passing pre-checks |
| **2. Git Repo** | Push to remote (GitHub/GitLab/Bitbucket). Triggers webhook | Code stored with commit hash (e.g., `abc1234`) |
| **3. CI (Test)** | Clone repo → Install deps → Lint → Unit tests → Integration tests | Test report + coverage |
| **4. Build & Package** | Compile/transpile → Docker build / bundle → Push to registry | Artifact (Docker image, `.js` bundle, `.ipa`, `.aab`) |
| **5. CD / Deploy** | Promote artifact through environments (dev → staging → canary → prod) | Running application |
| **6. Production** | Serve traffic, monitor metrics, watch for alerts | Live service |

---

### 2.2 Branch Strategy & Environment Mapping

How branches map to environments determines the deployment flow.

```
Branch                    Environment     Deploy Trigger
──────────────────────────────────────────────────────────
feature/xxx               None            CI only (tests + lint)
                     
develop / main ──────────▶ Dev / Staging   Auto-deploy on merge
                     
release/v1.2 ────────────▶ Staging         Manual approval gate
                     
tag: v1.2.0 ──────────────▶ Production      Tag triggers prod deploy
```

**Trunk-Based Development (CI/CD-friendly):**

```
Developer                 main                  Production
─────────────────────────────────────────────────────────────
                    ┌──────────┐              ┌──────────┐
feature/short-lived ─▶│  main    │──(auto)────▶│  Prod    │
  (PR + merge)      │  branch  │              │          │
                    └──────────┘              └──────────┘
                         │                        │
                    Short-lived feature flags   Canary deploy
                    keep incomplete code safe   monitors health
```

---

### 2.3 Flow by Project Type

#### Frontend (React / Next.js / Vue)

```
Developer                    GitHub                    CI (GitHub Actions)              CDN / Hosting
────────────────────────────────────────────────────────────────────────────────────────────────────
         │                      │                            │                              │
         │-- git push -------▶  │                            │                              │
         │                      │-- push webhook ---------▶  │                              │
         │                      │                            │                              │
         │                      │                            ├─ npm ci                      │
         │                      │                            ├─ npm run lint                │
         │                      │                            ├─ npm test -- --coverage      │
         │                      │                            ├─ npm run build               │
         │                      │                            │   (produces dist/)           │
         │                      │                            ├─ Upload to S3                │
         │                      │                            ├─ Invalidate CloudFront       │
         │                      │                            │                              │
         │                      │                            │──▶ Asset uploaded ──────────▶│
         │                      │                            │                              │── User hits URL
         │                      │                            │                              │── CDN serves new files
         │                      │                            │                              │
```

**Real Example — Tracing a Commit:**

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/cicd-frontend-pipeline.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — Frontend Deployment — Developer → GitHub → CI → Build → S3/CloudFront CDN. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>



```
1. Developer runs: git add . && git commit -m "feat: add dark mode"
2. Developer runs: git push origin feat/dark-mode
3. GitHub creates PR #123
4. CI triggers on push: runs lint + test + build
5. Reviewer approves PR
6. Developer clicks "Merge pull request"
7. CI triggers on main branch:
   - Runs all tests again
   - Builds production bundle (dist/)
   - Uploads to S3 bucket
   - Invalidates CloudFront cache
8. Production serves new dark mode feature
```

---

#### Backend (Node.js / Python / Go / Java / Rust)

```
Developer                    GitHub                    CI (GitHub Actions)              Container Registry          Kubernetes
────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
         │                      │                            │                              │                          │
         │-- git push -------▶  │                            │                              │                          │
         │                      │-- push webhook ---------▶  │                              │                          │
         │                      │                            │                              │                          │
         │                      │                            ├─ Install deps                │                          │
         │                      │                            ├─ Run linter                  │                          │
         │                      │                            ├─ Run unit tests              │                          │
         │                      │                            ├─ Docker build               │                          │
         │                      │                            ├─ Docker push ─────────────▶ │                          │
         │                      │                            │                              │                          │
         │                      │                            │──▶ Image stored ────────────▶│                          │
         │                      │                            │                              │                          │
         │                      │                            ├─ kubectl set image ──────────────────────────────────▶ │
         │                      │                            │                              │                          │
         │                      │                            │                              │                          ├─ Rolling update
         │                      │                            │                              │                          ├─ Health check
         │                      │                            │                              │                          ├─ Ready → serve
         │                      │                            │                              │                          │
```

**Real Example — Tracing a Commit (Backend):**

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/cicd-backend-pipeline.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — Backend Deployment — Dockerized service pipeline from commit to Kubernetes. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>



```
1. Developer pushes to main on GitHub
2. GitHub triggers GitHub Actions workflow:
   Job 1 — Test:
     - Checkout code
     - Install dependencies
     - Run linter (ruff/golangci-lint/eslint)
     - Run unit tests with coverage
     - Run integration tests (with test database)
   Job 2 — Build & Push:
     - needs: test
     - Build Docker image with commit SHA tag: myapp:abc1234
     - Push to Docker Hub / ECR / GHCR
   Job 3 — Deploy:
     - needs: build-and-push
     - Update Kubernetes deployment:
       kubectl set image deployment/myapp myapp=myapp:abc1234
3. Kubernetes performs rolling update:
   - Creates new pod with new image
   - Waits for readiness probe to pass
   - Terminates old pod
4. Service is now running the new code
```

---

#### Mobile (iOS / Android)

```
Developer                    GitHub                    CI (GitHub Actions / Bitrise)        App Store / Play Store
───────────────────────────────────────────────────────────────────────────────────────────────────────────────
         │                      │                            │                                    │
         │-- git push -------▶  │                            │                                    │
         │                      │-- push webhook ---------▶  │                                    │
         │                      │                            │                                    │
         │                      │                            ├─ Install dependencies               │
         │                      │                            ├─ Run linter + tests                │
         │                      │                            ├─ Build (archive / bundle)          │
         │                      │                            ├─ Sign with certificate             │
         │                      │                            ├─ Upload to TestFlight / Play       │
         │                      │                            │                                    │
         │                      │                            │──▶ App uploaded ──────────────────▶│
         │                      │                            │                                    ├─ Internal testing
         │                      │                            │                                    ├─ Alpha / Closed beta
         │                      │                            │                                    ├─ Open beta
         │                      │                            │                                    ├─ Submit for review
         │                      │                            │                                    ├─ Phased rollout
         │                      │                            │                                    │
```

---

### 2.4 Monolith Flow

```
┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐
│  Dev   │──▶│  PR    │──▶│  CI    │──▶│ Build  │──▶│ Stage  │──▶│  Prod  │──▶│  Live  │
│ Commit │   │ Review │   │  Test  │   │ Image  │   │ Deploy │   │Deploy  │   │  Site  │
└────────┘   └────────┘   └────────┘   └────────┘   └────────┘   └────────┘   └────────┘
                                                           │            │
                                                     Manual approval   Blue-Green
```

**Key characteristics:**
- Single pipeline for the entire application
- One artifact (one Docker image) that contains everything
- Longer build + test time (15-30+ min for large monoliths)
- Rollback means reverting the entire application
- Database migrations must be backward-compatible

---

### 2.5 Microservices Flow

```
Service A (Python FastAPI):
┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐
│  CI    │──▶│ Build  │──▶│ Push   │──▶│ Deploy │──▶│  Live  │
│  Test  │   │ Image  │   │ ECR    │   │ K8s    │   │ Service│
└────────┘   └────────┘   └────────┘   └────────┘   └────────┘

Service B (Go):
┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐
│  CI    │──▶│ Build  │──▶│ Push   │──▶│ Deploy │──▶│  Live  │
│  Test  │   │ Image  │   │ ECR    │   │ K8s    │   │ Service│
└────────┘   └────────┘   └────────┘   └────────┘   └────────┘

Service C (Java Spring Boot):
┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐
│  CI    │──▶│ Build  │──▶│ Push   │──▶│ Deploy │──▶│  Live  │
│  Test  │   │ Image  │   │ ECR    │   │ K8s    │   │ Service│
└────────┘   └────────┘   └────────┘   └────────┘   └────────┘

Each service has its OWN independent pipeline. They deploy independently.
```

**Deploying a coordinated change across services:**

```
1. Developer commits changes to Service A and Service B in separate PRs
2. Service A PR merges → CI builds → deploys Service A v2 (with backward-compatible API)
3. Service B PR merges → CI builds → deploys Service B v2 (now calls Service A v2's new endpoint)
4. Both services are updated without downtime because:
   - Service A's new endpoint is additive (old + new both work)
   - Service B's change only uses the new endpoint after Service A is confirmed healthy
```

---

### 2.6 Deployment Pipeline Visualization — Full Detail

Here is what a complete GitHub Actions → Kubernetes pipeline looks like step by step:

```
GitHub Repository                          GitHub Actions                         Kubernetes Cluster
┌──────────────────────┐              ┌────────────────────────────┐         ┌──────────────────────────┐
│                      │              │                            │         │                          │
│  main branch         │──push────▶   │  Job 1: Test               │         │  ┌──────────────────┐    │
│  ┌────────────────┐  │              │  ├── Checkout code         │         │  │  Namespace: prod  │    │
│  │ backend/main.py │  │              │  ├── pip install          │         │  │                   │    │
│  │ frontend/       │  │              │  ├── pytest               │         │  │  Service: myapp   │    │
│  │ Dockerfile      │  │              │  └── Upload coverage      │         │  │  ┌─────────────┐  │    │
│  │ deploy.yml      │  │              │                            │         │  │  │ Pod (v2)    │  │    │
│  └────────────────┘  │              │  Job 2: Build & Push       │         │  │  │ image: v2   │  │    │
│                      │              │  ├── Docker build -t v2    │         │  │  │ ready: yes   │  │    │
│  PR #123             │              │  ├── Docker push to ECR    │         │  │  └─────────────┘  │    │
│  feat/add-payment    │              │  └── Tag image: v2         │         │  │  ┌─────────────┐  │    │
│  (awaiting review)   │              │                            │         │  │  │ Pod (v1)    │  │    │
│                      │              │  Job 3: Deploy             │         │  │  │ image: v1   │  │    │
│  ✓ lint passes       │              │  ├── kubectl set image     │──────▶  │  │  │ draining    │  │    │
│  ✓ tests pass        │              │  ├── kubectl rollout status│         │  │  └─────────────┘  │    │
│  ✓ 2 approvals       │              │  ├── kubectl get pods      │         │  │                   │    │
│                      │              │  └── Health check: pass    │         │  │  Ingress ──▶ Users │    │
└──────────────────────┘              └────────────────────────────┘         └──────────────────────────┘
```

---

### 2.7 Artifact Promotion Across Environments

Every artifact goes through a promotion pipeline where it is validated at each stage before progressing:

```
Commit: abc1234
               
Build: myapp:abc1234
   │
   ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Dev        │────▶│  Staging    │────▶│  Canary     │────▶│  Production │
│             │     │             │     │             │     │             │
│ Auto-deploy │     │ Auto-deploy │     │ 5% traffic  │     │ 100% traffic│
│ on merge    │     │ smoke tests │     │ monitored   │     │ full rollout│
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
      │                    │                    │                    │
      │                    │                    │                    │
      ▼                    ▼                    ▼                    ▼
  Unit tests           E2E tests           Metrics check        Alert threshold
  Integration tests    Performance tests   Error budget         Monitoring
```

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



The end-to-end flow is the same pattern repeated across all project types:

> **Code → Commit → CI (Test) → Build (Artifact) → CD (Promote) → Production (Serve)**

The differences are only in the specific tools and artifacts:
- Frontend: `npm build` → `dist/` → S3/CDN
- Backend: `docker build` → image → Kubernetes
- Mobile: `xcodebuild` → `.ipa` → TestFlight → App Store

---

## 3. Deployment Strategies

| Strategy | Mechanism | Zero-Downtime | Rollback Speed | Risk |
|----------|-----------|:---:|:---:|:---:|
| **Rolling Update** | Replace instances gradually | ✅ | Slow | Low |
| **Blue-Green** | Two identical environments, switch traffic | ✅ | Instant | Very Low |
| **Canary Release** | Route small % of traffic to new version | ✅ | Instant | Very Low |
| **Shadow/Mirroring** | Send real traffic to both, ignore new response | ✅ | N/A | None |
| **Recreate** | Kill all old, start all new | ❌ | Fast | High |
| **Feature Flag** | Deploy code disabled, toggle on per-rollout | ✅ | Instant | Very Low |

### Blue-Green Deployment

```
       ┌─────────────┐     ┌─────────────┐
Users ─▶│  Load       │────▶│   Blue      │ (v1 — active)
       │  Balancer   │     └─────────────┘
       └─────────────┘     ┌─────────────┐
                           │   Green     │ (v2 — idle)
                           └─────────────┘

Switch: Update load balancer to route to Green.
Rollback: Switch back to Blue.
```

### Canary Release

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/cicd-blue-green-deployment.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — Blue-Green Deployment — Two identical environments with instant switch and rollback. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>



```
Users ─▶ Load Balancer ──── 90% ──▶ Old Version (v1)
                           └── 10% ──▶ New Version (v2)

Monitor metrics for 10% canary. If healthy → 25% → 50% → 100%.
If degraded → rollback instantly.
```

### Feature Flags (Feature Toggles)

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/cicd-canary-release.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — Canary Release — Progressive traffic shift with metric-based gates. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>



```javascript
// Code is deployed but feature is off
if (featureFlags.isEnabled('new-checkout-flow')) {
  // New implementation
} else {
  // Old implementation
}

// Toggle on via dashboard → no redeploy needed
```

**Tools:** LaunchDarkly, Split.io, Flagsmith, OpenFeature

---

## 4. Frontend Deployment

### React / Next.js / Vue / Angular

**Typical Pipeline:**

```
1. Install dependencies    npm ci / yarn install --frozen-lockfile
2. Lint & type-check       npm run lint / tsc --noEmit
3. Unit tests              npm test -- --coverage
4. Build                   npm run build (produces dist/ or .next/)
5. Analyze bundle          npx source-map-explorer dist/*.js
6. Upload artifacts        Upload to CDN / S3 / CloudFront
7. Invalidate cache        Purge CDN cache for new assets
8. E2E tests               npx playwright test
9. Deploy                  Update S3 + invalidate CloudFront
```

**Key Considerations:**

| Concern | Solution |
|----------|----------|
| **Cache busting** | Content-hashed filenames (`app.a1b2c3.js`) |
| **CDN distribution** | CloudFront, Cloudflare, Fastly, Akamai |
| **SSR/SSG (Next.js)** | Deploy to Vercel, or self-host with Node.js + Docker |
| **Environment config** | Runtime env vars (not build-time) for different stages |
| **Preview deployments** | Vercel/Netlify PR previews, or GitHub Pages for docs |
| **Static vs SPA** | SPA needs fallback to `index.html` for client-side routing |

**Example GitHub Actions Workflow (React):**

```yaml
name: Deploy Frontend
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'npm'

      - run: npm ci
      - run: npm run lint
      - run: npm test -- --coverage
      - run: npm run build

      - name: Deploy to S3
        run: aws s3 sync dist/ s3://${{ secrets.S3_BUCKET }}

      - name: Invalidate CloudFront
        run: aws cloudfront create-invalidation --distribution-id ${{ secrets.CF_DIST_ID }} --paths "/*"
```

---

## 5. Backend Deployment by Language

### 4.1 Node.js / TypeScript

**Build & Package:**
```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY package*.json ./
EXPOSE 3000
CMD ["node", "dist/main.js"]
```

**Pipeline:**
```
npm ci → lint → test (jest/mocha) → build (tsc) → docker build → push → deploy
```

**Framework-specific:**
- **Express/Fastify:** Standard Docker + reverse proxy (nginx)
- **NestJS:** Builds to `dist/`, same Docker pattern
- **Serverless:** Use `serverless` framework, deploy to AWS Lambda / Vercel Functions

### 4.2 Python (FastAPI / Django / Flask)

**Build & Package:**
```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN pip install --no-cache-dir .

# Multi-stage: smaller runtime image
FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /app /app
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Pipeline:**
```
pip install → lint (ruff/flake8) → type-check (mypy) → test (pytest) → build wheel → docker build → push → deploy
```

**Framework-specific:**
- **FastAPI:** Uvicorn/Gunicorn, auto-generated OpenAPI docs benefit staging review
- **Django:** `python manage.py migrate` must run as pre-deploy hook, collectstatic for assets
- **Flask:** Simple WSGI with Gunicorn + nginx

**Database Migrations (Django):**
```yaml
# Pre-deploy step — run before traffic switch
- name: Run migrations
  run: python manage.py migrate --noinput
```

### 4.3 Go

**Build & Package:**
```dockerfile
FROM golang:1.22 AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /app/server .

FROM alpine:3.19
RUN apk add --no-cache ca-certificates
COPY --from=builder /app/server /server
EXPOSE 8080
CMD ["/server"]
```

**Pipeline:**
```
go mod download → lint (golangci-lint) → test (go test -race) → build → docker build (scratch/alpine) → push → deploy
```

**Key advantages:**
- Single binary — no runtime dependencies
- Builds to `scratch` or `alpine` — tiny images (~5-15MB)
- Fast compile times
- Native cross-compilation: `GOOS=linux GOARCH=arm64 go build`

### 4.4 Java / Spring Boot

**Build & Package:**
```dockerfile
FROM maven:3.9-eclipse-temurin-21 AS builder
WORKDIR /app
COPY pom.xml .
RUN mvn dependency:go-offline
COPY src ./src
RUN mvn package -DskipTests

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=builder /app/target/*.jar app.jar
EXPOSE 8080
CMD ["java", "-jar", "app.jar"]
```

**Pipeline:**
```
mvn compile → test → package → docker build → push → deploy
```

**Key considerations:**
- **JVM tuning:** `-Xms`, `-Xmx`, GC flags per environment
- **GraalVM Native Image:** Smaller images, faster startup (good for serverless/K8s)
- **Build time:** Maven/Gradle caching is critical for CI speed
- **Health checks:** Spring Boot Actuator endpoints (`/actuator/health`)

### 4.5 Rust

```dockerfile
FROM rust:1.77 AS builder
WORKDIR /app
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main() {}" > src/main.rs
RUN cargo build --release  # Cache dependencies
COPY src ./src
RUN touch src/main.rs && cargo build --release

FROM debian:bookworm-slim
COPY --from=builder /app/target/release/myapp /myapp
EXPOSE 8080
CMD ["/myapp"]
```

---

## 6. Mobile Deployment

### iOS (Swift / SwiftUI / UIKit)

**Pipeline:**
```
1. Install dependencies    bundle install && pod install / SPM resolve
2. Lint & analyze          swiftlint / SwiftLint
3. Unit tests              xcodebuild test -scheme App
4. UI tests                xcodebuild test -scheme AppUITests -destination
5. Archive                 xcodebuild archive -scheme App
6. Export IPA              xcodebuild -exportArchive
7. Upload to TestFlight    xcrun altool --upload-app
8. Submit for review       App Store Connect API
9. Promote to production   Manual approval → release
```

**Key Considerations:**
- **Code signing:** Managed via Fastlane match + Apple Developer Portal
- **TestFlight:** Internal/External testing before App Store release
- **Phased release:** Roll out over 7 days to catch issues
- **CI runners:** Mac mini/MacStadium runners required (GitHub Actions now offers macOS)

**Fastlane Example:**
```ruby
lane :deploy do
  match(type: "appstore")
  gym(scheme: "App")
  pilot(
    app_identifier: "com.example.app",
    beta_app_review_info: { contact_email: "team@example.com" }
  )
end
```

### Android (Kotlin / Jetpack Compose)

**Pipeline:**
```
1. Lint                  ./gradlew lint
2. Unit tests            ./gradlew testDebugUnitTest
3. Build APK/Bundle      ./gradlew bundleRelease
4. Sign release          (via gradle + keystore)
5. Upload to Play Console  gradle publishReleaseBundle
6. Internal testing track  → Alpha → Beta → Production
7. Staged rollout          e.g., 5% → 20% → 100%
```

**Key Considerations:**
- **App Bundle (.aab):** Preferred over APK for Play Store distribution
- **ProGuard/R8:** Code obfuscation and minification enabled for release
- **Google Play Console API:** Automate track promotion
- **Testing tracks:** Internal → Closed Alpha → Open Beta → Production

---

## 7. Monolith Architecture

### Characteristics

- Single deployable unit (one binary/container)
- Shared database
- Tightly coupled modules

### CI/CD Strategy

```yaml
Pipeline:
  ├── Pre-commit hooks (lint, format)
  ├── CI (per branch):
  │   ├── Lint + Type-check
  │   ├── Unit tests
  │   ├── Build (compile + Docker)
  │   └── Integration tests
  ├── Staging (on merge to main):
  │   ├── Deploy to staging environment
  │   ├── Smoke tests
  │   └── E2E tests
  └── Production (on release tag):
      ├── Deploy → Blue-Green or Rolling
      ├── Health checks
      └── Monitoring alert
```

### Database Migrations

**Expand-Contract Pattern (Backward-Compatible):**

```sql
-- Phase 1 (Expand): Add new column, keep old
ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT FALSE;

-- Phase 2 (Migrate): Backfill data in background
UPDATE users SET email_verified = ...;

-- Phase 3 (Contract): Remove old column (next release)
ALTER TABLE users DROP COLUMN email_verified_legacy;
```

### Production Concerns

- **Build time:** Large monoliths can take 15-30+ minutes to build — invest in caching
- **Test time:** Parallel test execution, test splitting, and selective test execution
- **Rollback complexity:** Single rollback affects entire application
- **Scaling:** Scale entire app (vertical scaling) or run multiple instances behind LB

---

## 8. Microservices Architecture

### Characteristics

- Multiple independently deployable services
- Each service owns its data/database
- Communicate via APIs (REST/gRPC/messaging)
- Polyglot — different services can use different languages

### CI/CD Strategy

```yaml
Per-Service Pipeline (independent):
  ├── CI: Lint → Test → Build → Docker Image → Push to Registry
  ├── CD:
  │   ├── Deploy to staging (namespace per PR/branch)
  │   ├── Integration tests (contract tests via Pact)
  │   └── Deploy to production via GitOps (ArgoCD)

Shared Platform Pipeline:
  ├── Infrastructure-as-Code (Terraform/Pulumi)
  ├── Kubernetes manifests
  ├── Service mesh config (Istio/Linkerd)
  └── Monitoring & alerting rules
```

### GitOps with ArgoCD

```
                      ┌─────────────────┐
                      │   Git Repository │
                      │ (manifests repo) │
                      └────────┬────────┘
                               │ watch / sync
                               ▼
                      ┌─────────────────┐
                      │    ArgoCD        │
                      │  (in-cluster)    │
                      └────────┬────────┘
                               │ apply
                               ▼
                      ┌─────────────────┐
                      │  Kubernetes     │
                      │  Cluster        │
                      └─────────────────┘
```

### Service Mesh (Istio) for Deployments

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: user-service
spec:
  hosts:
  - user-service
  http:
  - match:
    - headers:
        x-canary:
          exact: "true"
    route:
    - destination:
        host: user-service
        subset: v2
      weight: 100
  - route:
    - destination:
        host: user-service
        subset: v1
      weight: 90
    - destination:
        host: user-service
        subset: v2
      weight: 10
```

### Inter-Service Testing

| Test Type | Tool | Purpose |
|-----------|------|---------|
| **Contract tests** | Pact, Spring Cloud Contract | Verify API compatibility between services |
| **Integration tests** | Testcontainers | Test against real dependencies |
| **E2E tests** | Playwright, Cypress | Full system validation |
| **Chaos engineering** | Chaos Mesh, Litmus | Test resilience under failure |

### Production Deployment Steps

```
1. Build service A (new version)
2. Run unit + integration tests for service A
3. Run contract tests (service A producer, consumers validate)
4. Deploy service A to staging
5. Run smoke + E2E tests
6. Deploy service A to production with canary (10%)
7. Monitor metrics (latency, errors, CPU, memory)
8. Gradual rollout: 25% → 50% → 100%
9. If healthy → mark complete; if degraded → rollback
```

---

## 9. CI/CD Pipeline by Tool

### GitHub Actions

```yaml
name: CI/CD

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: test
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - run: pip install -r requirements-dev.txt
      - run: ruff check .
      - run: mypy .
      - run: pytest --cov --cov-report=xml
      - uses: codecov/codecov-action@v3

  build-and-push:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v5
        with:
          push: true
          tags: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }}

  deploy:
    needs: build-and-push
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v4
      - uses: azure/setup-kubectl@v3
      - run: |
          kubectl set image deployment/myapp \
            myapp=${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }}
```

### GitLab CI

```yaml
stages:
  - test
  - build
  - deploy

variables:
  DOCKER_IMAGE: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA

test:
  stage: test
  script:
    - pip install -r requirements.txt
    - pytest --cov --cov-report=xml
  coverage: '/^TOTAL.+s+(d++)%/'

build:
  stage: build
  script:
    - docker build -t $DOCKER_IMAGE .
    - docker push $DOCKER_IMAGE

deploy:
  stage: deploy
  script:
    - kubectl set image deployment/myapp myapp=$DOCKER_IMAGE
  environment:
    name: production
  only:
    - main
```

### Jenkins Pipeline (Declarative)

```groovy
pipeline {
    agent any

    stages {
        stage('Checkout') {
            steps { checkout scm }
        }
        stage('Test') {
            steps {
                sh 'npm ci'
                sh 'npm test'
            }
        }
        stage('Build') {
            steps {
                sh 'npm run build'
                sh 'docker build -t myapp:${BUILD_NUMBER} .'
            }
        }
        stage('Push') {
            steps {
                sh 'docker push myapp:${BUILD_NUMBER}'
            }
        }
        stage('Deploy') {
            steps {
                sh 'kubectl set image deployment/myapp myapp=myapp:${BUILD_NUMBER}'
            }
        }
    }

    post {
        failure {
            slackSend(
                color: 'danger',
                message: "Build failed: ${env.JOB_NAME} - ${env.BUILD_NUMBER}"
            )
        }
    }
}
```

---

## 10. Production Best Practices

### Security

| Practice | Description |
|----------|-------------|
| **Shift left** | Scan dependencies (Snyk, Trivy) and secrets (truffleHog) in CI |
| **Image scanning** | Scan Docker images for vulnerabilities before deploy (Trivy, Grype) |
| **Minimal base images** | Use `distroless`, `alpine`, or `scratch` to reduce attack surface |
| **SBOM** | Generate Software Bill of Materials for each release (CycloneDX) |
| **Short-lived credentials** | Use OIDC/OAuth2 instead of long-lived secrets in CI |

### Observability

```yaml
Deploy Gate Checks (automated):
  ├── P99 latency < 500ms
  ├── Error rate < 0.1%
  ├── CPU usage < 80%
  ├── Memory usage < 85%
  └── No critical alerts firing
```

### Rollback Playbook

```
1. Detect: Alert triggers (latency spike, error rate increase)
2. Decide: On-call engineer confirms rollback
3. Rollback:
   Blue-Green:  Switch load balancer back to Blue
   Rolling:     kubectl rollout undo deployment/myapp
   Canary:      Shift traffic back to 100% old version
4. Verify: Monitor metrics return to baseline
5. Investigate: Root cause analysis → fix → re-deploy
```

### Environment Parity

| Aspect | Staging | Production |
|--------|---------|------------|
| **OS/runtime** | Same Docker image | Same Docker image |
| **Database** | Same version, smaller instance | Same version, sized for load |
| **Config** | Separate values, same structure | Production values |
| **Network** | Simulated topology | Real topology |
| **Data** | Anonymized subset | Real data |

---

## 11. Interview Questions

### Beginner

---

#### 1. Explain the difference between CI and CD.

**CI (Continuous Integration)** is the practice of merging developer code into a shared branch multiple times per day, with each merge automatically triggering a pipeline that runs linting, unit tests, and build verification. The goal is to detect integration bugs early — before they compound across long-lived branches.

**CD has two flavors:**

- **Continuous Delivery (CDel):** Every change that passes CI is automatically prepared and packaged for release. Promotion to production requires a *human approval gate*. This is the right model for regulated industries or high-risk changes.
- **Continuous Deployment (CDep):** Every change that passes all automated gates is automatically deployed to production *without human intervention*. This requires extremely high automated test coverage and robust monitoring.

**In practice at scale:** Most mature engineering organizations run Continuous *Delivery* to production (with automated gate checks like latency/error budgets replacing manual approval) and reserve Continuous *Deployment* for lower-risk services. The distinction matters less than the underlying principle: ship small, ship often, catch failures automatically.

```
CI → Build → Artifact
                │
                ├── Continuous Delivery:  Staging → [Human Gate] → Production
                └── Continuous Deployment: Staging → [Automated Gate] → Production
```

---

#### 2. What is a deployment strategy? Name three types.

A **deployment strategy** defines *how* a new version of software is rolled out to replace the old version, specifically controlling the risk of failures affecting users and the speed and ease of rollback.

**Three key strategies:**

1. **Rolling Update** — Replace instances of the old version incrementally (e.g., 1 pod at a time in Kubernetes). Zero-downtime, but during rollout both versions run simultaneously, which can cause API incompatibility issues.

2. **Blue-Green** — Two identical environments ("Blue" = live, "Green" = new). Deploy fully to Green, then switch the load balancer. Instant rollback by switching back to Blue. High infra cost (2x resources).

3. **Canary Release** — Route a small percentage (e.g., 5–10%) of real user traffic to the new version. Monitor metrics; if healthy, progressively increase to 100%. Best risk-adjusted approach for stateless services.

---

#### 3. How does blue-green deployment work?

**Concept:** You maintain two identical production environments: "Blue" (currently serving traffic) and "Green" (idle, staging the next release).

**Sequence:**
1. Deploy the new version to the **Green** environment (while Blue continues serving 100% of traffic).
2. Run smoke tests, integration checks, and any validation against Green while it's dark (receiving no real user traffic).
3. Once validated, update the **load balancer** (or DNS, or service mesh routing rule) to point all traffic to Green. Green is now live.
4. Blue is kept warm for a configurable period (e.g., 30 minutes). If alerts fire post-switch, you revert the load balancer back to Blue — rollback in under 60 seconds.
5. After confidence window, Blue becomes the next deployment target.

**Advantages:** Near-instant rollback, full validation before traffic switch, no mixed-version traffic during rollout.

**Trade-offs:** Requires 2x infrastructure cost, database schema must be compatible with both versions simultaneously, stateful sessions need sticky routing or external session store.

---

#### 4. What is the purpose of a build artifact?

A **build artifact** is the immutable, versioned, self-contained output of the build stage that will be promoted through environments without being rebuilt.

**Why it matters:**
- **Immutability:** The exact same binary/image that passed tests in staging is what runs in production. "Build once, deploy many" guarantees environmental fidelity.
- **Auditability:** Artifacts are tagged with commit SHAs and stored in a registry (ECR, GHCR, Nexus). You can always trace what is running in production back to the exact source commit.
- **Speed:** Rebuilding from source per environment introduces variance (flaky dependency resolution, different build tool versions). Artifact promotion eliminates that.
- **Rollback:** Rolling back is selecting a previous artifact tag, not re-running a build.

**Examples by type:**
| Stack | Artifact |
|-------|---------|
| Backend | Docker image (`myapp:abc1234`) |
| Frontend | Bundled static assets (`dist/`, content-hashed) |
| iOS | `.ipa` archive |
| Android | `.aab` bundle |
| Java | `.jar` / `.war` |
| Go | Compiled binary |

---

### Intermediate

---

#### 5. Compare rolling update vs. blue-green deployment. When would you use each?

| Dimension | Rolling Update | Blue-Green |
|-----------|---------------|------------|
| **How it works** | Replace old instances one-by-one | Flip all traffic at once after full standby deploy |
| **Zero-downtime** | ✅ Yes | ✅ Yes |
| **Mixed versions** | ✅ Yes — old and new run concurrently | ❌ No — clean switch |
| **Rollback speed** | Slow (re-roll the rolling update) | Instant (flip LB back) |
| **Infrastructure cost** | Same — in-place replacement | 2x — two full environments |
| **API compatibility required** | ✅ Critical — both versions serve traffic simultaneously | Lighter — only during validation window |

**Use rolling update when:**
- Running stateless, API-backward-compatible services
- Infrastructure cost is a constraint
- You have good readiness probes and pod disruption budgets configured
- Kubernetes is your orchestrator (default strategy)

**Use blue-green when:**
- You need guaranteed instant rollback (payment processing, checkout flows)
- You want to validate the full new environment under synthetic load before switching
- You're deploying a schema-breaking change that requires a clean cutover
- Regulatory requirements demand zero mixed-version exposure

**Staff-level nuance:** For most stateless microservices at scale, rolling updates are the operational default because they're resource-efficient and Kubernetes handles them natively. Blue-green is reserved for high-stakes deployments or schema migrations. Canary (partial traffic split) is increasingly the preferred alternative to both — it gives you real-signal validation with controlled blast radius.

---

#### 6. How do you handle database migrations in a CI/CD pipeline?

Database migrations are the hardest part of zero-downtime deployment because the database is shared and changes are not atomic with code deploys.

**The golden rule: migrations must be backward-compatible with the previous version of the application.**

**Expand-Contract Pattern (3-phase migration):**

```
Release N:    Add new column (nullable/with default). Old code ignores it.
Release N+1:  Populate column. New code reads/writes it. Old code still works.
Release N+2:  Remove old column or constraint once old code is fully retired.
```

**Pipeline integration:**
```yaml
# Pre-deploy hook — runs BEFORE traffic switch
- name: Run migrations
  run: |
    alembic upgrade head      # Python
    # or
    python manage.py migrate  # Django
    # or
    flyway migrate            # Java
```

**Key practices at scale:**
- **Never** run migrations as part of the application startup (causes race conditions across pods)
- Run migrations as a **Kubernetes Job** or **init container** that completes before pods roll
- Use **migration tools with locking** (Flyway, Liquibase, Alembic) to prevent concurrent runs
- Maintain a **dry-run mode** (`--dry-run`, `alembic upgrade head --sql`) to review SQL before execution
- **Separate DDL from DML**: `ALTER TABLE` statements are separate from data backfills (backfills run as background jobs)
- For large tables (100M+ rows), use **online schema change tools** (pt-online-schema-change, gh-ost for MySQL; `CREATE INDEX CONCURRENTLY` for PostgreSQL)

**Example: Zero-downtime column rename (PostgreSQL):**
```sql
-- Phase 1 (deploy v1): Add new column
ALTER TABLE orders ADD COLUMN customer_id BIGINT;

-- Phase 2 (backfill, background job): Copy data
UPDATE orders SET customer_id = user_id WHERE customer_id IS NULL;

-- Phase 3 (deploy v2): App writes to both columns
-- (dual-write period)

-- Phase 4 (deploy v3): App reads only from customer_id
-- Remove old column
ALTER TABLE orders DROP COLUMN user_id;
```

---

#### 7. What is GitOps and how does ArgoCD implement it?

**GitOps** is an operational model where the **Git repository is the single source of truth** for the desired state of infrastructure and deployments. Changes to the running system are made exclusively by committing to Git — never by running `kubectl apply` or `terraform apply` manually.

**Core principles:**
1. **Declarative:** Desired state is expressed as files (Kubernetes manifests, Helm charts, Kustomize overlays)
2. **Versioned:** Git history is the audit log for all changes
3. **Automated:** A reconciliation loop continuously compares desired (Git) vs. actual (cluster) state and converges them
4. **Observable:** Drift between desired and actual state is immediately detectable

**How ArgoCD implements GitOps:**
```
Developer commits Kubernetes manifest to Git
          │
          ▼
    ArgoCD watches Git repo (polling or webhook)
          │
          ▼
    ArgoCD detects diff: desired state ≠ cluster state
          │
          ▼
    ArgoCD applies manifests to Kubernetes cluster
          │
          ▼
    ArgoCD reports sync status: Healthy / Degraded / Out-of-sync
```

**Key ArgoCD concepts:**
- **Application:** ArgoCD CRD that maps a Git path to a cluster namespace
- **Sync:** The act of applying Git state to the cluster
- **Health status:** ArgoCD evaluates if pods/services are actually healthy post-sync
- **App-of-Apps pattern:** A parent ArgoCD application manages child applications — scales to 100s of services

**Staff-level nuance:** GitOps solves the "config drift" problem — the gap between what you think is deployed and what's actually running. In traditional push-based CD, drift accumulates through hotfixes, manual interventions, and failed rollouts. ArgoCD's reconciliation loop continuously enforces the desired state, making the cluster self-healing.

---

#### 8. How would you set up a canary release for a microservice?

**Goal:** Expose a new version to a small subset of real users, measure its behavior against production signals, and progressively expand or roll back.

**Option 1: Kubernetes + Service Mesh (Istio) — recommended for microservices:**

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: payment-service
spec:
  http:
  - route:
    - destination:
        host: payment-service
        subset: v1
      weight: 90      # 90% → stable
    - destination:
        host: payment-service
        subset: v2
      weight: 10      # 10% → canary
```

**Progressive promotion schedule:**
```
Deploy → 5% → Monitor (15 min) → 25% → Monitor (30 min) → 50% → Monitor → 100%
```

**Automated gate (what to measure):**
- P99 latency increase < 10% vs. baseline
- Error rate (5xx) < 0.1%
- Business-level metrics (payment success rate, conversion rate)
- No new alerts firing in observability platform (Datadog, Grafana)

**Option 2: Feature flags (for application-level canary):**
```python
if feature_flags.percentage_rollout('new-checkout', user_id=request.user_id, percent=10):
    return new_checkout_flow()
return old_checkout_flow()
```

**Automation with Argo Rollouts:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
spec:
  strategy:
    canary:
      steps:
      - setWeight: 10
      - pause: {duration: 15m}
      - analysis:
          templates:
          - templateName: success-rate   # Prometheus query
      - setWeight: 50
      - pause: {duration: 30m}
      - setWeight: 100
```

---

#### 9. Explain the expand-contract pattern for zero-downtime migrations.

The **expand-contract pattern** (also called "parallel change") is a technique for making breaking schema or API changes incrementally, across multiple deployments, without downtime.

**The problem:** You cannot simultaneously change the database schema AND deploy new code atomically — deployments are rolling, so old and new code run concurrently against the same database.

**Three phases:**

```
Phase 1 — EXPAND:
  Add new column/endpoint (backward-compatible addition)
  Old code: ignores new column (nullable/has default)
  New code: writes to both old and new column

Phase 2 — MIGRATE:
  Backfill data into the new column/format
  Run as background job, not in the deployment pipeline

Phase 3 — CONTRACT:
  Remove old column/endpoint once all consumers use the new one
  Deploy code that only reads/writes the new column
  Then drop the old column (DDL is safe now)
```

**Real example — renaming `user_id` to `customer_id`:**

```sql
-- Phase 1 (Expand): Add new column
ALTER TABLE orders ADD COLUMN customer_id BIGINT;

-- App code: write to both columns
INSERT INTO orders (user_id, customer_id, ...) VALUES (42, 42, ...);
```

```sql
-- Phase 2 (Migrate): Backfill
UPDATE orders SET customer_id = user_id WHERE customer_id IS NULL;
```

```sql
-- Phase 3 (Contract): Remove old column after all pods run new code
ALTER TABLE orders DROP COLUMN user_id;
```

**The same pattern applies to API changes:**
- **Expand:** Add new `/v2/checkout` endpoint alongside `/v1/checkout`
- **Migrate:** Update all consumers to call `/v2`
- **Contract:** Deprecate and remove `/v1`

**Why this matters at staff level:** The expand-contract pattern is what makes it possible to deploy schema changes without maintenance windows. It requires discipline: each "contract" step must be a separate, independently deployed release. Teams that skip the contract phase accumulate schema debt.

---

### Senior / Staff

---

#### 10. Design a CI/CD pipeline for a 50-microservice system with polyglot services (Go, Python, Java). How do you handle cross-service contract testing?

**The core challenge:** 50 independent pipelines that must not be micromanaged individually, with cross-language builds and API compatibility guarantees across service boundaries.

**Architecture Decision: Monorepo vs. Polyrepo**

| | Monorepo | Polyrepo |
|---|---|---|
| **CI trigger** | Smart change detection (only build affected services) | Each repo has its own pipeline |
| **Cross-service refactors** | Atomic commits across services | Requires coordinated PRs |
| **Tooling** | Bazel, Nx, Turborepo, Pants | Standard per-service CI |

For 50 services, I'd use a **polyrepo** approach with a shared **Platform Engineering** team owning standardized pipeline templates.

**Pipeline Architecture:**

```
Each service repo has a standard .github/workflows/ci.yml (templated via reusable workflows):

1. Detect language → select build strategy:
   - Go:     golangci-lint → go test -race → docker build (scratch)
   - Python: ruff → mypy → pytest → docker build (python:3.12-slim)
   - Java:   maven/gradle lint → junit → docker build (eclipse-temurin:21-jre)

2. Build Docker image tagged: {service}:{commit-sha}
3. Push to shared ECR / GHCR
4. Run contract tests
5. Deploy to staging namespace
6. Promote to production via GitOps (PR to manifests repo)
```

**Cross-Service Contract Testing with Pact:**

```
Consumer-Driven Contract Testing model:

Payment Service (Consumer) defines expectations:
  - "When I call /api/orders/{id}, I expect JSON: {id, status, amount}"

Order Service (Producer) verifies those expectations:
  - Pact Broker stores contracts
  - Order Service CI runs: pact verify → confirms it satisfies all consumer contracts

Flow:
  Payment Service CI → generates pact file → uploads to Pact Broker
  Order Service CI  → downloads pacts from Broker → runs provider verification
  If verification fails → Order Service pipeline BLOCKS
```

**Pact Broker integration in GitHub Actions:**
```yaml
- name: Publish consumer contract
  run: |
    pact-broker publish ./pacts \
      --broker-base-url $PACT_BROKER_URL \
      --consumer-app-version $GITHUB_SHA

- name: Can I Deploy? (check if safe to release)
  run: |
    pact-broker can-i-deploy \
      --pacticipant payment-service \
      --version $GITHUB_SHA \
      --to-environment production
```

**Shared Platform components (managed by Platform Engineering):**
- **Reusable GitHub Actions workflows** (language-specific build templates called via `uses:`)
- **Shared base Dockerfiles** stored in `platform/docker/` repo
- **Pact Broker** (central contract registry)
- **Centralized observability** (all services emit to same Datadog/Grafana stack)
- **Service catalog** (Backstage) tracking which version of each service is deployed where

---

#### 11. How do you ensure backward compatibility during a multi-service rollout?

**The fundamental problem:** In a distributed system, you cannot atomically deploy two services simultaneously. One service will always deploy first, creating a window where v2 of Service A runs against v1 of Service B (or vice versa).

**Strategy 1: Additive-Only API Changes (Robustness Principle)**
- APIs must be **backward-compatible**: new fields are optional with defaults, old fields are never removed in the same release
- **Never** change the meaning of an existing field — add a new field
- Use versioned endpoints (`/v2/`) for breaking changes, keep `/v1/` alive during transition

**Strategy 2: Tolerate Unknown Fields**
- Consumers must be built with **tolerant reader** pattern: ignore fields they don't understand
- Use `additionalProperties: true` in JSON Schema
- In protobuf, unknown fields are preserved by default

**Strategy 3: Deployment Ordering**
```
For a breaking change between Service A (producer) and Service B (consumer):

1. Deploy Service A v2 — adds NEW endpoint/field (EXPAND phase)
   Old consumers still work against old endpoint.

2. Deploy Service B v2 — starts calling new endpoint.
   If A is healthy → B upgrades work.

3. Deploy Service A v3 — removes old endpoint (CONTRACT phase).
   Only after all consumers are confirmed on v2.
```

**Strategy 4: API Versioning + Deprecation Pipeline**
```
Deprecation policy:
  - Mark old endpoint deprecated in OpenAPI spec
  - Emit deprecation warning metric (track consumers still calling it)
  - Set sunset date (e.g., 30 days)
  - Monitor: alert if deprecated endpoint traffic > 0 after sunset date
  - Remove in next major release
```

**Strategy 5: Consumer-Driven Contract Tests (see Q10)**
- These act as a compatibility gate: a producer cannot merge if it breaks any registered consumer contract

**Strategy 6: Feature flags for coordinated rollout**
```python
# Service B only activates new behavior after flag is enabled
if feature_flags.is_enabled('use-v2-order-api'):
    response = order_service.get_order_v2(order_id)
else:
    response = order_service.get_order_v1(order_id)
```
This lets you deploy both services independently, then coordinate the flag flip centrally.

---

#### 12. Design a deployment system that can handle 1,000+ deployments per day across 200 services.

**Scale context:** 1,000 deployments/day across 200 services = ~5 deployments/service/day = one deployment every 2–3 hours per service. This requires near-zero human intervention per deployment.

**Core architecture:**

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Control Plane                                │
│                                                                     │
│  Git Push → Webhook → Deployment Orchestrator → Queue → Executors  │
│                              │                                       │
│                    ┌─────────┴──────────┐                           │
│                    │  Deployment Queue  │  (per-service FIFO)       │
│                    └────────────────────┘                           │
└─────────────────────────────────────────────────────────────────────┘
```

**Key design decisions:**

**1. Parallelism with per-service serialization**
- Deployments to *different* services are fully parallel
- Deployments to the *same* service are serialized (queue) to prevent race conditions
- Use a distributed lock (Redis/Etcd) per service: at most 1 active deployment per service

**2. GitOps as the control plane (ArgoCD + Flux)**
- Each service has a Kubernetes manifest in a manifests repo
- CI pipeline creates a PR to update the image tag → auto-merge on CI pass → ArgoCD syncs
- ArgoCD handles the actual apply, health check, and rollback
- This decouples the deployment trigger from the execution — ArgoCD can retry, batch, or queue

**3. Deployment pipeline stages (all automated):**
```
Commit → CI (2-5 min) → Artifact Push → Staging Deploy (auto) →
Smoke Tests (2 min) → Canary 5% (15 min) →
SLO Gates (automated) → Canary 100% → Done
```
Total elapsed time: ~25–35 minutes per deployment, fully automated.

**4. SLO-based automatic promotion and rollback**
```yaml
# Argo Rollouts analysis template
metrics:
- name: success-rate
  provider:
    prometheus:
      query: |
        sum(rate(http_requests_total{status!~"5..",service="{{args.service}}"}[5m]))
        /
        sum(rate(http_requests_total{service="{{args.service}}"}[5m]))
  successCondition: result[0] >= 0.995   # 99.5% success rate
  failureLimit: 1
```

**5. Preventing deployment storms**
- **Rate limiting:** Max N concurrent deployments cluster-wide (Kubernetes resource quotas)
- **Time windows:** Optional quiet hours (block deployments 11pm–6am without on-call approval)
- **Dependency graph:** If Service A deploys, hold Service B (its consumer) until A is healthy

**6. Observability of the deployment system itself**
- **DORA metrics dashboard:** Deployment frequency, lead time, MTTR, change failure rate
- **Deployment timeline view:** See all 200 services' deployment status in one view
- **Failure reason classification:** Automated labeling (test failure, timeout, rollback, OOM)

**7. Self-service for developers**
- Backstage plugin showing each service's deployment status, recent history, and DORA metrics
- Slack bot: `/deploy payment-service to staging` triggers pipeline

---

#### 13. How do you implement progressive delivery with feature flags and canary releases in a service mesh?

**Progressive delivery** is the union of infrastructure-level canary (traffic splitting at the load balancer/service mesh) and application-level feature flags — giving you two independent dimensions of control over rollout.

**Layer 1: Service Mesh Canary (infrastructure level)**

Using Istio VirtualService + Argo Rollouts:
```yaml
# Argo Rollouts controls traffic weights automatically
apiVersion: argoproj.io/v1alpha1
kind: Rollout
spec:
  strategy:
    canary:
      trafficRouting:
        istio:
          virtualService:
            name: checkout-vs
      steps:
      - setWeight: 5        # 5% → canary
      - pause: {duration: 15m}
      - analysis:
          templates:
          - templateName: error-rate-check
      - setWeight: 25
      - pause: {duration: 30m}
      - setWeight: 100
```

**Layer 2: Feature Flags (application level)**

Feature flags let you deploy code fully (100% of traffic hitting new pods) but keep the feature *behaviorally* off until explicitly enabled:

```python
# Flag evaluation happens at runtime, not deploy time
def process_checkout(request):
    if flags.variation('new-tax-calculation', user_id=request.user.id):
        return new_tax_engine.calculate(request.cart)
    return legacy_tax_engine.calculate(request.cart)
```

**Combining both layers for maximum control:**

```
Scenario: Rolling out a risky new recommendation engine

Step 1: Deploy code (new pods running) → flag OFF (0% exposure)
        → canary at 5% traffic, but feature flag = OFF for all

Step 2: Enable flag for internal users only (LaunchDarkly targeting rule)
        → staff dog-food the feature at 5% infra canary

Step 3: Enable flag for 1% of users (random bucket)
        → measure recommendation click-through and revenue per session

Step 4: Expand flag to 10%, 25%, 50%, 100% on independent schedule
        → infra canary finishes at Step 2 (stable pods serving traffic)
        → feature rollout continues via flag config (zero redeploy)

Rollback:
  - Feature regression: flip flag OFF → instant, no redeploy
  - Infrastructure regression: Argo Rollouts detects SLO breach → auto-rollback pods
```

**Metric-driven flag promotion (OpenFeature + Prometheus):**
```yaml
# Automated flag promotion rule
flag: new-recommendation-engine
auto_promote:
  metric: revenue_per_session_increase
  threshold: ">= 0.02"   # 2% revenue uplift
  window: 24h
  current_exposure: 10%
  next_exposure: 25%
```

**Tools stack:**
- **Flag service:** LaunchDarkly, Flagsmith, OpenFeature (vendor-neutral SDK)
- **Traffic splitting:** Istio, Linkerd, AWS App Mesh
- **Progressive rollout automation:** Argo Rollouts, Flagger
- **Analysis:** Prometheus + Grafana, Datadog

---

#### 14. How would you migrate a monolith to microservices incrementally using CI/CD?

**The Strangler Fig Pattern** is the industry-standard approach: you grow the new system around the old one, gradually strangling (replacing) it piece by piece. You never do a big-bang rewrite.

**Phase 0: Instrument the Monolith**
Before extracting anything, add observability:
```
- Distributed tracing (OpenTelemetry) across all monolith modules
- Per-module SLOs (latency, error rate) — you need baselines
- Domain boundary identification: map bounded contexts via code ownership + DB table access patterns
```

**Phase 1: Extract + Proxy (0% traffic to new service)**
```
Traffic → Monolith → [Strangler Proxy] → Monolith handles request
                         │
                         └── New Service (shadow mode, responses discarded)
```
- Build the new service, deploy it alongside the monolith
- **Shadow traffic:** Route a copy of real requests to the new service, compare responses to the monolith — surface divergence without user impact
- Fix divergence before cutting any traffic

**Phase 2: Canary Cut (1% → 100%)**
```
Traffic → [Strangler Proxy]  ──── 99% → Monolith
                              └──  1% → New Service
```
- Proxy (nginx, Envoy, or service mesh rule) splits traffic
- Monitor new service SLOs vs. monolith SLOs
- Gradually shift: 1% → 5% → 25% → 50% → 100%

**Phase 3: Monolith calls New Service internally (for shared data)**
- After full traffic cutover to new service, update monolith to call the new service via API rather than direct DB access
- Enforce the domain boundary: monolith can no longer write to the extracted domain's tables

**Phase 4: Database Separation**
```
Before: Monolith DB (everything in one schema)
After:  Payment Service DB (payments schema)
        Order Service DB   (orders schema)
        Monolith DB        (remaining tables)
```
- Use dual-write + eventual consistency during transition
- Synchronize data with CDC (Change Data Capture — Debezium + Kafka) before cutting the DB connection

**CI/CD enablement throughout:**
- New service gets its own independent pipeline from Day 1 — no coupling to monolith deploy
- Strangler proxy config is in version control — traffic shifts are commits, fully auditable
- Shadow testing in CI: run new service against production traffic snapshots

**Common failure modes:**
- Extracting services before domain boundaries are stable → constant cross-service coupling
- Skipping shadow mode → discovering bugs in production
- Shared DB for too long → services still coupled at storage layer

---

#### 15. How do you handle the "diamond dependency" problem in microservice deployments?

**The diamond dependency problem** occurs when two services (B and C) both depend on a shared service (A), and a fourth service (D) depends on both B and C. When A changes in a breaking way, you must upgrade B and C atomically before D — but in a distributed system, you can't deploy atomically across multiple services.

```
        A (shared lib / shared service)
       / \
      B   C
       \ /
        D
```

**Example:** Service A is a user-profile service. B (notifications) and C (billing) both call A's `/profile` endpoint. D (dashboard) aggregates data from B and C. If A's `/profile` response changes, B and C must both update before D breaks.

**Solution 1: Expand-Contract across the diamond**

```
Step 1: A deploys v2 endpoint (/profile/v2) alongside v1 — EXPAND
Step 2: B deploys, switches to /profile/v2
Step 3: C deploys, switches to /profile/v2
Step 4: D deploys (if needed) — now all upstream services are on v2
Step 5: A removes /profile/v1 — CONTRACT
```

**Solution 2: Consumer-Driven Contract Tests as a dependency gate**

Using Pact:
```
B registers contract: "A's /profile returns {id, name, email}"
C registers contract: "A's /profile returns {id, name, tier}"

A's CI runs pact-broker can-i-deploy:
  → Checks ALL registered consumers (B and C)
  → Only passes if A v2 satisfies ALL consumer contracts
  → If C hasn't updated its contract yet, A cannot deploy
```

**Solution 3: API Versioning + Deprecation SLA**

```
Policy: Old API versions supported for 30 days post-deprecation
  → B and C have 30 days to migrate after A deprecates v1
  → Dashboard (D) is shielded because it only calls B and C, not A directly
  → Deprecation is tracked via metric: requests to /profile/v1 must reach 0 before removal
```

**Solution 4: Schema Registry (for event-driven diamonds)**

If A communicates via events (Kafka) instead of HTTP:
```
A publishes to Kafka topic: user.profile.updated
Schema registered in Confluent Schema Registry
B and C are consumers

Schema evolution rules:
  - BACKWARD compatible changes only (add optional fields)
  - Schema registry enforces compatibility on publish (CI fails if schema breaks consumers)
  - Consumers can read both old and new schema during transition
```

**Solution 5: Dependency graph in deployment orchestrator**

At scale, encode the diamond in the deployment system:
```yaml
# deployment-config.yaml
service: shared-user-service
version: v2.5.0
dependents:
  - notification-service   # must upgrade before A v1 is removed
  - billing-service        # must upgrade before A v1 is removed
sunset_date: 2026-09-01   # auto-enforced by deployment platform
```
The platform blocks the `contract` (removal) deploy of A until all dependents have confirmed migration.

**Staff-level principle:** The diamond problem is fundamentally a **versioning and coordination problem**, not a deployment problem. The solution is making breaking changes safe by treating them as multi-phase, multi-release processes — never as single-step updates. Invest in tooling (Pact Broker, schema registry, deprecation tracking) that makes this coordination automatic rather than relying on human communication.

---

> **Key Takeaway:** CI/CD is not just about automation — it's about building a repeatable, auditable, and safe delivery system that enables teams to ship frequently with confidence. The right strategy depends on your architecture, team size, risk tolerance, and business requirements.
