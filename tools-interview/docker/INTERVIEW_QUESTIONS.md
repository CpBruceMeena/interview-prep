# 🐳 Docker — Staff-Level Interview Questions

> *8 questions covering container runtime internals, image layers and build caching, supply-chain security, resource limits, networking, hardening and process lifecycle. Each answer leads with a 30-second version, then the mechanism, then failure modes and what the interviewer probes next.*

> **Companion files:** See [`../kubernetes/INTERVIEW_QUESTIONS.md`](../kubernetes/INTERVIEW_QUESTIONS.md) for Kubernetes scheduler, networking, RBAC, storage, controllers, and production operations.
>
> For deeper pod lifecycle, monitoring, and production control, see [`../kubernetes/POD_LIFECYCLE_AND_MONITORING.md`](../kubernetes/POD_LIFECYCLE_AND_MONITORING.md) and [`../kubernetes/PRODUCTION_CONTROL.md`](../kubernetes/PRODUCTION_CONTROL.md).

!!! info "Version baseline (October 2026)"
    - **BuildKit** has been the default builder in Docker Engine since **23.0** (2023). `docker build` is `docker buildx build` under the hood. The legacy builder is deprecated.
    - **Compose v2** is a Go CLI plugin invoked as `docker compose`. Compose v1 (`docker-compose`, Python) reached end of life in 2023. The top-level `version:` key in compose files is obsolete and ignored.
    - **Docker Engine 29** (late 2025) made the **containerd image store** the default for new installs (legacy graph drivers like `overlay2` are deprecated but still usable) and added experimental nftables support.
    - **cgroup v2** is the default on all current mainstream distros. Kubernetes 1.35 dropped cgroup v1 support in the kubelet by default.
    - **Docker Hardened Images** (minimal, non-root base images with SBOMs and provenance) became free and Apache-2.0 in December 2025, joining distroless and Chainguard as minimal-base options.

---

## Table of Contents

