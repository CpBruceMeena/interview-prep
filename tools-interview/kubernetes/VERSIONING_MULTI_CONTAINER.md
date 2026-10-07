# 📦 Versioning in Multi-Container / Multi-Service Deployments

> **Context:** Staff/Principal Engineer interview — API versioning, database migrations, rolling deployments, container image strategy, and backward compatibility across microservices.
>
> **Focus:** Real production patterns with code examples, not theory.

---

## Table of Contents

1. [Why Versioning Matters in Multi-Container Setups](#1-why-versioning-matters-in-multi-container-setups)
2. [API Versioning Strategies](#2-api-versioning-strategies)
3. [Database Schema Versioning & Migrations](#3-database-schema-versioning-migrations)
4. [Container Image Versioning](#4-container-image-versioning)
5. [Kubernetes Deployment Versioning & Rollbacks](#5-kubernetes-deployment-versioning-rollbacks)
6. [Service Mesh Versioning (Canary & Blue-Green)](#6-service-mesh-versioning-canary-blue-green)
7. [Handling Breaking Changes Across Services](#7-handling-breaking-changes-across-services)
8. [Code Examples: End-to-End Versioning Pipeline](#8-code-examples-end-to-end-versioning-pipeline)

---

## 1. Why Versioning Matters in Multi-Container Setups

In a **monolith**, versioning is simple: deploy one artifact, tag the release. In a **multi-container / microservices architecture**, every service evolves at its own pace. Without a disciplined versioning strategy, you get:

- **Dependency hell:** Service A v2.3 calls Service B v1.7, but v1.7 was already replaced by v3.0 with breaking changes.
- **Inconsistent deployments:** Canary deployment of Service A's v2 goes wrong because it expects a DB schema that hasn't been migrated yet.
- **Rollback nightmares:** Rolling back Service A to v1 means you must also roll back the DB schema, which may have already been used by Service B v2.
- **Debugging chaos:** Which version of which service is running in production? Without proper tagging, you can't tell.

!!! tip "30-second answer"
    During any rollout, old and new versions run **at the same time**: old and new pods, old and new consumers, old and new code against one schema. So every change must be compatible in both directions for at least one release: additive API changes (new major version only for true breaks), **expand → migrate → contract** for schemas, tolerant readers, and schema-registry compatibility rules for events. Deploy images by immutable tag or digest, make the rollout progressive (canary with automated analysis), and keep rollback a code-only operation: you roll code back, not the schema.

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
    cursor = int(request.args.get('cursor', 0))
    users = User.query.filter(User.id > cursor).order_by(User.id).limit(20).all()
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
# Flask example — version via a request header (custom "Accept-Version" here;
# the media-type variant is Accept: application/vnd.example.v2+json)

@app.route('/users')
def list_users():
    version = request.headers.get('Accept-Version', '1')   # default = oldest supported
    
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
**Cons:** Invisible in URLs and logs unless you log the header; caches and CDNs must key on it (`Vary: Accept-Version`), or they serve v1 bodies to v2 clients.

### 2.3 gRPC / Protobuf Versioning (Binary Protocol)

```protobuf
// users/v1/user.proto  (one package per file; v2 lives in users/v2/user.proto)
syntax = "proto3";
package users.v1;          // ← major version in the package name

message User {
    string id = 1;
    string name = 2;
    string email = 3 [deprecated = true];  // keep the field; mark it
    string phone = 4;                      // NON-breaking addition: new number
    reserved 5;                            // a removed field: number never reused
    reserved "fax";
}
```

```protobuf
// users/v2/user.proto: only for a real breaking change (types or semantics change).
// Both packages are served side by side until v1 clients are gone.
syntax = "proto3";
package users.v2;

message User {
    string id = 1;
    string display_name = 2;
    ContactInfo contact = 3;
}

message ContactInfo {
    string email = 1;
    string phone = 2;
}
```

**Key protobuf rules:** never reuse or renumber a field (use `reserved`), never change a field's type, add new fields with new numbers. Old readers skip unknown fields and new readers see defaults for missing ones, so additive changes are compatible both ways. Renames are wire-safe but break JSON transcoding and generated code, so treat them as breaking. Tools like `buf breaking` enforce this in CI.

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
ALTER TABLE users ADD COLUMN contact_email VARCHAR(255);  -- nullable: metadata-only, instant
-- Plain CREATE INDEX blocks writes for the whole build; on a live table use
-- CONCURRENTLY (cannot run inside a transaction block)
CREATE INDEX CONCURRENTLY idx_users_contact_email ON users(contact_email);

-- Trigger keeps both columns in sync while old and new code both write.
-- It must copy whichever column CHANGED; a naive COALESCE would keep a stale
-- contact_email when old code updates email.
CREATE OR REPLACE FUNCTION sync_user_email()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.contact_email := COALESCE(NEW.contact_email, NEW.email);
        NEW.email         := COALESCE(NEW.email, NEW.contact_email);
    ELSIF NEW.email IS DISTINCT FROM OLD.email THEN
        NEW.contact_email := NEW.email;            -- old code wrote email
    ELSIF NEW.contact_email IS DISTINCT FROM OLD.contact_email THEN
        NEW.email := NEW.contact_email;            -- new code wrote contact_email
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sync_user_email
    BEFORE INSERT OR UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION sync_user_email();

-- Backfill: populate contact_email from email.
-- On a large table do this in batches (e.g. 10k ids per transaction) to avoid
-- long locks, bloat and replication lag; shown as one statement for brevity.
UPDATE users SET contact_email = email WHERE contact_email IS NULL;

-- At this point: old code reads/writes `email`, new code reads/writes `contact_email`
-- Both work!

-- ============================================================

-- STEP 2 (Transition): Deploy new code that reads/writes contact_email
-- Old code (still running) reads email (sync trigger keeps it updated)
-- New code reads contact_email

-- ============================================================

-- STEP 3 (Contract): Remove the old column
-- Deploy AFTER old code is completely gone (including batch jobs, other services,
-- BI queries and anything that can still roll back to it)
DROP TRIGGER IF EXISTS trg_sync_user_email ON users;
DROP FUNCTION IF EXISTS sync_user_email();
ALTER TABLE users DROP COLUMN email;
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
    
    # Backfill (fine for small tables; batch it outside the migration for large ones,
    # since Alembic runs the whole migration in one transaction on Postgres)
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

With expand-contract, **rolling back is a code-only operation**. The expanded schema already works with v1, so you roll the Deployment back and leave the schema alone. Running the down migration would drop `contact_email` and destroy every value v2 wrote. Down migrations are for dev environments or for migrations nothing has used yet; in production you fix forward.

```bash
#!/bin/bash
# If v2 misbehaves: roll back CODE, keep the expanded schema.
set -euo pipefail

echo "Step 1: Roll back the deployment"
kubectl rollout undo deployment/user-service
kubectl rollout status deployment/user-service --timeout=5m

echo "Step 2: Verify all pods run the old image"
kubectl get pods -l app=user-service \
  -o jsonpath='{range .items[*]}{.spec.containers[0].image}{"\n"}{end}' | sort | uniq -c
# Expected: only user-service:v1.x

echo "Step 3: Leave the schema as is. The sync trigger keeps email and"
echo "contact_email consistent, so v1 keeps working and v2 can be re-deployed."
```

---

## 4. Container Image Versioning

### 4.1 Tagging Strategy

```yaml
# Bad: moving tags in deployment manifests
registry.example.com/user-service:latest     # ← NEVER deploy this
registry.example.com/user-service:stable     # ← same problem
# Nodes cache images, so pods on different nodes can run different "latest" builds,
# and rollbacks can't target a known artifact.

# Good: unique, traceable tags
registry.example.com/user-service:v1.2.3           # Semantic version
registry.example.com/user-service:v1.2.3-abcdef1   # + git SHA (unique per build)

# Best: deploy by digest (or tag@digest). A tag is only immutable if the registry
# enforces it (e.g. ECR tag immutability, Harbor immutable tag rules); a digest
# always identifies the exact bytes, and image signing/admission policies key on it.
registry.example.com/user-service:v1.2.3@sha256:4f1c...e9
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
      version: ${{ steps.meta.outputs.version }}   # must reference the step id "meta"
      sha: ${{ steps.meta.outputs.sha }}
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Extract metadata
        id: meta
        run: |
          echo "version=v$(jq -r .version services/user-service/package.json)" >> $GITHUB_OUTPUT
          echo "sha=${GITHUB_SHA::7}" >> $GITHUB_OUTPUT
      
      - name: Build and push
        uses: docker/build-push-action@v6
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
  minReadySeconds: 30                # Pod must stay Ready 30s before it counts as available
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
        version: v2                         # coarse label used by mesh subsets
        app.kubernetes.io/version: v2.0.0   # exact version for dashboards/alerts
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
# 2         v1.1.0: Add logging
# 3         v1.2.0: Bug fix
# 4         v2.0.0: Rename email to contact_email
# 5         v2.0.1: Hotfix                         ← current
# `undo --to-revision=3` re-applies revision 3's pod template as a NEW revision 6.
# Rollback only restores the pod template: not ConfigMaps/Secrets it references,
# not the schema, not other services. In GitOps setups, revert the commit instead,
# or the controller will re-apply the bad version.
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
    interval: 30s                # run checks every 30s
    threshold: 5                 # roll back after 5 FAILED checks (not a % error rate)
    maxWeight: 50                # Max 50% traffic to canary
    stepWeight: 5                # +5% per passing interval → 10 steps ≈ 5 min to 50%
    metrics:
    - name: request-success-rate # built-in metric (needs a mesh/ingress provider)
      thresholdRange:
        min: 99                  # ≥ 99% non-5xx
      interval: 1m
    - name: request-duration
      thresholdRange:
        max: 500                 # p99 latency ≤ 500ms
      interval: 1m
    webhooks:
    - name: load-test
      url: http://flagger-loadtester/
      timeout: 5s
      metadata:
        cmd: "hey -z 2m -q 10 http://user-service-canary:8080/health"

# Flagger automates:
# 1. Copies your Deployment to user-service-primary (serves traffic); your own
#    Deployment becomes the canary and is scaled to 0 between releases
# 2. On a new pod template it scales the canary up and shifts traffic
#    5% → 10% → ... → 50% via the mesh / ingress / Gateway API
# 3. At each step, checks success rate + latency (and runs webhooks, e.g. load tests)
# 4. If `threshold` checks fail → route 100% back to primary, scale canary to 0
# 5. If it reaches maxWeight healthy → copy the new spec to primary, then scale canary to 0
```

---

## 6. Service Mesh Versioning (Canary & Blue-Green)

### 6.1 Istio VirtualService for Canary Deployments

```yaml
# istio-canary.yaml
apiVersion: networking.istio.io/v1    # v1 is GA since Istio 1.22; v1beta1 still served
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
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata:
  name: user-service
spec:
  host: user-service
  subsets:
  - name: v1
    labels:
      version: v1                    # pods need a matching label; keep it coarse
  - name: v2
    labels:
      version: v2
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
  ports:
  - port: 80
    targetPort: 8080

---
# Step 3: After green is verified (smoke tests against a separate green Service),
# switch the live Service to green:
# kubectl patch service user-service -p '{"spec":{"selector":{"app":"user-service","color":"green"}}}'
# The switch is "atomic" for NEW connections only: existing keep-alive connections
# stay on blue until they close, so drain blue gracefully.

# Step 4: Keep blue running for fast rollback (patch the selector back), then
# scale blue down once green has proven itself. Cost: 2× capacity during the switch,
# and the DB schema must work for both colours (expand-contract again).
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
    appProtocol: grpc

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
    appProtocol: grpc

---
# gRPC uses long-lived HTTP/2 connections: kube-proxy balances per CONNECTION, so
# one client can pin to one pod. Use client-side balancing (headless Service +
# round_robin), a mesh, or periodic connection recycling (MaxConnectionAge).
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

import ldclient
from ldclient import Context
from ldclient.config import Config

ldclient.set_config(Config("sdk-key"))
client = ldclient.get()

class UserService:
    def list_users(self):
        # Check if user is in the v2 experiment
        use_v2_response = client.variation(
            "user-list-v2-response",                 # Feature flag key
            Context.builder(current_user_id).build(),  # Evaluation context
            False                                    # Default if flag service is down: v1
        )
        
        if use_v2_response:
            return self._list_users_v2()  # New format
        else:
            return self._list_users_v1()  # Old format
    
    def _list_users_v2(self):
        """V2 response with pagination and phone numbers"""
        cursor = int(request.args.get('cursor', 0))
        users = User.query.filter(User.id > cursor).limit(20).all()
        return {
            "data": [{"id": u.id, "name": u.name, "phone": u.phone}
                     for u in users],
            "next_cursor": users[-1].id if len(users) == 20 else None
        }
```

### 7.3 Versioned Event Schemas (Kafka)

```javascript
// Kafka event: UserCreated (JSON shown; Avro/Protobuf work the same way)
// Rule: never modify or remove existing fields; add new OPTIONAL fields with defaults.
// Use a Schema Registry compatibility mode to enforce it at produce time:
//   BACKWARD (default): new schema can read old data → upgrade consumers first
//   FORWARD:  old schema can read new data           → upgrade producers first
//   FULL:     both                                   → any order

// schema_version 2 of the event (v1 had no "phone")
{
  "schema_version": 2,
  "event_type": "UserCreated",
  "user_id": "abc-123",
  "name": "Alice",
  "email": "alice@example.com",
  "phone": null,                    // ← Added in v2, null for backward compat
  "timestamp": 1704067200000
}

// A consumer written for v1 can still read v2 events: it ignores "phone"
// (tolerant reader). Topics are replayed and retained, so consumers must also keep
// reading OLD versions for as long as retention (or compaction) keeps them.
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
- [ ] Rollback plan documented (code-only rollback; schema stays expanded until contract)
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
        uses: docker/build-push-action@v6
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
          # (In practice let Flagger/Argo Rollouts do this analysis; shown for clarity.)
          ERROR_RATE=$(curl -s --get http://prometheus:9090/api/v1/query \
            --data-urlencode 'query=sum(rate(http_requests_total{app="user-service",version="v2",code=~"5.."}[5m])) / sum(rate(http_requests_total{app="user-service",version="v2"}[5m]))' \
            | jq -r '.data.result[0].value[1] // "0"')
          # [ "$A" > "B" ] would be a shell REDIRECT, not a comparison; compare floats with awk
          if awk -v r="$ERROR_RATE" 'BEGIN { exit !(r > 0.01) }'; then
            echo "Error rate $ERROR_RATE too high! Rolling back..."
            kubectl apply -f k8s/istio-canary-v1.yaml  # Rollback
            exit 1
          fi
      
      - name: Promote to 100%
        run: |
          kubectl set image deployment/user-service \
            user-service=${{ env.REGISTRY }}/${{ env.SERVICE }}:${{ needs.build-and-push.outputs.version }}
          kubectl apply -f k8s/istio-primary-v2.yaml

# CONTRACT is NOT a job in this pipeline: a GitHub-hosted job can't wait 24h
# (6h job limit), and the trigger is a human/automated CHECK, not a timer.
# Ship it as the next release's migration, gated on evidence that nothing reads
# `email` anymore (all deployments on ≥ v2, pg_stat_statements shows no queries
# touching the column, a protected-environment approval):
#
#   DROP TRIGGER IF EXISTS trg_sync_user_email ON users;
#   DROP FUNCTION IF EXISTS sync_user_email();
#   ALTER TABLE users DROP COLUMN IF EXISTS email;
```

### 8.2 Health Check Endpoint for Version Awareness

```python
# Version/build info endpoint for operators. Keep it separate from the probe endpoints
# (probes must be cheap and must not depend on Redis/Kafka), and don't expose hosts
# publicly. For dashboards, also export a constant metric such as
#   app_build_info{version="v2.0.0", commit="a1b2c3d4"} 1
# so every graph can be split by version during a canary.
import time
START_TIME = time.time()

@app.route('/internal/version')
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
