# ☁️ AWS Networking — Staff-Level Interview Questions

> *10 questions covering VPC, ALB/NLB, CloudFront, Route53, Global Accelerator, Transit Gateway, VPN, and network security — every question expects principal engineer-level depth with production patterns.*

---

## Table of Contents

1. [VPC Design: Subnets, NAT, Peering, Endpoints](#1-vpc-design-subnets-nat-peering-endpoints)
2. [ALB vs NLB: Load Balancer Deep Dive](#2-alb-vs-nlb-load-balancer-deep-dive)
3. [Route53: Routing Policies & Health Checks](#3-route53-routing-policies-health-checks)
4. [CloudFront: CDN Architecture & Origin Shield](#4-cloudfront-cdn-architecture-origin-shield)
5. [AWS Global Accelerator vs CloudFront](#5-aws-global-accelerator-vs-cloudfront)
6. [Transit Gateway: Multi-VPC Connectivity](#6-transit-gateway-multi-vpc-connectivity)
7. [Site-to-Site VPN & Direct Connect](#7-site-to-site-vpn-direct-connect)
8. [VPC Flow Logs & Network Traffic Analysis](#8-vpc-flow-logs-network-traffic-analysis)
9. [AWS WAF & Shield: DDoS Protection](#9-aws-waf-shield-ddos-protection)
10. [Network ACLs vs Security Groups](#10-network-acls-vs-security-groups)

---

## 1. VPC Design: Subnets, NAT, Peering, Endpoints

**Q:** "Design a VPC architecture for a multi-tier SaaS platform with the following requirements: public-facing web tier, private application tier, and fully isolated database tier. Support cross-region replication and on-premises connectivity via Direct Connect. How do you size the CIDR blocks? How do VPC endpoints reduce data transfer costs?"

**What They're Really Testing:** Whether you understand VPC design at scale — CIDR planning to avoid overlapping ranges, NAT gateway cost optimization, and VPC endpoint architecture for private AWS service access.

### Answer

**VPC CIDR Planning:**

```yaml
Production VPC (us-east-1):
  VPC CIDR: 10.0.0.0/16 (65,536 IPs)

  Public subnets (for ALB, NAT Gateway):
    us-east-1a: 10.0.1.0/24    (256 IPs)
    us-east-1b: 10.0.2.0/24    (256 IPs)
    us-east-1c: 10.0.3.0/24    (256 IPs)

  Private subnets (application tier):
    us-east-1a: 10.0.10.0/23   (512 IPs)
    us-east-1b: 10.0.12.0/23   (512 IPs)
    us-east-1c: 10.0.14.0/23   (512 IPs)

  Isolated subnets (database tier — no internet access):
    us-east-1a: 10.0.20.0/24   (256 IPs)
    us-east-1b: 10.0.21.0/24   (256 IPs)
    us-east-1c: 10.0.22.0/24   (256 IPs)

  Reserved for future: 10.0.64.0/18 (16,384 IPs), 10.0.128.0/17 (32,768 IPs)

DR VPC (us-west-2):
  VPC CIDR: 10.1.0.0/16 (non-overlapping!)
  # Same subnet structure with 10.1.x.x prefix
```

**VPC Endpoints — Cost Savings:**

```yaml
# Without VPC Endpoints (traffic to S3 goes through NAT Gateway):
# NAT Gateway cost: $0.045/GB processed
# For 10TB/month of S3 traffic:
#   NAT cost: 10,000GB × $0.045 = $450/month
#   + NAT Gateway hourly: $32/month
#   Total: ~$482/month

# With VPC Endpoints (S3 Gateway Endpoint — FREE):
#   S3 Gateway Endpoint: $0/hour
#   S3 data transfer: $0.00/GB (free within region)
#   Total: ~$0/month

# Gateway Endpoints (free, use route table):
#   - S3
#   - DynamoDB

# Interface Endpoints (AWS PrivateLink, $0.01/AZ/hour + $0.01/GB):
#   - EC2, ECR, ECS, SNS, SQS, KMS, Secrets Manager
#   - CloudWatch, Lambda, Step Functions
#   - Cost: ~$7/AZ/month + $0.01/GB

# Strategy:
# - Use Gateway Endpoints for S3 and DynamoDB (free!)
# - Use Interface Endpoints for frequently accessed AWS services
# - Only use NAT Gateway for non-AWS external traffic
# - Typical savings: 60-80% on NAT data processing costs
```

**VPC Peering vs Transit Gateway:**

```yaml
VPC Peering:
  - Direct 1:1 connection between two VPCs
  - No transitive routing (A→B, B→C does NOT give A→C)
  - Each pair: separate peering connection + route table entries
  - 100 VPCs → 4950 peerings (N×(N-1)/2)
  - Cost: $0.01/AZ/hour per peering ($0.00 for inter-region data out)

Transit Gateway:
  - Hub-and-spoke: connect all VPCs through single gateway
  - Transitive routing: A→TGW→C works
  - 100 VPCs → 100 attachments (just 1 per VPC)
  - Cost: $0.05/hour per attachment ($0.00 for data transfer between attachments)
  - Supports: VPC, VPN, Direct Connect, Transit Gateway peering
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-vpc-peering-vs-tgw.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated VPC Peering vs Transit Gateway — 1:1 connection vs hub-and-spoke with transitive routing comparison — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **CIDR planning** | Reserves non-overlapping ranges, sizes subnets appropriately |
| **Endpoint strategy** | Uses Gateway Endpoints for free S3/DynamoDB access, Interface for others |
| **NAT cost** | Quantifies NAT gateway cost, explains endpoint alternatives |
| **Peering vs TGW** | Understands transitive routing limitation of peering |

---

## 2. ALB vs NLB: Load Balancer Deep Dive

**Q:** "Your application needs to handle 1M concurrent WebSocket connections with sub-10ms latency. Compare ALB vs NLB. How does each handle connection draining, sticky sessions, and TLS termination at scale? When would you use both in front of the same application?"

**What They're Really Testing:** Whether you understand the architectural differences between L7 and L4 load balancing — when the overhead of HTTP inspection is worth it, and when raw TCP performance is required.

### Answer

**ALB vs NLB Architecture Comparison:**

```yaml
ALB (Application Load Balancer):
  - Layer: L7 (HTTP/HTTPS/HTTP2/gRPC/WebSocket)
  - Latency: ~10-50ms added (TLS termination + header inspection)
  - Scaling: 1 ALB node per AZ, auto-scales based on traffic
  - Pricing: $0.0225/hour + $0.008/LCU (LCU = 25 connections/s + 3000 req/s + 1GB/h)
  - Features: Host-based routing, path-based routing, header conditions
  - WebSocket: Native support (upgrade from HTTP)
  - TLS: Full termination, SNI support, mutual TLS

NLB (Network Load Balancer):
  - Layer: L4 (TCP/UDP/TLS)
  - Latency: ~1-5ms (minimal processing, kernel-level forwarding)
  - Scaling: 1 NLB node per AZ, can handle millions of connections
  - Pricing: $0.0225/hour + $0.006/LCU (LCU = 800 connections/s + 400 flows/min)
  - Features: Source IP preservation, static IP (Elastic IP), Proxy Protocol v2
  - WebSocket: Pass-through (just TCP, no inspection)
  - TLS: TCP passthrough or TLS termination

Performance at 1M WebSocket connections:
  ALB: ~100 nodes, ~50ms latency, 10-15 LCUs ($0.08/LCU ≈ $0.80/hour)
  NLB: ~10 nodes, ~3ms latency, 1250 LCUs ($0.006/LCU ≈ $7.50/hour)
  
  NLB wins on latency but ALB may be more cost-effective at lower scale.
```

**Connection Draining:**

```yaml
ALB connection draining:
  - DeregistrationDelay: 300s max (default 300s)
  - Works at HTTP level: stops sending new requests, waits for in-flight
  - For WebSocket: waits for connections to close naturally
  - Health checks: continues until delay expires or connection closes

NLB connection draining:
  - DeregistrationDelay: 3600s max
  - Works at TCP level: stops sending new connections
  - For WebSocket: TCP connections persist until client closes
  - No application awareness — just TCP flow control

# Best practice for WebSocket:
alarm_on_draining:
  # Monitor draining connections, alert if > 100
  # Clients should reconnect after draining begins
```

**Sticky Sessions:**

```yaml
ALB sticky sessions:
  - Duration-based cookie: AWSALB (generated by ALB)
  - Application-based cookie: custom cookie name
  - Applies to HTTP requests only

NLB sticky sessions:
  - Source IP hash (flows to same target based on client IP)
  - Not true sticky sessions (many clients behind same IP)
  - For WebSocket: use Proxy Protocol to preserve client IP

# Combined architecture for WebSocket:
# NLB (static IP) → ALB (sticky sessions, WebSocket upgrade) → Targets
# Client → NLB (static IP) → ALB (stickiness) → ECS/Fargate
# Pros: Static IP for whitelisting + ALB features
# Cons: Extra hop, double LB cost
```

**TLS Termination Strategies:**

```yaml
ALB terminating TLS:
  Client → ALB (TLS) → Target (HTTP)
  - ALB decrypts TLS, sends plain HTTP to target
  - ALB adds X-Forwarded-For, X-Forwarded-Proto headers
  - Certificate management in ACM (auto-renewal)
  - Limitation: plain HTTP between ALB and target

NLB with TLS termination:
  Client → NLB (TLS) → Target (TCP or TLS)
  - NLB terminates TLS or passes through
  - With termination: can use ACM certs
  - Without termination: end-to-end encryption
  - No header injection (client IP preserved natively)

End-to-end encryption:
  Client → NLB (TLS passthrough) → Target (TLS)
  - Best security: no decryption in LB
  - Target handles TLS (more CPU on target)
  - Can't use X-Forwarded-For (use Proxy Protocol)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Latency math** | Quantifies ALB vs NLB latency difference in milliseconds |
| **WebSocket handling** | Knows ALB does native upgrade, NLB passes TCP through |
| **Connection draining** | Explains ALB HTTP-aware draining vs NLB TCP-level draining |
| **Combined architecture** | Can design NLB+ALB stack for static IP + stickiness |

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-alb-vs-nlb.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated ALB vs NLB Load Balancer Deep Dive — L7 HTTP routing vs L4 TCP/UDP, WebSocket connections, TLS termination, and combined architecture — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 3. Route53: Routing Policies & Health Checks

**Q:** "Design a global DNS routing strategy for a SaaS platform deployed across 3 AWS regions (us-east-1, eu-west-1, ap-southeast-1). You need latency-based routing with automatic failover. How do Route53 health checks work with ALB? How do you handle DNS TTL during failover?"

**What They're Really Testing:** Whether you understand Route53 routing policies at scale — the interaction between DNS TTL, health checks, and failover timing.

### Answer

**Multi-Region DNS Architecture:**

```yaml
# Route53 hosted zone: saas.example.com

# Primary record set (latency-based routing):
saas.example.com    A     ALIAS    latency/us-east-1    alb-us-east-1.elb.amazonaws.com
saas.example.com    A     ALIAS    latency/eu-west-1    alb-eu-west-1.elb.amazonaws.com
saas.example.com    A     ALIAS    latency/ap-southeast-1  alb-ap-southeast-1.elb.amazonaws.com

# Failover record set (if latency routing returns unhealthy region):
saas.example.com    A     FAILOVER   PRIMARY    alb-us-east-1.elb.amazonaws.com
saas.example.com    A     FAILOVER   SECONDARY  alb-eu-west-1.elb.amazonaws.com

# Health checks:
hc-us-east-1:    Route53 Health Check → ALB endpoint (/health)
hc-eu-west-1:    Route53 Health Check → ALB endpoint (/health)
hc-ap-southeast-1: Route53 Health Check → ALB endpoint (/health)
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-route53-dns-routing.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Route53 Multi-Region DNS Routing — latency-based routing with health check failover across 3 regions — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

**Failover Timing Breakdown:**

```yaml
# When us-east-1 becomes unhealthy:
# Total DNS failover time = Health check detection + TTL propagation

# Step 1: Health check detection
#   Interval: 10s (fastest)
#   Failure threshold: 3 consecutive failures
#   Detection time: 30s

# Step 2: DNS TTL
#   TTL = 60s (typical for failover)
#   DNS resolvers cache the record for up to 60s
#   Some resolvers ignore TTL (sticky for up to 5 min!)
#   
#   Best practice: Use 10-60s TTL for failover records
#   Route53 uses lower TTL internally for ALIAS records (updates propagate faster)

# Total worst-case failover time: 30s (detect) + 60s (cached TTL) = 90s

# Optimization: Use Route53 Application Recovery Controller (ARC)
# ARC can route traffic away from unhealthy endpoints in <30s
```

**Health Check Configuration:**

```yaml
HealthCheck:
  Type: HTTPS
  IPAddress: 203.0.113.10    # Or use ALB DNS name
  Port: 443
  ResourcePath: /health
  FullyQualifiedDomainName: api.saas.example.com
  
  RequestInterval: 10        # Check every 10 seconds
  FailureThreshold: 3        # 3 consecutive failures = unhealthy
  MeasureLatency: true       # Enable latency measurements
  
  # Health check regions: 6 regions minimum
  Regions:
    - us-west-2
    - us-east-1
    - eu-west-1
    - ap-southeast-1
    - sa-east-1
    - ap-northeast-1
  
  # String matching:
  SearchString: "HEALTHY"    # Response must contain "HEALTHY"
  
  # Alarm action:
  AlarmIdentifier:
    Name: saas-health-check
    Region: us-east-1

# Calculated health checks (compound):
# hc-combined: 3 health checks, need 2 out of 3 to pass
# Prevents single-AZ blip from triggering failover
```

**Weighted Routing (Canary Deployments):**

```yaml
# Canary deployment with Route53 weighted routing:
canary.saas.example.com    A     WEIGHTED    5     alb-canary.elb.amazonaws.com
stable.saas.example.com    A     WEIGHTED    95    alb-stable.elb.amazonaws.com

# Shift traffic 5% at a time:
# Day 1: 95/5  (95% stable, 5% canary)
# Day 2: 80/20
# Day 3: 50/50
# Day 4: 0/100 (canary = new stable)

# ALIAS records to ELB: Route53 resolves the ELB's IPs automatically
# No need to manage ELB IP changes
```

**Private DNS for Internal Services:**

```yaml
# Create private hosted zone for internal service discovery
# VPC: vpc-12345 (attached to private hosted zone)

internal.saas.example.com:
  mysql-primary    A    10.0.20.10    # Private IP
  mysql-replica    A    10.0.20.11
  redis-cluster    A    10.0.30.10    # SRV record for cluster
  redis-cluster    SRV  1 10 6379 redis-001.redis.internal
  redis-cluster    SRV  1 10 6379 redis-002.redis.internal

# Split-view DNS:
# Same domain, different records for internal vs external
# External: saas.example.com → public ALB
# Internal: saas.example.com → private ALB
# Use different hosted zones for public and private
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Latency routing** | Explains how Route53 uses latency measurements to route users |
| **Failover timing** | Quantifies detection + TTL propagation time |
| **Health checks** | Configures multi-region health checks to prevent false failover |
| **ALIAS records** | Knows ALIAS records are free and resolve to AWS resources (no charge) |

---

## 4. CloudFront: CDN Architecture & Origin Shield

**Q:** "Design a global CDN strategy for a video streaming platform serving 10PB/month. Users are distributed globally. How does CloudFront's edge cache work? What is Origin Shield and how does it reduce origin load? How do you handle cache invalidation for time-sensitive content?"

**What They're Really Testing:** Whether you understand CDN caching at scale — multi-tier cache architecture, origin offload strategies, and cache invalidation trade-offs.

### Answer

**CloudFront Edge Architecture:**

```yaml
User in Tokyo ─────────────────────────────────┐
User in London ──────────────────────────┐      │
User in Sydney ───────────────────┐      │      │
                                  ▼      ▼      ▼
                    ┌────────────────────────────-┐
                    │   CloudFront Edge Locations  │
                    │   450+ PoPs worldwide        │
                    │                              │
                    │   ┌──────┐  ┌──────┐        │
                    │   │ IAD  │  │ LHR  │   ...  │
                    │   └──┬───┘  └──┬───┘        │
                    │      │         │            │
                    └──────┼─────────┼────────────┘
                           │         │
                    ┌──────▼─────────▼────────────┐
                    │   Origin Shield (Regional)   │
                    │   us-east-1 (Ashburn)        │
                    │                              │
                    │   Cache tier: larger,        │
                    │   higher hit rate            │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │   Origin (S3 + ALB)          │
                    │   us-east-1                  │
                    └──────────────────────────────┘
```

**Cache Layers:**

```yaml
Edge Cache (450+ PoPs):
  - Size: ~1-10GB per PoP (most popular content)
  - TTL: 0-3600 seconds (depends on content type)
  - Miss: goes to Origin Shield or directly to origin
  - Eviction: LRU when cache is full

Origin Shield (Regional cache, ~20 locations):
  - Size: ~100-500GB per region
  - TTL: configurable, usually 1-2× edge TTL
  - Purpose: absorb multiple edge misses for the same content
  - Benefit: reduces origin load by 80-90%

S3 Origin (Source of truth):
  - Stores all content (PB-scale)
  - Serves only Origin Shield requests (not edge directly)
  - Shield = single point of aggregation → fewer S3 GET requests

# Cache hit ratios by layer:
# Edge-only: ~85% hit rate
# Edge + Shield: ~95-98% hit rate
# Origin load reduction: 10×-20× fewer requests to S3
```

**Cache Invalidation Strategies:**

```yaml
# Invalidation methods:

# 1. Invalidation by path (most common):
aws cloudfront create-invalidation \
  --distribution-id E12345 \
  --paths "/videos/*" "/thumbnails/*"

# Cost: First 1000 paths/month free, then $0.005/path
# Propagation: ~5-15 minutes to reach all edge locations
# Limit: 3000 paths per invalidation

# 2. Versioned URLs (recommended for constant updates):
# Instead of:  cdn.saas.com/video/abc123.mp4
# Use:         cdn.saas.com/video/abc123_v2.mp4
# New version = new URL = automatic cache miss
# No invalidation needed!

# 3. Cache behavior with TTL:
# Match content type to TTL:
/videos/*:
  MinTTL: 86400      # 1 day (videos rarely change)
  MaxTTL: 31536000   # 1 year
  DefaultTTL: 86400
  Compress: true     # Gzip/Brotli

/thumbnails/*:
  MinTTL: 3600       # 1 hour
  DefaultTTL: 3600

/api/*:
  MinTTL: 0          # Never cache API responses
  DefaultTTL: 0

# 4. Cache invalidation from origin:
# S3 event → Lambda → CreateCloudFrontInvalidation
# When new video uploaded, invalidate old version
```

**Origin Shield Configuration:**

```yaml
# Enable Origin Shield in CloudFront:
Origins:
  - DomainName: my-bucket.s3.us-east-1.amazonaws.com
    OriginShield:
      Enabled: true
      OriginShieldRegion: us-east-1    # Shield location
    
    # Connection attempts: Shield → S3
    # Connection timeout: 5s
    # Keep connections alive: 60s
    
    # S3 bucket policy (only allow Shield IPs):
    {
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::my-bucket/*",
      "Condition": {
        "IpAddress": {
          "aws:SourceIp": [
            "130.176.0.0/17",  # CloudFront Origin Shield CIDR
            "15.158.0.0/16"    # CloudFront edge CIDR
          ]
        }
      }
    }

# Performance comparison:
# Without Shield:
#   Tokyo edge miss → direct to us-east-1 origin (200ms RTT)
#   London edge miss → direct to us-east-1 origin (80ms RTT)
#   Both requests hit origin separately
#
# With Shield:
#   Tokyo edge miss → us-east-1 Shield (200ms)
#   London edge miss → us-east-1 Shield (80ms)
#   Shield → S3 origin (1 hop!)
#   Shield caches the response → London miss now HITS Shield cache
```

**Signed URLs & Geo-Restriction:**

```yaml
# Signed URLs for private content:
# 1. Trusted key group in CloudFront
# 2. Generate signed URL from your application

def generate_signed_url(video_path):
    expire_time = int(time.time()) + 3600  # 1 hour
    policy = {
        'Statement': [{
            'Resource': f'https://cdn.saas.com{video_path}',
            'Condition': {
                'DateLessThan': {'AWS:EpochTime': expire_time},
                'IpAddress': {'AWS:SourceIp': user_ip}
            }
        }]
    }
    signed_url = cloudfront_signer.sign(
        url=video_url,
        policy=json.dumps(policy),
        private_key=PRIVATE_KEY,
        key_pair_id=KEY_PAIR_ID
    )
    return signed_url

# Geo-restriction:
# Whitelist: allow only specific countries (e.g., US, CA, UK)
# Blacklist: block specific countries
# Use case: licensing restrictions, regional compliance
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Multi-tier cache** | Understands edge → shield → origin hierarchy |
| **Invalidation cost** | Knows versioned URLs are free, invalidation costs $ |
| **Origin Shield benefit** | Quantifies origin load reduction (80-90%) |
| **Signed URLs** | Implements time-expiring, IP-restricted access |

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-cloudfront-origin-shield.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated CloudFront CDN & Origin Shield — edge cache → regional cache → origin shield → origin, 95%+ cache hit rate, 80% origin load reduction — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 5. AWS Global Accelerator vs CloudFront

**Q:** "Your SaaS platform serves dynamic API content (not cacheable) to global users. P95 latency is 800ms for APAC users. Compare AWS Global Accelerator vs CloudFront. Which would you choose for non-cacheable API traffic? How does Global Accelerator's anycast routing improve TCP performance?"

**What They're Really Testing:** Whether you understand the architectural difference between CDN (cache-centric) and global accelerator (network-optimized) — and can match the right service to the workload.

### Answer

**Architecture Comparison:**

```yaml
CloudFront:
  - 450+ edge locations (cache-focused)
  - Optimized for: cacheable content (static files, video, images)
  - Dynamic content: still uses edge → origin (but no caching benefit)
  - Protocol: HTTP/HTTPS/WebSocket
  - Features: Lambda@Edge, cache behaviors, signed URLs

Global Accelerator:
  - 100+ edge locations (network-focused)
  - Optimized for: dynamic content, TCP/UDP traffic
  - Uses: anycast IPs (2 static IPs) → nearest edge → AWS backbone
  - Protocol: TCP/UDP (any protocol over TCP/UDP)
  - Features: Traffic dials, endpoint weights, gradual failover

# Key difference:
# CloudFront: HTTP application-level (cache, Lambda@Edge)
# Global Accelerator: Network-level (TCP optimization, anycast IPs)

For non-cacheable API:
  Latency with direct internet: 800ms (APAC → us-east-1)
  Latency with GA: 250ms (APAC edge → AWS backbone → us-east-1)
  Latency with CF: 300ms (CF edge → origin, but has HTTP overhead)
  
  GA wins for API traffic: TCP optimization + no cache overhead
```

**Anycast Routing with Global Accelerator:**

```yaml
# Anycast: Same IP address advertised from multiple locations
# BGP routes traffic to the nearest edge

Global Accelerator edge:
  US West (IAD):   203.0.113.1
  Europe (LHR):    203.0.113.1
  Asia (NRT):      203.0.113.1
  Australia (SYD): 203.0.113.1

# Client in Tokyo:
#   DNS resolves: ga-saas.awsglobalaccelerator.com → 203.0.113.1
#   BGP routing: Tokyo client → NRT edge (closest)
# 
# Without GA:
#   Client in Tokyo → 15 network hops → us-east-1 (200ms)
#   Packet loss: ~2%
#
# With GA:
#   Client in Tokyo → NRT edge (3 hops) → AWS backbone → us-east-1
#   AWS backbone: private fiber, <70ms NRT→IAD
#   Total: ~5 hops, ~80ms, <0.01% loss
```

**TCP Optimization with Global Accelerator:**

```yaml
# GA terminates TCP at the edge, re-establishes over AWS backbone:

Without GA:
  Client (Tokyo)                                 Server (us-east-1)
  ┌──────────┐  Internet (200ms, 2% loss)       ┌──────────┐
  │ TCP cwnd ├──●────●────●──────●────●────────►│ TCP cwnd │
  │ = 10     │  loss loss loss retrans. timeout  │ = 10     │
  └──────────┘                                   └──────────┘
  # Slow start: 10 rounds over 200ms RTT = 2 seconds to fill pipe
  # Loss at any point: cut cwnd in half, retransmit

With GA:
  Client (Tokyo)     GA Edge (NRT)    AWS Backbone    Server (us-east-1)
  ┌──────────┐  30ms ┌──────────┐  70ms  ┌──────────┐
  │ TCP cwnd ├──────►│ TCP cwnd ├───────►│ TCP cwnd │
  │ = 10     │       │ = 1000   │        │ = 1000   │
  └──────────┘       └──────────┘        └──────────┘
  
  # Client → Edge: short RTT (30ms), fast slow start
  # Edge → Server: AWS backbone (70ms), no packet loss
  # Edge buffers: client-side TCP is optimized (fast)
  # Backend TCP: optimized (fast, no loss)
```

**Traffic Dials & Gradual Failover:**

```yaml
# Traffic dials: control % of traffic to each endpoint group
EndpointGroup:
  us-east-1:
    TrafficDial: 100    # 100% of traffic
    EndpointWeights:
      alb-1: 80
      alb-2: 20
  
  us-west-2:
    TrafficDial: 0      # DR region, 0% until failover

# Gradual failover:
# Minute 0: us-east-1 dial = 100, us-west-2 dial = 0
# Minute 1: us-east-1 dial = 80, us-west-2 dial = 20
# Minute 2: us-east-1 dial = 60, us-west-2 dial = 40
# Minute 3: us-east-1 dial = 40, us-west-2 dial = 60
# Minute 4: us-east-1 dial = 20, us-west-2 dial = 80
# Minute 5: us-east-1 dial = 0, us-west-2 dial = 100
# → Zero-downtime failover!
```

**When to Use Which:**

```yaml
Use CloudFront when:
  - Content is cacheable (static assets, video, images)
  - Need Lambda@Edge for request/response modification
  - Need origin shield to reduce origin load
  - Need signed URLs/cookies for access control
  - Need WAF integration at edge

Use Global Accelerator when:
  - Traffic is dynamic/API (non-cacheable)
  - Need static IP addresses (for whitelisting)
  - Need TCP optimization for global users
  - Need gradual failover with traffic dials
  - Use UDP (e.g., gaming, streaming protocols)

Use both when:
  - Static assets → CloudFront
  - Dynamic API → Global Accelerator
  - Same application, different traffic types
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Anycast routing** | Explains how same IP is advertised globally, BGP routes to nearest |
| **TCP optimization** | Understands edge termination + backbone re-establishment |
| **Traffic dials** | Uses traffic dials for zero-downtime failover |
| **Use case selection** | Can clearly differentiate CF vs GA for given workload |

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-global-accelerator.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Global Accelerator vs CloudFront — anycast routing, TCP optimization, traffic dials, and when to use each — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 6. Transit Gateway: Multi-VPC Connectivity

**Q:** "Your company has 50 VPCs across 3 AWS regions (dev, staging, prod environments). Some VPCs need to communicate (prod→prod across regions), others must be isolated (dev→prod). Design a Transit Gateway architecture. How does TGW route tables work? How do you isolate environments?"

**What They're Really Testing:** Whether you understand Transit Gateway's routing architecture — route tables, attachments, and the hub-and-spoke model for multi-VPC connectivity.

### Answer

**Transit Gateway Architecture:**

```yaml
TGW Hub (us-east-1):
  ┌──────────────────────────────────────────────┐
  │  Transit Gateway                               │
  │                                                │
  │  Route Table: prod-rtb                         │
  │  10.0.0.0/16 → vpc-prod-east (attachment)     │
  │  10.1.0.0/16 → vpc-prod-west (TGW peering)    │
  │  0.0.0.0/0 → vpc-inspection (NAT/inspection)  │
  │                                                │
  │  Route Table: dev-rtb                          │
  │  10.100.0.0/16 → vpc-dev-east (attachment)    │
  │  10.200.0.0/16 → vpc-dev-west (no peering!)   │
  │  0.0.0.0/0 → vpc-inspection (NAT/inspection)  │
  │                                                │
  │  Route Table: isolated-rtb                     │
  │  (no routes to other environments)             │
  └────────────────────────────────────────────────┘
```

**Route Table Isolation:**

```yaml
# Create separate route tables for each environment:

TGW Route Table: prod
  Associations: vpc-prod-attachment, vpc-shared-services-attachment
  Propagations: vpc-prod-attachment (auto-learn CIDR)
  Routes:
    - Destination: 10.0.0.0/8     → blackhole (no prod→dev)
    - Destination: 10.0.0.0/16    → vpc-prod-attachment
    - Destination: 0.0.0.0/0      → vpc-inspection-attachment (NAT)
    - Destination: 10.1.0.0/16    → tgw-peering-us-west-2 (cross-region prod)

TGW Route Table: dev
  Associations: vpc-dev-attachment
  Propagations: vpc-dev-attachment
  Routes:
    - Destination: 10.0.0.0/8     → blackhole (no dev→prod)
    - Destination: 10.100.0.0/16  → vpc-dev-attachment
    - Destination: 0.0.0.0/0      → vpc-inspection-attachment

TGW Route Table: shared-services
  Associations: vpc-inspection-attachment, vpc-monitoring-attachment
  Routes:
    - Destination: 10.0.0.0/8     → all VPCs (can reach everything)
    # Shared services (SSO, logging, monitoring) need cross-environment access
```

**Cross-Region TGW Peering:**

```yaml
# Transit Gateway Peering Attachment:
# Connects us-east-1 TGW to us-west-2 TGW

# Peering attachment:
TGW Peering:
  Name: east-west-prod-peering
  TransitGatewayId: tgw-12345 (us-east-1)
  PeerTransitGatewayId: tgw-67890 (us-west-2)
  PeerRegion: us-west-2

# Route in us-east-1 TGW:
# Destination: 10.1.0.0/16 → tgw-peering-attachment (allows traffic to west)

# Route in us-west-2 TGW:
# Destination: 10.0.0.0/16 → tgw-peering-attachment (allows traffic to east)

# Cross-region data transfer cost:
# $0.02/GB transferred (vs $0.09/GB internet)
# Latency: ~65ms us-east-1 → us-west-2
```

**TGW vs VPC Peering at 50 VPCs:**

```yaml
VPC Peering (manual):
  - 50 VPCs → (50 × 49) / 2 = 1225 peerings
  - Each peering: create request, accept, add route in both route tables
  - Each VPC: up to 125 route table entries (fills up fast!)
  - Route table: 1225 routes → impossible
  - No transitive routing → full mesh = n² complexity

Transit Gateway:
  - 50 VPCs → 50 TGW attachments
  - 1 TGW route table per environment
  - Each VPC: 1 default route (0.0.0.0/0 → TGW)
  - Transitive routing: VPCs in same route table can communicate
  - 50 routes total (not 1225!)

Cost comparison (per month):
  VPC Peering: 1225 × $0.01/hour × 730 hours = $8,942
  Transit Gateway: 50 attachments × $0.05/hour × 730 = $1,825
                  + data transfer: ~$500
  Total TGW: ~$2,325/month (74% cheaper than VPC peering!)
```

**Inspection VPC (Centralized Security):**

```yaml
┌──────────────┐    ┌──────────────────┐    ┌──────────────┐
│  Prod VPC     │───►│  Inspection VPC  │◄───│  Dev VPC      │
│  10.0.0.0/16  │    │                  │    │  10.100.0.0/16│
│              │    │  ┌────────────┐   │    │              │
│              │    │  │ Firewall   │   │    │              │
│              │    │  │ (Fortinet/ │   │    │              │
│              │    │  │  Palo Alto)│   │    │              │
│              │    │  └────────────┘   │    │              │
│              │    │                  │    │              │
│              │    │  ┌────────────┐   │    │              │
│              │    │  │ IDS/IPS    │   │    │              │
│              │    │  └────────────┘   │    │              │
└──────────────┘    └──────────────────┘    └──────────────┘

# All traffic between VPCs routes through Inspection VPC
# Firewall inspects all traffic (costly but secure)
# Alternative: VPC Network Firewall (AWS-native, per-VPC)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Route table isolation** | Creates separate route tables per environment to isolate traffic |
| **Cross-region peering** | Uses TGW peering for cross-region connectivity |
| **Cost comparison** | Quantifies TGW vs VPC peering cost savings at scale |
| **Inspection VPC** | Designs centralized firewall/IDS for compliance |

---

## 7. Site-to-Site VPN & Direct Connect

**Q:** "Your on-premises data center needs connectivity to AWS for a hybrid cloud architecture. You need: 10Gbps throughput, <5ms latency, and 99.99% availability. Compare Direct Connect vs Site-to-Site VPN. Design a hybrid network with both active and failover paths."

**What They're Really Testing:** Whether you understand the operational trade-offs between VPN (internet-based, encrypted, variable latency) and Direct Connect (private fiber, consistent latency, higher cost).

### Answer

**Direct Connect vs VPN:**

```yaml
Site-to-Site VPN:
  - Connection: Internet (public)
  - Encryption: IPSec (mandatory)
  - Bandwidth: Up to 1.25 Gbps per tunnel (max 4 tunnels = 5 Gbps)
  - Latency: Variable (depends on internet routing)
  - SLA: 99.95% (if using 2 tunnels)
  - Setup: Hours (configure CGW + VGW)
  - Cost: $0.05/hour per VPN connection + data out

Direct Connect:
  - Connection: Private fiber (cross-connect at DX location)
  - Encryption: Optional (MACsec at L2, or IPSec over DX)
  - Bandwidth: 50Mbps to 100Gbps
  - Latency: Consistent (~1-5ms from DX location to region)
  - SLA: 99.99% (with redundant connections)
  - Setup: Weeks (fiber provisioning, cross-connect)
  - Cost: $0.02/hour per port + data out ($0.02-0.08/GB)

Hybrid Architecture (active-active + failover):
  ┌─────────────┐        ┌──────────────────┐
  │  On-premises │────────┤  Direct Connect   │──── Active path
  │              │  10Gbps │  (us-east-1)     │    (primary)
  │              │        └────────┬─────────┘│
  │              │                 │           │    AWS
  │              │        ┌────────▼─────────┐ │    Cloud
  │              │────────┤  Site-to-Site VPN │──── Failover path
  │              │ 1Gbps  │  (internet)      │    (backup)
  └─────────────┘        └──────────────────┘
```

**BGP Routing with Direct Connect:**

```yaml
# Direct Connect: BGP sessions over private VIF (VLAN)
# Two BGP sessions (one per DX connection) for redundancy

On-prem router (BGP config):
  router bgp 65001
    neighbor 169.254.10.1 remote-as 64512     # DX connection A
    neighbor 169.254.10.1 description "AWS Direct Connect VIF-A"
    
    address-family ipv4
      network 10.0.0.0/8      # Advertise on-prem CIDR
      neighbor 169.254.10.1 activate
      
      # AWS advertises: VPC CIDR (10.0.0.0/16)
      # Route preference: AS path prepend for backup
      
    neighbor 169.254.20.1 remote-as 64512     # DX connection B (backup)
    neighbor 169.254.20.1 description "AWS Direct Connect VIF-B"
    address-family ipv4
      neighbor 169.254.20.1 route-map PREPEND out
      
route-map PREPEND permit 10
  set as-path prepend 65001 65001 65001        # Prepend AS 3× = less preferred

# AWS side (Virtual Private Gateway):
# - Auto-accepts BGP routes from on-prem
# - Propagates to VPC route tables
# - Prefers specific routes over default (0.0.0.0/0 via VPN)
```

**Direct Connect Gateway:**

```yaml
# Direct Connect Gateway connects DX to multiple VPCs/regions
# Single DX connection → DX Gateway → multiple VPCs

┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
│ On-premises   │─────│ DX Connection │─────│  DX Gateway      │
│              │     │  (10Gbps)    │     │  (global)        │
└──────────────┘     └──────────────┘     └──┬───────┬───────┘
                                              │       │
                                    ┌─────────▼┐  ┌──▼────────┐
                                    │ VPC us-   │  │ VPC eu-   │
                                    │ east-1    │  │ west-1    │
                                    │ 10.0.0.0/16│  │ 10.1.0.0/16│
                                    └──────────┘  └──────────┘

# Benefits:
# - Single DX connection serves VPCs in all regions
# - No need for DX in each region
# - Centralized BGP management
# - Cost: $0.02/hour per VPC association + data transfer
```

**VPN CloudHub (Branch Offices):**

```yaml
# Multiple branch offices connecting to AWS via VPN:
# Each branch: Site-to-Site VPN to TGW
# TGW VPN attachments enable branch-to-branch routing

TGW: tgw-12345
  Attachments:
    - vpc-prod        (attachment)
    - vpn-branch-nyc  (VPN attachment)
    - vpn-branch-lon  (VPN attachment)
    - vpn-branch-tok  (VPN attachment)
  
  Route Table: branch
    Routes:
      - 10.10.0.0/16   → vpn-branch-nyc
      - 10.20.0.0/16   → vpn-branch-lon
      - 10.30.0.0/16   → vpn-branch-tok
      - 10.0.0.0/16    → vpc-prod
    
    # Branch offices can reach each other via TGW
    # NYC (10.10.x.x) → TGW → LON (10.20.x.x) works!
    # No need for site-to-site VPN between branches
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **DX vs VPN trade-offs** | Quantifies latency, bandwidth, SLA, and cost differences |
| **BGP routing** | Uses AS path prepend for route preference, active-active design |
| **DX Gateway** | Connects DX to multiple VPCs/regions through single gateway |
| **CloudHub** | Uses TGW VPN attachments for branch-to-branch routing |

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-directconnect-vpn.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Direct Connect & Site-to-Site VPN — dedicated fiber vs IPSec tunnel, BGP routing, hybrid connectivity with active-active + failover — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 8. VPC Flow Logs & Network Traffic Analysis

**Q:** "Your security team suspects a data exfiltration attempt. You need to analyze all outbound traffic from a VPC containing sensitive customer data. How do VPC Flow Logs work? How do you collect, aggregate, and analyze 100TB of flow logs per day? What patterns indicate exfiltration?"

**What They're Really Testing:** Whether you understand VPC Flow Logs' data model, the cost of logging at scale, and how to analyze network traffic for security threats.

### Answer

**VPC Flow Logs Data Model:**

```yaml
# Flow Log record (version 2-5):
# Fields: version account-id interface-id srcaddr dstaddr srcport dstport protocol packets bytes start end action log-status

# Example:
2 123456789012 eni-abc123 10.0.1.42 52.84.120.10 54321 443 6 10 1200 1625097600 1625097660 ACCEPT OK
#                        │          │             │     │   │  │   │    │          │        │      │
#                        │          │             │     │   │  │   │    │          │        │      │
#                        src        dst          src   dst  tcp pkts bytes start   end     action  status
#                                                  port  port

# Aggregation: Flow logs are aggregated every 10 minutes by default
# Each flow log record represents a unidirectional TCP/UDP flow
# Flow key: (src, dst, srcport, dstport, protocol)

# Cost at scale (100TB/day):
# Published to S3: $0.00 (free)
# Published to CloudWatch Logs: $0.50/GB ingested
#   = 100TB × 1024 × $0.50 = $51,200/day!
# Published to S3 via Kinesis Firehose: $0.00/GB (cheaper)
#   = $0.00 for flow logs + Firehose $0.03/GB
```

**Collecting Flow Logs at Scale:**

```yaml
# Recommended: Flow Logs → S3 → Athena (cheapest)

# Step 1: Enable flow logs at VPC level (all ENIs)
# Step 2: Publish to S3 with Hive-compatible partition
# Bucket: my-flow-logs-prod
# Path: AWSLogs/123456789012/vpcflowlogs/us-east-1/2024/01/15/

# Step 3: Create Athena table
CREATE EXTERNAL TABLE vpc_flow_logs (
  version int,
  account string,
  interface_id string,
  srcaddr string,
  dstaddr string,
  srcport int,
  dstport int,
  protocol int,
  packets bigint,
  bytes bigint,
  start bigint,
  end bigint,
  action string,
  log_status string
)
PARTITIONED BY (region string, day string)
ROW FORMAT DELIMITED
FIELDS TERMINATED BY ' '
LOCATION 's3://my-flow-logs-prod/AWSLogs/123456789012/vpcflowlogs/'
TBLPROPERTIES ("skip.header.line.count"="1");

# Step 4: Load partitions
MSCK REPAIR TABLE vpc_flow_logs;

# Partition pruning: only scan relevant data
SELECT * FROM vpc_flow_logs
WHERE region = 'us-east-1'
  AND day = '2024/01/15'
  AND dstaddr NOT LIKE '10.%'  # External traffic only
LIMIT 10;
```

**Exfiltration Detection Queries:**

```sql
-- Pattern 1: Large data transfers to new destinations
SELECT dstaddr, dstport, SUM(bytes) as total_bytes,
       COUNT(*) as flow_count,
       MIN(start) as first_seen,
       MAX(end) as last_seen
FROM vpc_flow_logs
WHERE action = 'ACCEPT'
  AND dstaddr NOT LIKE '10.%'      -- External IP
  AND dstaddr NOT LIKE '172.16.%'  -- Not VPC
  AND dstaddr NOT LIKE '192.168.%' -- Not local
  AND bytes > 100000000            -- > 100MB in single flow
  AND day = '2024/01/15'
GROUP BY dstaddr, dstport
ORDER BY total_bytes DESC
LIMIT 20;

-- Pattern 2: Beaconing (periodic small connections to same IP)
SELECT dstaddr,
       COUNT(*) as connection_count,
       COUNT(DISTINCT date(from_unixtime(start))) as active_days,
       MIN(start) as first_seen,
       MAX(start) as last_seen
FROM vpc_flow_logs
WHERE action = 'ACCEPT'
  AND dstport = 443
  AND bytes < 10000  -- Small payloads (beaconing)
  AND dstaddr NOT IN (
    -- Whitelist known services
    '52.84.120.10',  -- Internal API
    '8.8.8.8'        -- DNS
  )
  AND day >= '2024/01/01'
GROUP BY dstaddr
HAVING active_days >= 3
   AND connection_count >= 10
ORDER BY connection_count DESC;

-- Pattern 3: Data exfiltration to unusual ports
SELECT dstaddr, dstport, protocol, SUM(bytes) as total_bytes
FROM vpc_flow_logs
WHERE action = 'ACCEPT'
  AND dstaddr NOT LIKE '10.%'
  AND dstport NOT IN (80, 443, 22, 53, 25, 21, 3306, 5432) -- Unusual ports
  AND bytes > 10000000  -- > 10MB
  AND day = '2024/01/15'
GROUP BY dstaddr, dstport, protocol
ORDER BY total_bytes DESC;
```

**Flow Logs Cost Optimization:**

```yaml
# Cost optimization strategies for flow logs at scale:

# 1. Aggregate format (v5) instead of v2
# v5: includes subnets, VPC, region as fields → reduces Athena scanning
# Data size: v2 = 100TB, v5 = 80TB (20% less)

# 2. Partition by hour instead of day (for hot data)
s3://bucket/AWSLogs/.../us-east-1/2024/01/15/13/
# Query only last 2 hours for real-time analysis → 1/12th data scanned

# 3. Use S3 Intelligent-Tiering
# Flow logs older than 30 days → move to Glacier
# 95% cost reduction on storage

# 4. Sample instead of full capture
# For non-critical VPCs: accept only every N flows
# For critical VPCs: full capture (compliance requirement)

# 5. Use Kinesis Firehose to S3 with dynamic partitioning
# Cost: $0.03/GB (vs $0.50/GB if using CloudWatch Logs)
# 94% cost reduction!
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Flow log format** | Understands the record format, aggregation, and partitioning |
| **Exfiltration detection** | Can write Athena queries for beaconing, large transfers, unusual ports |
| **Cost at scale** | Quantifies CloudWatch Logs vs S3 cost difference (5x-10x) |
| **Partitioning** | Uses Hive partitions for efficient Athena querying |

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-vpc-flow-logs.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated VPC Flow Logs & Network Traffic Analysis — ENI capture → S3 → Athena query → GuardDuty detection → auto-remediation — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 9. AWS WAF & Shield: DDoS Protection

**Q:** "Your SaaS platform is targeted by a Layer 7 DDoS attack — thousands of unique IPs sending malicious requests that mimic legitimate traffic. Design a multi-layer DDoS defense strategy using AWS Shield Advanced, WAF, and CloudFront. How do you distinguish bot traffic from humans? How do you handle false positives?"

**What They're Really Testing:** Whether you understand defense-in-depth against application-layer DDoS — WAF rate limiting, bot control, and the operational challenges of managing false positives during an active attack.

### Answer

**Multi-Layer DDoS Defense:**

```yaml
Layer 1: Global edge (AWS Shield Standard — FREE, always-on)
  - Protects against L3/L4 attacks (SYN floods, UDP reflection, etc.)
  - AWS network: 100s of Gbps absorption capacity
  - Automatic: no configuration needed

Layer 2: Shield Advanced ($3,000/month + data out commit)
  - Enhanced DDoS detection and mitigation
  - DDoS Response Team (DRT) 24/7 access
  - Cost protection: credits for scaled resources
  - Proactive engagement: Shield auto-mitigates detected attacks

Layer 3: CloudFront + WAF
  - CloudFront absorbs at edge (450+ PoPs)
  - WAF Web ACL with rate-based rules
  - Bot Control managed rule group
  - Custom rule groups for application logic

Layer 4: ALB + WAF
  - Regional WAF Web ACL
  - WAF rate limiting per IP
  - WAF fraud control (account takeover prevention)

Layer 5: Application
  - CAPTCHA (CloudFront + WAF supports AWS WAF CAPTCHA)
  - JWT validation, session-based rate limiting
  - Circuit breaker patterns
```

**WAF Rate Limiting Rules:**

```json
{
  "Name": "rate-limit-per-ip",
  "Priority": 10,
  "Action": {
    "Block": {}
  },
  "VisibilityConfig": {
    "SampledRequestsEnabled": true,
    "CloudWatchMetricsEnabled": true,
    "MetricName": "RateLimitPerIP"
  },
  "Statement": {
    "RateBasedStatement": {
      "Limit": 2000,          // 2000 requests per 5 minutes
      "AggregateKeyType": "IP",
      "EvaluationWindowSec": 300,
      "ScopeDownStatement": {
        "ByteMatchStatement": {   // Only count API requests
          "SearchString": "/api/",
          "FieldToMatch": { "UriPath": {} },
          "TextTransformations": [{"Priority": 0, "Type": "NONE"}]
        }
      }
    }
  }
}
```

**Bot Control Rules:**

```json
{
  "Name": "AWS-AWSBotControl-Common",
  "Priority": 20,
  "Statement": {
    "ManagedRuleGroupStatement": {
      "VendorName": "AWS",
      "Name": "AWSManagedRulesBotControlRuleSet",
      "Version": "2.0",
      "ManagedRuleGroupConfigs": [
        {
          "AWSManagedRulesBotControlRuleSet": {
            "InspectionLevel": "TARGETED"  // "COMMON" or "TARGETED"
          }
        }
      ],
      "ExcludedRules": [
        {
          "Name": "SignalCatalog"  // Allow known good bots (Googlebot, etc.)
        }
      ]
    }
  },
  "OverrideAction": {
    "Count": {}  // First: count only, don't block (monitor mode)
  },
  "VisibilityConfig": {
    "SampledRequestsEnabled": true,
    "CloudWatchMetricsEnabled": true,
    "MetricName": "BotControl"
  }
}
```

**Handling False Positives:**

```json
{
  "Name": "bypass-for-trusted-ips",
  "Priority": 5,   // HIGHER priority than rate limiting
  "Action": {
    "Allow": {}
  },
  "Statement": {
    "IPSetReferenceStatement": {
      "ARN": "arn:aws:wafv2:us-east-1:123456789:regional/ipset/trusted-cidrs"
    }
  }
}

// IPSet: trusted-cidrs
// - Corporate office CIDR: 203.0.113.0/24
// - VPN CIDR: 10.200.0.0/16
// - Partner API CIDR: 198.51.100.0/24

// During attack: rate limits may block legitimate users behind shared IPs
// Mitigation: WAF CAPTCHA (challenge, don't block)
{
  "Name": "challenge-suspicious",
  "Priority": 15,
  "Action": {
    "Challenge": {}   // Present CAPTCHA to user
  },
  "Statement": {
    "RateBasedStatement": {
      "Limit": 100,
      "AggregateKeyType": "IP"
    }
  }
}
```

**Shield Advanced Proactive Engagement:**

```yaml
# Shield Advanced: DDoS Response Team (DRT) can access your WAF
# and modify rules during an active attack

# Enable proactive engagement:
ShieldSubscription:
  ProactiveEngagement: ENABLED
  EmergencyContact:
    - EmailAddress: oncall@saas.com
      PhoneNumber: "+1-555-123-4567"

# During attack:
# 1. Shield detects anomalous traffic
# 2. DRT reviews samples and metrics
# 3. DRT creates custom WAF rules to block attack
# 4. DRT applies mitigation within 5 minutes
# 5. After attack: DRT removes temporary rules

# Cost protection:
# If attack causes auto-scaling → Shield covers scaling costs
# Up to $3,000/month per month of DDoS-related scaling
```

**Attack Mitigation Playbook:**

```yaml
Active attack response (L7 DDoS):

Minute 0: Detection
  - CloudWatch alarm: WAF BlockedRequests > 10,000/min
  - CloudWatch alarm: ALB 5xx errors > 5%

Minute 1: Analysis
  - Review WAF sampled requests (IP, path, user-agent, referer)
  - Signatures: same path, unusual user-agent, no referer
  - Check Shield Advanced dashboard

Minute 2: Mitigation
  # Option A: Increase rate limiting
  Update WAF: rate limit from 2000 → 500 per IP
  
  # Option B: Block by path (if all requests hit /api/login)
  Update WAF: block requests to /api/login from non-corporate IPs
  
  # Option C: Enable challenge mode (CAPTCHA for suspicious)
  Update WAF: Challenge all requests above 100/5min

Minute 5: Verification
  - Check legitimate traffic: is it still flowing?
  - Check blocked traffic: is the rate reducing?
  - If false positives: adjust bypass rules

Minute 10: Post-attack
  - Remove temporary rules
  - Document attack pattern for permanent rules
  - Review Shield Advanced cost protection claim
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Multi-layer defense** | Designs from edge (Shield) → application (CAPTCHA) |
| **Rate limiting** | Uses rate-based rules with scope-down to specific paths |
| **Bot control** | Uses managed rule groups with targeted inspection level |
| **False positive handling** | Has IP whitelist, challenge mode, and CAPTCHA as less aggressive options |

---

## 10. Network ACLs vs Security Groups

**Q:** "Design a defense-in-depth network security architecture for a multi-tier application. Compare security groups (stateful) vs network ACLs (stateless). When would you use both? Walk through a web application firewall configuration: Internet → ALB → App → DB."

**What They're Really Testing:** Whether you understand the fundamental difference between stateful (SG) and stateless (NACL) firewalls — and how to layer them for defense-in-depth.

### Answer

**Security Groups vs Network ACLs:**

```yaml
Security Groups (Instance-level):
  - Stateful: return traffic automatically allowed
  - Default: deny all inbound, allow all outbound
  - Rules: allow only (no explicit deny)
  - Evaluation: all rules evaluated (not ordered)
  - Scope: attached to ENI (not subnet)
  - Supports: IP, CIDR, another SG, prefix list
  - Limits: 60 inbound + 60 outbound rules per SG

Network ACLs (Subnet-level):
  - Stateless: must define BOTH inbound AND outbound rules
  - Default: deny all inbound, deny all outbound
  - Rules: allow AND deny (explicit deny possible)
  - Evaluation: ordered (lowest number first)
  - Scope: attached to subnet (applies to all instances)
  - Supports: IP, CIDR (not SG or prefix list)
  - Limits: 20 inbound + 20 outbound rules per NACL
```

**Defense-in-Depth Architecture:**

```yaml
Internet ──► ALB ──► App ──► DB
  │          │         │       │
  ▼          ▼         ▼       ▼
 NACL-1    NACL-2    NACL-3  NACL-4
 (public)  (alb)     (app)   (db)
    │         │         │       │
 SG-ALB    SG-INST    SG-DB
 (ALB)     (instances) (RDS)

# Subnet NACLs:
NACL-1 (Public Subnet):
  Inbound:
    Rule 100: Allow 0.0.0.0/0 tcp/443       (HTTPS from internet)
    Rule 200: Allow 0.0.0.0/0 tcp/80        (HTTP redirect)
    Rule *:   Deny all
  
  Outbound:
    Rule 100: Allow 0.0.0.0/0 tcp/32768-65535 (Ephemeral responses)

NACL-2 (ALB Subnet):
  Inbound:
    Rule 100: Allow 0.0.0.0/0 tcp/443         (From internet to ALB)
    Rule *:   Deny all
  
  Outbound:
    Rule 100: Allow 0.0.0.0/0 tcp/8080        (ALB → App health checks)
    Rule 110: Allow 0.0.0.0/0 tcp/32768-65535  (Ephemeral responses)

NACL-3 (App Subnet):
  Inbound:
    Rule 100: Allow subnet-alb/24 tcp/8080      (From ALB subnet)
    Rule *:   Deny all
  
  Outbound:
    Rule 100: Allow subnet-db/24 tcp/3306       (App → DB)
    Rule 110: Allow 0.0.0.0/0 tcp/443          (App → external APIs)
    Rule 120: Allow 0.0.0.0/0 tcp/32768-65535   (Ephemeral responses)

NACL-4 (DB Subnet):
  Inbound:
    Rule 100: Allow subnet-app/24 tcp/3306     (From app subnet)
    Rule *:   Deny all
  
  Outbound:
    Rule 100: Allow 0.0.0.0/0 tcp/32768-65535  (Ephemeral responses)
```

**Security Group Rules:**

```yaml
# Security Groups (more flexible than NACLs):

SG-ALB:
  Inbound:
    - Type: HTTPS, Source: 0.0.0.0/0
    - Type: HTTP, Source: 0.0.0.0/0 (redirect to HTTPS)
  
  Outbound:
    - Type: Custom TCP, Port: 8080, Destination: SG-INST

SG-INST:
  Inbound:
    - Type: Custom TCP, Port: 8080, Source: SG-ALB (reference!)
    - Type: SSH, Port: 22, Source: corp-vpn-sg (from VPN)
  
  Outbound:
    - Type: MySQL/Aurora, Port: 3306, Destination: SG-DB
    - Type: HTTPS, Port: 443, Destination: 0.0.0.0/0
    - Type: HTTP, Port: 80, Destination: 0.0.0.0/0

SG-DB:
  Inbound:
    - Type: MySQL/Aurora, Port: 3306, Source: SG-INST (only app!)
    - Type: MySQL/Aurora, Port: 3306, Source: corp-vpn-sg (DBA access)
  
  Outbound: (none needed — stateful, response allowed)

# Key advantage of SG over NACL:
# SG-INST → SG-DB: only instances in SG-INST can reach DB
# Not CIDR-based → no need to track instance IPs!
# Auto-updates: new instances in SG-INST automatically allowed
```

**When to Use Both:**

```yaml
Use NACL + SG together for defense-in-depth:

NACL acts as STATELESS first line of defense:
  - Blocks known bad CIDRs (e.g., known attack IPs)
  - Explicit deny for certain traffic (malware C2 IPs)
  - Subnet-level protection even if SG misconfigured
  - Protects against accidental SG allow-all

SG acts as STATEFUL application-level firewall:
  - Fine-grained allow rules using SG references
  - Auto-updates as instances scale
  - No need to track ephemeral ports

Examples of NACL-only protections (not possible with SG):
  - Block traffic from specific country CIDRs
  - Explicit deny for known bad IPs
  - Protect against SG misconfiguration (e.g., someone opens 0.0.0.0/0)
  
# Common mistake: using NACLs without SGs (or vice versa)
# NACL without SG: instance-level exposure (NACL only protects subnet)
# SG without NACL: no subnet-level defense against misconfiguration
```

**Troubleshooting Connectivity:**

```yaml
# When connectivity fails, check both SG and NACL:

# 1. Check Security Group (most common culprit):
# Test: Is SG allowing inbound AND outbound?
# Symptom: SG allows inbound (SG-DB allows 3306 from SG-INST)
#          But SG-INST doesn't allow outbound 3306 → CONNECTION FAILS
# Fix: Add outbound rule to SG-INST

# 2. Check NACL (stateless causes asymmetric traffic issues):
# Test: Are outbound ephemeral ports allowed?
# Symptom: NACL-4 allows inbound 3306, but NOT outbound ephemeral ports
#          DB response on ephemeral port → DROPPED by NACL
# Fix: Add outbound rule for ephemeral ports (32768-65535)

# 3. Check route tables:
# Is there a route to the destination?
# Is there a NAT Gateway / Internet Gateway?

# 4. Check VPC Flow Logs (definitive):
# ACCEPT OK → traffic flowing
# REJECT OK → NACL blocked
# ACCEPT NODATA → SG blocked
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Stateful vs stateless** | Explains SG auto-allows return traffic, NACL requires explicit rules |
| **SG reference** | Uses security group references (not CIDRs) for instance-to-instance rules |
| **Defense-in-depth** | Uses NACL for subnet-level explicit denies + SG for application rules |
| **Troubleshooting** | Diagnoses connectivity by checking SG, NACL, and route table in order |

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-sg-vs-nacl.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Security Groups vs Network ACLs — stateful SG vs stateless NACL, defense-in-depth with SG references and subnet-level protection — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

> *All 10 questions cover the full breadth of AWS networking — from VPC design and load balancing to DDoS defense and security group architecture.*
