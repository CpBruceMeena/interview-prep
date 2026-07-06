# 📦 Versioning in Multi-Container / Multi-Service Deployments

> **Context:** Staff/Principal Engineer interview — API versioning, database migrations, rolling deployments, container image strategy, and backward compatibility across microservices.  \n
> **Focus:** Real production patterns with code examples, not theory.

---

## Table of Contents

1. [Why Versioning Matters in Multi-Container Setups](#1-why-versioning-matters-in-multi-container-setups)
2. [API Versioning Strategies](#2-api-versioning-strategies)
3. [Database Schema Versioning & Migrations](#3-database-schema-versioning--migrations)
4. [Container Image Versioning](#4-container-image-versioning)
5. [Kubernetes Deployment Versioning & Rollbacks](#5-kubernetes-deployment-versioning--rollbacks)
6. [Service Mesh Versioning (Canary & Blue-Green)](#6-service-mesh-versioning-canary--blue-green)
7. [Handling Breaking Changes Across Services](#7-handling-breaking-changes-across-services)
8. [Code Examples: End-to-End Versioning Pipeline](#8-code-examples-end-to-end-versioning-pipeline)

---

## 1. Why Versioning Matters in Multi-Container Setups

In a **monolith**, versioning is simple: deploy one artifact, tag the release. In a **multi-container / microservices architecture**, every service evolves at its own pace. Without a disciplined versioning strategy, you get:

- **Dependency hell:** Service A v2.3 calls Service B v1.7, but v1.7 was already replaced by v3.0 with breaking changes.
- **Inconsistent deployments:** Canary deployment of Service A's v2 goes wrong because it expects a DB schema that hasn't been migrated yet.
- **Rollback nightmares:** Rolling back Service A to v1 means you must also roll back the DB schema, which may have already been used by Service B v2.
- **Debugging chaos:** Which version of which service is running in production? Without proper tagging, you can't tell.

### Core Principles

| Principle | Description |
|-----------|-------------|
| **Independent versioning** | Each service owns its version number. No global release version. |
| **Backward compatibility** | Always design for N-1 compatibility. A service should work with one version older of its dependencies. |
| **Semantic versioning** | `MAJOR.MINOR.PATCH` — breaking changes, new features, bug fixes. |
| **Immutable tags** | Once a container image tag is pushed, never overwrite it. |
| **Expand-contract migrations** | DB schema changes must be backward compatible for at least one deploy cycle. |

---

## 2. API Versioning Strategies

### 2.1 URL Path Versioning (Most Common)

```python
# Flask example — version in URL path

@app.route('/v1/users')
def list_users_v1():
    """V1: Returns id, name, email"""
    return jsonify([{"id": u.id, "name": u.name, "email": u.email}
                    for u in User.query.all()])

@app.route('/v2/users')
def list_users_v2():
    """V2: Adds phone, removes email, uses cursor pagination"""
    cursor = request.args.get('cursor')
    users = User.query.filter(User.id > cursor).limit(20).all()
    return jsonify({
        "data": [{"id": u.id, "name": u.name, "phone": u.phone}
                 for u in users],
        "next_cursor": users[-1].id if users else None
    })
```

**Pros:** Simple, explicit, cache-friendly (different URL = different cache key).  \
**Cons:** URL pollution, can't negotiate version by client type.

### 2.2 Header Versioning (Cleaner URL)

```python
# Flask example — version via Accept header

@app.route('/users')
def list_users():
    version = request.headers.get('Accept-Version', '1')
    
    if version == '1':
        return jsonify([u.to_dict_v1() for u in User.query.all()])
    elif version == '2':
        return jsonify({
            "data": [u.to_dict_v2() for u in User.query.limit(20).all()],
            "next_cursor": None
        })
    else:
        return jsonify({"error": f"Unsupported version: {version}"}), 400
```

**Pros:** Clean URLs, RESTful, version negotiation.  \
**Cons:** Not visible in browser dev tools, harder to cache.

### 2.3 gRPC / Protobuf Versioning (Binary Protocol)

```protobuf
// users.proto
syntax = "proto3";

package users.v1;       // ← Version in package name!

message UserV1 {
    string id = 1;
    string name = 2;
    string email = 3;
}

// New version adds phone, deprecates email
package users.v2;

message UserV2 {
    string id = 1;
    string name = 2;
    string phone = 3;      // New field
    string email = 4 [deprecated = true];  // Still present for backward compat
}
```

**Key gRPC rule:** Never re-use field numbers. Always add new fields. Old clients ignore unknown fields. This makes gRPC naturally backward-compatible.

### 2.4 Version Compatibility Matrix

```yaml
# Compatibility: which service versions work together
# Updated after every major version bump

services:
  user-service:
    v1: compatible with order-service v1, v2
    v2: compatible with order-service v2, v3  # v1 dropped!
  
  order-service:
    v1: compatible with payment-service v1, v2
    v2: compatible with payment-service v2
    v3: compatible with payment-service v2, v3

  payment-service:
    v1: depends on user-service v1
    v2: depends on user-service v1, v2
    v3: depends on user-service v2  # v1 dropped
```

---

## 3. Database Schema Versioning & Migrations

### 3.1 The Expand-Contract Pattern (Critical for Zero-Downtime)

In a multi-container deployment, multiple versions of a service run simultaneously during rolling updates. The DB schema must work with **both old and new code** at the same time.

```sql
-- ============================================================
-- Example: Renaming `email` to `contact_email`
-- ============================================================

-- STEP 1 (Expand): Add the new column + keep old one
-- Deploy this BEFORE the new code
ALTER TABLE users ADD COLUMN contact_email VARCHAR(255);
CREATE INDEX idx_users_contact_email ON users(contact_email);

-- Create a trigger to keep both columns in sync
CREATE OR REPLACE FUNCTION sync_user_email()
RETURNS TRIGGER AS $$
BEGIN
    NEW.contact_email = COALESCE(NEW.contact_email, NEW.email);
    NEW.email = COALESCE(NEW.email, NEW.contact_email);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sync_user_email
    BEFORE INSERT OR UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION sync_user_email();

-- Backfill: populate contact_email from email
UPDATE users SET contact_email = email WHERE contact_email IS NULL;

-- At this point: old code reads/writes `email`, new code reads/writes `contact_email`
-- Both work!

-- ============================================================

-- STEP 2 (Transition): Deploy new code that reads/writes contact_email
-- Old code (still running) reads email (sync trigger keeps it updated)
-- New code reads contact_email

-- ============================================================

-- STEP 3 (Contract): Remove the old column
-- Deploy AFTER old code is completely gone
ALTER TABLE users DROP COLUMN email CASCADE;
DROP TRIGGER IF EXISTS trg_sync_user_email ON users;
DROP FUNCTION IF EXISTS sync_user_email();
```

### 3.2 Migration Tooling (Alembic Example)

```python
# alembic/versions/002_add_contact_email.py
"""add contact_email to users

Revision ID: 002
Revises: 001
Create Date: 2024-01-15 10:30:00

This is an EXPAND step — keeps backward compatibility.
"""

from alembic import op
import sqlalchemy as sa

revision = '002'
down_revision = '001'


def upgrade():
    # Add new column as nullable (old code doesn't know about it)
    op.add_column('users', sa.Column('contact_email', sa.String(255), nullable=True))
    op.create_index('idx_users_contact_email', 'users', ['contact_email'])
    
    # Backfill
    op.execute("UPDATE users SET contact_email = email WHERE contact_email IS NULL")


def downgrade():
    # Reversible: if rollback needed before old code is gone
    op.drop_index('idx_users_contact_email', table_name='users')
    op.drop_column('users', 'contact_email')
```

### 3.3 Multi-Service Migration Coordination

```yaml
# migration-plan.yaml
# Coordinated migration across 4 services + DB

migration: RENAME_EMAIL_TO_CONTACT_EMAIL
status: IN_PROGRESS

steps:
  - phase: EXPAND
    description: Add contact_email column, create sync trigger
    risk: LOW (non-breaking)
    sql_file: migrations/002_add_contact_email.sql
    rollback: migrations/002_rollback.sql
    completed_at: 2024-01-15T10:00:00Z
    
  - phase: DEPLOY_V2_CODE
    description: Deploy v2 of user-service, notification-service
    risk: MEDIUM (new code reads contact_email)
    services_updated:
      - user-service: v1.0.0 → v2.0.0
      - notification-service: v1.2.0 → v2.0.0
    verification:
      - Check logs for "contact_email" reads
      - Verify sync trigger is working (email == contact_email)
    completed_at: 2024-01-15T11:30:00Z
    
  - phase: MONITOR
    description: Run in dual-write mode for 24 hours
    duration: 24h
    checks:
      - Alert if email != contact_email for any row
      - Alert if error rate > 0.1% on either service
    
  - phase: CONTRACT
    description: Drop old email column, remove trigger
    risk: HIGH (breaking if old code is still running)
    requires: ALL services using 'email' have been updated
    sql_file: migrations/003_drop_email.sql
    scheduled_at: 2024-01-16T11:30:00Z
```

### 3.4 Handling Rollbacks with Schema Migrations

```bash
# If v2 deploy fails, rollback order is CRITICAL:
# 1. Roll back service code to v1 (kubectl rollout undo)
# 2. Run DB migration DOWN (only if schema change hasn't been consumed)

# Rollback script:
#!/bin/bash
set -euo pipefail

echo "Step 1: Rollback service deployments"
kubectl rollout undo deployment/user-service
kubectl rollout status deployment/user-service --timeout=5m

echo "Step 2: Verify all pods are on v1"
kubectl get pods -l app=user-service -o jsonpath='{.items[*].spec.containers[*].image}'
# Expected: user-service:v1.0.0 (not v2.0.0)

echo "Step 3: Run DB migration DOWN"
alembic downgrade -1  # Revert the last migration
```

---

## 4. Container Image Versioning

### 4.1 Tagging Strategy

```yaml
# Bad: mutable tags cause production issues
registry.example.com/user-service:latest     # ← NEVER do this!
registry.example.com/user-service:stable     # ← Also bad!

# Good: immutable, traceable tags
registry.example.com/user-service:v1.2.3           # Semantic version
registry.example.com/user-service:v1.2.3-build.456 # + CI build number
registry.example.com/user-service:sha-a1b2c3d4     # Git commit SHA

# Best: combination for human-readability + traceability
registry.example.com/user-service:v1.2.3
registry.example.com/user-service:v1.2.3-abcdef1
```

### 4.2 Multi-Architecture Images

```bash
# Build for both amd64 and arm64 with a single manifest
#!/bin/bash
set -euo pipefail

VERSION="v1.2.3"
SHA="${GITHUB_SHA::7}"

# Build for each architecture
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --tag registry.example.com/user-service:${VERSION} \
  --tag registry.example.com/user-service:${VERSION}-${SHA} \
  --tag registry.example.com/user-service:latest \
  --push \
  .

# The manifest automatically selects the right image per architecture
# On arm64 nodes: pulls the arm64 image
# On amd64 nodes: pulls the amd64 image
```

### 4.3 CI/CD Pipeline with Immutable Tags

```yaml
# .github/workflows/deploy.yml
name: Build and Deploy

on:
  push:
    branches: [main]
    paths:
      - 'services/user-service/**'

env:
  REGISTRY: registry.example.com
  SERVICE: user-service

jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      version: ${{ steps.version.outputs.version }}
      sha: ${{ steps.sha.outputs.sha }}
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Extract metadata
        id: meta
        run: |
          echo "version=v$(jq -r .version services/user-service/package.json)" >> $GITHUB_OUTPUT
          echo "sha=${GITHUB_SHA::7}" >> $GITHUB_OUTPUT
      
      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: services/user-service
          push: true
          tags: |
            ${{ env.REGISTRY }}/${{ env.SERVICE }}:${{ steps.meta.outputs.version }}
            ${{ env.REGISTRY }}/${{ env.SERVICE }}:${{ steps.meta.outputs.version }}-${{ steps.meta.outputs.sha }}
  
  deploy-staging:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - run: |
          kubectl set image deployment/user-service \
            user-service=${{ env.REGISTRY }}/${{ env.SERVICE }}:${{ needs.build.outputs.version }}
  
  deploy-production:
    needs: [build, deploy-staging]
    runs-on: ubuntu-latest
    environment: production
    steps:
      - run: |
          # Gradual rollout
          kubectl set image deployment/user-service \
            user-service=${{ env.REGISTRY }}/${{ env.SERVICE }}:${{ needs.build.outputs.version }}
```

---

## 5. Kubernetes Deployment Versioning & Rollbacks

### 5.1 Deployment with Revision History

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: user-service
  annotations:
    kubernetes.io/change-cause: "v2.0.0: Rename email to contact_email"
spec:
  replicas: 5
  revisionHistoryLimit: 5           # Keep last 5 revisions for rollback
  minReadySeconds: 30                # Wait 30s after pod is ready
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1                    # Roll 1 at a time (safe)
      maxUnavailable: 0              # Always serve traffic
  selector:
    matchLabels:
      app: user-service
  template:
    metadata:
      labels:
        app: user-service
        version: v2.0.0              # Label for monitoring
    spec:
      containers:
      - name: user-service
        image: registry.example.com/user-service:v2.0.0
        readinessProbe:              # ← CRITICAL for zero-downtime
          httpGet:
            path: /health/ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 30
```

### 5.2 Rolling Update Process

```bash
# 1. Apply the new deployment
kubectl apply -f deployment.yaml

# 2. Watch the rollout
kubectl rollout status deployment/user-service --watch

# 3. If something goes wrong, rollback immediately
kubectl rollout undo deployment/user-service

# 4. Rollback to a specific revision
kubectl rollout undo deployment/user-service --to-revision=3

# 5. View revision history
kubectl rollout history deployment/user-service
# Output:
# REVISION  CHANGE-CAUSE
# 1         v1.0.0: Initial deploy
# 2         v1.1.0: Add logging
# 3         v1.2.0: Bug fix
# 4         v2.0.0: Rename email to contact_email  ← Current
# 5         v2.0.1: Hotfix  ← Rolling back to this
```

### 5.3 Progressive Delivery with Flagger (Automated Canary)

```yaml
# flagger-canary.yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: user-service
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: user-service
  service:
    port: 8080
  analysis:
    interval: 30s
    iterations: 10               # 10 × 30s = 5 min total analysis
    threshold: 5                 # Max 5% error rate
    maxWeight: 50                # Max 50% traffic to canary
    stepWeight: 5                # Increment traffic by 5% each iteration
    metrics:
    - name: request-success-rate
      threshold: 99              # 99% of requests must succeed
      interval: 1m
    - name: request-duration
      threshold: 500             # p99 latency < 500ms
      interval: 1m
    webhooks:
    - name: load-test
      url: http://flagger-loadtester/
      timeout: 5s
      metadata:
        cmd: "hey -z 2m -q 10 http://user-service-canary:8080/health"

# Flagger automates:
# 1. Creates canary deployment (user-service-canary) with new version
# 2. Incrementally shifts traffic: 5% → 10% → 15% → ... → 50%
# 3. At each step, checks success rate + latency
# 4. If metrics degrade → full rollback automatically
# 5. If all iterations pass → promote canary to primary
```

---

## 6. Service Mesh Versioning (Canary & Blue-Green)

### 6.1 Istio VirtualService for Canary Deployments

```yaml
# istio-canary.yaml
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
          exact: "true"              # Route based on header
    route:
    - destination:
        host: user-service
        subset: v2
      weight: 100
  - route:
    - destination:
        host: user-service
        subset: v1
      weight: 90                     # 90% traffic to v1
    - destination:
        host: user-service
        subset: v2
      weight: 10                     # 10% traffic to v2

---
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: user-service
spec:
  host: user-service
  subsets:
  - name: v1
    labels:
      version: v1.0.0
  - name: v2
    labels:
      version: v2.0.0
```

### 6.2 Blue-Green Deployment

```yaml
# Blue-green: two identical environments, switch traffic atomically

# Step 1: Deploy "green" alongside existing "blue"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: user-service-green
  labels:
    app: user-service
    color: green
spec:
  replicas: 5
  selector:
    matchLabels:
      app: user-service
      color: green
  template:
    metadata:
      labels:
        app: user-service
        color: green
    spec:
      containers:
      - name: user-service
        image: registry.example.com/user-service:v2.0.0
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8080

---
# Step 2: Service initially points to blue
apiVersion: v1
kind: Service
metadata:
  name: user-service
spec:
  selector:
    app: user-service
    color: blue

---
# Step 3: After green is verified, switch service to green
# kubectl patch service user-service -p '{"spec":{"selector":{"color":"green"}}}'

# Step 4: Keep blue for rollback. Scale down green if promoted.
# Rollback: patch service back to blue
```

### 6.3 gRPC Service Versioning with Multiple Deployments

```yaml
# Run both v1 and v2 of the same gRPC service simultaneously
# Clients can target either version

apiVersion: v1
kind: Service
metadata:
  name: user-service-v1          # v1 endpoint
spec:
  selector:
    app: user-service
    version: v1
  ports:
  - port: 50051

---
apiVersion: v1
kind: Service
metadata:
  name: user-service-v2          # v2 endpoint
spec:
  selector:
    app: user-service
    version: v2
  ports:
  - port: 50051

---
# Client configuration: choose which version to call
# user-service-v1.default.svc.cluster.local:50051 → v1
# user-service-v2.default.svc.cluster.local:50051 → v2
```

---

## 7. Handling Breaking Changes Across Services

### 7.1 Tolerant Reader Pattern (Consumer-Side)

```python
# Consumer should be tolerant of extra fields
# This way, even if the producer adds a field, the consumer still works.

class UserServiceClient:
    def get_user(self, user_id: str) -> Optional[User]:
        response = requests.get(f"http://user-service/v2/users/{user_id}")
        data = response.json()
        
        # Tolerant reader: ignore unknown fields, handle missing fields
        return User(
            id=data.get("id"),
            name=data.get("name", "Unknown"),
            email=data.get("email"),                 # May be None (v2 moved to contact_email)
            phone=data.get("phone"),                 # Added in v2, absent in v1
            # Ignore: contact_email, created_at, updated_at, etc.
        )
```

### 7.2 Feature Flags for Gradual Rollout

```python
# Feature flags let you deploy code that's "dark" (not active)
# This decouples deployment from feature activation.

from launchdarkly import LDClient

client = LDClient("sdk-key")

class UserService:
    def list_users(self):
        # Check if user is in the v2 experiment
        use_v2_response = client.variation(
            "user-list-v2-response",     # Feature flag key
            {"key": current_user_id},     # User context
            False                         # Default: use v1
        )
        
        if use_v2_response:
            return self._list_users_v2()  # New format
        else:
            return self._list_users_v1()  # Old format
    
    def _list_users_v2(self):
        """V2 response with pagination and phone numbers"""
        cursor = request.args.get('cursor', 0)
        users = User.query.filter(User.id > cursor).limit(20).all()
        return {
            "data": [{"id": u.id, "name": u.name, "phone": u.phone}
                     for u in users],
            "next_cursor": users[-1].id if len(users) == 20 else None
        }
```

### 7.3 Versioned Event Schemas (Kafka)

```json
// Kafka event: UserCreated
// Rule: never modify existing fields, only add new ones.
// Use Schema Registry to enforce compatibility.

// v1 event (evolved from original)
{
  "schema_version": 2,
  "event_type": "UserCreated",
  "user_id": "abc-123",
  "name": "Alice",
  "email": "alice@example.com",
  "phone": null,                    // ← Added in v2, null for backward compat
  "timestamp": 1704067200000
}

// Consumer that only processes v1 events can still read v2 events:
// It ignores "phone" field (tolerant reader).
```

### 7.4 Breaking Change Checklist

```markdown
## Breaking Change Checklist

Before releasing a MAJOR version (breaking change):

- [ ] All downstream consumers are notified (Slack, email, GitHub discussion)
- [ ] Migration guide published (what changed, how to adapt)
- [ ] Old API version remains available for at least 3 months (URL versioning)
- [ ] Database migration follows expand-contract pattern
- [ ] Feature flags in place for gradual rollout
- [ ] Monitoring dashboards updated to compare v1 vs v2 metrics
- [ ] Rollback plan documented (code rollback + DB migration down)
- [ ] Canary deployment configured with Flagger/Istio
- [ ] Load test run against v2 to verify performance
- [ ] All dependent services tested against new version in staging
```

---

## 8. Code Examples: End-to-End Versioning Pipeline

### 8.1 Complete CI/CD with Version Management

```yaml
# .github/workflows/release.yml
# Automated release pipeline with semantic versioning + DB migrations

name: Release Pipeline

on:
  push:
    tags:
      - 'v*'  # e.g., v2.0.0, v2.0.1

env:
  REGISTRY: registry.example.com
  SERVICE: user-service

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Validate version tag matches package.json
        run: |
          TAG_VERSION="${GITHUB_REF_NAME#v}"       # v2.0.0 → 2.0.0
          PKG_VERSION=$(jq -r .version services/user-service/package.json)
          if [ "$TAG_VERSION" != "$PKG_VERSION" ]; then
            echo "Tag $TAG_VERSION != package.json $PKG_VERSION"
            exit 1
          fi

  migrate-db:
    needs: validate
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v4
      
      - name: Run DB migrations (EXPAND phase)
        run: |
          # Run only non-breaking expansion migrations
          alembic upgrade head
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
      
      - name: Verify migration health
        run: |
          # Check that both old and new columns are consistent
          psql "$DATABASE_URL" -c "
            SELECT COUNT(*) FROM users 
            WHERE contact_email IS NULL OR email IS NULL;
          "

  build-and-push:
    needs: validate
    runs-on: ubuntu-latest
    outputs:
      version: ${{ steps.meta.outputs.version }}
    steps:
      - uses: actions/checkout@v4
      
      - name: Extract version
        id: meta
        run: echo "version=v$(jq -r .version services/user-service/package.json)" >> $GITHUB_OUTPUT
      
      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: services/user-service
          push: true
          tags: |
            ${{ env.REGISTRY }}/${{ env.SERVICE }}:${{ steps.meta.outputs.version }}
            ${{ env.REGISTRY }}/${{ env.SERVICE }}:${{ steps.meta.outputs.version }}-${{ github.sha }}

  deploy-staging:
    needs: build-and-push
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - run: |
          kubectl set image deployment/user-service \
            user-service=${{ env.REGISTRY }}/${{ env.SERVICE }}:${{ needs.build-and-push.outputs.version }}
      
      - run: kubectl rollout status deployment/user-service --timeout=5m
      
      - name: Integration tests
        run: |
          # Test both v1 and v2 endpoints work
          curl -f http://user-service.staging:8080/v1/users/1
          curl -f http://user-service.staging:8080/v2/users/1

  deploy-production:
    needs: [build-and-push, migrate-db, deploy-staging]
    runs-on: ubuntu-latest
    environment: production
    steps:
      - name: Canary deploy 10%
        run: |
          # Set traffic split via Istio
          kubectl apply -f k8s/istio-canary-v2.yaml
      
      - name: Wait for canary validation (5 min)
        run: sleep 300
      
      - name: Check canary metrics
        run: |
          ERROR_RATE=$(curl -s prometheus:9090/api/v1/query?query=...)
          if [ "$ERROR_RATE" > "0.01" ]; then
            echo "Error rate too high! Rolling back..."
            kubectl apply -f k8s/istio-canary-v1.yaml  # Rollback
            exit 1
          fi
      
      - name: Promote to 100%
        run: |
          kubectl set image deployment/user-service \
            user-service=${{ env.REGISTRY }}/${{ env.SERVICE }}:${{ needs.build-and-push.outputs.version }}
          kubectl apply -f k8s/istio-primary-v2.yaml

  contract-db:
    needs: deploy-production
    runs-on: ubuntu-latest
    environment: production
    steps:
      - name: Wait for old pods to drain (24h)
        run: sleep 86400   # 24 hours
      
      - name: Run CONTRACT migration (drop old columns)
        run: |
          # Only run this AFTER verifying no old code is running
          psql "$DATABASE_URL" -c "
            ALTER TABLE users DROP COLUMN IF EXISTS email;
            DROP TRIGGER IF EXISTS trg_sync_user_email ON users;
          "
      
      - name: Update migration plan
        run: |
          echo "migration: RENAME_EMAIL complete" >> deployment-log.txt
```

### 8.2 Health Check Endpoint for Version Awareness

```python
# /health endpoint that reports version info for operational awareness
# This lets monitoring tools know which version is deployed

@app.route('/health')
def health():
    return jsonify({
        "service": "user-service",
        "version": "v2.0.0",
        "commit": "a1b2c3d4",
        "build_time": "2024-01-15T10:00:00Z",
        "dependencies": {
            "database": {
                "host": "postgres-primary",
                "schema_version": 12,
                "status": "connected"
            },
            "redis": {
                "host": "redis-cluster",
                "status": "connected"
            },
            "kafka": {
                "broker": "kafka-broker:9092",
                "last_heartbeat": "2024-01-15T12:00:00Z"
            }
        },
        "uptime_seconds": (time.time() - START_TIME),
        "deployment": {
            "strategy": "rolling-update",
            "previous_version": "v1.3.0"
        }
    })
```

---

## Summary: Versioning Decision Matrix

| Scenario | Recommended Strategy | Why |
|----------|---------------------|-----|
| **Public REST API** | URL path versioning (`/v2/users`) | Clear, cacheable, easy to deprecate |
| **Internal microservice** | Header versioning + gRPC | Clean URLs, protocol-level compat |
| **Database schema change** | Expand-contract (3-phase) | Zero-downtime, safe rollback |
| **Container images** | Semver + commit SHA tags | Traceable, immutable |
| **Kubernetes deploy** | Rolling update + revision history | Automatic rollback support |
| **High-risk deploy** | Canary (Istio/Flagger) + feature flags | Gradual rollout, automated rollback |
| **Event/streaming** | Schema Registry + tolerant reader | Backward/forward compatible |
| **Multi-service migration** | Coordinated phases + migration plan | Avoids dependency hell |

> **Principle:** Versioning is not just about code — it's about maintaining **safety** and **operability** across independently deployed services. Every version bump should answer: \"Can I rollback?\" with a clear \"Yes.\"
