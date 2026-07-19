# 🚀 Forward Deploy Engineer — Comprehensive Preparation Guide

> **Target Role:** Forward Deployed Engineer (FDE) at AI companies  
> **Also known as:** Solutions Engineer · Customer Engineer · Deployment Engineer · Field Engineering  
> **Level:** Mid-Senior to Staff

---

## Table of Contents

1. [What is a Forward Deployed Engineer?](#1-what-is-a-forward-deployed-engineer)
2. [Core FDE Skills](#2-core-fde-skills)
3. [Deployment Patterns for AI Systems](#3-deployment-patterns-for-ai-systems)
4. [Enterprise Integration & Security](#4-enterprise-integration-security)
5. [Data Pipeline Integration](#5-data-pipeline-integration)
6. [On-Premise & Air-Gapped Deployment](#6-on-premise-air-gapped-deployment)
7. [Monitoring & Observability in Customer Environments](#7-monitoring-observability-in-customer-environments)
8. [Customer-Facing Engineering](#8-customer-facing-engineering)
9. [The FDE Interview Process](#9-the-fde-interview-process)
10. [Interview Questions](#10-interview-questions)

---

## 1. What is a Forward Deployed Engineer?

### The FDE Mindset

```
"You are the bridge between what the product can do and what the customer needs."

As an FDE at an AI company:
- You deploy AI systems INTO customer environments (on-prem, cloud, hybrid)
- You solve problems that the product doesn't handle yet
- You represent engineering to the customer AND the customer to engineering
- You ship fast, iterate, and learn what actually works in the real world
```

### FDE vs Adjacent Roles

| Dimension | FDE | Solutions Architect | SWE (Product) | AI Engineer |
|-----------|-----|-------------------|---------------|-------------|
| **Primary focus** | Deploying into customer environments | Designing solutions | Building product features | Building AI features |
| **Customer exposure** | Daily, hands-on | Weekly, strategic | Rare | Occasional |
| **Code ownership** | High (integration, deployment) | Low (POC only) | High (product) | High (AI logic) |
| **Deployment** | Customer infra (anywhere) | Reference architecture | Internal infra | Internal infra |
| **Problem type** | Messy, ambiguous | Structured, scoped | Well-defined | Semi-structured |
| **Travel** | Often (customer site) | Sometimes | Rarely | Rarely |
| **Success metric** | Customer go-live | Deal closed | Feature shipped | Model quality |

### Why Companies Hire FDEs for AI

```
1. AI models are easy to demo, hard to deploy
   → FDEs bridge the "last mile" between model and production

2. Every enterprise has unique constraints
   → Legacy data, compliance requirements, custom auth, air-gap needs

3. AI products need hands-on integration
   → Data pipelines, API wiring, custom connectors, user workflows

4. Customers need a technical partner
   → Someone who understands THEIR infra AND the AI product
```

---

## 2. Core FDE Skills

### Technical Skills

| Skill | Importance | Details |
|-------|------------|---------|
| **Full-stack engineering** | 🔴 Critical | Build end-to-end integrations. APIs, auth, databases, frontends |
| **Infrastructure (K8s, Docker)** | 🔴 Critical | Deploy containerized applications into customer environments |
| **Networking** | 🟡 High | VPN, VPC peering, proxies, load balancers, DNS, TLS |
| **Data engineering** | 🟡 High | ETL pipelines, data connectors, schema mapping |
| **Security & auth** | 🟡 High | SSO (SAML/OIDC), RBAC, secrets management, encryption |
| **AI/ML fundamentals** | 🟡 High | Understand RAG, agents, models — you deploy and debug these |
| **Scripting & automation** | 🟢 Medium | Python, bash, Terraform, Ansible |
| **Monitoring & logging** | 🟢 Medium | Prometheus, Grafana, ELK, Datadog |

### Soft Skills

| Skill | Why it Matters |
|-------|----------------|
| **Problem decomposition** | Customers give vague requirements. You break them into actionable pieces. |
| **Communication** | Translate between customer stakeholders (CTO, engineers, ops) and your team. |
| **Empathy** | Understand customer pain points. Build trust. Handle frustration. |
| **Trade-off articulation** | "We can do X in 2 days or Y in 2 weeks. Here's what you get with each." |
| **Rapid learning** | Every customer environment is different. You figure it out fast. |

---

## 3. Deployment Patterns for AI Systems

### Deployment Topology

```ascii
┌─────────────────────────────────────────────────────────────┐
│                    DEPLOYMENT TOPOLOGIES                      │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  CLOUD-TO-CLOUD (Simplest)                                   │
│  ┌─────────────┐          ┌─────────────┐                    │
│  │ Customer AWS │◄────────│  Your Cloud  │                    │
│  │ (VPC peered) │          │  (SaaS)     │                    │
│  └─────────────┘          └─────────────┘                    │
│                                                               │
│  HYBRID (Common for enterprise)                               │
│  ┌──────────────────┐   ┌──────────────────┐                │
│  │ Customer On-Prem  │   │ Customer Cloud   │                │
│  │ (Database, apps)  │   │ (AI workloads)   │                │
│  └────────┬─────────┘   └────────┬─────────┘                │
│           │                      │                            │
│           └──────────┬───────────┘                            │
│                      │                                        │
│                 ┌────▼────┐                                   │
│                 │  VPN /  │                                   │
│                 │ Direct  │                                   │
│                 │ Connect │                                   │
│                 └─────────┘                                   │
│                                                               │
│  ON-PREMISE / AIR-GAPPED (Most challenging)                  │
│  ┌──────────────────────────────────────────────────┐       │
│  │  Customer Data Center                             │       │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │       │
│  │  │  Models  │ │  Agent   │ │  Customer Apps   │ │       │
│  │  │ (Local)  │ │ Service  │ │  (No internet)   │ │       │
│  │  └──────────┘ └──────────┘ └──────────────────┘ │       │
│  └──────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### Deployment Decision Matrix

| Factor | Cloud-to-Cloud | Hybrid | On-Premise |
|--------|---------------|--------|------------|
| **Setup time** | Hours | Days | Weeks |
| **Maintenance** | Your team | Shared | Customer ops |
| **Model updates** | Easy (push) | Moderate | Complex (sneakernet) |
| **Data privacy** | Medium | High | Highest |
| **Latency** | 10-50ms | 1-20ms | <1ms |
| **Compliance** | Standard | HIPAA, SOC2 | Air-gapped, classified |
| **Cost** | Low (shared) | Medium | High (dedicated infra) |

### Containerized AI Deployment Package

```yaml
# deployment-package/docker-compose.yml
# Standardized deployment for customer environments

version: '3.8'
services:
  ai-agent:
    image: myregistry/ai-agent:${VERSION}
    ports:
      - "8080:8080"
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - AUTH_PROVIDER=${AUTH_PROVIDER}
      - MODEL_TYPE=${MODEL_TYPE}
      - LOG_LEVEL=info
    volumes:
      - ./config:/app/config
      - ./data:/app/data
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      retries: 3

  vector-db:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - ./qdrant_storage:/qdrant/storage

  monitoring:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml

  cache:
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

### Kubernetes Deployment for Enterprise

```yaml
# k8s/ai-agent-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ai-agent
  namespace: customer-ai
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0  # Zero-downtime deployment
  selector:
    matchLabels:
      app: ai-agent
  template:
    spec:
      containers:
      - name: agent
        image: myregistry/ai-agent:v2.1.0
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: customer-db-credentials
              key: url
        resources:
          requests:
            memory: "4Gi"
            cpu: "2"
            nvidia.com/gpu: 1
          limits:
            memory: "8Gi"
            cpu: "4"
            nvidia.com/gpu: 1
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: ai-agent-service
spec:
  type: ClusterIP  # Internal only (customer VPN)
  ports:
  - port: 8080
    targetPort: 8080
  selector:
    app: ai-agent
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: agent-network-policy
spec:
  podSelector:
    matchLabels:
      app: ai-agent
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: customer-apps
    ports:
    - port: 8080
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: vector-db
    ports:
    - port: 6333
  - to:
    - podSelector:
        matchLabels:
          app: cache
    ports:
    - port: 6379
```

---

## 4. Enterprise Integration & Security

### Authentication Integration

```python
# Customer auth adapters for different providers

class AuthAdapter:
    """Unified interface for customer auth providers."""
    
    async def authenticate(self, request) -> User:
        """Authenticate using the configured provider."""
        pass
    
    async def authorize(self, user: User, action: str, resource: str) -> bool:
        """Check if user can perform action on resource."""
        pass

class SAMLAuthAdapter(AuthAdapter):
    """For enterprise customers using SAML SSO."""
    
    def __init__(self, metadata_url: str, entity_id: str):
        self.saml_client = SAMLClient(metadata_url, entity_id)
    
    async def authenticate(self, request) -> User:
        saml_response = request.headers.get("X-SAML-Response")
        if not saml_response:
            # Redirect to IdP
            return RedirectResponse(self.saml_client.get_login_url())
        
        attributes = await self.saml_client.parse_response(saml_response)
        return User(
            email=attributes["email"],
            roles=attributes.get("roles", ["user"]),
            tenant_id=attributes["tenant_id"]
        )

class OIDCAuthAdapter(AuthAdapter):
    """For customers using OIDC (Okta, Auth0, Azure AD)."""
    
    def __init__(self, issuer_url: str, client_id: str, client_secret: str):
        self.oidc_client = OIDCClient(issuer_url, client_id, client_secret)
    
    async def authenticate(self, request) -> User:
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        claims = await self.oidc_client.verify_token(token)
        return User(
            email=claims["email"],
            roles=claims.get("roles", ["user"]),
            tenant_id=claims.get("tenant_id")
        )
```

### Secrets Management

```python
class SecretsManager:
    """Handle secrets differently based on customer deployment."""
    
    def __init__(self, deployment_type: str):
        if deployment_type == "cloud":
            self.backend = AWSSecretsManager()
        elif deployment_type == "on_prem":
            self.backend = HashiCorpVault()
        elif deployment_type == "air_gapped":
            self.backend = EncryptedFileStore("/etc/secrets")
    
    async def get(self, key: str) -> str:
        return await self.backend.get_secret(key)
    
    async def set(self, key: str, value: str):
        await self.backend.set_secret(key, value)

# Deployment checklist for secrets:
# ❌ Never: Hardcode secrets in code or config files
# ❌ Never: Store secrets in Docker image layers
# ✅ Always: Use environment variables (injected at runtime)
# ✅ Always: Encrypt secrets at rest and in transit
# ✅ Always: Rotate secrets on a schedule
```

### Network Security

```python
NETWORK_SECURITY_CHECKLIST = {
    "in_transit": [
        "TLS 1.3 for all API communication",
        "mTLS for service-to-service auth",
        "VPN or Direct Connect for cloud-to-on-prem",
    ],
    "at_rest": [
        "Encrypt volumes (AWS EBS encryption, LUKS)",
        "Encrypt database at rest",
        "Encrypt model weights at rest",
    ],
    "access_control": [
        "Network policies (K8s NetworkPolicy)",
        "Security groups (AWS) / firewall rules",
        "IP allowlisting for API access",
    ],
    "audit": [
        "All API calls logged with timestamp and user",
        "Access attempts (successful and failed) logged",
        "Configuration changes tracked",
    ],
}
```

---

## 5. Data Pipeline Integration

### Common Enterprise Data Sources

```python
class DataSourceConnector:
    """Abstract connector for customer data sources."""
    
    async def connect(self) -> Connection: ...
    async def extract(self, config: ExtractionConfig) -> Iterator[Document]: ...
    async def get_schema(self) -> Schema: ...

class SQLDatabaseConnector(DataSourceConnector):
    """Connect to customer SQL databases (PostgreSQL, MySQL, SQL Server)."""
    
    def __init__(self, connection_string: str):
        self.pool = await asyncpg.create_pool(connection_string)
    
    async def extract(self, config: ExtractionConfig) -> Iterator[Document]:
        async with self.pool.acquire() as conn:
            async for row in conn.cursor(config.query):
                yield Document(
                    content=str(row),
                    metadata={
                        "source": config.table,
                        "row_id": row.get("id"),
                        "updated_at": row.get("updated_at")
                    }
                )

class SalesforceConnector(DataSourceConnector):
    """Connect to Salesforce via REST API."""
    
    def __init__(self, instance_url: str, client_id: str, client_secret: str):
        self.client = SalesforceClient(instance_url, client_id, client_secret)
    
    async def extract(self, config: ExtractionConfig) -> Iterator[Document]:
        records = await self.client.query(
            f"SELECT {config.fields} FROM {config.object} "
            f"WHERE LastModifiedDate > {config.last_run}"
        )
        for record in records:
            yield Document(content=record, metadata={"source": "salesforce"})

class SharePointConnector(DataSourceConnector):
    """Connect to SharePoint/OneDrive for document extraction."""
    
    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.graph = MicrosoftGraphClient(tenant_id, client_id, client_secret)
    
    async def extract(self, config: ExtractionConfig) -> Iterator[Document]:
        files = await self.graph.list_files(config.site_id, config.drive_id)
        for file in files:
            content = await self.graph.download_file(file.id)
            text = await self._parse_document(content, file.extension)
            yield Document(content=text, metadata={"source": "sharepoint", "file": file.name})
```

### Incremental Sync Strategy

```python
class IncrementalSync:
    """Sync only changed data since last run."""
    
    def __init__(self, storage):
        self.storage = storage
    
    async def get_last_checkpoint(self, pipeline_id: str) -> datetime:
        """Get the last successful sync timestamp."""
        return await self.storage.get(f"checkpoint:{pipeline_id}")
    
    async def run_sync(self, pipeline_id: str, connector: DataSourceConnector):
        last_run = await self.get_last_checkpoint(pipeline_id)
        
        config = ExtractionConfig(last_modified_after=last_run)
        documents = []
        
        async for doc in connector.extract(config):
            documents.append(doc)
            
            # Process in batches
            if len(documents) >= 100:
                await self.process_batch(pipeline_id, documents)
                documents = []
        
        # Process remaining
        if documents:
            await self.process_batch(pipeline_id, documents)
        
        # Update checkpoint
        await self.storage.set(
            f"checkpoint:{pipeline_id}",
            datetime.utcnow()
        )
```

---

## 6. On-Premise & Air-Gapped Deployment

### The Air-Gapped Challenge

```python
"""
AIR-GAPPED DEPLOYMENT — No internet access, no external APIs.

Challenges:
1. Model weights: Must be transferred physically (USB drive, portable HDD)
   → ~100GB for 70B model (FP16)
   → Need validation checksums to ensure integrity

2. No external LLM APIs: Must use local model
   → Options: Llama, Mistral, Qwen (local or quantized)
   → Quantized models: AWQ (4-bit) = ~35GB for 70B model

3. No package repositories: Must pre-bundle ALL dependencies
   → Python packages (wheels), system packages, base images
   → Use Docker images with everything included

4. No telemetry: Must deploy local monitoring
   → Prometheus + Grafana on-premise
   → Local logging (file-based or ELK on-premise)
"""

def build_airgap_package():
    """Build a self-contained deployment package for air-gapped environments."""
    return {
        "images": {
            "ai-agent": "ai-agent:2.1.0.tar",  # Pre-built Docker image
            "vector-db": "qdrant:1.8.0.tar",
            "redis": "redis:7-alpine.tar",
            "model-server": "vllm:0.4.0.tar",
        },
        "model_weights": {
            "llama-70b-awq": "llama-70b-awq.tar.gz",  # ~35GB
            "embedding-model": "bge-large-en.tar.gz",   # ~1.3GB
            "checksums.sha256": "checksums.txt",
        },
        "dependencies": {
            "python_wheels": "wheels/",  # All Python deps pre-downloaded
            "system_packages": "packages/",  # .deb or .rpm files
        },
        "configs": {
            "docker-compose.yml": "...",
            "prometheus.yml": "...",
            "nginx.conf": "...",
        },
        "scripts": {
            "install.sh": "Setup script",
            "verify.sh": "Checksum verification",
            "start.sh": "Start all services",
            "backup.sh": "Backup data",
        },
        "documentation": {
            "deployment_guide.pdf": "Step-by-step deployment instructions",
            "troubleshooting.md": "Common issues and fixes",
        },
    }
```

### Local Model Server Setup

```yaml
# airgap/docker-compose.model-server.yml
version: '3.8'
services:
  vllm:
    image: vllm:v0.4.0
    command: >
      --model /models/llama-70b-awq
      --quantization awq
      --max-model-len 4096
      --gpu-memory-utilization 0.9
      --max-num-batched-tokens 4096
      --enforce-eager
    ports:
      - "8000:8000"
    volumes:
      - /mnt/models:/models  # Model weights mounted from local storage
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 4  # Need 4x A100-80GB for 70B model
              capabilities: [gpu]
    environment:
      - CUDA_VISIBLE_DEVICES=0,1,2,3
  
  embedding:
    image: vllm:v0.4.0
    command: >
      --model /models/bge-large-en
      --max-model-len 512
      --gpu-memory-utilization 0.5
    ports:
      - "8001:8000"
    volumes:
      - /mnt/models:/models
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

---

## 7. Monitoring & Observability in Customer Environments

### Local Monitoring Stack

```yaml
# monitoring/docker-compose.yml
# Deployed inside customer environment (no external access)

services:
  prometheus:
    image: prom/prometheus:v2.45.0
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"
  
  grafana:
    image: grafana/grafana:10.0.0
    volumes:
      - ./grafana/dashboards:/etc/grafana/provisioning/dashboards
      - ./grafana/datasources:/etc/grafana/provisioning/datasources
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"
    environment:
      - GF_AUTH_DISABLE_LOGIN_FORM=true  # SSO with customer auth
      - GF_AUTH_PROXY_ENABLED=true
  
  loki:
    image: grafana/loki:2.9.0
    ports:
      - "3100:3100"
    volumes:
      - loki_data:/loki
```

### Health Check Endpoints

```python
# Standard health check for deployed AI agents

@router.get("/health")
async def health_check():
    """Comprehensive health check for deployed agent."""
    return {
        "status": "ok",
        "version": "2.1.0",
        "uptime": time.time() - start_time,
        "components": {
            "llm": await check_llm_health(),
            "vector_db": await check_vector_db_health(),
            "database": await check_database_health(),
            "cache": await check_cache_health(),
        },
        "metrics": {
            "requests_total": request_counter,
            "requests_last_hour": get_requests_last_hour(),
            "avg_latency_ms": avg_latency_ms,
            "error_rate": error_rate,
            "gpu_utilization": get_gpu_utilization(),
        }
    }

@router.get("/ready")
async def readiness():
    """Readiness check — is the agent ready to serve requests?"""
    llm_ready = await check_llm_loaded()
    db_ready = await check_migrations_applied()
    return {"ready": llm_ready and db_ready}
```

---

## 8. Customer-Facing Engineering

### The FDE Communication Framework

```python
"""
When talking to customers, follow this framework:

1. LISTEN first
   └── "Tell me more about the problem you're trying to solve."
   └── "What does success look like for you?"
   └── "What have you tried so far?"

2. CLARIFY constraints
   └── "What's your timeline?"
   └── "What compliance requirements do you have?"
   └── "What's the team's technical background?"

3. PROPOSE options
   └── "Option A: Quick deployment (2 weeks), limited features"
   └── "Option B: Full deployment (2 months), all features"
   └── Always explain trade-offs in business terms

4. SET expectations
   └── "What will be ready by when"
   └── "What won't be in scope"
   └── "What risks exist"

5. FOLLOW UP relentlessly
   └── Daily update during deployment
   └── Weekly check-in after go-live
   └── Document everything
"""
```

### Handling Common Customer Objections

| Objection | Response |
|-----------|----------|
| "This is too expensive" | Frame in terms of ROI: "What's the cost of not doing this?" |
| "We can't share our data" | On-premise deployment, data never leaves VPC |
| "We need 99.99% uptime" | Multi-region HA deployment with failover |
| "Our data is in a legacy system" | Connector adapters for most enterprise systems |
| "The model doesn't work well enough" | Fine-tuning with their data (quick improvement) |
| "Our team doesn't know AI" | Training sessions, documentation, support SLA |

### Shipping and Iterating

```python
"""
The FDE Mantra: 'Ship, Learn, Iterate'

Phase 1 — MVP (2 weeks):
  └── Deploy basic RAG Q&A on existing knowledge base
  └── Only 80% accuracy, but delivers value immediately
  └── Customer sees value → builds trust → more access

Phase 2 — Improve (1 month):
  └── Fine-tune model on customer data
  └── Add agent features (tool use, multi-step)
  └── Improve retrieval with hybrid search

Phase 3 — Scale (2 months):
  └── Multi-tenant, full RBAC
  └── Custom workflows for different departments
  └── Integration with more data sources
"""
```

---

## 9. The FDE Interview Process

### Typical Interview Flow

```
ROUND 1: Phone Screen (45 min)
  ├── Background and experience
  ├── Why FDE? Why this company?
  ├── High-level deployment experience
  └── Customer-facing example

ROUND 2: Coding / Technical (60 min)
  ├── Not pure LeetCode — more applied
  ├── System design with coding
  ├── "Build an API endpoint that..."
  ├── "Design a system that syncs data from..."
  └── Python, Go, or Java (depends on company)

ROUND 3: System Design / Whiteboarding (60 min)
  ├── Vague problem → decomposing → solution
  ├── "Customer wants to use AI for support"
  ├── "Design a deployment for an on-premise customer"
  └── Focus on trade-offs and decision-making

ROUND 4: Deployment Deep Dive (60 min)
  ├── "How would you deploy our product in an air-gapped environment?"
  ├── "Walk me through a complex deployment you did"
  ├── Infrastructure, security, networking
  └── What went wrong and how you fixed it

ROUND 5: Behavioral / Cross-Functional (45 min)
  ├── Customer empathy stories
  ├── Conflict resolution with customers
  ├── "Tell me about a time you shipped something imperfect"
  └── "Tell me about a time you had to say no to a customer"
```

### What Interviewers Are Looking For

| Quality | How It Shows |
|---------|-------------|
| **Problem decomposition** | Breaks vague requirement into clear steps before coding |
| **Customer empathy** | Leads with understanding user needs, not technical solutions |
| **Pragmatism** | Knows when perfect is the enemy of good |
| **Technical breadth** | Can discuss databases, networking, auth, deployment |
| **Ownership** | Takes responsibility for the full deployment, end-to-end |
| **Communication** | Explains technical concepts to non-technical stakeholders |

---

## 10. Interview Questions

### Question 1: Problem Decomposition

**Prompt:** *"A large bank wants to deploy our AI agent to help their customer support team. They have 2000 support agents, a knowledge base in a legacy on-premise database, and strict compliance requirements (data cannot leave their data center). They want to reduce response time by 50% in 6 months. Walk me through your approach."*

<details>
<summary>🎯 Answer Approach</summary>

**Step 1: Clarify requirements**
- What does "reduce response time" mean? (first response? resolution?)
- What compliance standards? (SOX? PCI? GDPR?)
- What's the current response time baseline?
- What's the team structure? (IT team to support deployment?)

**Step 2: Map the constraints**
- Air-gapped: No external API calls → local LLM only
- Legacy DB: Need connector or ETL pipeline
- 2000 agents → meaningful throughput requirement
- 6 months → phased approach

**Step 3: Phased deployment plan**

```
Phase 1 (Weeks 1-4): Assessment & Setup
  ├── Audit customer infra (compute, network, storage)
  ├── Set up deployment environment (K8s on-prem)
  ├── Data pipeline: ETL from legacy DB to vector store
  └── Model selection: Quantized 70B (local, air-gapped)
      → Need 4x A100-80GB or equivalent

Phase 2 (Weeks 5-8): Agent-Assisted Support
  ├── Deploy RAG agent for AGENT use (not customer-facing)
  ├── Agents use the tool to quickly look up answers
  ├── Monitor: Does it actually reduce response time?
  └── Iterate on retrieval quality

Phase 3 (Weeks 9-16): Escalated Features
  ├── Add more data sources
  ├── Improve accuracy with customer data fine-tuning
  ├── Add human-in-the-loop for sensitive queries
  └── Begin testing with live support agents

Phase 4 (Weeks 17-24): Scale & Optimize
  ├── Roll out to all 2000 agents
  ├── Monitor and optimize throughput
  ├── Measure: 50% response time reduction?
  └── Plan phase 2: Customer-facing agent
```

**Step 4: Key risks**
- Legacy database performance during ETL
- Model accuracy on domain-specific queries (banking terminology)
- Agent adoption (will support agents actually use it?)
- Compliance audit of the deployment
</details>

### Question 2: Air-Gapped Deployment

**Prompt:** *"The customer wants to deploy our AI system in a completely air-gapped environment (no internet access). How do you get the software, models, and dependencies onto their systems? Walk me through the process."*

<details>
<summary>🎯 Answer</summary>

**1. Package everything into a deployment bundle (physical transfer)**

```
Model weights (35GB for quantized 70B) → USB drive or portable HDD
Docker images (10GB) → USB drive
Python dependencies (2GB wheels) → USB drive
Configuration files → USB drive
Deployment scripts → USB drive
```

**2. Verification on arrival**
```bash
# Customer runs verify.sh
sha256sum -c checksums.txt  # Verify every file
docker load < ai-agent.tar    # Load Docker images
```

**3. Local model server**
```yaml
# Pre-configured for local inference only
MODEL_PATH=/mnt/models/llama-70b-awq
EMBEDDING_MODEL=/mnt/models/bge-large-en
EXTERNAL_API_ENABLED=false  # No external calls
```

**4. Monitoring (local only)**
```yaml
# Prometheus + Grafana deployed inside the cluster
# No external telemetry — dashboards available via customer VPN
```

**5. Updates (quarterly or as needed)**
```python
# Update process:
# 1. Build new bundle on our end
# 2. Transfer via secure physical media (or approved transfer mechanism)
# 3. Customer runs update.sh (zero-downtime if possible)
# 4. Rollback available via previous bundle
```
</details>

### Question 3: Customer Escalation

**Prompt:** *"You've deployed the AI system. After 2 weeks, the customer reports that response times have INCREASED — agents are spending more time double-checking the AI's answers than before. What do you do?"*

<details>
<summary>🎯 Answer</summary>

**Step 1: Investigate with data**
```python
# Check the metrics
metrics = await get_customer_metrics(customer_id)
print(f"Avg response time: {metrics.avg_response_time}")  # Increased!
print(f"AI acceptance rate: {metrics.ai_acceptance_rate}")  # Maybe 30%?
print(f"Agent override rate: {metrics.override_rate}")  # High?
```

**Root cause analysis:**
1. **Low accuracy:** If AI answers are wrong 40%+ of the time, agents will check everything
2. **Poor UX:** If the AI answer isn't clearly presented, agents spend time reformatting
3. **Low trust:** If the first few answers were wrong, agents never built trust
4. **Wrong metric:** Maybe first response time improved, but total resolution time increased

**Step 2: Identify the specific issue**
```python
# Sample recent queries to assess quality
samples = await get_recent_queries(customer_id, n=100)
accuracy = await evaluate_accuracy(samples)
print(f"Accuracy: {accuracy}%")

# If accuracy < 80%:
issues = await classify_failures(samples)
# "lack_of_context" = 45%
# "wrong_kb_article" = 30%
# "hallucination" = 15%
# "correct_but_unclear" = 10%
```

**Step 3: Action plan**
```
If accuracy is the problem:
  └── Improve retrieval (hybrid search, better chunking)
  └── Add domain-specific fine-tuning
  └── Add confidence scores: show only when > 90% confident

If UX is the problem:
  └── Redesign how AI answers are displayed
  └── Add one-click "use as draft" button
  └── Show citations clearly (click to verify)

If trust is the problem:
  └── Add feedback loop ("Was this helpful?")
  └── Show accuracy metrics to agents
  └── Gradual rollout (start with 10% of agents)

If wrong metric:
  └── Pivot to measuring resolution time, not first response time
  └── The AI might be correct, but the workflow needs optimization
```

**Step 4: Communicate with customer**
```
"I understand the frustration. Our data shows the AI is correct about 65% of the time,
which means agents are spending time verifying. Here's our plan:

1. This week: Add confidence scores — AI only shows answers it's >90% confident about
2. Next week: Improve retrieval to address the 45% of failures from missing context
3. In 2 weeks: Add feedback loop so we can measure and improve

Would you like me to set up a weekly check-in to review progress?"
```
</details>

### Question 4: System Design — AI for Enterprise

**Prompt:** *"Design a system that takes a customer's on-premise SQL database of product information, indexes it for RAG, and serves queries through an API. The customer must be able to update their data and see results within 5 minutes."*

<details>
<summary>🎯 Answer</summary>

**Architecture:**

```ascii
Customer On-Premise                Customer Cloud / Our Infra
┌─────────────────────┐          ┌────────────────────────┐
│ SQL Database         │          │                       │
│ (Products table)     │──CDC───►│ Change Data Capture    │
└─────────────────────┘          │       │               │
                                 │       ▼               │
                                 │ ┌─────────────┐       │
                                 │ │ Embedding    │       │
                                 │ │ Pipeline     │       │
                                 │ └──────┬──────┘       │
                                 │        │               │
                                 │        ▼               │
                                 │ ┌─────────────┐       │
                                 │ │ Vector DB    │       │
                                 │ │ (Qdrant)     │       │
                                 │ └─────────────┘       │
                                 │        ▲               │
                                 │        │               │
                                 │ ┌──────┴──────┐       │
                                 │ │ Query API    │       │
                                 │ │ (Agent)      │       │
                                 │ └─────────────┘       │
                                 └────────────────────────┘
```

**Key decisions:**
- **CDC (Change Data Capture):** Debezium or native PG logical replication → near real-time
- **Embedding pipeline:** Process changed records only (incremental)
- **Vector DB:** Qdrant (supports filtering, high performance)
- **5-minute SLA:** CDC latency < 30s, embedding < 2min, indexing < 1min

**Scaling:**
- 1000 QPS: 3 agent replicas, read replicas of vector DB
- 10K products ← 10K updates/day: CDC handles easily
- 1M products: Partition vector DB by product category
</details>

---

## FDE Quick Reference

| Situation | Do This |
|-----------|---------|
| Customer gives vague requirement | Ask clarifying questions, decompose into phases |
| Deployment in air-gapped env | Build self-contained bundle, verify checksums |
| Customer unhappy with results | Analyze data first, then present improvement plan |
| Legacy system integration | Build connector adapter, incremental sync |
| Compliance requirements | On-premise deployment, encryption everywhere, audit logs |
| Model accuracy issues | Fine-tuning, better retrieval, confidence thresholds |
| Customer wants everything now | Prioritize: what delivers most value in 2 weeks? |
