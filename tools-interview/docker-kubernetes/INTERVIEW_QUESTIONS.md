# 🐳 Docker & Kubernetes — Staff-Level Interview Questions

> *8 questions covering container runtime internals, Kubernetes scheduler, networking, RBAC, and production operations — every question expects principal engineer-level depth.*

---

## Table of Contents

1. [Container Runtime: Namespaces & Cgroups](#1-container-runtime-namespaces--cgroups)
2. [Docker: Images, Layers & UnionFS](#2-docker-images-layers--unionfs)
3. [Kubernetes Scheduler: Binding & Node Selection](#3-kubernetes-scheduler-binding--node-selection)
4. [Kubernetes Networking: CNI, Services, DNS](#4-kubernetes-networking-cni-services-dns)
5. [Kubernetes Security: RBAC, PSP, Pod Identity](#5-kubernetes-security-rbac-psp-pod-identity)
6. [Storage: CSI, Persistent Volumes, StatefulSets](#6-storage-csi-persistent-volumes-statefulsets)
7. [Controllers: ReplicaSet, Deployment, Operator](#7-controllers-replicaset-deployment-operator)
8. [Production: Autoscaling, Rolling Updates, Chaos](#8-production-autoscaling-rolling-updates-chaos)

---

## 1. Container Runtime: Namespaces & Cgroups

**Q:** "Walk through what happens when you run 'docker run -it ubuntu bash' — at the OS level. What kernel primitives are invoked? How do namespaces and cgroups isolate the container?"

**What They're Really Testing:** Whether you understand containers are just Linux processes with isolation — not VMs. Namespaces provide isolation, cgroups provide resource limits.

### Answer

**What Happens at the Kernel Level:**

```
docker run -it ubuntu bash

1. Docker client → dockerd → containerd → runc

2. runc creates the container:
   a. Creates new namespaces:
      - Mount (CLONE_NEWNS): /proc/mounts isolated
      - PID (CLONE_NEWPID): process 1 = bash, not init
      - Network (CLONE_NEWNET): own network stack
      - IPC (CLONE_NEWIPC): System V IPC isolated
      - UTS (CLONE_NEWUTS): own hostname
      - User (CLONE_NEWUSER): UID/GID mapping (root in container ≠ root on host)
      
   b. Configures cgroups:
      - cpu.cfs_quota_us: CPU max
      - memory.limit_in_bytes: RAM limit
      - blkio.throttle.write_bps_device: disk I/O limit
      - pids.max: max processes
      
   c. Sets up the root filesystem:
      - pivot_root() to the container image layer
      
   d. Executes bash as PID 1
```

**Namespace Details:**

```c
// Each namespace wraps a global resource in an isolated instance

// PID namespace:
//   Container sees: PID 1 (bash), PID 2 (child processes)
//   Host sees: PID 32453 (the container's bash)
//   Process inside can't see host processes → isolation!

// Network namespace:
//   Container has: lo, eth0 (veth pair)
//   Host has: vethXXXXX (other end of the pair)
//   Container's iptables rules don't affect host
//   Container can't see host's listening ports

// Mount namespace:
//   /proc/mounts inside container: shows only container mounts
//   Host mounts: inaccessible (unless explicitly bind-mounted)
//   pivot_root() ensures container can't escape to host FS

// User namespace (rootless containers):
//   Container's root (UID 0) maps to host UID 100000
//   The container user has NO special privileges on the host
//   UID mapping: /etc/subuid (root:100000:65536)
```

**Cgroups v2 (Modern Linux):**

```bash
# cgroups v2 hierarchy: /sys/fs/cgroup/
# Each container gets its own cgroup directory

/sys/fs/cgroup/system.slice/docker-<container>.scope/
├── cpu.max              # "100000 100000" → 1 CPU core max
├── memory.max           # "2147483648" → 2GB RAM limit
├── memory.high          # "1610612736" → 1.5GB throttle threshold
├── memory.zswap.current  # Compressed swap usage
├── io.max               # Disk I/O limits
└── pids.max             # "1000" max processes

# CPU shares vs CPU quota:
# cpu.weight (shares): relative weight when CPU is contended
# cpu.max (quota): hard limit on CPU time

# Memory pressure notification:
# memory.events: reports low/high/oom events
# Used by k8s to evict pods with memory.high exceeded

# Why cgroups v2 matters:
# - Unified hierarchy (no more separate cpu, memory, blkio controllers)
# - Delegation safe (non-root users can manage their own cgroups)
# - Pressure Stall Information (PSI) for memory/CPU/IO
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Namespace isolation** | Can list 6+ namespace types and explain what each isolates |
| **User namespace** | Understands UID mapping for rootless containers |
| **Cgroups v2** | Knows the unified hierarchy and PSI monitoring |
| **Secure computing mode** | Mentions seccomp-bpf profiles for system call filtering |

---

## 2. Docker: Images, Layers & UnionFS

**Q:** "You have a Docker image that's 2GB and takes 5 minutes to pull on deploy. How do you optimize build times and image size? Explain how Docker layers work, layer caching, and multi-stage builds."

**What They're Really Testing:** Whether you understand Docker's union filesystem — how layers compose into the container filesystem, and how to design efficient builds.

### Answer

**Docker Image Layers:**

```
Dockerfile:
  FROM ubuntu:22.04                        ← Layer 1: ~77MB (base image)
  RUN apt-get update && apt-get install -y \ ← Layer 2: ~500MB (dependencies)
      python3 nodejs postgresql-client
  COPY requirements.txt ./                  ← Layer 3: ~1KB (small change)
  RUN pip install -r requirements.txt       ← Layer 4: ~200MB (Python packages)
  COPY app/ ./app                           ← Layer 5: ~10MB (app code)
  CMD ["python3", "app/main.py"]

Storage:
  /var/lib/docker/overlay2/
  ├── 1234abcd... (layer 1: ubuntu base)
  ├── 5678efab... (layer 2: apt packages)
  ├── 90abcdef... (layer 3: requirements.txt)
  ├── 12345678... (layer 4: pip packages)
  └── 90123456... (layer 5: app code)

  Container view: union mount of ALL layers (topmost wins)
  ┌──────────────────────────────┐
  │ Layer 5: app code (R/W)      │ ← Writable layer (container)
  ├──────────────────────────────┤
  │ Layer 4: pip packages        │
  ├──────────────────────────────┤
  │ Layer 3: requirements.txt    │
  ├──────────────────────────────┤
  │ Layer 2: apt packages        │
  ├──────────────────────────────┤
  │ Layer 1: ubuntu base         │
  └──────────────────────────────┘
```

**Layer Cache Optimization:**

```dockerfile
# OPTIMIZED: layer ordering for maximum cache hits
FROM python:3.11-slim AS builder

# 1. Install system deps FIRST (rarely changes)
RUN apt-get update && apt-get install -y \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Copy requirements FIRST (changes less than source code)
COPY requirements.txt .
RUN pip install --user -r requirements.txt

# 3. Copy source code LAST (changes most frequently)
COPY app/ .

# Multi-stage build: final image only has runtime deps
FROM python:3.11-slim

RUN apt-get update && apt-get install -y libpq5 \  # Runtime libs only
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
COPY --from=builder /app /app

# Final image size: ~150MB (vs 2GB for non-optimized!)
```

**Multi-Stage Build Pattern:**

```dockerfile
# Stage 1: Compile
FROM golang:1.21 AS build
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o server .

# Stage 2: Runtime (distroless! ~5MB image)
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /app/server /server
EXPOSE 8080
ENTRYPOINT ["/server"]

# Result: 5MB image (vs 1.2GB with golang base image!)
# No shell, no package manager, no vulnerabilities!
```

**Image Size Reduction:**

```yaml
Technique            | Saving  | Example
---------------------|---------|-----------------------
Multi-stage builds   | 80-90%  | Go: 1.2GB → 5MB
Distroless base      | 90-95%  | ubuntu (77MB) → distroless (2MB)
Alpine base          | 50-70%  | python:3.11 (336MB) → python:3.11-alpine (47MB)
Remove package caches| 10-20%  | apt-get → rm -rf /var/lib/apt/lists/*
Layer squashing      | 10-30%  | docker-squash or BuildKit
.dockerignore        | 10-50%  | Exclude node_modules, .git, __pycache__

# BuildKit cache mounts (no apt cache in layers):
RUN --mount=type=cache,target=/var/lib/apt/lists \
    --mount=type=cache,target=/var/cache/apt \
    apt-get update && apt-get install -y build-essential
```

**Docker BuildKit (docker buildx):**

```bash
# BuildKit features for faster builds:
docker buildx build \
  --cache-from type=registry,ref=myapp:cache \
  --cache-to type=registry,ref=myapp:cache,mode=max \
  --output type=image,push=true \
  -t myapp:latest .

# Distributed caching: share build cache across CI runners
# → 5 min build → 30 sec build (incremental)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Layer caching** | Optimizes Dockerfile layer ordering for cache hits |
| **Multi-stage builds** | Uses separate build and runtime stages |
| **Distroless images** | Knows gcr.io/distroless for minimal attack surface |
| **BuildKit** | Understands distributed layer caching with --cache-from/to |

---

## 3. Kubernetes Scheduler: Binding & Node Selection

**Q:** "You have 1000 pods to schedule on 50 nodes. Walk through the Kubernetes scheduler algorithm. How does it filter, score, and bind pods to nodes? What happens when a pod can't be scheduled due to resource constraints?"

**What They're Really Testing:** Whether you understand the Kubernetes scheduling framework — the predicate/priority pipeline (now Filter/Score plugins) and binding.

### Answer

**Scheduling Pipeline (Kubernetes Scheduler):**

```
Scheduling cycle (for each unscheduled pod):

1. Queue: unscheduled pods in SchedulingQueue
   - Priority-based: higher priority pods scheduled first
   - Pod groups: gang scheduling (all-or-nothing)

2. Filtering (Predicates):
   Test ALL nodes (50 nodes) → reduce to feasible nodes
   
   Filters (examples):
   - PodFitsResources:  Requested(CPU,Mem) ≤ Allocatable(Node)
   - PodFitsHost:       spec.nodeName matches
   - PodFitsHostPorts:  Requested port not in use
   - NodeSelector:      node labels match pod's nodeSelector
   - NodeAffinity:      requiredDuringScheduling... matches
   - TaintToleration:   pod tolerates all node taints
   - CheckVolumeBinding: PVC can be bound
   - NodeUnschedulable:  spec.unschedulable? (cordoned)
   
   Result: 50 → 12 feasible nodes

3. Scoring (Priorities):
   Score each feasible node (0-100)
   
   Plugins (examples):
   - NodeResourcesFit:  MostAllocated (50) or LeastAllocated (100)
   - ImageLocality:     Node has image cached (higher score)
   - InterPodAffinity:  Prefer co-location
   - NodeAffinity:      preferredDuringScheduling weight
   - TaintToleration:   Score for tolerated taints
   
   Example scores:
   Node A: Resources(75) + Image(10) + Affinity(5) = 90
   Node B: Resources(80) + Image(5) + Affinity(0) = 85
   
   Winner: Node A (highest score)

4. Binding:
   - Write binding to etcd: Pod scheduled to Node A
   - kubelet on Node A detects bound pod → pulls image → starts container
```

**Advanced Scheduling:**

```yaml
# Pod Topology Spread Constraints
# Ensure pods are spread across zones/nodes:
spec:
  topologySpreadConstraints:
  - maxSkew: 1                    # Max 1 pod difference between zones
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: DoNotSchedule  # or ScheduleAnyway
    labelSelector:
      matchLabels:
        app: my-app

# Pod Disruption Budget
# Ensure minimum availability during voluntary disruptions:
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: my-app-pdb
spec:
  minAvailable: 3                 # At least 3 pods must be available
  selector:
    matchLabels:
      app: my-app

# Node Affinity (advanced)
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: topology.kubernetes.io/zone
            operator: In
            values:
            - us-east-1a
            - us-east-1b      # Only schedule to these zones
      preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 80
        preference:
          matchExpressions:
          - key: instance-type
            operator: In
            values:
            - c5.4xlarge       # Prefer this instance type (weight=80)
```

**Unschedulable Pod Handling:**

```
When a pod can't be scheduled:

1. Failed Filtering:
   - Pod stays in SchedulingQueue
   - Backoff: exponential backoff (100ms → 200ms → 400ms → ... → 5min max)
   - Periodic retry: every 5 minutes (after backoff cap)
   - Events: "0/50 nodes available: 25 insufficient CPU, 25 insufficient memory"

2. Reasons:
   - Insufficient resources (CPU/Mem/GPU)
   - Taints that no toleration matches
   - Node selector no node matches
   - PVC not found or not bound
   - Port conflicts

3. Solutions:
   a. Descheduler: Evict pods to rebalance
   b. Cluster Autoscaler: Add nodes (must be configured!)
   c. Priority-based eviction: Lower-priority pods preempted
   d. Pod suspend: SuspendJob (batch workloads)

# Priority-based preemption:
# If high-priority pod can't fit:
# 1. Identify nodes where preempting lower-priority pods would help
# 2. Select victim pods (lowest priority first)
# 3. Terminate victim pods (graceful shutdown)
# 4. Schedule high-priority pod on freed resources
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Filter/Score pipeline** | Understands the two-phase filtering and scoring across ALL nodes |
| **Topology spread** | Knows maxSkew and topologyKey for zonal distribution |
| **Unschedulable handling** | Explains backoff, eviction, cluster autoscaler as escalation paths |
| **Priority/preemption** | Understands how higher-priority pods can preempt lower-priority pods |

---

## 4. Kubernetes Networking: CNI, Services, DNS

**Q:** "A pod in namespace-a cannot reach a Service in namespace-b. All pods have IPs, but the DNS resolution fails. Walk through the Kubernetes networking model: how do pods get IPs, how does Service DNS work, and how does kube-proxy handle traffic?"

**What They're Really Testing:** Whether you understand the complete Kubernetes networking stack — CNI plugin, Service abstraction, kube-proxy modes, and CoreDNS resolution.

### Answer

**Kubernetes Networking Model (4 Requirements):**

```
1. Pod-to-Pod: All pods can reach each other (no NAT)
2. Pod-to-Node: Pods can reach all nodes
3. Node-to-Pod: Nodes can reach all pods
4. External-to-Service: Outside world reaches pods via Services

Networking implementations (CNI plugins):
  - Calico: BGP-based, network policies, VXLAN/IP-in-IP/DSR
  - Cilium: eBPF-based, transparent encryption, Hubble observability
  - Flannel: overlay (VXLAN), simple, no network policies
  - AWS VPC CNI: native VPC IPs, direct ENI attachment
  - Weave: mesh topology, encryption, multicast
```

**CNI Plugin Lifecycle:**

```
1. Pod creation → kubelet calls CNI plugin
2. CNI plugin allocates IP from pool
3. CNI plugin creates veth pair:
   - One end: eth0 inside pod (container namespace)
   - Other end: vethXXXX on host
4. CNI plugin configures routing:
   - Default gateway (bridge or overlay)
   - IP masquerade (pod → external world)

Example (Calico with VXLAN):
  Pod IP: 10.2.3.4/24
  Host interface: veth-abc123
  VXLAN tunnel: traffic goes host → VXLAN → destination host
  IP-in-IP: traffic goes host → IPIP tunnel → destination host
```

**Service Types (Abstraction):**

```yaml
# ClusterIP (default): virtual IP, internal only
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  type: ClusterIP
  selector:
    app: my-app
  ports:
  - port: 80
    targetPort: 8080

# NodePort: external access via node IP + port
spec:
  type: NodePort
  ports:
  - port: 80
    nodePort: 30080      # Access via node-ip:30080

# LoadBalancer: cloud provider's LB (often NodePort + LB)
spec:
  type: LoadBalancer
  # Cloud provider creates LB → points to NodePort on all nodes

# Headless Service (no virtual IP, direct pod DNS):
spec:
  clusterIP: None         # No load balancing!
  # DNS returns all pod IPs (A/AAAA records)
  # Used by StatefulSets (each pod gets DNS name)
```

**kube-proxy Modes:**

```
1. userspace (legacy):
   - kube-proxy listens on port, proxies to pods
   - User space → kernel → user space → kernel → pod
   - High overhead, rarely used

2. iptables (default):
   - kube-proxy programs iptables rules
   - Service IP → random pod IP (NAT)
   - Each service = ~100 iptables rules
   - 10K services = 1M rules → rule evaluation latency!
   
   iptables -t nat -L KUBE-SERVICES
   # Chain KUBE-SERVICES (1 references)
   # KUBE-SVC-XXXXX  tcp -- 0.0.0.0/0 10.96.0.1 match tcp dpt:443
   # → KUBE-SEP-XXXXX (statistical probability: 33% each backend)

3. IPVS (recommended for large clusters):
   - Uses Linux IP Virtual Server (kernel module)
   - O(1) lookups (hash table, not linear chain)
   - Supports: rr, wrr, lc, wlc, sh, dh, lblc
   - Scales to 10K+ services
   - Must: modprobe ip_vs ip_vs_rr ip_vs_wrr ip_vs_sh
```

**CoreDNS & DNS Resolution:**

```yaml
# Pod DNS resolution:
# my-service.my-namespace.svc.cluster.local

# Resolution flow:
pod → /etc/resolv.conf → CoreDNS → Kubernetes API → resolved IP

# /etc/resolv.conf inside pod:
search my-namespace.svc.cluster.local svc.cluster.local cluster.local
nameserver 10.96.0.10     # CoreDNS ClusterIP
options ndots:5            # Try DNS with search domains first

# Why cross-namespace resolution fails:
# my-service (short name): searched as:
#   1. my-service.my-namespace.svc.cluster.local → found! (same ns)
#   2. NOT my-service.other-ns.svc.cluster.local (doesn't search other ns)
# Solution: use FQDN: my-service.other-ns.svc.cluster.local

# CoreDNS configuration (ConfigMap):
apiVersion: v1
kind: ConfigMap
metadata:
  name: coredns
  namespace: kube-system
data:
  Corefile: |
    .:53 {
        errors
        health
        kubernetes cluster.local in-addr.arpa ip6.arpa {
          pods insecure
          fallthrough in-addr.arpa ip6.arpa
          ttl 30
        }
        prometheus :9153
        forward . /etc/resolv.conf
        cache 30
        reload
    }
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **CNI model** | Understands veth pair, IP allocation, and overlay vs direct routing |
| **kube-proxy modes** | Compares iptables vs IPVS (scalability, O(1) vs O(N)) |
| **Service types** | Knows ClusterIP, NodePort, LoadBalancer, Headless differences |
| **DNS resolution** | Explains search domains, ndots, and why cross-namespace needs FQDN |

---

## 5. Kubernetes Security: RBAC, PSP, Pod Identity

**Q:** "Design a multi-tenant Kubernetes cluster where Team A and Team B have namespaces team-a and team-b. Team A should only manage their own resources. Team B has read access to Team A's services. How do you implement this with RBAC?"

**What They're Really Testing:** Whether you understand Kubernetes RBAC — the Role/ClusterRole/ServiceAccount/Binding model, and how to implement least-privilege security.

### Answer

**RBAC Model:**

```
Subject (who): ServiceAccount, User, Group
    │
    ├─→ RoleBinding (namespaced) or ClusterRoleBinding (cluster-wide)
    │
    ▼
Role/ClusterRole (what):
  apiGroups: apps, networking.k8s.io, batch, etc.
  resources: pods, deployments, services, configmaps, secrets, etc.
  verbs: get, list, watch, create, update, patch, delete
```

**Multi-Tenant RBAC Implementation:**

```yaml
# Role for Team A (full access to team-a namespace):
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: team-a
  name: team-a-full-access
rules:
- apiGroups: ["", "apps", "batch", "networking.k8s.io"]
  resources: ["pods", "deployments", "services", "configmaps", "secrets",
              "ingresses", "horizontalpodautoscalers", "jobs", "cronjobs"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: ["autoscaling"]
  resources: ["horizontalpodautoscalers"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["events", "pods/log", "pods/exec"]
  verbs: ["get", "list", "watch"]    # Read-only for diagnostics

---
# RoleBinding: Bind Role to Team A's ServiceAccount
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  namespace: team-a
  name: team-a-binding
subjects:
- kind: ServiceAccount
  name: team-a-sa
  namespace: team-a
roleRef:
  kind: Role
  name: team-a-full-access
  apiGroup: rbac.authorization.k8s.io
```

**Cross-Namespace Access (Team B reads Team A):**

```yaml
# Role for Team B (read-only access to team-a namespace):
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: team-a              # Team B can read team-a resources
  name: team-b-read-access
rules:
- apiGroups: ["", "apps"]
  resources: ["pods", "services", "deployments", "endpoints"]
  verbs: ["get", "list", "watch"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  namespace: team-a
  name: team-b-read-binding
subjects:
- kind: ServiceAccount
  name: team-b-sa
  namespace: team-b                # Team B's SA in team-b namespace
roleRef:
  kind: Role
  name: team-b-read-access
  apiGroup: rbac.authorization.k8s.io
```

**Pod Security Standards (Pod Security Admission — PSA, replacing PSP):**

```yaml
# Deprecated: PodSecurityPolicy (removed in 1.25)
# New: Pod Security Admission (built-in, no webhook!)

# Namespace-level enforcement:
apiVersion: v1
kind: Namespace
metadata:
  name: team-a
  labels:
    pod-security.kubernetes.io/enforce: restricted  # Reject violating pods
    pod-security.kubernetes.io/audit: baseline      # Log violations
    pod-security.kubernetes.io/warn: baseline        # Warn on violations

# Levels:
# privileged:    No restrictions (system components)
# baseline:      Minimal restrictions (typical workloads)
# restricted:    Full hardening (PCI/HIPAA compliance)

# Example restricted requirements:
# - RunAsNonRoot: true
# - Seccomp profile: RuntimeDefault or Localhost
# - Capabilities: drop ALL, add only NET_BIND_SERVICE
# - readOnlyRootFilesystem: true
# - allowPrivilegeEscalation: false
```

**ServiceAccount & Pod Identity:**

```yaml
# Each pod gets a ServiceAccount identity
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-app-sa
  namespace: team-a
automountServiceAccountToken: true   # Mount token in pod

# Token mounted at: /var/run/secrets/kubernetes.io/serviceaccount/token
# Pod uses this token to authenticate to API server

# Workload Identity (cloud-specific):
# AWS:     ServiceAccount annotation → IAM role
# GKE:     Workload Identity → GCP SA
# Azure:   Azure AD Pod Identity → Azure AD managed identity

# AWS EKS example:
apiVersion: v1
kind: ServiceAccount
metadata:
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789:role/my-app-role
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **RBAC model** | Understands Role vs ClusterRole, Binding vs ClusterRoleBinding |
| **Least privilege** | Grants minimum verbs/resources per role |
| **PSA over PSP** | Knows PodSecurityPolicy is deprecated, Pod Security Admission is current |
| **ServiceAccount identity** | Understands pod identity via tokens for cloud IAM integration |

---

## 6. Storage: CSI, Persistent Volumes, StatefulSets

**Q:** "Design a stateful application (e.g., PostgreSQL) on Kubernetes. How do PV/PVC bindings work? How does the Container Storage Interface (CSI) provision volumes? How do StatefulSets guarantee stable storage for each pod?"

**What They're Really Testing:** Whether you understand the Kubernetes storage model — dynamic provisioning via CSI, PV/PVC lifecycle, and StatefulSet ordering guarantees.

### Answer

**PV/PVC Binding Lifecycle:**

```
1. User creates PVC (PersistentVolumeClaim):
   apiVersion: v1
   kind: PersistentVolumeClaim
   spec:
     storageClassName: premium-ssd
     accessModes: [ReadWriteOnce]
     resources:
       requests:
         storage: 100Gi

2. Kubernetes finds or provisions PV (PersistentVolume):
   - If matching PV exists (static provisioning): bind PVC to PV
   - If StorageClass has provisioner (dynamic): CSI plugin creates PV
   
3. PVC becomes Bound → pod can use it:
   spec:
     volumes:
     - name: data
       persistentVolumeClaim:
         claimName: my-pvc

4. Pod runs on node → kubelet mounts volume:
   - CSI node plugin attaches device
   - Formats (if first use)
   - Mounts to pod's filesystem

5. Pod deleted → PVC still exists → data persists!
6. PVC deleted → PV deleted (unless retain policy configured)
```

**CSI (Container Storage Interface):**

```
CSI plugin architecture:
  Controller Plugin (deployment):
    - CreateSnapshot, DeleteSnapshot
    - CreateVolume, DeleteVolume
    - ControllerPublishVolume, ControllerUnpublishVolume
  
  Node Plugin (DaemonSet):
    - NodeStageVolume (mount device, format)
    - NodePublishVolume (bind mount to pod)
    - NodeGetVolumeStats

  Identity Plugin:
    - GetPluginInfo
    - Probe (health check)

Example: EBS CSI Driver flow:
  1. Create PVC with storageClassName: ebs-sc
  2. CSI Controller.CreateVolume → EC2.CreateVolume (100Gi gp3)
  3. Pod scheduled to EC2 instance
  4. CSI Node.NodeStageVolume → Attach EBS volume to EC2
  5. CSI Node.NodePublishVolume → mount /dev/xvdh to /var/lib/kubelet/...
  6. Pod sees the volume at mount path
```

**StatefulSet Storage Guarantee:**

```yaml
# StatefulSet: stable network identity + stable storage

apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  serviceName: postgres          # Headless Service (for DNS)
  replicas: 3
  selector:
    matchLabels:
      app: postgres
  template:
    spec:
      containers:
      - name: postgres
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:          # Each replica gets its OWN PVC
  - metadata:
      name: data
    spec:
      storageClassName: premium-ssd
      accessModes: [ReadWriteOnce]
      resources:
        requests:
          storage: 100Gi

# PVC naming: <volume-claim-template-name>-<statefulset-name>-<ordinal>
# Pod postgres-0 → PVC data-postgres-0 → PV (bound automatically)
# Pod postgres-1 → PVC data-postgres-1 → PV (different volume!)
# Pod postgres-2 → PVC data-postgres-2 → PV

# Storage guarantees:
# 1. Each pod gets UNIQUE, STABLE PVC (not shared!)
# 2. If pod-0 dies and reschedules: reuses PVC data-postgres-0 (same data!)
# 3. If pod-1 is deleted: PVC survives (data preserved)
# 4. To delete everything: delete StatefulSet, then delete PVCs manually

# Issue: manual PVC cleanup needed when scaling DOWN
# Pod postgres-2 deleted → PVC still exists → must delete manually!
```

**Storage Best Practices:**

```yaml
# Retain policy for critical data:
apiVersion: v1
kind: StorageClass
apiVersion: storage.k8s.io/v1
metadata:
  name: premium-ssd-retain
provisioner: ebs.csi.aws.com
reclaimPolicy: Retain          # Default: Delete
# Retain: PV persists after PVC deleted (manual cleanup)
# Delete: PV and underlying storage are removed

# Volume Snapshot & Clone:
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: postgres-snapshot-pre-upgrade
spec:
  volumeSnapshotClassName: ebs-snapshot-class
  source:
    persistentVolumeClaimName: data-postgres-0

# Ephemeral volumes (for scratch space):
spec:
  volumes:
  - name: scratch
    ephemeral:
      volumeClaimTemplate:
        spec:
          storageClassName: premium-ssd
          accessModes: [ReadWriteOnce]
          resources:
            requests:
              storage: 10Gi
# Pod-created-on-demand, deleted with pod
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **PV/PVC lifecycle** | Understands dynamic provisioning, binding, mounting, deletion |
| **CSI architecture** | Knows Controller (in/out-of-tree) vs Node (DaemonSet) plugins |
| **StatefulSet storage** | Explains volumeClaimTemplates → stable PVC per ordinal |
| **Retain vs Delete** | Knows reclaim policy implications for data persistence |

---

## 7. Controllers: ReplicaSet, Deployment, Operator

**Q:** "Walk through what happens when you run 'kubectl apply -f deployment.yaml' with replicas=5. How does the Deployment controller interact with ReplicaSet? How would you build a Kubernetes Operator using the operator-sdk?"

**What They're Really Testing:** Whether you understand Kubernetes control loops — how controllers watch, reconcile, and converge desired state.

### Answer

**Deployment → ReplicaSet → Pod Chain:**

```
kubectl apply -f deployment.yaml (replicas: 5)

1. Deployment Controller (kube-controller-manager):
   - Watches: Deployments, ReplicaSets, Pods
   - Apply event: deployment my-app CREATED/UPDATED
   - Creates ReplicaSet with matching pod template hash

2. ReplicaSet Controller:
   - Watches: ReplicaSets, Pods
   - Detects: ReplicaSet.my-app-6b8d9f7c9 with replicas=5, but 0 pods running
   - Creates 5 pod objects (parallel creation, not sequential)
   - Pod template: from the ReplicaSet spec (hash 6b8d9f7c9)

3. Scheduler:
   - Watches: unscheduled Pods
   - Schedules each pod to a node

4. kubelet:
   - Watches: pods scheduled to its node
   - Creates containers (CRI: containerd), mounts volumes (CSI)
   - Reports pod status back to API server

Reflection:
  Deployment → 1 ReplicaSet → 5 Pods
  ├── my-app-6b8d9f7c9-abcde
  ├── my-app-6b8d9f7c9-bcdef
  ├── my-app-6b8d9f7c9-cdefg
  ├── my-app-6b8d9f7c9-defgh
  └── my-app-6b8d9f7c9-efghi
```

**Rolling Update Mechanics:**

```yaml
# Initial state:
Deployment: my-app, replicas: 5
ReplicaSet v1: my-app-6b8d9f7c9 (5 pods, all ready)

# User updates image from v1 to v2:
kubectl set image deployment/my-app my-container=my-app:v2

# Deployment controller:
# 1. Creates ReplicaSet v2: my-app-9f8e7d6c5 (replicas: 0)
# 2. Scales UP v2 by 1 → scales DOWN v1 by 1
# 3. Waits for v2 pod to become Ready
# 4. Repeat: scale up v2 by 1, scale down v1 by 1
# 5. Eventually: v2 has 5 replicas, v1 has 0

Rolling update parameters:
spec:
  replicas: 5
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1          # Max 1 extra pod during update (5+1=6 total)
      maxUnavailable: 0     # Min 5 pods always available (0 unavailable)

# Result: NO DOWNTIME!
# Min available = replicas - maxUnavailable = 5 - 0 = 5
# Always 5 pods serving traffic → zero-downtime deployment
```

**Kuberentes Operator Pattern:**

```yaml
# Operator = Controller + Custom Resource Definition (CRD)
# Extends Kubernetes API with application-specific logic

# Example: PostgreSQL Operator (Crunchy Data, Zalando, CloudNativePG)

# Custom Resource:
apiVersion: postgresql.example.com/v1
kind: PostgreSQLCluster
metadata:
  name: my-cluster
spec:
  instances: 3                   # Number of PostgreSQL replicas
  version: 16
  storage:
    size: 100Gi
    storageClass: premium-ssd
  backup:
    schedule: "0 2 * * *"       # Daily backup at 2 AM
    retention: 30                # Keep 30 backups

# Operator Controller:
# 1. Watches: PostgreSQLCluster CRs
# 2. Reconcile:
#    - Create StatefulSet (3 pods, headless service)
#    - Configure streaming replication (primary → replicas)
#    - Set up automated backups (CronJob for pg_dump)
#    - Handle failover (detect primary failure, promote replica)
#    - Handle scaling (add/remove replicas with re-replication)

# Operator SDK tools:
# - kubebuilder (Go, most popular)
# - operator-sdk (Ansible, Helm, Go)
# - Kopf (Python)
```

**Custom Controller Code Pattern:**

```go
// Simplified controller reconcile loop (Go)
func (r *MyAppReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
    // 1. Fetch the custom resource
    var app myappv1.MyApp
    if err := r.Get(ctx, req.NamespacedName, &app); err != nil {
        return ctrl.Result{}, client.IgnoreNotFound(err)
    }

    // 2. Observe current state (what exists now?)
    var currentDeploy appsv1.Deployment
    err := r.Get(ctx, types.NamespacedName{Name: app.Name}, &currentDeploy)

    // 3. Compute desired state (what should exist?)
    desiredDeploy := buildDesiredDeployment(&app)

    // 4. Reconcile (make current → match desired)
    if err != nil {
        // Does not exist → create it
        return ctrl.Result{}, r.Create(ctx, desiredDeploy)
    }
    
    // Exists → update it if different
    if !deploymentsEqual(&currentDeploy, desiredDeploy) {
        return ctrl.Result{}, r.Update(ctx, desiredDeploy)
    }

    // 5. Update status
    app.Status.Ready = currentDeploy.Status.ReadyReplicas
    r.Status().Update(ctx, &app)

    // 6. Requeue for next reconciliation (periodic recheck)
    return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Controller reconciliation** | Understands current vs desired state, informer-based watches |
| **Rolling update mechanics** | Can explain maxSurge/maxUnavailable and zero-downtime guarantee |
| **Operator pattern** | Knows CRD + controller = operator, with kubebuilder/operator-sdk |
| **Reconcile loop** | Can write a basic reconcile function: get, observe, compute, apply |

---

## 8. Production: Autoscaling, Rolling Updates, Chaos

**Q:** "Your Kubernetes deployment handles variable traffic — 100 requests/s during off-peak and 10K requests/s during peak. Design autoscaling, rolling updates, and chaos engineering for this system. How does HPA work? How do you test resilience?"

**What They're Really Testing:** Whether you understand Kubernetes production patterns — HPA/VPA, pod disruption budgets, readiness probes, and chaos engineering with Litmus/ChaosMesh.

### Answer

**Horizontal Pod Autoscaler (HPA):**

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 3
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70    # Target 70% CPU utilization
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  - type: Pods
    pods:
      metric:
        name: requests_per_second
      target:
        type: AverageValue
        averageValue: 500        # Target 500 RPS per pod
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300  # Wait 5 min before scaling down
      policies:
      - type: Percent
        value: 10                    # Max 10% pods removed per minute
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0   # Scale up immediately
      policies:
      - type: Percent
        value: 100                   # Double pods per minute
        periodSeconds: 60
```

**VPA (Vertical Pod Autoscaler):**

```yaml
# VPA: adjust CPU/Memory requests based on actual usage
# Use when: workloads that can't easily horizontal scale

apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: my-app-vpa
spec:
  targetRef:
    apiVersion: "apps/v1"
    kind: Deployment
    name: my-app
  updatePolicy:
    updateMode: "Auto"          # Recommends AND applies
    # Alternative: "Initial" (apply on new pod creation)
    #              "Off" (recommend only)
  resourcePolicy:
    containerPolicies:
    - containerName: '*'
      minAllowed:
        cpu: 100m
        memory: 128Mi
      maxAllowed:
        cpu: 4
        memory: 4Gi
      controlledResources: ["cpu", "memory"]
```

**Production Readiness:**

```yaml
# Pod specifications for production:

apiVersion: v1
kind: Pod
spec:
  containers:
  - name: my-app
    resources:
      requests:              # Minimum reservation (used by scheduler)
        cpu: 500m
        memory: 512Mi
      limits:                # Hard cap (used by kubelet)
        cpu: 2
        memory: 2Gi
    
    # Startup probe: for slow-starting containers (e.g., JVM)
    startupProbe:
      httpGet:
        path: /healthz
        port: 8080
      initialDelaySeconds: 10
      periodSeconds: 5
      failureThreshold: 30    # 30 × 5 = 150s max startup time!
    
    # Readiness probe: is this pod ready to serve traffic?
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      periodSeconds: 10
    
    # Liveness probe: restart pod if unresponsive
    livenessProbe:
      httpGet:
        path: /live
        port: 8080
      periodSeconds: 30
      failureThreshold: 3

    # Lifecycle hooks (graceful shutdown)
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "sleep 10"]
          # Wait 10s for load balancer to drain connections
```

**Chaos Engineering (Litmus/ChaosMesh):**

```yaml
# LitmusChaos: inject failures to test resilience

# Example: pod-kill chaos experiment
apiVersion: litmuschaos.io/v1alpha1
kind: ChaosEngine
metadata:
  name: pod-kill-chaos
spec:
  appinfo:
    appns: default
    applabel: app=my-app
    appkind: deployment
  chaosServiceAccount: litmus-sa
  experiments:
  - name: pod-delete
    spec:
      components:
        env:
        - name: TOTAL_CHAOS_DURATION
          value: '60'          # Kill pods for 60 seconds
        - name: CHAOS_INTERVAL
          value: '10'          # Kill every 10 seconds
        - name: FORCE
          value: 'true'        # SIGKILL instead of SIGTERM
        - name: PODS_AFFECTED_PERC
          value: '30'          # Kill 30% of pods

# What to test:
# 1. Pod failure: Pod deleted → HPA/ReplicaSet replaces → no impact?
# 2. Network latency: pod-to-pod delay → retry logic works?
# 3. Node failure: cordon/drain node → pods reschedule?
# 4. DNS failure: CoreDNS down → fallback DNS works?
# 5. API server flapping: rate limiting → controller retries?
```

**Cluster Autoscaler:**

```yaml
# Cluster Autoscaler: add/remove NODES when pods can't schedule

# Config (AWS EKS):
deployment:
  command:
  - ./cluster-autoscaler
  - --node-group-auto-discovery=asg:tag=k8s.io/cluster-autoscaler/enabled
  - --scale-down-delay-after-add=10m       # Wait 10 min after scale up
  - --scale-down-delay-after-delete=10s    # 
  - --scale-down-unneeded-time=10m          # 10 min idle before scale down
  - --max-node-provision-time=15m           # Max 15 min for new node
  - --balance-similar-node-groups=true      # Balance across AZs

# Node group definition (Terraform):
resource "aws_autoscaling_group" "workers" {
  min_size         = 3
  max_size         = 20      # Cluster autoscaler will scale within this
  
  tag {
    key                 = "k8s.io/cluster-autoscaler/enabled"
    value               = "true"
    propagate_at_launch = true
  }
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **HPA tuning** | Sets stabilization windows, scale-up/down policies, multiple metrics |
| **Probes** | Differentiates startup (slow boot) vs readiness (traffic) vs liveness (health) |
| **Chaos engineering** | Uses Litmus or ChaosMesh for controlled failure injection |
| **Cluster autoscaler** | Understands node-level autoscaling as complement to HPA (pod-level) |

---

> *All 8 questions cover the full breadth of Docker & Kubernetes — from kernel namespaces to production autoscaling, security, and chaos engineering.*
