# ☁️ AWS Networking — Staff-Level Interview Questions

> *10 questions covering VPC, ALB/NLB, CloudFront, Route 53, Global Accelerator, Transit Gateway, VPN, Direct Connect and network security. Each answer leads with the 30-second version, then the mechanism, trade-offs, failure modes and what interviewers probe next. Prices are us-east-1 list prices and limits were checked against AWS documentation, October 2026.*

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

!!! tip "30-second answer"
    Allocate CIDRs centrally (VPC IPAM) so no VPC, Region or on-prem range overlaps, because overlap blocks peering, Transit Gateway and Direct Connect routing forever. Use three subnet tiers per AZ across three AZs: public (load balancers only), private app (egress via NAT), isolated data (no internet route). Size app subnets generously; containers and Lambda consume IPs fast. Add **gateway endpoints** for S3 and DynamoDB (free) and **interface endpoints** for heavily used AWS APIs so that traffic skips NAT processing charges and stays private. Plan IPv6 (dual-stack) now: every public IPv4 address costs $0.005/hour since February 2024.

**CIDR plan:**

```yaml
Production VPC (us-east-1): 10.0.0.0/16      # from an IPAM pool, never hand-picked
  Public (ALB, NAT):        10.0.0.0/24, 10.0.1.0/24, 10.0.2.0/24          # 3 AZs
  Private app:              10.0.32.0/19, 10.0.64.0/19, 10.0.96.0/19       # 8,187 usable each
  Isolated data:            10.0.128.0/24, 10.0.129.0/24, 10.0.130.0/24
  Reserved for growth:      10.0.192.0/18
  IPv6: Amazon-provided /56, a /64 per subnet (dual-stack)

DR VPC (us-west-2): 10.1.0.0/16                # non-overlapping with prod and on-prem
On-prem:            172.16.0.0/12              # must not overlap any VPC
```

- AWS reserves 5 addresses in every subnet (network, router, DNS, future, broadcast).
- EKS with the VPC CNI, Fargate and Lambda each take one IP per pod/task/ENI, which is why app subnets are /19 here. You can add secondary CIDRs later (including 100.64.0.0/10 for pods), but you cannot shrink or move the primary.
- Isolated subnets have no `0.0.0.0/0` route at all; databases reach AWS APIs through endpoints only.
- **VPC Block Public Access** (Nov 2024) can enforce "no IGW traffic" at the account or Region level, with exclusions, as a guardrail.

**Egress and endpoints:**

| Path | Price | Notes |
|---|---|---|
| NAT gateway | ~$0.045/hour per gateway + $0.045/GB processed | One per AZ for zonal resilience, or a **regional NAT gateway** (Nov 2025) that spans AZs automatically |
| Gateway endpoint (S3, DynamoDB) | Free | Route-table entry using a prefix list; same-Region only |
| Interface endpoint (PrivateLink) | ~$0.01/hour per AZ + $0.01/GB | ENIs in your subnets with private DNS; works from on-prem and peered VPCs |

Example: 10 TB/month of S3 traffic through a NAT gateway costs ~$450 in processing alone; through a gateway endpoint it costs $0. Interface endpoints pay off once an AWS service's traffic is a few hundred GB/month per VPC; in multi-VPC setups centralise them in a shared-services VPC with Route 53 Resolver rules.

**VPC peering vs Transit Gateway vs VPC Lattice:**

