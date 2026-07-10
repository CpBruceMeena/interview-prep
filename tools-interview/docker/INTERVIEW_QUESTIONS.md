# 🐳 Docker — Staff-Level Interview Questions

> *2 questions covering container runtime internals, image layers, and build optimization — every question expects principal engineer-level depth.*

> **Companion files:** See [`../kubernetes/INTERVIEW_QUESTIONS.md`](../kubernetes/INTERVIEW_QUESTIONS.md) for Kubernetes scheduler, networking, RBAC, storage, controllers, and production operations.
>
> For deeper pod lifecycle, monitoring, and production control, see [`../kubernetes/POD_LIFECYCLE_AND_MONITORING.md`](../kubernetes/POD_LIFECYCLE_AND_MONITORING.md) and [`../kubernetes/PRODUCTION_CONTROL.md`](../kubernetes/PRODUCTION_CONTROL.md).

---

## Table of Contents

1. [Container Runtime: Namespaces & Cgroups](#1-container-runtime-namespaces-cgroups)
2. [Docker: Images, Layers & UnionFS](#2-docker-images-layers-unionfs)

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
  RUN apt-get update && apt-get install -y \\ ← Layer 2: ~500MB (dependencies)
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

RUN apt-get update && apt-get install -y libpq5 \\  # Runtime libs only
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

> *These 2 questions cover the core Docker fundamentals — from kernel namespaces and cgroups to image layer optimization and multi-stage builds. For Kubernetes questions, see the companion file: [`../kubernetes/INTERVIEW_QUESTIONS.md`](../kubernetes/INTERVIEW_QUESTIONS.md).*