1. [Container Runtime: Namespaces & Cgroups](#1-container-runtime-namespaces-cgroups)
2. [Docker: Images, Layers & UnionFS](#2-docker-images-layers-unionfs)
3. [BuildKit: Build Cache, Remote Cache & Multi-Platform Builds](#3-buildkit-build-cache-remote-cache-multi-platform-builds)
4. [Supply-Chain Security: SBOM, Provenance, Signing & Scanning](#4-supply-chain-security-sbom-provenance-signing-scanning)
5. [Resource Limits: Memory, CPU Throttling & Runtime Awareness](#5-resource-limits-memory-cpu-throttling-runtime-awareness)
6. [Container Networking](#6-container-networking)
7. [Runtime Hardening & Rootless Containers](#7-runtime-hardening-rootless-containers)
8. [PID 1, Signals & Graceful Shutdown](#8-pid-1-signals-graceful-shutdown)

---

## 1. Container Runtime: Namespaces & Cgroups

**Q:** "Walk through what happens when you run 'docker run -it ubuntu bash' — at the OS level. What kernel primitives are invoked? How do namespaces and cgroups isolate the container?"

**What They're Really Testing:** Whether you understand that containers are ordinary Linux processes with a restricted view (namespaces) and a resource budget (cgroups), sharing the host kernel. They aren't VMs.

!!! tip "30-second answer"
    The CLI calls `dockerd`, which asks **containerd** to create the container. containerd starts a **shim**, which runs **runc** with an OCI spec. runc creates new namespaces (what the process can *see*), puts the process in a cgroup (what it can *use*), mounts the image's root filesystem and `pivot_root`s into it, drops capabilities, applies seccomp and AppArmor/SELinux, then `exec`s `bash`. runc exits and the shim stays as the container's parent. Because the kernel is shared, a kernel exploit is a container escape. That's the security boundary to keep in mind.

### Answer

**What happens:**

```
docker run -it ubuntu bash

1. docker CLI → dockerd (REST over /var/run/docker.sock)
   - pulls ubuntu if missing, prepares the rootfs snapshot (overlayfs)
2. dockerd → containerd (gRPC) → containerd-shim-runc-v2 → runc create/start
3. runc, from the OCI config.json:
   a. clone()/unshare() new namespaces:
      mnt    – own mount table
      pid    – the process sees itself as PID 1
      net    – own interfaces, routes, iptables, ports
      ipc    – own SysV IPC / POSIX message queues
      uts    – own hostname
      cgroup – own view of /sys/fs/cgroup (default on cgroup v2 hosts)
      user   – UID/GID mapping. NOT used by default in rootful Docker
               (needs --userns-remap or rootless mode), so container root = host UID 0.
      (time namespace exists in the kernel but Docker doesn't use it)
   b. creates a cgroup (v2) and writes limits: cpu.max, cpu.weight, memory.max, io.max, pids.max
   c. mounts the rootfs, /proc, /dev, /sys (mostly read-only), then pivot_root()
   d. drops capabilities to Docker's default set, sets no_new_privs if requested,
      loads the seccomp-bpf profile, applies the AppArmor/SELinux label
   e. execve("bash"). The shim keeps stdio and reports the exit status. runc exits.
```

**Namespace details:**

| Namespace | What the container sees | Notes |
|---|---|---|
| PID | Its processes only, with its own PID 1 | Host sees the same process under a different PID. `--pid=host` breaks this. |
| Network | `lo` + `eth0` (one end of a veth pair). The other end sits on a host bridge. | Own iptables and ports. `--network=host` shares the host stack. |
| Mount | Image rootfs + volumes / bind mounts | `pivot_root` (not `chroot`) so the old root can be unmounted |
| User | UID 0 inside maps to e.g. host UID 100000 (`/etc/subuid`) | The strongest isolation upgrade. Default in rootless Docker and Podman, opt-in for rootful Docker. |

**cgroup v2:**

```bash
/sys/fs/cgroup/system.slice/docker-<id>.scope/
├── cpu.max        # "100000 100000" = 100 ms quota per 100 ms period = 1 CPU   (--cpus=1)
├── cpu.weight     # relative share under contention                          (--cpu-shares)
├── memory.max     # hard limit → OOM kill inside the cgroup                  (--memory)
├── memory.high    # soft limit → throttle + reclaim (Docker doesn't set it by default)
├── io.max         # per-device bps/iops limits                               (--device-write-bps)
├── pids.max       # fork-bomb protection                                     (--pids-limit)
├── memory.events  # counters: low, high, max, oom, oom_kill
└── cpu.stat       # nr_throttled, throttled_usec (see Q5)
```

What v2 brought over v1: a single unified hierarchy (no separate cpu/memory/blkio trees that could disagree), safe delegation of subtrees to unprivileged users (which is what makes rootless resource limits possible), **PSI** pressure metrics (`cpu.pressure`, `memory.pressure`, `io.pressure`), and better accounting of page cache and writeback per cgroup.

On Kubernetes: the kubelet evicts pods based on **node-level** pressure signals (memory available, disk), not on `memory.high`. Kubernetes' optional Memory QoS feature is what sets `memory.high` for pods.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Runtime stack** | dockerd → containerd → shim → runc. Knows why the shim exists (containers survive daemon restarts). |
| **Namespace isolation** | Lists them, and knows **user namespaces are off by default** in rootful Docker |
| **Cgroups v2** | Maps Docker flags to cgroup files. PSI, `memory.events`. |
| **Shared kernel** | Capabilities, seccomp and LSMs as defense in depth. gVisor/Kata when you need a stronger boundary. |

**What they probe next:** "Container vs VM isolation?" Containers share the kernel, so for multi-tenant untrusted code you use gVisor (a user-space kernel) or Kata/Firecracker (micro-VMs). "What's in `docker inspect` State?" `OOMKilled`, `ExitCode` 137 = SIGKILL.

---

## 2. Docker: Images, Layers & UnionFS

**Q:** "You have a Docker image that's 2GB and takes 5 minutes to pull on deploy. How do you optimize build times and image size? Explain how Docker layers work, layer caching, and multi-stage builds."

**What They're Really Testing:** Whether you understand content-addressed layers and the overlay filesystem, and can design Dockerfiles that are small, cache well and ship nothing but the runtime.

!!! tip "30-second answer"
    An image is a manifest pointing at a config and an ordered list of **read-only, content-addressed layer tarballs**. A container adds one thin **writable** layer on top, and overlayfs merges them (copy-on-write). Every `RUN`/`COPY`/`ADD` creates a layer, and **deleting a file in a later layer doesn't shrink the image**. Shrink it with **multi-stage builds** (compile in a fat stage, copy only artifacts into a minimal runtime base like distroless, slim or a hardened image) plus `.dockerignore`. Speed up builds by ordering instructions from least to most frequently changing and using BuildKit cache mounts and remote cache (Q3). Speed up pulls by sharing base layers across services and keeping big, stable layers near the bottom.

### Answer

**Layers and the container filesystem:**

```
Dockerfile                                   Layer
  FROM ubuntu:24.04                          L1  base (read-only)
  RUN apt-get update && apt-get install ...  L2  packages (read-only)
  COPY requirements.txt .                    L3  1 KB (read-only)
  RUN pip install -r requirements.txt        L4  Python deps (read-only)
  COPY app/ ./app                            L5  app code (read-only)
  CMD ["python3", "app/main.py"]             (metadata only, no layer)

Running container (overlayfs):
  ┌────────────────────────────────────┐
  │ container layer (READ-WRITE)       │ ← upperdir. Discarded with the container.
  ├────────────────────────────────────┤
  │ L5 app code                        │
  │ L4 pip packages                    │ ← lowerdirs, read-only, shared by
  │ L3 requirements.txt                │   every container/image that uses them
  │ L2 apt packages                    │
  │ L1 ubuntu base                     │
  └────────────────────────────────────┘
  Read: topmost layer containing the path wins.
  Write to an existing file: copy-up of the WHOLE file into the upper layer (slow for big files).
  Delete: a "whiteout" marker in the upper layer. The bytes still exist below.
```

Consequences:

- `RUN apt-get install ... && rm -rf /var/lib/apt/lists/*` must be **one** `RUN`. A separate `RUN rm` adds a whiteout, not a saving.
- A secret `COPY`'d and later deleted is **still in the image**. Use `RUN --mount=type=secret` (Q3).
- Write-heavy data (databases, logs) belongs in **volumes**, not the copy-on-write layer.
- Layers are addressed by digest, so identical base layers are pulled and stored once per host. Standardizing base images across services saves real pull time.

**Cache rules (BuildKit):** each instruction's cache key is roughly hash(parent layer + instruction text + for `COPY`/`ADD` the checksums of the files copied). The first miss invalidates **every instruction after it**. So order from least to most frequently changing: OS packages → dependency manifest → dependency install → source code.

**A Python service, before and after:**

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.13-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt
COPY app/ ./app/

FROM python:3.13-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /app
USER 10001
CMD ["python", "-m", "app.main"]
```

The runtime stage has no compiler, no headers and no pip cache. The virtualenv makes the dependency copy a single directory, and running as a non-root UID is a free security win.

**Go: static binary on distroless:**

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.26 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/server .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/server /server
ENTRYPOINT ["/server"]
```

The result is the size of the binary plus about 2 MB of base (CA certs, tzdata, `/etc/passwd` with a `nonroot` user). There's no shell or package manager. That means **far fewer CVEs and nothing for an attacker to live off**, but not "no vulnerabilities": your binary and its dependencies can still have them. The cost is debuggability: use `kubectl debug` with an ephemeral container, or the `:debug` distroless tags, rather than `docker exec sh`.

**Choosing a base image:**

| Base | Size | Trade-offs |
|---|---|---|
| `ubuntu` / `debian` | Tens of MB compressed | Familiar, glibc, shell + apt. Largest CVE surface. |
| `*-slim` (e.g. `python:3.13-slim`) | Smaller Debian | Good default for interpreted languages that need glibc |
| `alpine` | Smallest with a shell | **musl** libc: Python wheels need `musllinux` builds (or compile from source), DNS resolver and threading behaviour differ, and performance can differ |
| distroless / Docker Hardened Images / Chainguard | Minimal | No shell, non-root by default, SBOMs provided, frequent rebuilds. Harder to debug. |
| `scratch` | Empty | Only for fully static binaries. You add CA certs and tzdata yourself. |

**Other size levers:** `.dockerignore` (`.git`, `node_modules`, build output, local env files, which also keeps secrets out of the build context), `--no-install-recommends`, production-only dependency installs (`npm ci --omit=dev`), and stripping debug symbols.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Layer model** | Read-only layers + one writable layer. Copy-up and whiteouts. Delete doesn't shrink. |
| **Layer caching** | Cache key rules and instruction ordering |
| **Multi-stage builds** | Build and runtime stages separated, only artifacts copied |
| **Base image choice** | Distroless/hardened vs slim vs alpine, including the musl caveat and the debuggability trade-off |

**What they probe next:** "How do you find what's bloating an image?" `docker history`, `dive`. "Why is the 2 GB pull slow even when only code changed?" If the code is in a low layer, every layer above it changes too, so put code last. Also consider lazy pulling (eStargz/SOCI) for very large images.

---

## 3. BuildKit: Build Cache, Remote Cache & Multi-Platform Builds

**Q:** "CI builds take 12 minutes because every runner starts with a cold cache, and you now need images for both amd64 and arm64 (Graviton/Apple silicon). How do you fix build time and produce multi-arch images?"

**What They're Really Testing:** Whether you know BuildKit's model (a DAG with parallel stages, cache mounts, secret mounts, exportable cache) and the three ways to build for another architecture.

!!! tip "30-second answer"
    BuildKit solves the Dockerfile as a **DAG**. Independent stages run in parallel and unused stages are skipped. For speed: order layers well, use `RUN --mount=type=cache` for package-manager caches, and **export the layer cache** to a registry or the CI cache (`--cache-to/--cache-from`) so ephemeral runners start warm. For multi-arch, `docker buildx build --platform linux/amd64,linux/arm64` produces one **manifest list** (image index). Build each architecture natively on separate builder nodes, or cross-compile using `$BUILDPLATFORM`/`$TARGETARCH`. QEMU emulation works for anything but can be 5-20× slower for compile-heavy steps.

### Answer

**BuildKit features that matter:**

| Feature | Syntax | Why |
|---|---|---|
| Cache mount | `RUN --mount=type=cache,target=/root/.cache/pip ...` | Package cache persists between builds on that builder but is **not** in the image |
| Secret mount | `RUN --mount=type=secret,id=npmrc,target=/root/.npmrc npm ci` + `--secret id=npmrc,src=$HOME/.npmrc` | The secret is never written to a layer or the build history |
| SSH mount | `RUN --mount=type=ssh git clone ...` + `--ssh default` | Private repos without copying keys |
| Bind mount | `RUN --mount=type=bind,source=go.sum,target=go.sum ...` | Use a file without creating a `COPY` layer |
| Parallel stages | Multiple `FROM ... AS x` | Independent stages build concurrently |
| Heredocs | `RUN <<EOF ... EOF` | Readable multi-line scripts in one layer |

For apt cache mounts on Debian/Ubuntu bases, remove `/etc/apt/apt.conf.d/docker-clean` first, otherwise apt deletes the cached packages anyway.

**Remote cache for ephemeral CI runners:**

```bash
docker buildx build \
  --cache-from type=registry,ref=registry.example.com/myapp:buildcache \
  --cache-to   type=registry,ref=registry.example.com/myapp:buildcache,mode=max \
  -t registry.example.com/myapp:${GIT_SHA} --push .
# mode=min (default) exports only layers of the final image.
# mode=max also exports intermediate stages (builder deps) → more hits, bigger cache.
# GitHub Actions: type=gha. Other backends: s3, azblob, local (dir).
```

Note that **cache mounts are not exported** with `--cache-to`. They live on the builder. For their benefit in CI, use a persistent builder (a remote BuildKit instance or a Kubernetes driver) or a CI-specific cache action.

**Multi-platform builds:**

```bash
docker buildx create --name multi --use        # docker-container driver
docker buildx build --platform linux/amd64,linux/arm64 \
  -t registry.example.com/myapp:1.4.0 --push .
docker buildx imagetools inspect registry.example.com/myapp:1.4.0   # shows the index + per-arch manifests
```

| Approach | How | Speed | Use when |
|---|---|---|---|
| **QEMU emulation** | binfmt_misc runs arm64 binaries on amd64 | Slow for compilation | Simple images, mostly `COPY` + package installs |
| **Cross-compilation** | Builder stage runs on `$BUILDPLATFORM` and targets `$TARGETOS/$TARGETARCH` | Native speed | Go, Rust, Java and other toolchains that cross-compile easily |
| **Native nodes** | `buildx create --append` an arm64 builder. BuildKit routes each platform to a matching node. | Native speed | Heavy native builds (C extensions), or anything that won't cross-compile |

```dockerfile
FROM --platform=$BUILDPLATFORM golang:1.26 AS build
ARG TARGETOS TARGETARCH
WORKDIR /src
COPY . .
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -o /out/server .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/server /server
ENTRYPOINT ["/server"]
```

**Reproducibility:** pin base images **by digest** (`FROM python:3.13-slim@sha256:...`) and let a bot (Renovate/Dependabot) bump them. Otherwise "the same commit" builds a different image next week. `SOURCE_DATE_EPOCH` and `rewrite-timestamp=true` on the output make layers byte-for-byte reproducible.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **BuildKit model** | DAG, parallel stages, cache vs secret vs ssh mounts |
| **CI caching** | Registry/GHA cache export, min vs max, cache mounts aren't exported |
| **Multi-arch** | Manifest lists; emulation vs cross-compile vs native builders, and when each fits |
| **Reproducibility** | Digest pinning with automated bumps |

**What they probe next:** "A multi-arch image works on amd64 but crashes on arm64?" A native dependency was built for the wrong architecture, or a base image lacks that platform. Check with `imagetools inspect` and test both architectures in CI.

---

## 4. Supply-Chain Security: SBOM, Provenance, Signing & Scanning

**Q:** "After a dependency compromise in the industry, security asks: how do we know what's in our images, who built them, and that production only runs images we built? Design the pipeline."

**What They're Really Testing:** Whether you can turn SBOMs, provenance, signatures and admission policy into a coherent chain of trust, not just "we run a scanner".

!!! tip "30-second answer"
    Build in CI from a pinned base, generating an **SBOM** (what's inside) and **SLSA provenance** (which source, builder and parameters produced it) as attestations attached to the image. **Sign the image digest** with cosign, ideally keyless: CI's OIDC identity gets a short-lived certificate from Fulcio, and the signature is recorded in the Rekor transparency log. **Scan** the SBOM continuously, not just at build time, because new CVEs appear for old images. Enforce at deploy time with an admission controller (Kyverno, Sigstore policy-controller) that only admits images **by digest**, signed by your CI identity, with acceptable provenance.

### Answer

**Pipeline:**

```
source (signed commits, reviewed PRs)
   │
   ▼
CI build (ephemeral, isolated runner, pinned base digests)
   │  docker buildx build --sbom=true --provenance=mode=max --push -t reg/app:${SHA} .
   │    → image + attestations (SPDX SBOM, SLSA provenance) stored alongside it in the registry
   ▼
sign by digest:   cosign sign reg/app@sha256:...        (keyless: OIDC → Fulcio cert → Rekor log)
   ▼
scan:             Trivy / Grype / Docker Scout against the SBOM. Fail on fixable criticals.
                  Use VEX statements to suppress CVEs that aren't exploitable in context.
   ▼
deploy:           admission policy checks signature identity + provenance + "no :latest, digest only"
   ▼
runtime:          rescan deployed digests daily. Alert when a new CVE affects a running image.
```

**Verification example:**

```bash
cosign verify reg/app@sha256:abc... \
  --certificate-identity-regexp '^https://github.com/acme/app/.github/workflows/release.yml@refs/tags/v' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com

docker buildx imagetools inspect reg/app@sha256:abc... --format '{{ json .Provenance }}'
```

**Key concepts:**

| Concept | What it answers | Notes |
|---|---|---|
| **Digest** (`@sha256:`) | "Exactly which bytes?" | Tags are mutable. Sign and deploy digests. |
| **SBOM** (SPDX / CycloneDX) | "What's inside?" | Lets you answer "are we affected by CVE-X?" in minutes |
| **Provenance** (SLSA) | "Who built it, from what?" | Build-level attestation. SLSA Build L3 requires a hardened, isolated builder. |
| **Signature** (cosign / Notation) | "Did our pipeline produce it?" | Keyless signing avoids long-lived keys. The identity is the CI workflow. |
| **Transparency log** (Rekor) | "Can a signature be quietly backdated or forged?" | Public, append-only, auditable |
| **Admission policy** | "Can anything else run?" | Without enforcement, signatures are decoration |

**Base image hygiene:** start from minimal bases that ship their own SBOM and provenance (distroless, Docker Hardened Images, Chainguard). Rebuild on a schedule even when the code hasn't changed, so base-layer CVE fixes land. Fewer packages means fewer CVEs to triage.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Chain of trust** | Source → build → attest → sign → verify at admission. Each step justified. |
| **Digest discipline** | Deploys by digest, knows tags are mutable |
| **Keyless signing** | OIDC identity, Fulcio, Rekor, and verifying the *identity*, not just "is signed" |
| **Continuous scanning** | Rescans running images, uses VEX to cut noise |

**What they probe next:** "A critical CVE drops in a base image: how fast can you know your exposure?" Query SBOMs across deployed digests. "What doesn't this protect against?" A malicious dependency at a pinned version, and a compromised CI workflow. Mitigate with review, dependency pinning plus provenance checks, and least-privilege CI tokens.

---

## 5. Resource Limits: Memory, CPU Throttling & Runtime Awareness

**Q:** "A Java service in a container with `--memory=2g --cpus=2` is OOM-killed intermittently, and p99 latency spikes even though average CPU is 40%. Explain both."

**What They're Really Testing:** Whether you understand how cgroup memory limits and CFS bandwidth control actually behave, and whether language runtimes size themselves correctly inside containers.

!!! tip "30-second answer"
    **OOM:** `memory.max` covers *everything* the cgroup charges: JVM heap plus metaspace, thread stacks, direct buffers, JIT code, glibc arenas, tmpfs files and unreclaimable page cache. Exceeding it makes the kernel OOM-kill a process in the cgroup (exit 137, `OOMKilled=true`). Size the heap at around 60-75% of the limit (`-XX:MaxRAMPercentage`) and leave the rest as headroom. **Latency:** `--cpus=2` is a quota of 200 ms CPU per 100 ms period. A burst of many threads (GC, request fan-out) uses the quota early in the period, then the whole cgroup is **throttled** until the next period. That's invisible in average CPU and visible as p99 spikes. Check `cpu.stat` `nr_throttled`, and size threads to the quota or raise or remove the limit.

### Answer

**Memory:**

```
--memory=2g            → memory.max = 2 GiB   (exceed → OOM kill inside the cgroup)
--memory-reservation   → soft target used under host memory pressure
--memory-swap          → memory + swap total (= --memory means no swap)

Counted: anonymous memory (heap, native allocations), kernel memory for the cgroup,
         tmpfs/shm, page cache (reclaimable, so reclaimed before OOM, but dirty or
         mmapped-in-use pages can't always be dropped quickly)
Signals: memory.events (high, max, oom_kill), memory.pressure (PSI) gives early warning
```

**Runtime awareness:**

| Runtime | Container-aware? | What to set |
|---|---|---|
| **JVM** (JDK 10+, 8u191+) | Reads cgroup v1/v2 limits. The default max heap is **25%** of the limit, which is often too small. | `-XX:MaxRAMPercentage=70`, cap direct memory, and watch native memory (`-XX:NativeMemoryTracking=summary`) |
| **Go** | `GOMAXPROCS` respects the cgroup CPU limit since **Go 1.25**. Older versions use the host core count. | Set `GOMEMLIMIT` to around 90% of the memory limit so the GC works harder before the OOM killer acts |
| **Node.js** | Heap limit is derived from available memory in recent versions. Libuv threadpool fixed at 4. | `--max-old-space-size` explicitly, below the limit |
| **Python** | `os.cpu_count()` returns **host** cores | Set worker counts (gunicorn, multiprocessing pools) explicitly from the CPU limit |

**CPU:**

```
--cpus=2         → cpu.max = "200000 100000"  (quota/period): HARD cap, enforced every 100 ms
--cpu-shares     → cpu.weight: relative share, only matters under contention
--cpuset-cpus    → pin to specific cores (latency-critical, NUMA)

Throttling example: --cpus=2, the app runs 16 busy threads for a burst
  → 16 threads × 12.5 ms = 200 ms of quota used 12.5 ms into the period
  → the cgroup is frozen for the remaining 87.5 ms → request latency +87.5 ms
Diagnose: cat /sys/fs/cgroup/.../cpu.stat → nr_periods, nr_throttled, throttled_usec
```

Fixes: match thread pools and `GOMAXPROCS` to the quota. Raise the limit. Use `cpu.max.burst` (kernel 5.14+) to allow short bursts. On Kubernetes, many teams set CPU **requests** (for scheduling and weight) but no CPU **limit** for latency-sensitive services. Memory limits stay, because memory isn't compressible.

**Other limits:** `--pids-limit` (fork bombs, thread leaks), `--ulimit nofile=...`, and `--device-read-bps`/`io.max` (disk-heavy neighbours). `io.max` throttling of buffered writes only works on cgroup v2.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Memory accounting** | Knows the limit covers more than the heap, and exit 137 / `OOMKilled` |
| **CFS throttling** | Explains quota/period and why averages hide it. Uses `cpu.stat`. |
| **Runtime awareness** | JVM percentage flags, Go 1.25 `GOMAXPROCS` + `GOMEMLIMIT`, Python's host core count |
| **Policy** | Limits vs requests trade-off for latency-sensitive services |

**What they probe next:** "Container killed but `OOMKilled=false`?" Either the app exited on its own after SIGTERM, or the **host** OOM killer chose it because the node ran out of memory, not the cgroup. Check `dmesg`/journal. "Is page cache why my memory graph is near the limit?" Possibly. Look at `memory.stat` (anon vs file) before panicking.

---

## 6. Container Networking

**Q:** "Explain how traffic reaches a container on `-p 8080:80`. Why can two containers on the default bridge not resolve each other by name? When would you use host networking, and what's the security catch with published ports?"

**What They're Really Testing:** Whether you can trace packets through veth pairs, bridges, NAT and DNS, and know the classic pitfalls.

!!! tip "30-second answer"
    Each container gets a network namespace with an `eth0` that's one end of a **veth pair**, the other end plugged into a Linux **bridge** (`docker0` or a user-defined bridge). Outbound traffic is masqueraded (SNAT) to the host IP. `-p 8080:80` adds a **DNAT** rule (iptables or nftables), so host:8080 → container:80. Only **user-defined** networks get Docker's embedded DNS (`127.0.0.11`) for name resolution. The default bridge doesn't, for legacy reasons. Host networking removes the NAT hop and the isolation. The catch: published ports bind to **all interfaces** by default and Docker's rules are evaluated before host firewalls like UFW, so "firewalled" ports can be exposed to the internet.

### Answer

```
Inbound to -p 8080:80
  client → host eth0:8080
         → nat PREROUTING: DOCKER chain DNAT → 172.18.0.5:80
         → FORWARD (DOCKER-USER chain first: put your own filtering here)
         → bridge br-xxxx → vethA ⇄ container eth0:80
  (docker-proxy, a userland proxy, handles localhost→published-port and hairpin cases)

Outbound from the container
  container eth0 → veth → bridge → host routing → nat POSTROUTING MASQUERADE → internet
```

| Driver | What it is | Use for |
|---|---|---|
| **bridge** (user-defined) | Private L2 network on one host, embedded DNS, isolation between networks | Default choice for single-host apps / Compose |
| **default bridge** (`docker0`) | Same, but **no automatic DNS** between containers (only legacy `--link`) | Avoid |
| **host** | Shares the host network namespace. No NAT, no port mapping. | Max throughput / lowest latency, many ports. Loses isolation and risks port clashes. |
| **none** | Loopback only | Batch jobs with no network |
| **macvlan / ipvlan** | Container gets its own IP on the physical LAN | Legacy apps that need L2 presence |
| **overlay** | VXLAN across hosts (Swarm) | Multi-host without Kubernetes. Kubernetes uses CNI plugins instead. |

**Pitfalls:**

- `-p 8080:80` means `0.0.0.0:8080` (and `[::]`). For local-only services use `-p 127.0.0.1:8080:80`.
- Docker inserts its iptables rules ahead of UFW/firewalld rules, so a published port bypasses them. Filter in the `DOCKER-USER` chain, or don't publish. Engine 28 tightened default isolation so **unpublished** container ports are no longer reachable from other hosts on the LAN.
- DNS: containers inherit the host's resolv.conf (filtered). Alpine's musl resolver behaves differently (search domains, TCP fallback), a frequent source of "works on Debian, fails on Alpine".
- MTU mismatches (VPNs, overlay/VXLAN overhead) cause hangs on large packets only. Set the network MTU explicitly.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Packet path** | veth + bridge + DNAT/MASQUERADE, can debug with `nsenter`/`tcpdump` |
| **DNS** | Embedded DNS on user-defined networks only |
| **Driver choice** | bridge vs host vs macvlan vs overlay trade-offs |
| **Security** | Published ports bind all interfaces and bypass UFW. `DOCKER-USER`. |

**What they probe next:** "How does Kubernetes differ?" No NAT between pods (a flat pod network via CNI). Services are implemented by kube-proxy (iptables/IPVS/nftables) or eBPF (Cilium). "Debug a container that can't reach the DB?" Check DNS resolution, then routing, then MTU, then security groups or NetworkPolicy, from inside the namespace (`nsenter -t <pid> -n`).

---

## 7. Runtime Hardening & Rootless Containers

**Q:** "A security review says our containers 'run as root'. What does that actually mean, how bad is it, and how do you harden containers at runtime? What does rootless Docker change?"

**What They're Really Testing:** Whether you understand the layers of container confinement and the real difference between root-in-container, rootless and user-namespaced runtimes.

!!! tip "30-second answer"
    In rootful Docker without user namespaces, UID 0 in the container **is** UID 0 on the host, restricted only by dropped capabilities, seccomp and AppArmor/SELinux. A kernel bug or a careless mount (`/var/run/docker.sock`, `--privileged`, host paths) turns that into host root. Harden in layers: run as a **non-root user**, **drop all capabilities** and add back only what's needed, set `no-new-privileges`, use a **read-only root filesystem**, keep the default seccomp profile, and never mount the Docker socket. **Rootless** Docker or Podman runs the daemon and containers as an unprivileged host user via user namespaces, so even a breakout lands as a normal user.

### Answer

```bash
docker run \
  --user 10001:10001 \
  --cap-drop ALL --cap-add NET_BIND_SERVICE \
  --security-opt no-new-privileges \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --pids-limit 256 --memory 512m --cpus 1 \
  myapp@sha256:...
```

| Control | Blocks | Notes |
|---|---|---|
| Non-root `USER` | Most file-permission based escalation | Set it in the Dockerfile so it's the default |
| Capabilities (`--cap-drop ALL`) | `CAP_SYS_ADMIN` (mount etc.), `CAP_NET_RAW`, ... | Docker's default set is already reduced. `--privileged` gives everything **and** all devices. |
| `no-new-privileges` | setuid binaries regaining privileges | Cheap, almost always safe |
| seccomp (default profile) | ~40+ dangerous syscalls (`keyctl`, `bpf`, `mount` without caps, ...) | `seccomp=unconfined` is a red flag |
| AppArmor / SELinux | File and capability access by policy | Default profiles applied automatically when the host supports them |
| Read-only rootfs | Malware persistence, tampering | Use volumes/tmpfs for writable paths |
| User namespaces | Container root → unprivileged host UID | `--userns-remap` (rootful) or rootless mode |

**Rootless Docker:** `dockerd` itself runs as a normal user (setup via `dockerd-rootless-setuptool.sh`), with RootlessKit and user namespaces.

- **Gains:** a daemon or container compromise doesn't give host root.
- **Limits:** binding ports below 1024 needs a sysctl or capability. Networking goes through a user-space stack (slirp4netns/pasta) with some throughput cost. Resource limits need cgroup v2 with delegation. Some storage drivers and features are unavailable.
- **Alternatives:** Podman is rootless and daemonless by default. Kubernetes supports user namespaces for pods (`hostUsers: false`, beta and on by default in recent releases).

**Mounting `/var/run/docker.sock`** into a container (CI agents, monitoring tools) gives that container full control of the daemon, which is host root in rootful Docker. Use rootless BuildKit, Kaniko-style builders, or a socket proxy with an allowlist instead.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Threat model** | Root-in-container = host root without userns. The shared kernel is the boundary. |
| **Layered controls** | Non-root, capabilities, no-new-privileges, seccomp, LSM, read-only rootfs |
| **Rootless** | What it changes and its operational limits |
| **Red flags** | `--privileged`, docker.sock mounts, host PID/network, `seccomp=unconfined` |

**What they probe next:** "When do you need gVisor or Kata?" Running untrusted or multi-tenant code where a kernel exploit is in your threat model. "How do you enforce this fleet-wide?" Pod Security Admission (`restricted` profile) or Kyverno/OPA policies in Kubernetes. Image linting in CI.

---

## 8. PID 1, Signals & Graceful Shutdown

**Q:** "During deploys, our containers take 10 seconds to stop and drop in-flight requests. Sometimes we also see zombie processes accumulating. What's going on?"

**What They're Really Testing:** Whether you know PID 1's special signal semantics, shell vs exec form, and how a stop sequence works.

!!! tip "30-second answer"
    `docker stop` sends **SIGTERM**, waits (10 s by default), then sends **SIGKILL**. If the app is PID 1 and hasn't installed a SIGTERM handler, the kernel **ignores** the signal, because PID 1 gets no default signal actions. If the Dockerfile uses **shell form** (`CMD python app.py`), PID 1 is `/bin/sh`, which doesn't forward SIGTERM to the app. Either way the app is SIGKILLed mid-request after 10 s. PID 1 must also **reap zombies**. Fix: use exec form (`CMD ["python", "app.py"]`), handle SIGTERM (stop accepting, drain, exit), and add a tiny init (`docker run --init` / tini) if the app spawns children.

### Answer

```dockerfile
# Bad: shell form. PID 1 = /bin/sh -c, SIGTERM never reaches python.
CMD python -m app.main

# Good: exec form. python is PID 1 and gets SIGTERM.
CMD ["python", "-m", "app.main"]

# Entrypoint scripts must `exec` the final process so it replaces the shell:
#   #!/bin/sh
#   ./render-config.sh
#   exec "$@"
```

**Graceful shutdown sequence the app should implement:**

1. On SIGTERM, mark itself not ready, so the load balancer or Kubernetes readiness check stops sending traffic.
2. Stop accepting new connections and let in-flight requests finish (with a deadline shorter than the stop timeout).
3. Flush buffers and commit offsets, then close DB pools.
4. Exit 0.

Set `--stop-timeout` / `stop_grace_period` (Compose) / `terminationGracePeriodSeconds` (Kubernetes) to cover the drain. In Kubernetes, add a short `preStop` sleep, because endpoint removal propagates asynchronously and traffic can still arrive for a few seconds after SIGTERM. `STOPSIGNAL` in the Dockerfile changes the signal for apps that expect a different one (e.g. `SIGQUIT` for nginx graceful shutdown).

**Zombies:** a child that exits stays a zombie until its parent `wait()`s. Orphans are re-parented to PID 1 of the namespace. An app that isn't written as an init never reaps them, so the PID table fills (`pids.max`). `--init` injects tini as PID 1, which forwards signals and reaps.

**Exit codes to know:** 137 = 128+9 (SIGKILL: OOM or stop timeout), 143 = 128+15 (SIGTERM, handled by exiting), 139 = SIGSEGV.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **PID 1 semantics** | No default signal actions, zombie reaping |
| **Shell vs exec form** | And `exec "$@"` in entrypoint scripts |
| **Drain sequence** | Readiness → stop accepting → drain → exit within the grace period |
| **Exit codes** | Reads 137/143 correctly when debugging |

**What they probe next:** "Compose for local dev, what's changed?" `docker compose` (v2 plugin), `depends_on` with `condition: service_healthy`, `develop.watch` for live sync, profiles for optional services, and the obsolete `version:` key.

---

> *These 8 questions cover Docker from kernel primitives to production builds, supply chain, limits, networking and hardening. For orchestration, see [`../kubernetes/INTERVIEW_QUESTIONS.md`](../kubernetes/INTERVIEW_QUESTIONS.md).*