| | VPC peering | Transit Gateway | VPC Lattice |
|---|---|---|---|
| Model | 1:1, non-transitive | Hub-and-spoke router, transitive, route tables | Application-layer service network (HTTP/HTTPS/gRPC/TCP) |
| Scale | Full mesh needs N(N−1)/2 links; max 125 peerings per VPC | Thousands of attachments | Service-to-service across VPCs/accounts |
| Overlapping CIDRs | Not allowed | Not allowed | Allowed (it isn't IP routing) |
| Cost | No hourly fee; same-AZ data free, cross-AZ/Region data charged | $0.05/hour per attachment + $0.02/GB processed | Per service-hour + per GB + per request |
| Best for | A few VPCs with heavy traffic between them | Many VPCs, on-prem, central inspection | Microservices across accounts with IAM auth policies |

**What they probe next:** cross-AZ data transfer ($0.01/GB each way) as the hidden cost of "spread everything across AZs"; why NAT gateways per AZ (an AZ failure shouldn't kill egress for the others); private DNS for interface endpoints across many VPCs; IPv6-only subnets with DNS64/NAT64 to escape IPv4 charges.

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-vpc-peering-vs-tgw.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated VPC Peering vs Transit Gateway — 1:1 connection vs hub-and-spoke with transitive routing comparison — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **CIDR planning** | Reserves non-overlapping ranges centrally, sizes subnets for IP-hungry compute |
| **Endpoint strategy** | Uses Gateway Endpoints for free S3/DynamoDB access, Interface for others |
| **NAT cost** | Quantifies NAT gateway cost, explains endpoint alternatives |
| **Peering vs TGW** | Understands transitive routing limitation of peering, and when Lattice fits |

---

## 2. ALB vs NLB: Load Balancer Deep Dive

**Q:** "Your application needs to handle 1M concurrent WebSocket connections with sub-10ms latency. Compare ALB vs NLB. How does each handle connection draining, sticky sessions, and TLS termination at scale? When would you use both in front of the same application?"

**What They're Really Testing:** Whether you understand the architectural differences between L7 and L4 load balancing — when the overhead of HTTP inspection is worth it, and when raw TCP performance is required.

### Answer

!!! tip "30-second answer"
    For 1M long-lived WebSockets, the **NLB** is the natural fit: it forwards TCP flows (no HTTP parsing), adds well under a millisecond, gives static IPs per AZ, and is far cheaper per idle connection (100,000 active connections per NLCU vs 3,000 per ALB LCU). Choose the **ALB** when you need L7 features: path/host routing, OIDC/Cognito auth, WAF, gRPC, per-request stickiness. Put an **NLB in front of an ALB** (ALB-type target group) when you need both static IPs/PrivateLink and L7 routing. Either way, the real bottleneck at 1M connections is usually your targets' file descriptors and memory, plus reconnect storms during deploys.

**Comparison:**

| | ALB | NLB |
|---|---|---|
| Layer | L7: HTTP/1.1, HTTP/2, gRPC, WebSocket | L4: TCP, UDP, TLS (QUIC passthrough via UDP) |
| Added latency | A few ms (parses HTTP, evaluates rules) | Typically sub-ms (flow-hash forwarding on Hyperplane) |
| IPs | Changing IPs; use DNS (alias) | One static IP per AZ, can be Elastic IPs |
| Client IP | `X-Forwarded-For` header | Preserved at the packet level (instance targets) or Proxy Protocol v2 |
| Security groups | Yes | Yes (since Aug 2023) |
| TLS | Terminates; SNI; re-encrypts to HTTPS targets; **mTLS** verify or passthrough (Nov 2023) | Terminates (TLS listener) or passes through (TCP listener) |
| Idle timeout | Default 60 s, up to 4,000 s | TCP default 350 s, configurable 60–6,000 s |
| Stickiness | Duration cookie (`AWSALB`) or application cookie | Source-IP affinity |
| Price | $0.0225/hour + $0.008/LCU-hour | $0.0225/hour + $0.006/NLCU-hour |

**Cost of 1M idle WebSockets (connection dimension only):**

```
ALB: 1,000,000 active / 3,000 per LCU   ≈ 333 LCUs × $0.008 ≈ $2.67/hour (~$1,950/month)
NLB: 1,000,000 active / 100,000 per NLCU =  10 NLCUs × $0.006 = $0.06/hour (~$44/month)
(Billing uses the highest of the dimensions: new connections, active connections, bytes, and for ALB rule evaluations.)
```

**Connection draining:** both use the target group's **deregistration delay** (0–3,600 s, default 300 s). For HTTP the ALB stops routing new requests to the target and waits for in-flight ones; for WebSockets and TCP, existing connections keep flowing until they close or the delay expires, then they're cut. Design clients to reconnect with jittered backoff and have the server close connections gradually during shutdown, otherwise each deploy creates a thundering herd of reconnects.

**Scaling to 1M connections:**

- Both load balancers scale horizontally on their own, but scaling takes minutes. For a known event, use **LCU capacity reservations** (Nov 2024) to pre-provision ALB/NLB capacity instead of filing a pre-warm ticket.
- NLB cross-zone load balancing is off by default (and cross-AZ data is charged when you enable it); with uneven targets per AZ, connections skew.
- Targets: raise `ulimit -n`, tune kernel socket buffers, and keep per-connection memory small; 1M connections across 20 targets is 50,000 each.

**TLS termination options:**

| Pattern | Pros | Cons |
|---|---|---|
| ALB terminates, HTTP to targets | Simple; ACM auto-renewing certs; WAF can inspect | Plaintext inside the VPC (often acceptable; Nitro encrypts traffic between supported instances anyway) |
| ALB terminates, HTTPS to targets | Encrypted end-to-end, still L7 features | Target certs to manage; ALB doesn't validate target certs |
| NLB TLS listener | Offloads TLS, keeps L4 performance | No HTTP awareness |
| NLB TCP passthrough | True end-to-end TLS; client certs reach the app | Targets do TLS work; no WAF |

**What they probe next:** gRPC (ALB supports it natively with HTTP/2 to targets), slow-start mode and least-outstanding-requests routing on ALB, NLB's handling of target health with "fail open" when all targets are unhealthy, and why you'd consider API Gateway WebSocket APIs (managed connections, per-message pricing) or AppSync Events instead of running sockets yourself.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Latency and cost math** | Quantifies ALB vs NLB latency and per-connection cost correctly |
| **WebSocket handling** | Knows ALB does native upgrade, NLB passes TCP through, and idle timeouts matter |
| **Connection draining** | Explains deregistration delay and reconnect storms |
| **Combined architecture** | Can design NLB+ALB stack for static IP + L7 routing |

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

!!! tip "30-second answer"
    Create three **latency** alias records for the same name, one per Region, each with a health check (or `EvaluateTargetHealth` on the ALB alias). Route 53 answers with the lowest-latency **healthy** Region, so failover is built in; you don't need a separate failover record. Worst-case failover time is detection (≈ interval × threshold, ~30 s with fast checks) plus resolver caching (the TTL, 60 s for ELB aliases) plus clients that cache longer. For deterministic, operator-driven failover use **Route 53 ARC** routing controls or Region switch, and for second-scale failover without DNS use Global Accelerator.

**Records:**

```yaml
# Same name, same type, different SetIdentifier and Region
api.saas.example.com  A  ALIAS  latency  us-east-1       → ALB us-east-1       EvaluateTargetHealth: true  HealthCheck: hc-use1
api.saas.example.com  A  ALIAS  latency  eu-west-1       → ALB eu-west-1       EvaluateTargetHealth: true  HealthCheck: hc-euw1
api.saas.example.com  A  ALIAS  latency  ap-southeast-1  → ALB ap-southeast-1  EvaluateTargetHealth: true  HealthCheck: hc-apse1
```

You can't mix routing policies on the same name and type. To combine them (e.g. latency between Regions, weighted within a Region, failover to a static page), build a **tree**: latency records alias to weighted or failover records under other names. Traffic Flow policies draw this tree for you.

**Routing policies:**

| Policy | Use |
|---|---|
| Simple | One answer (multiple values returned in random order, no health checks) |
| Weighted | Canary or blue/green between endpoints (same name, weights per record) |
| Latency | Lowest measured latency between the resolver's network and the AWS Region |
| Failover | Active-passive; secondary only when primary is unhealthy |
| Geolocation | By continent/country/state; compliance and localisation; needs a default record |
| Geoproximity | By distance with a bias to grow or shrink a Region's catchment |
| IP-based | By client CIDR (e.g. ISP-specific routing) |
| Multivalue answer | Up to 8 healthy records, a poor man's client-side load balancing |

**How health checks work:**

- Checkers in multiple Regions (you choose at least 3) probe the endpoint; an endpoint is healthy if more than 18% of checkers report healthy.
- HTTPS checks can require a **search string** in the first 5,120 bytes of the response.
- Interval 30 s (standard) or 10 s (fast, extra cost); failure threshold 1–10.
- **Calculated** health checks combine others (e.g. "healthy if 2 of 3 child checks pass").
- **CloudWatch-alarm** health checks follow a metric alarm (e.g. 5xx rate), which is better than a shallow `/health` ping for detecting a sick Region. Private endpoints can only be checked this way, since checkers run on the internet.
- `EvaluateTargetHealth` on an ALB alias marks the record unhealthy when the ALB has no healthy targets in any AZ, at no extra cost.

**Failover timing:**

```
detection:   10 s interval × 3 failures       ≈ 30 s
propagation: Route 53 updates answers         ≈ seconds
caching:     resolvers honour TTL (ELB alias = 60 s); some clients and JVMs cache longer
worst case:  ~1.5–2 minutes for most clients; long-lived connections never re-resolve
```

Mitigations: keep TTLs at 60 s or less on failover-critical names, make clients reconnect (and re-resolve) on errors, set the JVM DNS cache TTL (`networkaddress.cache.ttl`), and pre-scale the surviving Regions, since failover doubles their load instantly.

**Route 53 Application Recovery Controller (ARC):** routing controls are on/off switches backed by health checks whose state lives in a highly available cluster across five Regions. You flip them through the cluster's data-plane endpoints, so failover doesn't depend on the Route 53 control plane in us-east-1. **ARC Region switch** (2025) orchestrates a whole-application Region failover plan (DNS, Aurora global database switchover, scaling steps). Readiness checks catch capacity or config drift between Regions before you need them.

**Weighted canary (correct form):**

```yaml
api.saas.example.com  A  ALIAS  weighted  SetIdentifier: stable  Weight: 95  → alb-stable
api.saas.example.com  A  ALIAS  weighted  SetIdentifier: canary  Weight: 5   → alb-canary
```

DNS canaries are coarse: resolvers cache and big resolvers serve millions of users, so the actual split is lumpy. Prefer ALB weighted target groups or service-level canaries for fine control.

**Private DNS:** private hosted zones associated with VPCs (or shared across accounts) give internal names; the same domain in a public and a private zone gives split-horizon DNS. Route 53 Resolver inbound/outbound endpoints and forwarding rules connect VPC DNS with on-prem DNS. Resolver DNS Firewall blocks lookups to malicious domains, a key control against DNS exfiltration.

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="800" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/aws-route53-dns-routing.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Route53 Multi-Region DNS Routing — latency-based routing with health check failover across 3 regions — Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Latency routing** | Explains how Route53 uses latency measurements and health to choose a Region |
| **Failover timing** | Quantifies detection + TTL + client caching |
| **Health checks** | Uses deep or alarm-based health checks to avoid false failover |
| **ALIAS records** | Knows alias queries to AWS resources are free and inherit the target's TTL |

---

## 4. CloudFront: CDN Architecture & Origin Shield

**Q:** "Design a global CDN strategy for a video streaming platform serving 10PB/month. Users are distributed globally. How does CloudFront's edge cache work? What is Origin Shield and how does it reduce origin load? How do you handle cache invalidation for time-sensitive content?"

**What They're Really Testing:** Whether you understand CDN caching at scale — multi-tier cache architecture, origin offload strategies, and cache invalidation trade-offs.

### Answer

!!! tip "30-second answer"
    CloudFront is a cache hierarchy: **edge PoPs** (750+) → **regional edge caches** (larger, longer retention) → optional **Origin Shield** (one designated regional cache in front of each origin) → origin. Origin Shield collapses requests from every regional cache into one, so each object is fetched from origin roughly once; pick the Shield Region closest to the origin. For video, use HLS/DASH with immutable, versioned segment names and long TTLs, short TTLs only on manifests, and avoid invalidations except for emergencies. Lock the S3 origin with **Origin Access Control**, and protect paid content with signed URLs or cookies.

**Cache hierarchy:**

```
viewer ──► edge PoP (nearest of 750+)            miss
             └──► regional edge cache (13 RECs)   miss
                    └──► Origin Shield (one chosen Region, e.g. us-east-1)   miss
                           └──► origin (S3 / ALB / MediaPackage)
```

- Regional edge caches are on by default; Origin Shield is an opt-in extra layer, charged per request that passes through it.
- Request collapsing: concurrent misses for the same object at a cache layer become one upstream fetch.
- Hit ratio depends on the cache key. Every header, cookie or query string you add to the cache policy multiplies variants; forward to the origin what it needs via an **origin request policy** without adding it to the cache key.

**Video design at 10 PB/month:**

| Object | Naming | TTL | Why |
|---|---|---|---|
| Segments (`.ts`/`.m4s`) | Immutable, content-addressed or versioned | Long (days to a year) | Never change, so no invalidation |
| VOD manifests | Versioned per rendition | Hours | Rarely change |
| Live manifests | Fixed name | 1–2 s, matching the segment duration | Must refresh constantly |
| API responses | — | 0 (CachingDisabled policy) | Dynamic |

At this scale, negotiate committed pricing (CloudFront security savings bundle or a private pricing agreement); for smaller sites CloudFront's **flat-rate plans** (bundling CDN, WAF and DDoS protection with no overage charges) can be simpler than pay-as-you-go.

**Invalidation:**

```bash
aws cloudfront create-invalidation --distribution-id E12345 \
  --paths "/live/channel1/manifest.m3u8" "/thumbnails/*"
```

- First 1,000 paths per month free, then $0.005 per path; a wildcard counts as one path.
- Limits: up to 3,000 individual paths, or 15 wildcard paths, in progress at once.
- Invalidation removes objects from caches but doesn't stop browsers or players that already cached them. **Versioned URLs** fix both problems and are the default answer.

**Locking down the S3 origin (OAC, not IP allow-lists):**

```json
{
  "Effect": "Allow",
  "Principal": { "Service": "cloudfront.amazonaws.com" },
  "Action": "s3:GetObject",
  "Resource": "arn:aws:s3:::media-bucket/*",
  "Condition": {
    "StringEquals": { "AWS:SourceArn": "arn:aws:cloudfront::123456789012:distribution/E12345" }
  }
}
```

Origin Access Control (2022) replaces the legacy Origin Access Identity and supports SSE-KMS buckets. Don't allow CloudFront IP ranges in a bucket policy: any CloudFront distribution, including an attacker's, uses those IPs. For ALB or EC2 origins in private subnets, use **VPC origins** (Nov 2024) so the origin needs no public exposure at all; otherwise restrict the ALB security group to the CloudFront managed prefix list and check a secret custom header.

**Signed URLs for private content:**

```python
import datetime
from botocore.signers import CloudFrontSigner
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

KEY_ID = "K2JCJMDEHXQW5F"          # public key ID in the distribution's trusted key group
PRIVATE_KEY = load_private_key()    # e.g. from Secrets Manager

def rsa_signer(message: bytes) -> bytes:
    # SHA-1 is the default. Since April 2026 CloudFront also accepts SHA-256
    # signatures when the URL carries Hash-Algorithm=SHA256.
    return PRIVATE_KEY.sign(message, padding.PKCS1v15(), hashes.SHA1())

signer = CloudFrontSigner(KEY_ID, rsa_signer)

def signed_url(path: str, client_ip: str) -> str:
    url = f"https://cdn.example.com{path}"
    expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    policy = signer.build_policy(url, date_less_than=expires, ip_address=f"{client_ip}/32")
    return signer.generate_presigned_url(url, policy=policy)
```

For HLS/DASH, use **signed cookies** (one credential covers every segment) rather than signing each segment URL. IP-bound policies break for mobile users who change networks; use them sparingly.

**What they probe next:** cache key design and `Vary` headers, CloudFront Functions (sub-millisecond viewer request/response JavaScript) vs Lambda@Edge (heavier, can call the network, runs at regional edge caches), geo-restriction for licensing, origin failover groups, and real-time logs or standard logging v2 for QoE analytics.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Multi-tier cache** | Understands edge → regional edge cache → shield → origin hierarchy |
| **Invalidation cost** | Knows versioned URLs are free and correct, invalidation costs $ and doesn't clear clients |
| **Origin Shield benefit** | Explains request collapsing into one upstream fetch per object |
| **Origin security** | Uses OAC / VPC origins and signed URLs or cookies |

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

!!! tip "30-second answer"
    Both get users onto the AWS backbone at a nearby edge and terminate TCP (and for CloudFront, TLS) close to the user, so both help non-cacheable APIs. Choose **CloudFront** for HTTP(S) APIs: TLS termination at the edge, connection reuse to the origin, WAF, CloudFront Functions, and lower cost. Choose **Global Accelerator** for non-HTTP protocols (TCP/UDP: gaming, VoIP, MQTT), when clients need **two static anycast IPs** to allow-list, or for multi-Region failover in seconds without DNS TTLs. But first check the 800 ms: if the API makes several sequential round trips to a single Region, an edge network only trims each hop; deploying the API in an APAC Region fixes the cause.

**How each path works:**

```
Internet only:   client ──(many ISP hops, ~200 ms RTT, loss)──────────► ALB us-east-1

CloudFront:      client ──(~20 ms)──► edge: TCP+TLS terminated ──(AWS backbone,
                                       warm pooled connections)──────► origin

Global Accel.:   client ──(~20 ms)──► GA edge (anycast IP): TCP terminated ──(AWS backbone)──► endpoint
                                       UDP is proxied without termination
```

Why edge termination helps: the TCP and TLS handshakes (2–3 round trips) happen over the short client-to-edge leg, and congestion-window growth and loss recovery happen on short, clean links rather than across the Pacific. It doesn't remove the speed-of-light cost of the backbone leg.

**Comparison:**

| | CloudFront | Global Accelerator |
|---|---|---|
| Protocols | HTTP/1.1, HTTP/2, HTTP/3, WebSocket | TCP, UDP |
| Entry point | DNS name (IPs vary) | 2 static anycast IPv4 addresses (plus IPv6 for dual-stack) |
| Caching | Yes | No |
| Edge compute, WAF | CloudFront Functions, Lambda@Edge, WAF | No (WAF on the ALB behind it) |
| Failover | Origin groups (per request, on errors) | Health-based across endpoint groups in seconds; **traffic dials** per Region and endpoint weights |
| Client IP to backend | `X-Forwarded-For` / CloudFront-Viewer-Address header | Client IP preservation for ALB/EC2 endpoints |
| Pricing | Data out + requests | $0.025/hour per accelerator + data-transfer premium per GB |

**Traffic dials for controlled shifts:**

```yaml
EndpointGroups:
  us-east-1:  { TrafficDialPercentage: 100, Endpoints: [{alb-1: weight 128}, {alb-2: weight 128}] }
  us-west-2:  { TrafficDialPercentage: 0 }      # warm standby; raise to shift traffic
```

Dial down a Region in steps during maintenance or a regional incident; because the anycast IPs never change, clients don't need to re-resolve DNS.

**Decision guide:**

- Static assets and HTTP APIs: CloudFront (often one distribution with a `CachingDisabled` behaviour for `/api/*`).
- Non-HTTP, static IP allow-listing, or fast multi-Region failover: Global Accelerator.
- Both in one product is common: CloudFront for the web app, GA for a game server or IoT endpoint.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Anycast routing** | Explains how same IP is advertised globally, BGP routes to nearest |
| **TCP optimization** | Understands edge termination + backbone, and its limits |
| **Traffic dials** | Uses traffic dials for controlled regional shifts |
| **Use case selection** | Can clearly differentiate CF vs GA for given workload, and questions the root cause |

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

!!! tip "30-second answer"
    One Transit Gateway per Region, peered across Regions (or **Cloud WAN** with segments if you want a managed global policy). Each attachment is **associated** with exactly one TGW route table (which table is used to route its traffic) and **propagates** its CIDR into whichever tables should reach it. Isolation is simply not propagating: dev's routes never appear in prod's table and vice versa, while shared services propagate into all. Send inter-VPC and egress traffic through an inspection VPC (AWS Network Firewall with appliance mode on). Share the TGW across accounts with AWS RAM.

**Route tables:**

```yaml
TGW (us-east-1), shared via RAM to all accounts

Route table: prod
  Associated:  prod VPC attachments
  Propagated:  prod VPCs, shared-services VPC
  Static:      10.1.0.0/16 → TGW peering (prod us-west-2)
               0.0.0.0/0   → inspection VPC attachment

Route table: dev
  Associated:  dev VPC attachments
  Propagated:  dev VPCs, shared-services VPC
  Static:      0.0.0.0/0   → inspection VPC attachment

Route table: shared
  Associated:  shared-services and inspection attachments
  Propagated:  every VPC (so return traffic works)
```

- Routes are not propagated across TGW **peering** attachments; you add static routes on both sides.
- Using `0.0.0.0/0 → inspection` in the prod and dev tables means any unknown destination, including the other environment, goes to the firewall, where policy denies it. A blackhole route for the other environment's summary range is an extra guard.
- Turn on **appliance mode** on the inspection VPC attachment so both directions of a flow go through the same AZ's firewall endpoint; otherwise stateful inspection drops asymmetric traffic.

**Why not peering at 50 VPCs:**

| | VPC peering mesh | Transit Gateway |
|---|---|---|
| Connections | 1,225 peering links | 50 attachments |
| Routes per VPC | Up to 49 entries (route table quota 50 by default, max 1,000) | A summary route to the TGW |
| Transitive / central inspection | No | Yes |
| Cost | No hourly fee; data transfer only | 50 × $0.05 × 730 ≈ $1,825/month + $0.02/GB processed |

TGW isn't cheaper than peering for raw traffic (it adds a processing fee); it's cheaper to *operate*. For a few very chatty VPC pairs, add a direct peering alongside the TGW and let the more specific route win.

**Cross-Region:** TGW peering uses the AWS backbone, is encrypted, and charges inter-Region data transfer (typically $0.02/GB between US Regions). Latency is physics: ~60–70 ms us-east-1 to us-west-2.

**Inspection VPC:**

```
spoke VPC ──► TGW (spoke route table: 0.0.0.0/0 → inspection)
                 └──► inspection VPC: AWS Network Firewall endpoints per AZ (appliance mode)
                          └──► TGW (firewall route table) ──► destination VPC / NAT / on-prem
```

AWS Network Firewall can attach to a Transit Gateway natively (mid-2025), removing the need to build the inspection VPC by hand. Third-party appliances use Gateway Load Balancer (GENEVE) endpoints.

**What they probe next:** TGW bandwidth (up to 100 Gbps per VPC attachment per AZ), MTU 8500 through TGW, multicast, Cloud WAN vs TGW peering at many Regions, and VPC Lattice as an alternative for service-to-service traffic that doesn't need IP routing.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Route table isolation** | Uses association/propagation per environment to isolate traffic |
| **Cross-region peering** | Uses TGW peering with static routes (or Cloud WAN) for cross-region connectivity |
| **Cost comparison** | Knows peering has no hourly fee and TGW adds per-GB processing; picks on operability |
| **Inspection VPC** | Designs centralized firewall with appliance mode for symmetric flows |

---

## 7. Site-to-Site VPN & Direct Connect

**Q:** "Your on-premises data center needs connectivity to AWS for a hybrid cloud architecture. You need: 10Gbps throughput, <5ms latency, and 99.99% availability. Compare Direct Connect vs Site-to-Site VPN. Design a hybrid network with both active and failover paths."

**What They're Really Testing:** Whether you understand the operational trade-offs between VPN (internet-based, encrypted, variable latency) and Direct Connect (private fiber, consistent latency, higher cost).

### Answer

!!! tip "30-second answer"
    10 Gbps with consistent low latency means **Direct Connect**; 99.99% means AWS's *maximum resiliency* model: two DX locations, two connections at each, all advertising the same prefixes, with BGP and BFD for fast failover. Terminate on a **Direct Connect gateway** attached to a Transit Gateway (transit VIF) so one set of connections reaches VPCs in every Region. VPN over the internet is the cheap backup (now up to 5 Gbps per tunnel) but can't meet a 5 ms SLA. DX isn't encrypted by default: use **MACsec** on 10/100/400 Gbps dedicated connections or IPsec VPN over DX if policy requires it. "<5 ms" also depends on the distance from your data centre to the DX location and from there to the Region.

**Comparison:**

| | Site-to-Site VPN | Direct Connect |
|---|---|---|
| Path | IPsec over the internet | Private circuit via a DX location |
| Bandwidth | 1.25 Gbps per tunnel by default; up to **5 Gbps per tunnel** (Nov 2025); scale further with ECMP over multiple connections on a TGW | Dedicated 1, 10, 100, 400 Gbps; hosted 50 Mbps–25 Gbps via partners |
| Latency | Variable | Consistent |
| Encryption | Always | Optional: MACsec (L2) or IPsec over DX |
| SLA | 99.95% per VPN connection | Up to 99.99% with the maximum resiliency model |
| Lead time | Minutes | Weeks (cross-connects, partners) |
| Cost | ~$0.05/hour per connection + standard data out | Port-hour fee (e.g. ~$2.25/hour for 10 Gbps dedicated in US locations) + reduced data-out rate (~$0.02/GB in the US) |

**Resilient design:**

```
On-prem DC-A ─┬─ DX location 1: conn 1a (10G) ─┐
              └─ DX location 1: conn 1b (10G) ─┤
On-prem DC-B ─┬─ DX location 2: conn 2a (10G) ─┼─► DX gateway ─► Transit Gateways (us-east-1, eu-west-1, ...)
              └─ DX location 2: conn 2b (10G) ─┘
              └─ Site-to-Site VPN (backup, terminates on the TGW)
```

**BGP traffic engineering:**

- **AWS → on-prem**: AWS prefers the longest prefix first, then DX over VPN for equal prefixes. Among DX paths, you influence AWS with AS-path prepending or AWS's local-preference BGP communities (`7224:7100` low, `7224:7200` medium, `7224:7300` high) on your advertisements.
- **On-prem → AWS**: controlled by your routers (local preference on the routes learned from AWS).
- Enable **BFD** so failover takes about a second rather than the 90-second default BGP hold timer.

```
router bgp 65001
 neighbor 169.254.10.1 remote-as 64512          ! DX connection A (preferred)
 neighbor 169.254.10.1 fall-over bfd
 neighbor 169.254.20.1 remote-as 64512          ! DX connection B (backup)
 neighbor 169.254.20.1 fall-over bfd
 address-family ipv4
  network 10.200.0.0 mask 255.255.0.0           ! on-prem range
  neighbor 169.254.10.1 activate
  neighbor 169.254.20.1 activate
  neighbor 169.254.20.1 route-map PREPEND out   ! AWS → on-prem prefers A
!
route-map PREPEND permit 10
 set as-path prepend 65001 65001 65001
```

**Direct Connect gateway:** a global object with no charge of its own. A private VIF to a DX gateway reaches virtual private gateways in any Region (outside China); a transit VIF reaches Transit Gateways. Allowed-prefix lists on the association control what's advertised on-prem. Watch the quotas: on-prem can advertise at most 100 prefixes over a private VIF (exceed it and the BGP session goes down, so summarise), and a DX gateway has limits on associated gateways.

**Branch offices:** terminate each branch VPN on the Transit Gateway; branches reach each other through it (the older VGW-based pattern was called VPN CloudHub). For many branches with SD-WAN, use TGW Connect (GRE + BGP) or Cloud WAN.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **DX vs VPN trade-offs** | Quantifies latency, bandwidth, SLA, encryption and cost differences |
| **BGP routing** | Knows which side each knob affects (prepend/communities vs local preference) and uses BFD |
| **DX Gateway** | Connects DX to multiple VPCs/Regions through DX gateway and TGW |
| **Resiliency model** | Can describe what 99.99% actually requires |

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

!!! tip "30-second answer"
    Flow logs record metadata, not payloads: per ENI, per aggregation window (1 or 10 minutes), a line per 5-tuple flow with packets, bytes and ACCEPT/REJECT. Deliver them to **S3 in Parquet with hourly, Hive-compatible partitions** and query with Athena (or load into Security Lake). They're billed as vended logs (cheaper per GB to S3 than to CloudWatch Logs, with volume tiers), so choose only the fields you need. Exfiltration signals: unusually large outbound bytes to new external destinations, traffic on odd ports, periodic beaconing, and big DNS volumes. Flow logs alone can't see DNS tunnelling contents; add Route 53 Resolver query logs, and let **GuardDuty** do baseline anomaly detection.

**Record format (default fields, version 2):**

```
version account-id interface-id srcaddr dstaddr srcport dstport protocol packets bytes start end action log-status
2 123456789012 eni-abc123 10.0.1.42 52.84.120.10 54321 443 6 10 1200 1625097600 1625097660 ACCEPT OK
```

- Custom formats add fields such as `vpc-id`, `subnet-id`, `instance-id`, `tcp-flags`, `pkt-srcaddr`/`pkt-dstaddr` (the original IPs behind a NAT gateway), `flow-direction`, `traffic-path` (versions 3–5), and ECS fields (version 7 adds `ecs-cluster-name` and friends).
- `log-status`: `OK`, `NODATA` (no traffic in the window), `SKIPDATA` (records dropped due to capacity).
- Not captured: traffic to the Amazon DNS resolver, instance metadata (169.254.169.254), Time Sync, DHCP, and the reserved VPC router address.

**Delivery and cost:**

| Destination | Price model | Use |
|---|---|---|
| CloudWatch Logs | Vended-log ingestion, $0.50/GB for the first 10 TB, tiered down with volume, plus storage | Small volumes, metric filters, Logs Insights |
| S3 | Vended-log delivery, $0.25/GB for the first 10 TB tiered down to $0.05/GB, plus S3 storage; Parquet conversion extra per GB | Default for scale; Athena, Security Lake |
| Data Firehose | Vended-log rate plus Firehose processing | Streaming to a SIEM or OpenSearch |

At 100 TB/day you're deep in the cheapest tiers but still paying thousands of dollars per day, so scope logging (sensitive VPCs fully, others at the subnet or ENI level, or REJECT-only), trim fields, and lifecycle old data to Glacier tiers.

**Athena table with partition projection (no `MSCK REPAIR`):**

```sql
CREATE EXTERNAL TABLE vpc_flow_logs (
  version int, account_id string, interface_id string,
  srcaddr string, dstaddr string, srcport int, dstport int, protocol bigint,
  packets bigint, bytes bigint, `start` bigint, `end` bigint,
  action string, log_status string
)
PARTITIONED BY (`aws-account-id` string, `aws-service` string, `aws-region` string,
                `year` string, `month` string, `day` string, `hour` string)
STORED AS PARQUET
LOCATION 's3://my-flow-logs/AWSLogs/'
TBLPROPERTIES (
  'projection.enabled'='true',
  'projection.aws-account-id.type'='enum', 'projection.aws-account-id.values'='123456789012',
  'projection.aws-service.type'='enum',    'projection.aws-service.values'='vpcflowlogs',
  'projection.aws-region.type'='enum',     'projection.aws-region.values'='us-east-1',
  'projection.year.type'='integer', 'projection.year.range'='2024,2030',
  'projection.month.type'='integer','projection.month.range'='1,12', 'projection.month.digits'='2',
  'projection.day.type'='integer',  'projection.day.range'='1,31',  'projection.day.digits'='2',
  'projection.hour.type'='integer', 'projection.hour.range'='0,23', 'projection.hour.digits'='2',
  'storage.location.template'='s3://my-flow-logs/AWSLogs/aws-account-id=${aws-account-id}/aws-service=${aws-service}/aws-region=${aws-region}/year=${year}/month=${month}/day=${day}/hour=${hour}'
);
```

**Exfiltration queries:**

```sql
-- Helper predicate: destination is outside RFC 1918 space
-- (Athena/Trino: contains(cidr, ip) on IPPREFIX / IPADDRESS types)

-- 1. Largest outbound volumes to external destinations in a day
SELECT dstaddr, dstport, SUM(bytes) AS total_bytes, COUNT(*) AS flows,
       MIN(from_unixtime("start")) AS first_seen, MAX(from_unixtime("end")) AS last_seen
FROM vpc_flow_logs
WHERE year = '2026' AND month = '10' AND day = '06'
  AND action = 'ACCEPT'
  AND NOT contains('10.0.0.0/8',     CAST(dstaddr AS IPADDRESS))
  AND NOT contains('172.16.0.0/12',  CAST(dstaddr AS IPADDRESS))
  AND NOT contains('192.168.0.0/16', CAST(dstaddr AS IPADDRESS))
GROUP BY dstaddr, dstport
ORDER BY total_bytes DESC
LIMIT 20;

-- 2. Beaconing: many small, regular connections to the same external host
SELECT dstaddr, COUNT(*) AS flows,
       COUNT(DISTINCT day) AS active_days,
       stddev(bytes) AS byte_stddev
FROM vpc_flow_logs
WHERE year = '2026' AND month = '10'
  AND action = 'ACCEPT' AND dstport = 443 AND bytes < 10000
  AND NOT contains('10.0.0.0/8', CAST(dstaddr AS IPADDRESS))
GROUP BY dstaddr
HAVING COUNT(DISTINCT day) >= 3 AND COUNT(*) >= 100
ORDER BY flows DESC;

-- 3. Large transfers on unusual ports
SELECT dstaddr, dstport, protocol, SUM(bytes) AS total_bytes
FROM vpc_flow_logs
WHERE year = '2026' AND month = '10' AND day = '06'
  AND action = 'ACCEPT'
  AND dstport NOT IN (80, 443, 53, 123)
  AND NOT contains('10.0.0.0/8', CAST(dstaddr AS IPADDRESS))
GROUP BY dstaddr, dstport, protocol
HAVING SUM(bytes) > 100000000
ORDER BY total_bytes DESC;
```

Beware: traffic through a NAT gateway shows the NAT's private IP as the source on the NAT ENI; use `pkt-srcaddr` to find the real instance. Exfiltration to S3 buckets in *other* accounts looks like normal S3 traffic, which is why VPC endpoint policies (restrict to your organisation's buckets with `aws:ResourceOrgID`) matter as a preventive control.

**Other tools:** GuardDuty (analyses flow logs, DNS logs and CloudTrail without you enabling them, flags known-bad IPs and anomalous volumes), Traffic Mirroring (full packets for forensics), Network Access Analyzer (finds unintended network paths), Reachability Analyzer (explains why A can or can't reach B).

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Flow log format** | Understands the record format, aggregation window, what isn't captured |
| **Exfiltration detection** | Can write Athena queries for beaconing, large transfers, unusual ports |
| **Cost at scale** | Knows vended-log pricing tiers and why S3 + Parquet is the scalable choice |
| **Partitioning** | Uses Hive partitions with projection for efficient Athena querying |

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

!!! tip "30-second answer"
    Put everything behind CloudFront (absorbs L3/L4 floods at the edge, Shield Standard is automatic and free) with a WAF web ACL there. Against a distributed L7 attack, per-IP rate limits barely bite, so layer: the **anti-DDoS managed rule group / Shield Advanced automatic application-layer mitigation** (baselines your traffic and blocks attack signatures), **Bot Control** (signals, browser fingerprinting via the JS SDK, and verified-bot allow-listing), **rate-based rules keyed on more than IP** (path, header, session cookie, JA4 fingerprint), and **Challenge/CAPTCHA** actions instead of Block where false positives would hurt. Roll new rules out in Count mode, and keep a runbook with pre-built, disabled emergency rules.

**Layers:**

| Layer | Control | Notes |
|---|---|---|
| Edge network | Shield Standard (all customers, free) | SYN/UDP floods, reflection attacks |
| Edge L7 | WAF on CloudFront: managed rules, rate-based rules, Bot Control, anti-DDoS rule group | Scope `CLOUDFRONT`, resources created in us-east-1 |
| Advanced | Shield Advanced: $3,000/month per organisation (1-year commitment) + data-transfer fees | Automatic L7 mitigation, Shield Response Team (SRT), cost protection credits for scaling during attacks, health-based detection, WAF included for protected resources |
| Origin | ALB only reachable from CloudFront (VPC origin or managed prefix list + secret header); regional WAF for anything not behind CloudFront | Prevents attackers bypassing the CDN |
| App | Per-user/session rate limits, cheap 429s, caches, circuit breakers | The cheapest request is the one you never process |

**Rate-based rule with a scope-down:**

```json
{
  "Name": "rate-limit-login",
  "Priority": 10,
  "Action": { "Block": {} },
  "Statement": {
    "RateBasedStatement": {
      "Limit": 100,
      "EvaluationWindowSec": 60,
      "AggregateKeyType": "CUSTOM_KEYS",
      "CustomKeys": [
        { "IP": {} },
        { "UriPath": { "TextTransformations": [{ "Priority": 0, "Type": "LOWERCASE" }] } }
      ],
      "ScopeDownStatement": {
        "ByteMatchStatement": {
          "SearchString": "/api/login",
          "FieldToMatch": { "UriPath": {} },
          "PositionalConstraint": "STARTS_WITH",
          "TextTransformations": [{ "Priority": 0, "Type": "LOWERCASE" }]
        }
      }
    }
  },
  "VisibilityConfig": { "SampledRequestsEnabled": true, "CloudWatchMetricsEnabled": true, "MetricName": "RateLimitLogin" }
}
```

Evaluation windows are 60, 120, 300 or 600 seconds; custom keys can combine IP, forwarded IP, headers, cookies, query arguments, labels and JA3/JA4 fingerprints. Rate-based rules react within tens of seconds, not instantly.

**Bot Control (start in Count):**

```json
{
  "Name": "bot-control",
  "Priority": 20,
  "OverrideAction": { "Count": {} },
  "Statement": {
    "ManagedRuleGroupStatement": {
      "VendorName": "AWS",
      "Name": "AWSManagedRulesBotControlRuleSet",
      "ManagedRuleGroupConfigs": [
        { "AWSManagedRulesBotControlRuleSet": { "InspectionLevel": "TARGETED" } }
      ],
      "RuleActionOverrides": [
        { "Name": "CategoryHttpLibrary", "ActionToUse": { "Challenge": {} } }
      ]
    }
  },
  "VisibilityConfig": { "SampledRequestsEnabled": true, "CloudWatchMetricsEnabled": true, "MetricName": "BotControl" }
}
```

- `COMMON` identifies self-declared bots (verified search engines are allowed by default); `TARGETED` adds behavioural detection, browser interrogation and ML for sophisticated bots, at higher cost.
- Rules add **labels**; later rules can act on labels (e.g. block `bot:category:http_library` only on `/api/checkout`).
- For credential stuffing and fake sign-ups add Account Takeover Prevention (ATP) and Account Creation Fraud Prevention (ACFP).

**Handling false positives:**

- **Challenge** runs a silent browser interrogation (no user interaction) and sets a token; **CAPTCHA** shows a puzzle. Both fail for API clients and mobile apps unless they integrate the WAF SDK, so use them on browser paths only.
- Allow-list partners and monitoring with an IP set rule at a higher priority (lower number). Public endpoints only see public IPs, so a corporate VPN's private range is useless here.
- Watch `CountedRequests` and sampled requests per rule, and roll changes out with Count → Challenge → Block.

**During an attack (runbook):**

1. Confirm: CloudFront/ALB request rate and 5xx alarms, Shield event, WAF top talkers by IP, path, user-agent, country, JA4.
2. Mitigate in order of collateral damage: enable pre-built emergency rules (geo or path-specific rate limits) in Count, then Challenge, then Block; raise caching for anything cacheable.
3. With Shield Advanced, engage the SRT (or let proactive engagement page you when health checks degrade).
4. Afterwards: turn emergency rules into permanent, tuned rules; file a cost-protection request for attack-driven scaling charges.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Multi-layer defense** | Designs from edge (Shield, CloudFront) → origin lockdown → application |
| **Rate limiting** | Uses rate-based rules with custom keys and scope-down to specific paths |
| **Bot control** | Uses managed rule groups, labels and Count-first rollout |
| **False positive handling** | Uses Challenge/CAPTCHA appropriately, allow-lists, staged rollout |


---

## 10. Network ACLs vs Security Groups

**Q:** "Design a defense-in-depth network security architecture for a multi-tier application. Compare security groups (stateful) vs network ACLs (stateless). When would you use both? Walk through a web application firewall configuration: Internet → ALB → App → DB."

**What They're Really Testing:** Whether you understand the fundamental difference between stateful (SG) and stateless (NACL) firewalls — and how to layer them for defense-in-depth.

### Answer

!!! tip "30-second answer"
    **Security groups** are stateful allow-lists on each ENI and can reference other security groups, so "DB accepts 5432 only from the app SG" survives scaling. **NACLs** are stateless, ordered allow/deny rules on a subnet: you must allow return traffic on ephemeral ports explicitly. Do the real segmentation with SG references; use NACLs sparingly as a coarse subnet guardrail (e.g. the data subnets only talk to app subnets) and for explicit denies, which SGs can't express. Overly tight NACLs are a common cause of outages.

**Comparison:**

| | Security group | Network ACL |
|---|---|---|
| Attached to | ENI (instance, task, Lambda ENI, endpoint, load balancer) | Subnet |
| State | Stateful: return traffic allowed automatically | Stateless: both directions need rules |
| Rules | Allow only | Allow and deny, evaluated in number order, first match wins |
| Sources | CIDR, prefix list, **another SG** (also across peered VPCs and, since 2024, across a Transit Gateway in the same Region) | CIDR only |
| Defaults | New SG: no inbound, all outbound | Default NACL: **allow all** both ways; a new custom NACL: deny all |
| Quotas (default) | 60 inbound + 60 outbound rules per SG, 5 SGs per ENI (adjustable) | 20 rules per direction (up to 40) |

**Security groups for Internet → ALB → App → DB:**

```yaml
sg-alb:
  inbound:  443 from 0.0.0.0/0 and ::/0      # or the CloudFront managed prefix list
  outbound: 8080 to sg-app
sg-app:
  inbound:  8080 from sg-alb
  outbound: 5432 to sg-db; 443 to 0.0.0.0/0 (external APIs via NAT) or to endpoint SGs
sg-db:
  inbound:  5432 from sg-app
  outbound: none needed                     # responses are allowed by state
```

No SSH rules: use Session Manager for shell access, and IAM database auth or a bastion-less proxy for DBAs.

**NACLs as a guardrail (three subnet tiers):**

```yaml
nacl-public (ALB subnets):
  inbound:  100 allow tcp 443 from 0.0.0.0/0
            110 allow tcp 1024-65535 from 10.0.0.0/16     # responses from app targets
            *   deny all
  outbound: 100 allow tcp 8080 to app subnet CIDRs         # one rule per subnet
            110 allow tcp 1024-65535 to 0.0.0.0/0           # responses to clients
            *   deny all

nacl-app:
  inbound:  100 allow tcp 8080 from public subnet CIDRs
            110 allow tcp 1024-65535 from 0.0.0.0/0         # responses from DB, NAT, external APIs
  outbound: 100 allow tcp 5432 to data subnet CIDRs
            110 allow tcp 443 to 0.0.0.0/0
            120 allow tcp 1024-65535 to public subnet CIDRs # responses to the ALB

nacl-data:
  inbound:  100 allow tcp 5432 from app subnet CIDRs
  outbound: 100 allow tcp 1024-65535 to app subnet CIDRs
```

Use 1024–65535 for ephemeral ranges: clients behind ELB and NAT gateways use the full range, not just Linux's 32768–60999. Every extra NACL rule is something to update when CIDRs change, which is why many teams keep the default allow-all NACL everywhere except the data tier.

**Explicit deny cases (NACL or something better):**

- Block a known-bad CIDR at the subnet: NACL deny (but at the edge, WAF IP sets or Network Firewall scale better and log).
- Prevent data subnets from ever reaching the internet: no route plus NACL as a second guard.
- Org-wide guardrails against "someone opened 0.0.0.0/0 on 22": AWS Firewall Manager security group policies and Config rules are more effective than NACLs.

**Troubleshooting connectivity (in order):**

1. **Reachability Analyzer** between the two ENIs: it names the blocking component (route, SG, NACL, gateway).
2. Security groups: inbound on the destination and, if outbound was restricted, outbound on the source.
3. NACLs on *both* subnets, *both* directions, including ephemeral return ports.
4. Route tables and gateways (NAT, IGW, TGW, endpoints) and endpoint policies.
5. **Flow logs**: an SG or NACL denial both show as `REJECT`; `NODATA` just means no traffic in the window. Because SGs are stateful, an accepted inbound request whose *response* shows `REJECT` points at a NACL.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Stateful vs stateless** | Explains SG auto-allows return traffic, NACL requires explicit rules |
| **SG reference** | Uses security group references (not CIDRs) for instance-to-instance rules |
| **Defense-in-depth** | Uses NACLs as coarse guardrails and explicit denies, SGs for application rules |
| **Troubleshooting** | Diagnoses connectivity with Reachability Analyzer, SG, NACL, routes and flow logs |

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
