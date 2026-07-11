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

```
Users ─▶ Load Balancer ──── 90% ──▶ Old Version (v1)
                           └── 10% ──▶ New Version (v2)

Monitor metrics for 10% canary. If healthy → 25% → 50% → 100%.
If degraded → rollback instantly.
```

### Feature Flags (Feature Toggles)

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

10. **Design a CI/CD pipeline for a 50-microservice system with polyglot services (Go, Python, Java). How do you handle cross-service contract testing?**
11. **How do you ensure backward compatibility during a multi-service rollout?**
12. **Design a deployment system that can handle 1,000+ deployments per day across 200 services.**
13. **How do you implement progressive delivery with feature flags and canary releases in a service mesh?**
14. **How would you migrate a monolith to microservices incrementally using CI/CD?**
15. **How do you handle the "diamond dependency" problem in microservice deployments?**

---

> **Key Takeaway:** CI/CD is not just about automation — it's about building a repeatable, auditable, and safe delivery system that enables teams to ship frequently with confidence. The right strategy depends on your architecture, team size, risk tolerance, and business requirements.
