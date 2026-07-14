import { SequenceData } from "./SequenceDiagram";

export const AWS_NETWORKING_SEQUENCES: SequenceData[] = [
  // ═══════════════════════════════════════════════════════════
  // NETWORKING — ALB vs NLB
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-alb-vs-nlb",
    title: "ALB vs NLB — Load Balancer Deep Dive",
    subtitle:
      "ALB (L7, HTTP/gRPC, path/host routing, WAF) vs NLB (L4, TCP/UDP, ultra-low latency, static IP) — choose by workload",
    actors: [
      "Client",
      "ALB\n(Layer 7)",
      "NLB\n(Layer 4)",
      "Target\nGroup",
      "AWS WAF",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "HTTP POST /api/orders",
        detail: "ALB terminates TLS, inspects headers",
      },
      {
        from: 1,
        to: 1,
        label: "Path-based routing: /api/* → API TG",
        detail: "Host-based: /orders → order-svc",
      },
      {
        from: 1,
        to: 4,
        label: "WAF: inspect request body",
        detail: "SQL injection, XSS rules, rate-based",
      },
      {
        from: 4,
        to: 1,
        label: "Request passes WAF ✅",
        detail: "No threats detected",
      },
      {
        from: 1,
        to: 3,
        label: "Forward to healthy target",
        detail: "Round-robin, sticky sessions optional",
      },
      {
        from: 0,
        to: 2,
        label: "TCP :443 (gRPC stream)",
        detail: "NLB: no TLS termination, ultra-low latency",
      },
      {
        from: 2,
        to: 3,
        label: "Forward to target group",
        detail: "TCP flow hash, preserves client IP",
      },
      {
        from: 2,
        to: 0,
        label: "Static Elastic IP: 203.0.113.10",
        detail: "NLB preserves client source IP for security",
      },
      {
        from: 0,
        to: 1,
        label: "ALB: slow start 300s",
        detail: "Gradually ramp traffic to new targets",
      },
      {
        from: 2,
        to: 2,
        label: "NLB: cross-zone load balancing",
        detail: "Distribute evenly across AZs",
      },
    ],
    durationInFrames: 360,
  },

  // ═══════════════════════════════════════════════════════════
  // NETWORKING — CloudFront + Origin Shield
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-cloudfront-origin-shield",
    title: "CloudFront CDN + Origin Shield Architecture",
    subtitle:
      "Edge Location → Regional Edge Cache → Origin Shield → S3/ALB Origin — 95%+ cache hit rate, Origin Shield saves 80% origin load",
    actors: [
      "Global User",
      "CloudFront\nEdge",
      "Regional\nEdge Cache",
      "Origin\nShield",
      "S3 / ALB\nOrigin",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "GET /images/hero.png",
        detail: "Routed to nearest edge location (50ms)",
      },
      {
        from: 1,
        to: 1,
        label: "Cache MISS at edge",
        detail: "First request for this object",
      },
      {
        from: 1,
        to: 2,
        label: "Forward to Regional Edge Cache",
        detail: "us-east-1 regional cache layer",
      },
      {
        from: 2,
        to: 2,
        label: "Cache MISS at regional",
        detail: "Forward to Origin Shield",
      },
      {
        from: 2,
        to: 3,
        label: "Origin Shield: deduplicate",
        detail: "Collapses multiple edge MISS into one origin req",
      },
      {
        from: 3,
        to: 4,
        label: "GET /images/hero.png",
        detail: "Single request to S3 origin",
      },
      {
        from: 4,
        to: 3,
        label: "200 OK + ETag: abc123",
        detail: "Object served from S3 (TTL: 24h)",
      },
      {
        from: 3,
        to: 1,
        label: "Cached at Origin Shield → edge",
        detail: "80% origin load reduction!",
      },
      {
        from: 1,
        to: 0,
        label: "✅ Served from edge: 12ms",
        detail: "Cache HIT for next user",
      },
      {
        from: 0,
        to: 1,
        label: "GET /api/data (dynamic)",
        detail: "CloudFront forwards to ALB origin",
      },
      {
        from: 1,
        to: 4,
        label: "Proxy to ALB origin",
        detail: "CloudFront as CDN for dynamic + static",
      },
      {
        from: 4,
        to: 1,
        label: "TTL=0: always fresh",
        detail: "CloudFront with cache policies per behavior",
      },
    ],
    durationInFrames: 390,
  },

  // ═══════════════════════════════════════════════════════════
  // NETWORKING — Global Accelerator vs CloudFront
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-global-accelerator",
    title: "Global Accelerator vs CloudFront",
    subtitle:
      "GA: Anycast IP → AWS edge → Regional endpoint (TCP/UDP, 60% faster) | CF: HTTP cache + DDoS at edge",
    actors: [
      "Global User",
      "AWS Global\nNetwork",
      "Global\nAccelerator",
      "CloudFront\nCDN",
      "Regional\nEndpoint",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "DNS resolves to anycast IP",
        detail: "2 static IPs (GA) or CF DNS name",
      },
      {
        from: 1,
        to: 2,
        label: "GA: traffic enters edge location",
        detail: "Anycast: closest edge → AWS backbone",
      },
      {
        from: 2,
        to: 4,
        label: "GA: route to us-east-1 NLB",
        detail: "Over AWS global network (not public internet)",
      },
      {
        from: 4,
        to: 2,
        label: "200 OK (GA): 80ms",
        detail: "60% faster than public internet",
      },
      {
        from: 1,
        to: 3,
        label: "CF: HTTP request to edge",
        detail: "Cache HIT: served from edge cache",
      },
      {
        from: 3,
        to: 0,
        label: "200 OK (CF): 12ms",
        detail: "Static content cached at edge!",
      },
      {
        from: 2,
        to: 2,
        label: "GA: TCP/UDP, no cache",
        detail: "Any protocol: HTTP, MQTT, gaming, VoIP",
      },
      {
        from: 3,
        to: 3,
        label: "CF: HTTP/HTTPS only",
        detail: "Cache, Lambda@Edge, WAF, Shield",
      },
      {
        from: 0,
        to: 1,
        label: "Failover: us-east-1 → us-west-2",
        detail: "GA: 1s failover, CF: DNS failover 60s",
      },
      {
        from: 2,
        to: 4,
        label: "GA: instant traffic shift",
        detail: "Health checks trigger endpoint switch",
      },
    ],
    durationInFrames: 330,
  },

  // ═══════════════════════════════════════════════════════════
  // NETWORKING — Direct Connect + VPN
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-directconnect-vpn",
    title: "Hybrid Connectivity — Direct Connect & Site-to-Site VPN",
    subtitle:
      "DX: Dedicated fiber (1/10/100Gbps, <5ms, SLA) | VPN: Internet-encrypted (IPSec, backup, 30min setup)",
    actors: [
      "On-Prem\nDatacenter",
      "Direct\nConnect",
      "Site-to-Site\nVPN",
      "Virtual\nGateway",
      "AWS\nRegion",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "DX: 10Gbps dedicated fiber",
        detail: "Cross-connect at AWS Direct Connect location",
      },
      {
        from: 1,
        to: 3,
        label: "Private VIF → Virtual Gateway",
        detail: "BGP session, VLAN 100, < 5ms latency",
      },
      {
        from: 3,
        to: 4,
        label: "Route: 10.0.0.0/8 → VPC",
        detail: "Direct path, no internet, SLA-backed",
      },
      {
        from: 0,
        to: 2,
        label: "VPN: IPSec tunnel (backup)",
        detail: "Internet-based, 30min to provision",
      },
      {
        from: 2,
        to: 3,
        label: "VPN connection → Virtual GW",
        detail: "AES-256 encrypted, 1.25Gbps per tunnel",
      },
      {
        from: 3,
        to: 4,
        label: "VPN: secondary path",
        detail: "BGP prepend: DX preferred over VPN",
      },
      {
        from: 1,
        to: 1,
        label: "⚠️ DX circuit DOWN",
        detail: "BGP session drops, routes withdrawn",
      },
      {
        from: 3,
        to: 3,
        label: "BGP failover → VPN path",
        detail: "Auto-failover, routes switch in < 30s",
      },
      {
        from: 2,
        to: 4,
        label: "VPN: traffic encrypted over internet",
        detail: "Higher latency but available",
      },
      {
        from: 1,
        to: 3,
        label: "DX restored → taken back",
        detail: "BGP prefer DX: lower AS path length",
      },
      {
        from: 0,
        to: 0,
        label: "Cost: DX $2K/mo + $0.02/GB",
        detail: "VPN: free (internet-only cost)",
      },
    ],
    durationInFrames: 360,
  },

  // ═══════════════════════════════════════════════════════════
  // NETWORKING — VPC Flow Logs + Network Monitoring
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-vpc-flow-logs",
    title: "VPC Flow Logs & Network Traffic Analysis",
    subtitle:
      "ENI → Flow Logs (10-min window) → S3/CloudWatch → Athena → GuardDuty → Anomaly Detection",
    actors: [
      "EC2 ENI",
      "VPC Flow\nLogs",
      "S3 Bucket\n(Logs)",
      "Athena /\nGuardDuty",
      "Security\nDashboard",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "Capture: src IP, dst IP, port, protocol",
        detail: "All accepted/rejected traffic, 10-min window",
      },
      {
        from: 1,
        to: 2,
        label: "Stream logs to S3",
        detail: "S3://vpc-flow-logs/account/region/",
      },
      {
        from: 2,
        to: 3,
        label: "Athena query: top talkers",
        detail: "SELECT src_ip, count(*) GROUP BY src_ip",
      },
      {
        from: 3,
        to: 4,
        label: "Dashboard: p95 bandwidth, top rejected",
        detail: "CloudWatch + Grafana visualizations",
      },
      {
        from: 0,
        to: 1,
        label: "⚠️ 10K rejected connections/min",
        detail: "Port scan detected (dst_port: 22, 3389)",
      },
      {
        from: 1,
        to: 3,
        label: "GuardDuty: analyze flow logs",
        detail: "ML detects brute force pattern",
      },
      {
        from: 3,
        to: 4,
        label: "HIGH severity finding: BruteForce",
        detail: "UnauthorizedPortProbe SSH/3389",
      },
      {
        from: 4,
        to: 4,
        label: "Auto-remediate: block SG",
        detail: "Lambda adds deny rule for offender IP",
      },
      {
        from: 1,
        to: 2,
        label: "Flow log cost: $0.05/GB ingested",
        detail: "S3 lifecycle: move to Glacier after 30d",
      },
      {
        from: 0,
        to: 0,
        label: "Subnet scope vs VPC scope",
        detail: "Aggregated at subnet or VPC level",
      },
    ],
    durationInFrames: 360,
  },

  // ═══════════════════════════════════════════════════════════
  // NETWORKING — Security Groups vs NACLs
  // ═══════════════════════════════════════════════════════════

  {
    id: "aws-sg-vs-nacl",
    title: "Security Groups vs Network ACLs — Defense in Depth",
    subtitle:
      "SG: Stateful, ALLOW only, instance-level, default-deny (in) — NACL: Stateless, ALLOW/DENY, subnet-level, rule-order matters",
    actors: [
      "Internet\nTraffic",
      "NACL\n(Subnet-level)",
      "Security\nGroup (ENI)",
      "EC2\nInstance",
      "Subnet\nRouter",
    ],
    steps: [
      {
        from: 0,
        to: 4,
        label: "Packet enters VPC subnet",
        detail: "src: 203.0.113.1:45000, dst: 10.0.1.10:443",
      },
      {
        from: 4,
        to: 1,
        label: "NACL evaluates — Stateless!",
        detail: "CHECK: Inbound rule matches? (Allow/Deny)",
      },
      {
        from: 1,
        to: 1,
        label: "Rule 100: Allow HTTPS (443)",
        detail: "Rule 200: Deny SSH (22), Rule *: Deny all",
      },
      {
        from: 1,
        to: 2,
        label: "NACL ALLOW → SG evaluation",
        detail: "Stateful: automatically tracks connection",
      },
      {
        from: 2,
        to: 2,
        label: "SG: Inbound HTTPS allowed",
        detail: "No explicit Deny, default deny all inbound",
      },
      {
        from: 2,
        to: 3,
        label: "SG ALLOW → Instance receives",
        detail: "Response automatically allowed (stateful)",
      },
      {
        from: 3,
        to: 0,
        label: "Response: 443→45000",
        detail: "SG auto-allows return traffic ✅",
      },
      {
        from: 0,
        to: 4,
        label: "SSH attempt: 203.0.113.5:22",
        detail: "Malicious actor tries to brute force",
      },
      {
        from: 4,
        to: 1,
        label: "NACL Rule 200: Deny SSH",
        detail: "BLOCKED at subnet boundary!",
      },
      {
        from: 1,
        to: 0,
        label: "❌ NACL DROPS packet",
        detail: "Doesn't reach SG at all",
      },
      {
        from: 0,
        to: 0,
        label: "SG: stateful, no explicit Deny",
        detail: "NACL: stateless, must define RETURN rules!",
      },
    ],
    durationInFrames: 360,
  },
];
