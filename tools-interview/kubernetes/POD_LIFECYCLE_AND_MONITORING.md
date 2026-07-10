# 🐳 Pod Lifecycle, Monitoring & Observability — Staff-Level Deep Dive

> *Deep-dive into Kubernetes pod internals, lifecycle management, production monitoring, and observability — every section expects principal engineer-level depth with production incident experience.*

> **Prerequisites:** This file builds on the foundational Kubernetes content in [`INTERVIEW_QUESTIONS.md`](./INTERVIEW_QUESTIONS.md) (scheduler, networking, RBAC, storage, controllers) and Docker fundamentals in [`../docker/INTERVIEW_QUESTIONS.md`](../docker/INTERVIEW_QUESTIONS.md) (container runtime, namespaces, cgroups, images). The companion file [`PRODUCTION_CONTROL.md`](./PRODUCTION_CONTROL.md) covers GitOps, admission controllers, deployment strategies, and service mesh.
>
> **Docker monitoring** (dockerd metrics, `docker stats`, Docker events, container health) is covered in the Docker-specific sections of [`../docker/INTERVIEW_QUESTIONS.md`](../docker/INTERVIEW_QUESTIONS.md) Q1 and Q2.

---

## Table of Contents

1. [Pod Lifecycle: Phase, Conditions & Container States](#1-pod-lifecycle-phase-conditions--container-states)
2. [Init Containers, Sidecars & Ephemeral Containers](#2-init-containers-sidecars--ephemeral-containers)
3. [Probes: Startup, Readiness & Liveness in Production](#3-probes-startup-readiness--liveness-in-production)
4. [Pod QoS Classes & Resource Management](#4-pod-qos-classes--resource-management)
5. [Pod Priority, Preemption & Disruption Budgets](#5-pod-priority-preemption--disruption-budgets)
6. [Pod Security: Standards, Contexts & Admission](#6-pod-security-standards-contexts--admission)
7. [Kubernete Monitoring Stack: kubelet, cAdvisor, Metrics Server](#7-kubernetes-monitoring-stack-kubelet-cadvisor-metrics-server)
8. [kube-state-metrics & Node Exporter](#8-kube-state-metrics--node-exporter)
9. [Prometheus Operator: ServiceMonitor, PodMonitor & Rules](#9-prometheus-operator-servicemonitor-podmonitor--rules)
10. [Custom Metrics, KEDA & Event-Driven Autoscaling](#10-custom-metrics-keda--event-driven-autoscaling)
11. [Pod Logging: Fluentd, Loki, Structured Logging](#11-pod-logging-fluentd-loki-structured-logging)
12. [Kubernetes Events & Audit Logs](#12-kubernetes-events--audit-logs)
13. [Grafana Dashboards for Kubernetes](#13-grafana-dashboards-for-kubernetes)
14. [Pod Alerting Rules & Runbooks](#14-pod-alerting-rules--runbooks)
15. [eBPF Observability: Cilium Hubble & Pixie](#15-ebpf-observability-cilium-hubble--pixie)

---

## 1. Pod Lifecycle: Phase, Conditions & Container States

**Q:** "A pod is stuck in `Pending` for 10 minutes. Walk through every possible reason and how to diagnose each one. Then explain the full state machine: pod phases, pod conditions, and container states."

**What They're Really Testing:** Whether you understand the complete Kubernetes pod state machine — the difference between pod-level and container-level state, and can systematically debug any pod lifecycle issue.

### Answer

**Pod Phases (High-Level Lifecycle):**

```
           ┌──────────┐
           │  Pending  │ ◄── Pod accepted, but not all containers running
           └────┬─────┘
                │
                ▼
           ┌──────────┐
    ┌──────│ Running  │◄────── All containers running (at least one)
    │      └────┬─────┘
    │           │
    │      ┌────▼─────┐
    │      │ Succeeded│◄────── All containers terminated with exit 0
    │      └──────────┘
    │
    │      ┌──────────┐
    └─────►│  Failed  │◄────── At least one container terminated with non-zero exit
           └──────────┘

           ┌──────────┐
           │ Unknown  │◄────── Node communication lost
           └──────────┘
```

**Pod Conditions (Detailed Status):**

```yaml
# Conditions are individual status signals, each with True/False/Unknown
# A pod can have multiple conditions simultaneously

conditions:
  - type: PodScheduled          # Has the pod been scheduled to a node?
    status: True
    lastTransitionTime: ...
    reason: SuccessAssigned
    message: "Pod assigned to node ip-10-0-1-42"

  - type: Initialized           # Have all init containers completed?
    status: True
    reason: Completed
    message: "Init containers completed successfully"

  - type: ContainersReady       # Are all containers ready?
    status: True                # If False → readiness probe failing
    reason: ReadinessProbeFailed
    message: "Readiness probe failed: HTTP probe failed with statuscode: 503"

  - type: Ready                 # Is the pod ready to serve traffic?
    status: True
    reason: MinimumReplicasAvailable
```

**Container States (Inside Each Container):**

```
                    ┌──────────┐
                    │  Waiting │ ◄── Container starting, pulling image, waiting
                    └────┬─────┘
                         │
                    ┌────▼─────┐
             ┌──────│ Running  │ ◄── Container executing
             │      └────┬─────┘
             │           │
             │      ┌────▼─────┐
             └─────►│Terminated│ ◄── Container stopped (exit code)
                    └──────────┘
```

**Common Waiting Reasons:**

| Reason | Meaning | Diagnosis |
|--------|---------|-----------|
| `ContainerCreating` | Container is being created (image pull, volume mount) | Check image pull status, PVC binding |
| `PodInitializing` | Init containers running | `kubectl logs <pod> -c <init-container>` |
| `ImagePullBackOff` | Image pull failed (backing off) | Check image name, registry credentials, network |
| `ErrImagePull` | Image pull failed (initial attempt) | `kubectl describe pod <pod>` for events |
| `CrashLoopBackOff` | Container starts and crashes repeatedly | Check logs, exit codes, resource limits |
| `CreateContainerError` | Container creation failed | Check volume mounts, security context |
| `InvalidImageName` | Image name is invalid | Check image:tag syntax |

**CrashLoopBackOff Deep Dive:**

```bash
# Diagnosis commands
kubectl get pods -o wide                    # Check node and pod IP
kubectl describe pod <pod>                  # Events, conditions, container states
kubectl logs <pod> -c <container> --previous # Logs from the PREVIOUS (crashed) instance
kubectl logs <pod> --all-containers         # Logs from all containers

# CrashLoopBackOff backoff progression:
# 0s → 10s → 20s → 40s → 80s → 160s → 300s (capped at 5 min)
# Resets after 10 minutes of stability

# Common causes:
# 1. OOMKilled: container exceeded memory limit
#    → kubectl describe pod | grep -A5 "State:"
#    Check: Last State: Terminated / Reason: OOMKilled / Exit Code: 137
#
# 2. Missing config: configmap or secret not mounted
#    → Container can't read configuration → panics → crashes
#    Check: env vars, volume mounts in describe output
#
# 3. Port conflict: container tries to bind port already in use
#    → Exit code: 1 or 125
#
# 4. Liveness probe failure: probe fails → kubelet restarts container
#    → Check liveness probe configuration
#
# 5. Init container failure: init container exits with error
#    → Pod stays in Init:CrashLoopBackOff (different from container crash)
```

**`kubectl get pods` Output Decoded:**

```bash
NAME                          READY   STATUS             RESTARTS   AGE
my-app-7d4f8b9c6-abc12       1/1     Running            0          2d
my-app-7d4f8b9c6-def34       0/1     CrashLoopBackOff   3          5m
my-app-7d4f8b9c6-ghi56       0/1     Init:0/2           0          30s
my-app-7d4f8b9c6-jkl78       0/1     Pending            0          10m

# READY: 0/1 → Container not ready (probe failing or not yet started)
# RESTARTS: 3 → Container has been restarted 3 times
# STATUS: Init:0/2 → 2 init containers, 0 completed
# STATUS: Pending → Not yet scheduled (check events)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Phase vs Condition** | Understands phases are aggregate state, conditions are specific signals |
| **Container state machine** | Can trace Waiting → Running → Terminated with reasons |
| **CrashLoopBackOff** | Knows backoff progression and can diagnose by exit code |
| **Systematic debugging** | Uses `kubectl describe`, `logs --previous`, and exit codes in order |

---

## 2. Init Containers, Sidecars & Ephemeral Containers

**Q:** "Design a pod that needs to (a) wait for a database to be ready, (b) run a schema migration, (c) start the main application, and (d) have a logging sidecar. How do init containers, sidecar containers, and ephemeral containers each serve different purposes?"

**What They're Really Testing:** Whether you understand the three container types in a pod — init containers (run-to-completion before main), sidecars (long-running alongside main), and ephemeral containers (injected at runtime for debugging).

### Answer

**Init Containers:**

```yaml
# Init containers run sequentially, each must complete successfully
# before the next one starts. All must complete before main containers start.

apiVersion: v1
kind: Pod
metadata:
  name: my-app-with-init
spec:
  initContainers:
  - name: wait-for-db                    # Run first
    image: busybox:1.36
    command: ['sh', '-c', '
      until nc -z db-service 5432; do
        echo "Waiting for database...";
        sleep 2;
      done;
      echo "Database is ready!";
    ']

  - name: run-migrations                 # Run second (after db is ready)
    image: my-app-migrations:v1.2.3
    env:
    - name: DATABASE_URL
      valueFrom:
        secretKeyRef:
          name: db-secret
          key: url
    # If migration fails → pod fails → Deployment controller recreates

  containers:
  - name: main-app                       # Runs after both init containers succeed
    image: my-app:v1.2.3
    ports:
    - containerPort: 8080

# Key behaviors:
# - Init containers can have different images and resource requests than main
# - Init containers can access secrets that main containers shouldn't (principle of least privilege)
# - Pod restarts if any init container fails (backoff applies)
# - Init containers with restartPolicy: Always are native sidecars (K8s 1.29+)
```

**Init Container Use Cases:**

```yaml
# 1. Wait for dependencies (database, cache, service mesh)
# 2. Run schema migrations
# 3. Generate configuration files from templates
# 4. Pre-populate shared volumes (emptyDir)
# 5. Check license keys or security policies
# 6. Download model files for ML inference

# Resource considerations:
# - Init containers share pod-level resource requests/limits
# - Highest init container resource request defines pod scheduling req
# - Main container resources don't count until init is done
```

**Native Sidecar Containers (Kubernetes 1.29+):**

```yaml
# Sidecar containers run alongside main containers (not before)
# Key: restartPolicy: Always in initContainers

apiVersion: v1
kind: Pod
metadata:
  name: app-with-sidecar
spec:
  initContainers:
  - name: logging-sidecar                # Sidecar (runs alongside)
    image: fluent-bit:2.1
    restartPolicy: Always                # ← This makes it a sidecar!
    volumeMounts:
    - name: logs
      mountPath: /var/log/app

  - name: wait-for-db                    # True init (runs first)
    image: busybox:1.36
    command: ['sh', '-c', 'until nc -z db:5432; do sleep 2; done']

  containers:
  - name: main-app
    image: my-app:v1.2.3
    volumeMounts:
    - name: logs
      mountPath: /var/log/app

# Sidecar vs Regular initContainers:
# - Sidecar uses restartPolicy: Always → survives if it crashes
# - Regular init containers stop on failure → pod restarts from first init
# - Sidecars start in order but don't block next init from starting
# - Sidecars stop AFTER all main containers (graceful shutdown)

# Traditional sidecar pattern (pre-1.29):
# - Sidecar as a regular container (runs in parallel with main)
# - No lifecycle ordering guarantees
# - Must manually handle restart via liveness probe
```

**Ephemeral Containers (Debugging):**

```bash
# Ephemeral containers are TEMPORARY — injected into RUNNING pods
# No resource requests, no ports, no restart policy
# Perfect for debugging without modifying the pod spec

# Debug a running pod:
kubectl debug my-app-7d4f8b9c6-abc12 \
  --image=nicolaka/netshoot:latest \
  --target=main-app          # Attach to the same namespace/network as main-app

# Debug a node (creates a pod on the node):
kubectl debug node/ip-10-0-1-42 \
  --image=ubuntu:22.04

# Copy mode: create a copy of the pod with debug tools
kubectl debug my-app-7d4f8b9c6-abc12 \
  --copy-to=my-app-debug \
  --container=main-app \
  --set-args=--debug=true

# Common ephemeral container uses:
# - Check network connectivity (dnsutils, netshoot)
# - Inspect filesystem without exec access
# - Run tcpdump for network troubleshooting
# - Profile container resource usage
# - Debug volume mount permissions
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Init containers** | Knows sequential execution, failure restarts from scratch, resource behavior |
| **Sidecar patterns** | Understands native sidecars (1.29+) vs traditional sidecar-as-regular-container |
| **Ephemeral containers** | Knows `kubectl debug` for non-invasive troubleshooting |
| **Use case distinction** | Can articulate when to use each: init for setup, sidecar for support, ephemeral for debug |

---

## 3. Probes: Startup, Readiness & Liveness in Production

**Q:** "Your deployment has 10 replicas, but during a rolling update, traffic is routed to pods before they're ready — causing 502 errors for 15 seconds. How do you fix this? Design a probe strategy for a JVM application that takes 90 seconds to warm up, has occasional GC pauses, and should be restarted if it deadlocks."

**What They're Really Testing:** Whether you understand the three probe types and their distinct roles — startup (slow boot), readiness (traffic routing), and liveness (self-healing) — and can design a probe strategy for real application behaviors.

### Answer

**Three Probe Types:**

```yaml
# STARTUP PROBE: "Is the application ready to start being checked?"
# Purpose: Prevent readiness/liveness from killing slow-starting containers
# Runs: Only during initial startup, stops after first success

# READINESS PROBE: "Should this pod receive traffic?"
# Purpose: Control Service endpoints, only when ready
# Runs: Continuously throughout pod lifetime
# Failure: Pod removed from Service endpoints (no traffic)

# LIVENESS PROBE: "Should this container be killed and restarted?"
# Purpose: Detect deadlocks, infinite loops, unrecoverable states
# Runs: Continuously throughout pod lifetime
# Failure: Container killed and restarted by kubelet
```

**JVM Application Probe Strategy (90s Warmup):**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: java-app
spec:
  containers:
  - name: java-app
    image: java-app:1.0.0
    ports:
    - containerPort: 8080

    # STARTUP PROBE: 90s JVM warmup
    # - Prevents readiness/liveness from triggering during slow startup
    # - Succeeds once (not retried after first success)
    startupProbe:
      httpGet:
        path: /health/startup
        port: 8080
      initialDelaySeconds: 5     # Wait 5s before first probe
      periodSeconds: 5           # Probe every 5 seconds
      failureThreshold: 30       # 30 × 5s = 150s max startup time
      # After startup succeeds: startup probe STOPS,
      # readiness and liveness begin

    # READINESS PROBE: Traffic routing
    # - Returns 200 only when app is ready to serve
    # - During GC pause: might fail (remove from Service temporarily)
    readinessProbe:
      httpGet:
        path: /health/ready
        port: 8080
      initialDelaySeconds: 0     # Startup probe handles initial delay
      periodSeconds: 10          # Check every 10 seconds
      timeoutSeconds: 3          # 3s timeout per probe
      successThreshold: 1        # 1 success = ready
      failureThreshold: 3        # 3 failures = not ready (30s)

    # LIVENESS PROBE: Self-healing
    # - Detects deadlocks (thread dump shows no progress)
    # - Does NOT check dependencies (use readiness for that!)
    livenessProbe:
      httpGet:
        path: /health/live
        port: 8080
      periodSeconds: 30          # Check less frequently (don't add load)
      timeoutSeconds: 5
      failureThreshold: 3        # 3 × 30s = 90s of failure → restart
      # If app deadlocks, liveness fails → pod killed → recreated
```

**Probe Implementation (Python/Flask Example):**

```python
# /health/startup - Returns 200 when JVM/application is initialized
# /health/ready   - Returns 200 only when serving traffic
# /health/live    - Always returns 200 (unless deadlocked)

@app.route('/health/startup')
def health_startup():
    """Startup probe: returns success only after initialization.
    Used to prevent readiness/liveness from triggering during boot."""
    if not app.initialized:
        return jsonify({"status": "starting"}), 503
    return jsonify({"status": "ok"}), 200


@app.route('/health/ready')
def health_ready():
    """Readiness probe: checks if this pod should receive traffic.
    Failures mean the pod is removed from Service endpoints."""
    checks = {
        "database": check_database_connectivity(),
        "cache": check_cache_connectivity(),
        "queue_depth": get_queue_depth(),
    }

    # Critical dependency failure → not ready
    if not checks["database"]:
        return jsonify({
            "status": "not ready",
            "checks": checks
        }), 503

    # Queue too deep → stop accepting traffic
    if checks["queue_depth"] > 1000:
        return jsonify({
            "status": "backpressure",
            "checks": checks
        }), 503

    return jsonify({"status": "ready", "checks": checks}), 200


@app.route('/health/live')
def health_live():
    """Liveness probe: is the application process healthy?
    Should only check if the process is alive, NOT dependencies.
    Dependency failures should NOT restart the pod - they should
    remove it from traffic (readiness)."""
    if not is_thread_alive():
        return jsonify({"status": "deadlocked"}), 500

    return jsonify({"status": "alive"}), 200
```

**Probe Anti-Patterns:**

```yaml
# 🔴 ANTI-PATTERN 1: Liveness probe checks external dependencies
livenessProbe:
  httpGet:
    path: /health/dependencies   # ← BAD!
# If database is down, liveness fails → pod restarts
# But restarting won't fix the database!
# ALL pods restart → cascading failure
# ✅ Fix: Use readiness for dependencies, liveness for process health

# 🔴 ANTI-PATTERN 2: Readiness probe same as liveness probe
# Using same endpoint for both:
# If app is slow: readiness fails (removed from traffic) → OK
# But if app is slow: liveness also fails → pod restarted → BAD!
# Slow doesn't mean dead → don't restart!
# ✅ Fix: Liveness = process alive, Readiness = dependencies available

# 🔴 ANTI-PATTERN 3: No startup probe for slow apps
startupProbe: (missing)
readinessProbe:
  initialDelaySeconds: 5
  failureThreshold: 30
# Without startup probe, readiness counts failures from the start
# App takes 90s to start → readiness fails for 90s → pod eventually restarts
# ✅ Fix: Add startup probe with long failureThreshold

# 🔴 ANTI-PATTERN 4: Too aggressive liveness
livenessProbe:
  periodSeconds: 2      # Too frequent!
  failureThreshold: 1   # Too sensitive!
# Every GC pause, every slow request triggers restart
# ✅ Fix: 30s period, 3 failure threshold

# 🔴 ANTI-PATTERN 5: Not setting timeoutSeconds
# Default timeout is 1 second — too short for many apps
# ✅ Fix: Set timeoutSeconds to 3-5 seconds
```

**Probe Recommendation by Application Type:**

| App Type | Startup | Readiness | Liveness |
|----------|---------|-----------|----------|
| **Fast API (Go/Rust)** | Not needed | Check DB connectivity | Check process health |
| **Slow API (Java/Spring)** | 90-120s threshold | Check DB + queue depth | Check thread health |
| **Worker (batch)** | Not needed | Not needed (no traffic) | Check process health |
| **ML inference** | Model load time | Check model loaded | Check inference latency |
| **Web server (nginx)** | Config parse time | Check upstreams | Check process health |

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Probe distinctions** | Clearly separates startup (boot), readiness (traffic), liveness (restart) |
| **Dependency management** | Readiness checks dependencies, liveness checks process only |
| **Slow startup handling** | Uses startup probe to prevent false-positive failures during boot |
| **GC/deadlock awareness** | Knows GC pauses might fail readiness (OK) but not liveness (bad) |

---

## 4. Pod QoS Classes & Resource Management

**Q:** "You have three pods on a node: one with guaranteed QoS, one burstable, one best-effort. The node runs out of memory. Which pod gets killed first? Walk through the OOM kill order. How do you design resource requests/limits to ensure critical workloads survive?"

**What They're Really Testing:** Whether you understand the Kubernetes QoS model — how requests and limits map to QoS classes, and the OOM kill order when nodes are under memory pressure.

### Answer

**QoS Classes Defined:**

```yaml
# QOS CLASS: Guaranteed
# Conditions: ALL containers have requests == limits for CPU AND memory
resources:
  requests:
    cpu: 1
    memory: 1Gi
  limits:
    cpu: 1          # Same as request
    memory: 1Gi     # Same as request
# → cgroup settings: cpu.shares=1024, memory.limit=1Gi
# → Pod cannot exceed its limit
# → Least likely to be evicted

# QOS CLASS: Burstable
# Conditions: At least one container has request < limit (or only request)
resources:
  requests:
    cpu: 500m       # Base reservation
    memory: 512Mi
  limits:
    cpu: 2          # Can burst up to 2 cores
    memory: 1Gi     # Can burst up to 1Gi
# → cgroup settings: cpu.shares=512, memory.limit=1Gi
# → Can use idle resources up to limit
# → Medium eviction priority

# QOS CLASS: BestEffort (NO requests or limits set)
# Conditions: No resource requests or limits
resources: {}   # Empty!
# → No cgroup limits
# → Uses whatever is available (competes with all processes)
# → First to be evicted under pressure
# → Can cause node instability (unbounded resource usage)
```

**OOM Kill Order Under Memory Pressure:**

```
Node runs out of memory:

1. Kernel invokes OOM killer
2. Kubernetes kubelet monitors memory pressure
3. Eviction order (by QoS):

   ┌─────────────────────────────────────────────────────┐
   │ 1. BestEffort pods (killed first)                    │
   │ 2. Burstable pods (killed next, by priority)          │
   │ 3. Guaranteed pods (killed LAST, only if necessary)    │
   └─────────────────────────────────────────────────────┘

Within same QoS class:
  - Pods are ordered by priority (higher priority = evicted later)
  - Same priority: pod with higher memory usage vs request is evicted first

Beyond QoS:
  - Kernel OOM killer: chooses process with highest oom_score
  - oom_score = memory_used * 10 + OOM_SCORE_ADJ (set by kubelet)
  - Guaranteed pods: oom_score_adj = -998 (almost never killed)
  - Burstable pods: oom_score_adj = min(1000, 1000 - (1000 * memory_request / memory_limit))
  - BestEffort pods: oom_score_adj = 1000 (always killed first)
```

**Resource Management Design Patterns:**

```yaml
# Pattern 1: Reserve for critical workloads (Guaranteed)
apiVersion: v1
kind: Pod
metadata:
  name: critical-payment-processor
  annotations:
    scheduler.alpha.kubernetes.io/critical-pod: ""
spec:
  priorityClassName: high-priority
  containers:
  - name: app
    resources:
      requests:
        cpu: 2
        memory: 4Gi
      limits:
        cpu: 2
        memory: 4Gi
# → Guaranteed QoS + high priority = survives eviction

# Pattern 2: Burstable for elastic workloads
apiVersion: v1
kind: Pod
metadata:
  name: elastic-worker
spec:
  containers:
  - name: worker
    resources:
      requests:
        cpu: 500m
        memory: 256Mi
      limits:
        cpu: 4
        memory: 1Gi
# → Gets baseline 500m/256Mi, bursts to 4CPU/1Gi when available
# → Medium eviction priority

# Pattern 3: LimitRange for namespace policy
apiVersion: v1
kind: LimitRange
metadata:
  name: mem-limit-range
  namespace: team-a
spec:
  limits:
  - default:
      cpu: 500m
      memory: 512Mi        # Default limit if not specified
    defaultRequest:
      cpu: 100m
      memory: 256Mi        # Default request if not specified
    max:
      cpu: 4
      memory: 8Gi          # Hard cap per container
    min:
      cpu: 50m
      memory: 64Mi         # Minimum per container
    type: Container

# Pattern 4: ResourceQuota for namespace limits
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-a-quota
  namespace: team-a
spec:
  hard:
    requests.cpu: 20
    requests.memory: 40Gi
    limits.cpu: 40
    limits.memory: 80Gi
    requests.ephemeral-storage: 500Gi
    limits.ephemeral-storage: 1Ti
    persistentvolumeclaims: 10
    pods: 50
    count/secrets: 20
```

**CPU Throttling Deep Dive:**

```yaml
# CPU limits use CFS quota (Completely Fair Scheduler)
# Container with cpu.limit=2 → cpu.cfs_quota_us = 200000 (2 cores)
# cpu.cfs_period_us = 100000 (100ms default)

# Problem: CPU throttling with low limits
container with cpu: 500m (0.5 core)
→ cfs_quota_us = 50000, cfs_period_us = 100000
→ Container can use 50ms of CPU per 100ms window
→ After 50ms: throttled until next period
→ Even if CPU is idle, container is throttled!

# Throttling-aware design:
# - Set CPU limits HIGHER than requests for burstable workloads
# - For latency-sensitive: use Guaranteed QoS (no throttling if within limits)
# - Monitor: container_cpu_cfs_throttled_seconds_total

# Better approach for latency-sensitive:
resources:
  requests:
    cpu: 2
  limits:
    cpu: 2        # Same = Guaranteed = no throttle worry
```

**Memory Limits Deep Dive:**

```yaml
# Memory limits use cgroup memory controller
# Container with memory.limit=512Mi
# → kernel sets memory.max = 512Mi
# → Process over limit → OOM killed (by kernel, not kubelet!)

# Detect OOM kills:
# 1. kubectl describe pod: Exit Code: 137 (SIGKILL)
#    Reason: OOMKilled
# 2. Pod status: container_status.state.terminated.reason = OOMKilled
# 3. Node: dmesg | grep -i "killed process"
#    "Memory cgroup out of memory: Killed process 12345 (java)"
# 4. Prometheus: kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}

# Prevent OOM:
# - Set memory limits based on actual usage (monitor with metrics-server)
# - Add 20-30% headroom above steady-state for GC/surges
# - Use VPA (Vertical Pod Autoscaler) to automatically adjust requests
# - Set memory requests ≈ 80% of expected peak for Guaranteed QoS
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **QoS classes** | Knows the exact conditions for each class (request = limit, request < limit, no request) |
| **Eviction order** | Can explain the exact OOM kill order: BestEffort → Burstable → Guaranteed |
| **CPU throttling** | Understands CFS quota and throttling as a real production issue |
| **Resource planning** | Uses LimitRange + ResourceQuota for namespace governance |

---

## 5. Pod Priority, Preemption & Disruption Budgets

**Q:** "Your cluster is overloaded. A high-priority batch job needs to schedule, but all resources are consumed by lower-priority web servers. How does Kubernetes preempt lower-priority pods? How do PodDisruptionBudgets protect critical workloads during voluntary disruptions like node maintenance?"

**What They're Really Testing:** Whether you understand the Kubernetes priority and preemption system — how PriorityClass controls scheduling order, how preemption evicts lower-priority pods, and how PDBs limit disruption.

### Answer

**PriorityClass:**

```yaml
# PriorityClass defines relative importance of pods
# Higher priority = scheduled first, survives eviction longer

apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: critical-production
value: 1000000              # Higher number = higher priority
globalDefault: false         # If true, this is the default for all pods
description: "Critical production workloads (must never be preempted)"

---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: batch-jobs
value: 1000
description: "Best-effort batch jobs (can be preempted)"

---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: low-priority
value: 100
description: "Low priority test/staging workloads"

# Reserved priority range:
# 1000000000+ : System critical pods (kube-system)
# 1000000-999999999: User-facing production workloads
# 1-999999: Batch, test, dev workloads
# < 1: Best-effort (preempted first)
```

**Preemption in Action:**

```yaml
# Scenario: High-priority batch job can't schedule

# Step 1: Batch job (priority: 1000) needs 4 CPU, 8GB
# Step 2: All nodes are at capacity
# Step 3: Scheduler identifies nodes where preempting lower-priority pods
#         would free enough resources

# Preemption algorithm:
# 1. Find feasible nodes (filter by taints, affinity, etc.)
# 2. For each node, identify lower-priority pods to preempt
# 3. Calculate "victim pods" (lowest priority first)
# 4. Dry run: if preempting victims would free enough resources → candidate
# 5. Pick the best candidate node (highest score after preemption)
# 6. Delete victim pods (with graceful termination period)
# 7. Schedule high-priority pod

# Victim selection:
# - Only preempt pods with LOWER priority
# - Same priority: not preempted (need PriorityClass differentiation)
# - PodDisruptionBudget: checked but NOT enforced (preemption overrides PDB!)
# - Minimum victims: preempt the fewest pods to make room

# Preemption notification:
# - Victim pods get: "Preempted by <high-priority-pod>"
# - A preempted pod is NOT rescheduled (it's deleted)
# - Its controller (Deployment, Job) will recreate it IF replicas < desired
# - But recreated pod still has low priority → might be preempted again!

apiVersion: v1
kind: Pod
metadata:
  name: low-priority-web-abc
  annotations:
    preemption: "Preempted by batch-job-xyz to free resources on node-42"
```

**PodDisruptionBudget (PDB):**

```yaml
# PDB protects pods from VOLUNTARY disruptions:
# - Draining a node (kubectl drain)
# - Cluster autoscaler scaling down
# - Descheduler rebalancing
# - Node maintenance (not involuntary like node failure)

# PDB does NOT protect against:
# - Node failure (involuntary)
# - Preemption (higher-priority pod)
# - Eviction by resource pressure (NodePressure)
# - Manual pod deletion

# Example: minAvailable
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: payment-service-pdb
spec:
  minAvailable: 3             # At least 3 pods must be available
  selector:
    matchLabels:
      app: payment-service

# Example: maxUnavailable
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: payment-service-pdb-alt
spec:
  maxUnavailable: 1           # At most 1 pod can be unavailable
  selector:
    matchLabels:
      app: payment-service

# How PDB works:
# kubectl drain node-42
# 1. Check if draining would violate PDB (payment-service has 5 replicas)
# 2. Allowed: 1 pod can be evicted (5 - 1 = 4 ≥ 3 minAvailable)
# 3. If ALLOWED: evict payment-service pod → drain continues
# 4. If BLOCKED: node stays cordoned, drain PAUSES
# 5. Drain output: "Cannot evict pod: would violate PodDisruptionBudget"

# PDB calculation:
# With deployment replicas=5, minAvailable=3:
#   - Available pods must remain ≥ 3
#   - Only 2 pods can be disrupted at a time
#   - If 2 pods are already down (crash, restart): further eviction BLOCKED
```

**PDB Design Patterns:**

```yaml
# Pattern 1: Critical stateful services (keep majority)
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: kafka-broker-pdb
spec:
  minAvailable: 3              # At least 3 broker pods
  selector:
    matchLabels:
      app: kafka-broker
# Kafka requires majority for ISR → at least 2/3 for RF=3
# minAvailable=3 ensures at least 3/5 brokers are up

# Pattern 2: Stateless services (max disruption)
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: web-server-pdb
spec:
  maxUnavailable: 25%          # At most 25% can be down
  selector:
    matchLabels:
      app: web-server
# Rolling updates usually handle one at a time
# PDB ensures drain doesn't take more than 25% at once

# Pattern 3: Singleton critical (no disruption allowed)
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: singleton-pdb
spec:
  minAvailable: 1              # Must have exactly 1 available
  selector:
    matchLabels:
      app: single-instance
# WARNING: This blocks ALL drains!
# Use only for truly singleton services with no HA
# Better to: make it multi-instance instead

# Pattern 4: Queue worker (disruption sensitive)
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: worker-pdb
spec:
  minAvailable: 80%            # 80% must be available
  selector:
    matchLabels:
      app: queue-worker
# Queue workers process messages — slowdown is OK, total stop is not
```

**Combined Priority + PDB Design:**

```yaml
# Priority levels for a production cluster:

# Tier 1: Critical infrastructure (never preempted, PDB = 100%)
- name: cluster-critical
  value: 1000000000
  # Pods: CoreDNS, kube-dns, networking (Cilium, Calico)
  # PDB: Keep all available

# Tier 2: User-facing production (preempted only by Tier 1)
- name: production-critical
  value: 1000000
  # Pods: API servers, payment processing, auth service
  # PDB: minAvailable = replicas - 1

# Tier 3: Internal services (medium priority)
- name: production-default
  value: 100000
  # Pods: Internal APIs, background workers, batch reports
  # PDB: minAvailable = 50%

# Tier 4: Batch/analytics (preempted by all above)
- name: batch
  value: 1000
  # Pods: Data processing, ML training, CI/CD runners
  # PDB: none (OK to be preempted)

# Tier 5: Test/dev (first to be preempted)
- name: test
  value: 100
  # Pods: Staging, dev environments, integration tests
  # PDB: none

# Behavior under pressure:
# 1. Node fills up → BestEffort pods evicted first
# 2. More pressure → test pods preempted
# 3. More pressure → batch pods preempted
# 4. Critical: never preempted (highest priority + Guaranteed QoS)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Preemption mechanics** | Knows victim selection algorithm (lowest priority, fewest pods) |
| **PDB scope** | Understands PDB protects voluntary disruptions only (not preemption, not node failure) |
| **PDB calculation** | Explains minAvailable = replicas - allowed_disruptions |
| **Priority design** | Designs multi-tier priority with corresponding PDB strategies |

---

## 6. Pod Security: Standards, Contexts & Admission

**Q:** "Your security team requires that all pods in production must: run as non-root, drop all capabilities except NET_BIND_SERVICE, use read-only root filesystem, and have seccomp profile set to RuntimeDefault. How do you enforce this across 500 pods without modifying every deployment? Design a Pod Security Standards strategy."

**What They're Really Testing:** Whether you understand the three layers of pod security — SecurityContext (pod-level), Pod Security Standards (namespace-level), and Admission Controllers (cluster-level) — and can design a defense-in-depth approach.

### Answer

**Pod Security Standards (PSA — Pod Security Admission):**

```yaml
# Pod Security Standards (replaces deprecated PodSecurityPolicy)
# Three levels: Privileged, Baseline, Restricted

# Namespace enforcement labels:
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    pod-security.kubernetes.io/enforce: restricted    # REJECT violating pods
    pod-security.kubernetes.io/enforce-version: v1.29 # Lock to specific version
    pod-security.kubernetes.io/audit: baseline        # LOG violations (don't block)
    pod-security.kubernetes.io/warn: restricted       # WARN user (don't block)

# Level differences:
# PRIVILEGED: Unrestricted (for system components, service mesh sidecars)
# BASELINE: Minimal restrictions (typical workloads)
#   - Prevents: privileged containers, hostPID, hostNetwork, hostPorts > 1024
#   - Requires: AppArmor (runtime/default), SELinux, seccomp
# RESTRICTED: Full hardening (PCI/HIPAA/SOC2 compliance)
#   - Adds: RunAsNonRoot: true, readOnlyRootFilesystem: true
#   - Capabilities: drop ALL, add ONLY NET_BIND_SERVICE
#   - seccomp: RuntimeDefault (mandatory)
#   - allowPrivilegeEscalation: false
#   - Runs with specific seccomp profile
```

**SecurityContext Deep Dive:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secure-app
spec:
  securityContext:                              # Pod-level security (applies to ALL containers)
    runAsUser: 1000                              # UID 1000 (non-root)
    runAsGroup: 3000                             # GID 3000
    fsGroup: 2000                                # Volume ownership (for volumes mounted)
    supplementalGroups: [1000]                   # Additional GIDs for process
    seccompProfile:
      type: RuntimeDefault                       # Use container runtime's default seccomp profile
    # Alternative: type: Localhost, localhostProfile: "profiles/audit.json"

  containers:
  - name: app
    securityContext:                             # Container-level security (overrides pod-level)
      runAsNonRoot: true                         # Ensure container is NOT running as root
      readOnlyRootFilesystem: true               # Container's root FS is read-only
      allowPrivilegeEscalation: false            # Don't allow privilege escalation (setuid)
      capabilities:
        drop:                                    # Drop ALL capabilities (recommended)
        - ALL
        add:                                     # Only add what's absolutely needed
        - NET_BIND_SERVICE                       # Allow binding to ports < 1024
      privileged: false                          # Not privileged (forbidden in baseline+)
      procMount: Default                         # Mount /proc as read-only (strict: Unmasked)

    volumeMounts:
    - name: tmp
      mountPath: /tmp                            # Writable directory for temp files
    - name: logs
      mountPath: /var/log/app                    # Writable directory for logs

  volumes:
  - name: tmp
    emptyDir: {}
  - name: logs
    emptyDir: {}

# For Pod Security Standard RESTRICTED compliance, a pod must have:
# 1. runAsNonRoot: true (all containers)
# 2. readOnlyRootFilesystem: true (all containers)
# 3. allowPrivilegeEscalation: false (all containers)
# 4. capabilities.drop: ["ALL"] (all containers)
# 5. seccompProfile.type: "RuntimeDefault"
# 6. runAsUser: not 0 (optional if runAsNonRoot: true)
```

**SecurityContext for Common Workloads:**

```yaml
# Java/JVM application (needs /tmp for JIT, logs)
apiVersion: v1
kind: Pod
metadata:
  name: java-app
spec:
  securityContext:
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault
  containers:
  - name: java-app
    securityContext:
      runAsNonRoot: true
      readOnlyRootFilesystem: true        # Need writable volume for temp
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
        add: ["NET_BIND_SERVICE"]         # Bind to port 8080
    volumeMounts:
    - name: tmp
      mountPath: /tmp                     # JVM JIT compilation needs writable /tmp
    - name: logs
      mountPath: /var/log/app
  volumes:
  - name: tmp
    emptyDir: {}
  - name: logs
    emptyDir: {}
  # Result: app writes to /tmp (ephemeral) and /var/log/app → security compliant

# Node.js (temp directory for npm modules)
apiVersion: v1
kind: Pod
metadata:
  name: node-app
spec:
  containers:
  - name: node-app
    securityContext:
      runAsNonRoot: true
      readOnlyRootFilesystem: true
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
    volumeMounts:
    - name: tmp
      mountPath: /tmp
  volumes:
  - name: tmp
    emptyDir: {}
  # Note: Node might need NODE_OPTIONS=--max-old-space-size for tuning

# Nginx (needs to bind to port 80, write logs)
apiVersion: v1
kind: Pod
metadata:
  name: nginx
spec:
  containers:
  - name: nginx
    securityContext:
      capabilities:
        drop: ["ALL"]
        add: ["NET_BIND_SERVICE"]        # Bind to port 80 (or use port 8080)
      readOnlyRootFilesystem: true
      runAsNonRoot: true
    volumeMounts:
    - name: nginx-tmp
      mountPath: /var/cache/nginx       # Nginx writes cache here
    - name: nginx-run
      mountPath: /var/run               # PID file
    - name: nginx-logs
      mountPath: /var/log/nginx
    # With nginx on port 8080: no need for NET_BIND_SERVICE
    # With nginx on port 80: need CAP_NET_BIND_SERVICE
```

**Seccomp, AppArmor & SELinux:**

```yaml
# SECCOMP (Secure Computing Mode): Filter system calls
# Approaches:
#   1. RuntimeDefault: let container runtime manage (Docker/containerd default)
#   2. Localhost: custom seccomp profile

# Custom seccomp profile (audit-logs violations without blocking):
# profiles/audit.json
{
  "defaultAction": "SCMP_ACT_LOG",           # Log all syscalls
  "architectures": ["SCMP_ARCH_X86_64"],
  "syscalls": [
    {"names": ["execve", "execveat"], "action": "SCMP_ACT_ALLOW"},
    {"names": ["clone", "fork", "vfork"], "action": "SCMP_ACT_ALLOW"},
    {"names": ["mount", "umount2"], "action": "SCMP_ACT_ERRNO"}  # Block mounts
  ]
}

# After audit, create strict profile:
{
  "defaultAction": "SCMP_ACT_ERRNO",         # Block unknown syscalls
  "architectures": ["SCMP_ARCH_X86_64"],
  "syscalls": [
    {"names": ["read", "write", "open", "close", "stat", "mmap",
               "brk", "sched_yield", "futex", "nanosleep", "exit_group",
               "gettid", "set_robust_list", "rt_sigaction",
               "epoll_create1", "epoll_wait", "epoll_ctl"], "action": "SCMP_ACT_ALLOW"},
    # Add syscalls that the application ACTUALLY needs
  ]
}

# APPARMOR: MAC (Mandatory Access Control) for file paths
# SELinux: Label-based MAC (CentOS/RHEL)
# Both provide: file access control, network access control, capability control

# For restricted compliance:
securityContext:
  seccompProfile:
    type: RuntimeDefault      # Minimum for Baseline, required for Restricted
  # AppArmor annotation (deprecated, use seccomp instead):
  # container.apparmor.security.beta.kubernetes.io/<container>: runtime/default
```

**Enforcing Security Across All Pods:**

```yaml
# Strategy: Namespace-level enforcement + Admission Controller

# Step 1: Label namespaces
apiVersion: v1
kind: Namespace
metadata:
  name: team-a-prod
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: v1.29
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted

# Step 2: Exception for system namespaces
apiVersion: v1
kind: Namespace
metadata:
  name: kube-system
  labels:
    pod-security.kubernetes.io/enforce: privileged    # System components
    pod-security.kubernetes.io/enforce-version: v1.29

# Step 3: Exceptions for specific pods (via labels)
apiVersion: v1
kind: Pod
metadata:
  name: sidecar-injector
  annotations:
    pod-security.kubernetes.io/enforce: privileged    # Override namespace
spec:
  ...

# Step 4: Use Kyverno or OPA for advanced policies
# (Beyond PSA's three levels — for custom rules)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **PSA levels** | Knows Privileged, Baseline, Restricted and exact requirements for each |
| **SecurityContext** | Can configure runAsNonRoot, readOnlyRootFS, capabilities, seccomp correctly |
| **Enforcement strategy** | Uses namespace labels + admission controller for cluster-wide enforcement |
| **Exception handling** | Knows how to exempt system components and sidecars from restricted policy |

---

## 7. Kubernetes Monitoring Stack: kubelet, cAdvisor, Metrics Server

**Q:** "Design a pod monitoring pipeline that captures CPU, memory, network, disk, and OOM events every 15 seconds. Explain the difference between kubelet metrics, cAdvisor metrics, and metrics-server data. Which one should you use for HPA? Which one for diagnosing OOM kills?"

**What They're Really Testing:** Whether you understand the three sources of pod resource metrics in Kubernetes — kubelet's /metrics endpoint, cAdvisor's container metrics, and metrics-server's aggregation — and their distinct use cases.

### Answer

**Three Metrics Sources:**

```
┌─────────────────────────────────────────────────────────────┐
│                       Node (Linux)                           │
│                                                              │
│  ┌────────────────────────────────────┐                     │
│  │         kubelet                     │                     │
│  │  ┌─────────────────────────────┐   │                     │
│  │  │  /metrics/resource          │   │  ← Summary API      │
│  │  │  Pod CPU, Memory (15s)     │   │    (used by         │
│  │  │  Scrape cost: LOW          │   │     metrics-server)  │
│  │  └─────────────────────────────┘   │                     │
│  │                                    │                     │
│  │  ┌─────────────────────────────┐   │                     │
│  │  │  /metrics/cadvisor          │   │  ← cAdvisor         │
│  │  │  Container CPU, Mem, Net,  │   │    (embedded in     │
│  │  │  Disk, Filesystem, OOM     │   │     kubelet)        │
│  │  │  Scrape cost: HIGH         │   │                     │
│  │  └─────────────────────────────┘   │                     │
│  │                                    │                     │
│  │  ┌─────────────────────────────┐   │                     │
│  │  │  /metrics/probes            │   │  ← Probe metrics    │
│  │  │  Startup, Readiness,       │   │    (latency,         │
│  │  │  Liveness probe stats      │   │     status)         │
│  │  └─────────────────────────────┘   │                     │
│  └────────────────────────────────────┘                     │
│                                                              │
│  ┌────────────────────────────────────┐                     │
│  │      metrics-server                  │                     │
│  │  Aggregates /metrics/resource       │                     │
│  │  across all nodes                   │                     │
│  │  Used by: kubectl top, HPA, VPA    │                     │
│  └────────────────────────────────────┘                     │
└─────────────────────────────────────────────────────────────┘
```

**Metrics-Server (Resource Metrics API):**

```yaml
# metrics-server: the simplest, most essential monitoring component
# Installed as a Deployment, scrapes kubelet /metrics/resource every 60s

# Installation:
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# Usage:
kubectl top nodes                    # CPU/Memory per node
kubectl top pods -n my-namespace     # CPU/Memory per pod
kubectl top pod my-pod --containers  # CPU/Memory per container

# Output:
NAME                     CPU(cores)   MEMORY(bytes)
my-app-7d4f8b9c6-abc12  125m         456Mi
my-app-7d4f8b9c6-def34  200m         789Mi

# metrics-server data flow:
# 1. kubelet collects cAdvisor container stats every 10s
# 2. kubelet caches and serves via /metrics/resource (lower cardinality)
# 3. metrics-server scrapes all kubelets every 60s (configurable)
# 4. metrics-server aggregates and serves via Resource Metrics API
# 5. HPA, kubectl top, VPA consume from Resource Metrics API

# Limitations:
# - No network/disk metrics
# - No container restart counts
# - No filesystem usage
# - Only current values (no historical data)
# - ~60s delay (configurable with --metric-resolution)

# Production deployment:
apiVersion: apps/v1
kind: Deployment
metadata:
  name: metrics-server
  namespace: kube-system
spec:
  replicas: 2
  selector:
    matchLabels:
      k8s-app: metrics-server
  template:
    spec:
      containers:
      - name: metrics-server
        image: registry.k8s.io/metrics-server/metrics-server:v0.7.2
        args:
        - --kubelet-insecure-tls         # For self-signed kubelet certs
        - --kubelet-preferred-address-types=InternalIP,Hostname,ExternalIP
        - --metric-resolution=15s        # Scrape every 15s (default: 60s)
        resources:
          requests:
            cpu: 100m
            memory: 200Mi
```

**cAdvisor Metrics (Detailed Container Metrics):**

```yaml
# cAdvisor is embedded in kubelet, provides detailed container metrics
# Endpoint: https://<node-ip>:10250/metrics/cadvisor

# Key metrics exposed:
# ── CPU ──
container_cpu_usage_seconds_total{container="app", pod="my-app-abc", namespace="prod"}
container_cpu_cfs_throttled_seconds_total{container="app"}
container_cpu_load_average_10s{container="app"}

# ── Memory ──
container_memory_usage_bytes{container="app", pod="my-app-abc"}
container_memory_working_set_bytes{container="app"}                # Actual memory in use
container_memory_rss{container="app"}                              # RSS only
container_memory_cache{container="app"}
container_memory_swap{container="app"}
container_memory_failures_total{container="app"}                   # OOM events!
container_memory_failcnt{container="app"}                          # OOM count

# ── Network ──
container_network_receive_bytes_total{pod="my-app-abc"}
container_network_transmit_bytes_total{pod="my-app-abc"}
container_network_receive_errors_total{pod="my-app-abc"}
container_network_transmit_errors_total{pod="my-app-abc"}

# ── Disk / Ephemeral Storage ──
container_fs_usage_bytes{container="app"}
container_fs_limit_bytes{container="app"}
container_fs_writes_bytes_total{container="app"}

# ── Filesystem ──
container_fs_inodes_total{container="app"}
container_fs_inodes_free{container="app"}

# ── Processes ──
container_processes{container="app"}
container_file_descriptors{container="app"}

# ── Network (per interface) ──
container_network_receive_bytes_total{interface="eth0"}
container_network_transmit_bytes_total{interface="eth0"}

# Which source for what:
# - HPA/VPA: metrics-server (low overhead, designed for autoscaling)
# - OOM detection: cAdvisor (container_memory_failures_total)
# - Network troubleshooting: cAdvisor (container_network_*)
# - CPU throttling: cAdvisor (container_cpu_cfs_throttled_*)
# - Disk usage: cAdvisor (container_fs_*)
```

**kubelet Probe Metrics:**

```yaml
# kubelet exposes probe metrics at /metrics/probes
# These are critical for understanding pod health issues

# Probes exposed:
#   - probe: "startup", "readiness", "liveness"
#   - status: "succeeded", "failed", "unknown"
#   - container, pod, namespace

prober_probe_total{container="app", pod="my-app", namespace="prod",
                    probe="readiness", result="succeeded"} 10
prober_probe_total{container="app", pod="my-app", namespace="prod",
                    probe="readiness", result="failed"} 2

# Key metrics:
prober_probe_total                               # Count of probe results
prober_probe_duration_seconds{probe="readiness"} # How long probes took
last_readiness_check_success_time{container="app"} # Timestamp of last success

# Alert queries:
# High readiness failure rate
rate(prober_probe_total{result="failed", probe="readiness"}[5m]) > 0.05
# Probe taking too long
histogram_quantile(0.99, rate(prober_probe_duration_seconds_bucket[5m])) > 5
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Metrics sources** | Can differentiate kubelet metrics, cAdvisor, and metrics-server by endpoint and use case |
| **metrics-server role** | Knows it's for Resource Metrics API (HPA, kubectl top), not detailed monitoring |
| **cAdvisor depth** | Knows specific metric names: container_memory_working_set_bytes, container_cpu_throttled |
| **Probe metrics** | Understands prober_probe_total for monitoring probe health |

---

## 8. kube-state-metrics & Node Exporter

**Q:** "Your team needs to monitor Kubernetes object states — deployments with unavailable replicas, pods in CrashLoopBackOff, PVCs stuck in Pending. How does kube-state-metrics provide this? What metrics does it expose? How does it differ from cAdvisor and node-exporter?"

**What They're Really Testing:** Whether you understand that kube-state-metrics provides Kubernetes object state (not container metrics), node-exporter provides node OS metrics, and cAdvisor provides container runtime metrics — three distinct monitoring domains.

### Answer

**kube-state-metrics (KSM):**

```yaml
# kube-state-metrics: watches Kubernetes API and generates metrics about object state
# NOT container-level metrics — those come from cAdvisor
# KSM tells you: "how many deployments, what's their status, are pods healthy"

# Deployment metrics:
kube_deployment_status_replicas{deployment="my-app", namespace="prod"}
kube_deployment_status_replicas_available{deployment="my-app"}
kube_deployment_status_replicas_unavailable{deployment="my-app"}
kube_deployment_status_replicas_updated{deployment="my-app"}
kube_deployment_metadata_generation{deployment="my-app"}
kube_deployment_spec_replicas{deployment="my-app"}

# Pod metrics:
kube_pod_info{pod="my-app-abc", node="node-1", namespace="prod"}
kube_pod_status_phase{phase="Running", pod="my-app-abc"}         # 1 if Running
kube_pod_status_phase{phase="Pending", pod="my-app-def"}         # 1 if Pending
kube_pod_status_phase{phase="Failed", pod="my-app-ghi"}          # 1 if Failed
kube_pod_status_reason{reason="Evicted", pod="my-app-jkl"}       # 1 if Evicted
kube_pod_restart_policy{type="Always", pod="my-app-abc"}
kube_pod_completion_time{pod="batch-job-xyz"}                    # For Jobs
kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"}
kube_pod_container_status_waiting_reason{reason="ImagePullBackOff"}
kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}
kube_pod_container_resource_requests{resource="cpu", unit="core", pod="my-app"}
kube_pod_container_resource_requests{resource="memory", unit="byte", pod="my-app"}
kube_pod_container_resource_limits{resource="cpu", pod="my-app"}

# Node metrics:
kube_node_status_condition{condition="Ready", status="true", node="node-1"}
kube_node_status_capacity{resource="cpu", node="node-1"}
kube_node_status_capacity{resource="memory", node="node-1"}
kube_node_status_allocatable{resource="cpu", node="node-1"}
kube_node_spec_taint{key="node.kubernetes.io/unreachable", node="node-1"}

# PVC metrics:
kube_persistentvolumeclaim_status_phase{phase="Pending", namespace="prod"}
kube_persistentvolumeclaim_status_phase{phase="Bound", namespace="prod"}
kube_persistentvolumeclaim_resource_requests_storage_bytes{namespace="prod"}

# Other objects:
kube_namespace_status_phase{phase="Active", namespace="prod"}
kube_secret_info{namespace="prod", secret="my-secret"}
kube_configmap_info{namespace="prod", configmap="app-config"}
kube_service_info{namespace="prod", service="my-service"}
kube_horizontalpodautoscaler_spec_max_replicas{hpa="my-app-hpa"}
kube_horizontalpodautoscaler_status_current_replicas{hpa="my-app-hpa"}
kube_horizontalpodautoscaler_status_desired_replicas{hpa="my-app-hpa"}

# Event metrics:
kube_event{type="Warning", reason="BackOff", namespace="prod"}
kube_event{type="Warning", reason="FailedScheduling", namespace="prod"}
kube_event{type="Warning", reason="NodeNotReady", node="node-1"}

# Alert examples using KSM:
# 1. Pod in CrashLoopBackOff:
kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"} > 0
# 2. Deployment with unavailable replicas:
kube_deployment_status_replicas_unavailable > 0
# 3. PVC stuck in Pending:
kube_persistentvolumeclaim_status_phase{phase="Pending"} > 0
# 4. Node not ready for 5 minutes:
kube_node_status_condition{condition="Ready", status="true"} == 0
# 5. HPA at max replicas (can't scale further):
kube_horizontalpodautoscaler_status_current_replicals == kube_horizontalpodautoscaler_spec_max_replicas
```

**Node Exporter:**

```yaml
# node_exporter: exposes OS-level metrics from Linux nodes
# NOT container metrics — those come from cAdvisor
# node_exporter tells you: "is the node healthy, disk full, network saturated?"

# CPU:
node_cpu_seconds_total{mode="idle"}               # CPU idle time
node_cpu_seconds_total{mode="user"}               # User space CPU
node_cpu_seconds_total{mode="system"}             # Kernel CPU
node_cpu_seconds_total{mode="iowait"}             # I/O wait time

# Memory:
node_memory_MemTotal_bytes                        # Total RAM
node_memory_MemAvailable_bytes                    # Available (free + cache - reserved)
node_memory_MemFree_bytes                         # Completely free
node_memory_Buffers_bytes
node_memory_Cached_bytes
node_memory_SwapTotal_bytes
node_memory_SwapFree_bytes

# Disk:
node_filesystem_size_bytes{mountpoint="/"}
node_filesystem_free_bytes{mountpoint="/"}
node_filesystem_avail_bytes{mountpoint="/"}       # Available to non-root
node_disk_io_time_seconds_total{device="nvme0n1"} # Disk I/O time
node_disk_read_bytes_total{device="nvme0n1"}
node_disk_written_bytes_total{device="nvme0n1"}

# Network:
node_network_receive_bytes_total{device="eth0"}
node_network_transmit_bytes_total{device="eth0"}
node_network_receive_errors_total{device="eth0"}
node_network_transmit_errors_total{device="eth0"}
node_network_receive_drop_total{device="eth0"}
node_network_transmit_drop_total{device="eth0"}

# System:
node_boot_time_seconds                          # Node uptime (last boot)
node_load1, node_load5, node_load15
node_nf_conntrack_entries                       # Connection tracking
node_filefd_allocated                           # File descriptors used
node_sockstat_TCP_alloc                         # TCP sockets allocated
node_sockstat_TCP_tw                            # TCP TIME_WAIT sockets
node_entropy_available_bits                     # Entropy pool (for /dev/random)

# Node exporter collectors (enable/disable via --collectors.<name>):
# Enabled by default: cpu, diskstats, filesystem, loadavg, meminfo, netstat,
#                     network, ntp, processes, stat, textfile, time, uname
# Often enabled: systemd, nfs, nfsd, interrupts, cpufreq
# Disabled by default: bonding, buddyinfo, drbd, edac, entropy, fibrechannel,
#                       hwmon, infiniband, ipvs, lmsensors, mdadm, meminfo_numa,
#                       mountstats, netclass, netdev, perf, powersupplyclass,
#                       pressure, rapl, schedstat, selinux, sockstat, softnet,
#                       tcpstat, thermal_zone, udp, xfs, zfs

# Production deployment (DaemonSet):
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-exporter
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: node-exporter
  template:
    spec:
      hostPID: true                          # Access host process info
      hostNetwork: true                       # Access host network stats
      containers:
      - name: node-exporter
        image: prom/node-exporter:v1.8.2
        args:
        - --path.procfs=/host/proc
        - --path.sysfs=/host/sys
        - --path.rootfs=/host/root
        - --collector.filesystem.mount-points-exclude=^/(dev|proc|sys|run/k3s|var/lib/docker)
        - --collector.textfile.directory=/var/lib/node_exporter/textfile
        ports:
        - containerPort: 9100
        volumeMounts:
        - name: proc
          mountPath: /host/proc
          readOnly: true
        - name: sys
          mountPath: /host/sys
          readOnly: true
        - name: root
          mountPath: /host/root
          mountPropagation: HostToContainer    # Access host filesystem
      volumes:
      - name: proc
        hostPath:
          path: /proc
      - name: sys
        hostPath:
          path: /sys
      - name: root
        hostPath:
          path: /
```

**Monitoring Component Comparison:**

```yaml
Component          | Source           | What It Monitors                | Key Metrics                      | Used For
-------------------|------------------|--------------------------------|----------------------------------|-----------------------
metrics-server     | kubelet API      | Pod CPU/Memory (summary)       | cpu, memory                      | HPA, kubectl top
cAdvisor (kubelet) | container runtime | Container resources             | CPU, Mem, Net, Disk, OOM         | Detailed pod metrics
kube-state-metrics | Kubernetes API   | Kubernetes object states        | Deployments, Pods, Nodes, PVCs   | Object health alerts
node-exporter     | Linux OS         | Node OS-level metrics           | CPU, Mem, Disk, Network, Load    | Node health alerts

# What to install:
# Minimum: metrics-server (required for HPA)
# Essential: kube-state-metrics + node-exporter + Prometheus
# Complete: Add cAdvisor scraping, kubelet metrics, probe metrics
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **KSM vs cAdvisor** | Knows KSM = k8s object state, cAdvisor = container runtime stats |
| **node-exporter role** | Understands it's for node OS metrics, not container metrics |
| **Alert examples** | Can construct PromQL alerts from KSM metrics for common pod issues |
| **DaemonSet deployment** | Knows node-exporter runs as DaemonSet with hostPath volumes |

---

## 9. Prometheus Operator: ServiceMonitor, PodMonitor & Rules

**Q:** "Design a Prometheus monitoring architecture for a 200-microservice platform using the Prometheus Operator. How do ServiceMonitor and PodMonitor work? How do you dynamically discover new services and apply alerting rules without restarting Prometheus?"

**What They're Really Testing:** Whether you understand the Prometheus Operator's custom resources — how ServiceMonitor and PodMonitor translate to scrape configs, and how PrometheusRule dynamically adds alerting/recording rules.

### Answer

**Prometheus Operator Architecture:**

```
┌─────────────────────────────────────────────────────────────┐
│                   Prometheus Operator                        │
│                                                              │
│  Watches CRDs and reconciles Prometheus/PrometheusRule/      │
│  ServiceMonitor/PodMonitor/AlertmanagerConfig resources      │
└──────────┬──────────┬──────────┬──────────┬──────────────────┘
           │          │          │          │
           ▼          ▼          ▼          ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ Prometheus│ │Prometheus│ │Service   │ │PodMonitor│
│ (stateful)│ │ Rule     │ │ Monitor  │ │          │
└──────────┘ └──────────┘ └──────────┘ └──────────┘
                                    │          │
                                    │          ▼
                                    │  ┌──────────────┐
                                    │  │ Pod with      │
                                    │  │ /metrics      │
                                    │  └──────────────┘
                                    ▼
                          ┌──────────────┐
                          │ Service       │
                          │ (selects pods)│
                          └──────────────┘
```

**ServiceMonitor vs PodMonitor:**

```yaml
# ServiceMonitor: Discovers targets through a Service resource
# PodMonitor: Discovers targets directly from pods (no Service needed)

# When to use ServiceMonitor:
# - Service has a /metrics endpoint
# - Need the Service's DNS/load balancing
# - Standard use case (most common)

# When to use PodMonitor:
# - No Service exists (cronjobs, batch jobs)
# - StatefulSet with headless Service (each pod individually)
# - DaemonSet where each pod has different metrics (node-specific)
# - Want to scrape ALL pod replicas individually (not through service load balancing)
```

**ServiceMonitor Example:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: my-app-monitor
  namespace: monitoring                  # Prometheus watches this namespace
  labels:
    release: prometheus                  # Match Prometheus' serviceMonitorSelector
spec:
  selector:
    matchLabels:
      app: my-app                        # Select services with this label
  namespaceSelector:
    any: true                            # Scrape from ANY namespace
    # Or: matchNames: ["prod", "staging"]
  endpoints:
  - port: metrics                        # Port name from Service spec
    path: /metrics                       # Metrics endpoint
    interval: 15s                        # Scrape every 15 seconds
    scrapeTimeout: 10s
    scheme: http
    # TLS config (if using https):
    # tlsConfig:
    #   insecureSkipVerify: true
    # Basic auth:
    # basicAuth:
    #   username:
    #     name: prometheus-credentials
    #     key: username
    #   password:
    #     name: prometheus-credentials
    #     key: password
    relabelings:
    - sourceLabels: [__meta_kubernetes_pod_node_name]
      targetLabel: node                  # Add node label to metrics
    - sourceLabels: [__meta_kubernetes_service_name]
      targetLabel: k8s_service
    metricRelabelings:
    - sourceLabels: [__name__]
      regex: 'container_memory_(cache|swap|kernel).*'
      action: drop                       # Drop high-cardinality memory metrics
```

**PodMonitor Example:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: daemonset-pods
  namespace: monitoring
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app: node-exporter                 # Select pods with this label
  namespaceSelector:
    any: true
  podMetricsEndpoints:
  - port: metrics                        # Container port name
    path: /metrics
    interval: 30s
    relabelings:
    - sourceLabels: [__meta_kubernetes_pod_node_name]
      targetLabel: node
      action: replace
    - sourceLabels: [__meta_kubernetes_pod_name]
      targetLabel: pod
      action: replace
```

**PrometheusRule (Alerting and Recording Rules):**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: kubernetes-alerts
  namespace: monitoring
  labels:
    release: prometheus                   # Match Prometheus' ruleSelector
spec:
  groups:
  - name: kubernetes-pods
    interval: 30s                         # Evaluate every 30 seconds
    rules:
    - alert: KubePodCrashLooping
      expr: |
        max by (namespace, pod, container) (
          kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"}
        ) > 0
      for: 5m                             # Must be true for 5 minutes
      labels:
        severity: critical
        team: platform
      annotations:
        summary: "Pod {{ $labels.pod }} is crashing"
        description: "Pod {{ $labels.pod }} in {{ $labels.namespace }} is in CrashLoopBackOff"
        runbook_url: "https://runbooks.internal/crashloop"

    - alert: KubePodNotReady
      expr: |
        kube_pod_status_phase{phase="Running"} != 1
        and on (pod, namespace)
        kube_pod_status_phase{phase="Pending"} == 1
      for: 15m
      labels:
        severity: warning
      annotations:
        summary: "Pod {{ $labels.pod }} is not ready for 15 minutes"

    - alert: KubePodOOMKilled
      expr: |
        increase(kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}[5m]) > 0
      labels:
        severity: warning
      annotations:
        summary: "Pod {{ $labels.pod }} OOM killed"
        description: "Container {{ $labels.container }} in {{ $labels.pod }} was OOM killed"

    - alert: KubeDeploymentReplicasMismatch
      expr: |
        kube_deployment_spec_replicas != kube_deployment_status_replicas_available
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Deployment {{ $labels.deployment }} replicas mismatch"
        description: "Expected {{ $value }} replicas, not all available"

    - alert: KubePodImagePullBackOff
      expr: |
        kube_pod_container_status_waiting_reason{reason="ImagePullBackOff"} > 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Pod {{ $labels.pod }} cannot pull image"

    - alert: KubeContainerRestartHigh
      expr: |
        rate(kube_pod_container_status_restarts_total[1h]) > 5
      labels:
        severity: warning
      annotations:
        summary: "Container {{ $labels.container }} restarted {{ $value }} times per hour"

    - alert: KubePodCPUThrottling
      expr: |
        rate(container_cpu_cfs_throttled_seconds_total{container!=""}[5m]) > 0.5
        and on (container, pod, namespace)
        container_cpu_cfs_periods_total{container!=""} > 0
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Container {{ $labels.container }} CPU throttled {{ $value }}s/s"

    - alert: KubePersistentVolumeUsageCritical
      expr: |
        kubelet_volume_stats_available_bytes / kubelet_volume_stats_capacity_bytes < 0.05
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "PV usage critical for {{ $labels.persistentvolumeclaim }}"

    - alert: KubePodEphemeralStorageUsage
      expr: |
        (
          sum by (pod, namespace) (
            container_fs_usage_bytes{container!=""}
          )
          / sum by (pod, namespace) (
            kube_pod_container_resource_limits{resource="ephemeral-storage"}
          )
        ) > 0.85
      for: 5m
      labels:
        severity: warning

  - name: kubernetes-nodes
    interval: 30s
    rules:
    - alert: KubeNodeNotReady
      expr: |
        kube_node_status_condition{condition="Ready", status="true"} == 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Node {{ $labels.node }} is not ready"

    - alert: KubeNodeMemoryPressure
      expr: |
        kube_node_status_condition{condition="MemoryPressure", status="true"} == 1
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Node {{ $labels.node }} has memory pressure"

    - alert: KubeNodeDiskPressure
      expr: |
        kube_node_status_condition{condition="DiskPressure", status="true"} == 1
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Node {{ $labels.node }} has disk pressure"

  - name: pod-resource-recording
    interval: 60s
    rules:
    - record: pod:cpu_usage_avg_5m
      expr: |
        avg by (pod, namespace, node) (
          rate(container_cpu_usage_seconds_total{container!=""}[5m])
        )
    - record: pod:memory_usage_avg_5m
      expr: |
        avg by (pod, namespace) (
          container_memory_working_set_bytes{container!=""}
        )
    - record: namespace:cpu_usage_avg_5m
      expr: |
        sum by (namespace) (
          rate(container_cpu_usage_seconds_total{container!=""}[5m])
        )
    - record: namespace:memory_usage_avg_5m
      expr: |
        sum by (namespace) (
          container_memory_working_set_bytes{container!=""}
        )
```

**Prometheus Custom Resource:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: k8s
  namespace: monitoring
spec:
  version: v2.53.0
  replicas: 2                            # HA pair
  retention: 30d
  retentionSize: 100GB
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: ssd
        resources:
          requests:
            storage: 200Gi
  serviceMonitorSelector:
    matchLabels:
      release: prometheus                # Only scrape ServiceMonitors with this label
  podMonitorSelector:
    matchLabels:
      release: prometheus                # Only scrape PodMonitors with this label
  ruleSelector:
    matchLabels:
      release: prometheus                # Only load rules with this label
  resources:
    requests:
      memory: 8Gi
      cpu: 2
    limits:
      memory: 16Gi
  additionalScrapeConfigs:
    name: additional-scrape-configs      # For custom scrape configs (kubelet, cAdvisor)
    key: prometheus-additional.yaml
  alerting:
    alertmanagers:
    - namespace: monitoring
      name: alertmanager-operated
      port: web
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **ServiceMonitor vs PodMonitor** | Can articulate when to use each (Service-based vs direct pod scraping) |
| **PrometheusRule** | Knows how alerting and recording rules are dynamically loaded |
| **Selectors** | Understands how Prometheus CR uses label selectors to discover ServiceMonitors/Rules |
| **CRD architecture** | Understands the Operator pattern: CRDs define desired state, Operator reconciles |

---

## 10. Custom Metrics, KEDA & Event-Driven Autoscaling

**Q:** "Your application needs to autoscale based on the number of messages in a RabbitMQ queue — not CPU or memory. How do you implement custom metrics autoscaling? Compare the custom-metrics-apiserver approach with KEDA."

**What They're Really Testing:** Whether you understand the Kubernetes custom metrics pipeline beyond the standard Resource Metrics API, and can design event-driven autoscaling with KEDA.

### Answer

**Custom Metrics Pipeline:**

```
Standard autoscaling (Resource Metrics API):
  metrics-server → HPA (CPU/Memory)

Custom autoscaling (Custom Metrics API):
  Adapter (e.g., prometheus-adapter) → HPA (any metric)

External autoscaling (External Metrics API):
  Adapter (e.g., KEDA) → HPA (external system metrics)

Stack:
┌──────────┐    ┌────────────────────┐    ┌─────┐
│ Prometheus│◄───│ prometheus-adapter  │◄───│ HPA │
│ (custom   │    │ (/apis/custom.metrics│    └─────┘
│  metrics) │    │  .k8s.io)           │
└──────────┘    └────────────────────┘
```

**KEDA (Kubernetes Event-Driven Autoscaling):**

```yaml
# KEDA: Event-driven autoscaling — scale based on external event sources
# No custom metrics adapter needed! KEDA creates/updates HPA resources directly

# KEDA architecture:
# 1. ScaledObject (CRD): defines triggers (Kafka, RabbitMQ, Prometheus, etc.)
# 2. KEDA operator: watches ScaledObjects, creates HPA
# 3. KEDA metrics adapter: serves external metrics to HPA
# 4. HPA: scales the target (Deployment, StatefulSet, etc.)

# KEDA vs prometheus-adapter:
# - KEDA: simpler, more scalers (50+), opinionated
# - prometheus-adapter: more flexible for custom Prometheus queries
# - KEDA supports: scaling to ZERO (HPA minReplicas can be 0!)
```

**KEDA ScaledObject Examples:**

```yaml
# 1. Autoscale by RabbitMQ queue depth
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: worker-scaler
  namespace: prod
spec:
  scaleTargetRef:
    name: worker-deployment          # Deployment to scale
    apiVersion: apps/v1
  minReplicaCount: 1                  # Minimum 1 replica (always on)
  maxReplicaCount: 20                 # Maximum 20 replicas
  pollingInterval: 15                 # Check queue every 15 seconds
  cooldownPeriod: 60                  # Wait 60s before scaling down
  triggers:
  - type: rabbitmq
    metadata:
      protocol: amqp09
      queueName: tasks
      mode: QueueLength               # Or: MessagesUnacked
      value: "10"                     # Scale up when queue length > 10

# 2. Autoscale by Kafka consumer lag
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: kafka-consumer-scaler
  namespace: prod
spec:
  scaleTargetRef:
    name: kafka-consumer
  minReplicaCount: 2
  maxReplicaCount: 50
  triggers:
  - type: kafka
    metadata:
      bootstrapServers: kafka-cluster:9092
      topic: orders
      consumerGroup: orders-consumer
      lagThreshold: "100"             # Scale up when lag > 100 per partition
      offsetResetPolicy: latest
    authenticationRef:
      name: keda-kafka-auth           # SASL/SCRAM authentication

# 3. Autoscale by Prometheus metric (HTTP request rate)
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: api-scaler
  namespace: prod
spec:
  scaleTargetRef:
    name: api-deployment
  minReplicaCount: 3
  maxReplicaCount: 50
  triggers:
  - type: prometheus
    metadata:
      serverAddress: http://prometheus.monitoring:9090
      metricName: http_requests_per_second
      query: |
        sum by (pod) (
          rate(http_requests_total{namespace="prod", handler="api"}[2m])
        )
      threshold: "100"               # Scale up when RPS > 100 per pod

# 4. Autoscale by CPU + custom metric (combined)
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: combined-scaler
  namespace: prod
spec:
  scaleTargetRef:
    name: my-app
  minReplicaCount: 2
  maxReplicaCount: 20
  triggers:
  - type: cpu
    metadata:
      type: Utilization
      value: "70"                    # Target 70% CPU utilization
  - type: memory
    metadata:
      type: Utilization
      value: "80"                    # Target 80% memory utilization

# 5. Scaling to ZERO (batch/worker workloads)
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: batch-worker-scale-to-zero
  namespace: prod
spec:
  scaleTargetRef:
    name: batch-worker
  minReplicaCount: 0                  # Scale to ZERO when no work!
  maxReplicaCount: 20
  triggers:
  - type: rabbitmq
    metadata:
      queueName: batch-tasks
      mode: QueueLength
      value: "1"                      # Scale from 0 to 1 when 1 message queued
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 300  # Wait 5 min before scaling to 0
```

**KEDA Advanced Configuration:**

```yaml
# ScaledObject with custom HPA behavior
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: advanced-scaler
spec:
  scaleTargetRef:
    name: my-app
  minReplicaCount: 1
  maxReplicaCount: 50
  triggers:
  - type: rabbitmq
    metadata:
      queueName: tasks
      value: "10"
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 300  # Stabilize before scaling down
          policies:
          - type: Percent
            value: 10                      # Max 10% pods removed per minute
            periodSeconds: 60
        scaleUp:
          stabilizationWindowSeconds: 0    # Scale up immediately
          policies:
          - type: Pods
            value: 5                       # Add up to 5 pods per minute
            periodSeconds: 60
          selectPolicy: Max

# Multiple triggers (scale on ANY trigger)
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: multi-trigger-scaler
spec:
  scaleTargetRef:
    name: my-app
  triggers:
  - type: rabbitmq
    metadata:
      queueName: high-priority
      value: "5"
  - type: rabbitmq
    metadata:
      queueName: low-priority
      value: "50"
  # Scale target: use the metric that suggests the most replicas (max)
```

**prometheus-adapter (Alternative to KEDA):**

```yaml
# prometheus-adapter: direct Prometheus integration for custom/external metrics
# More flexible but more complex than KEDA

apiVersion: v1
kind: ConfigMap
metadata:
  name: adapter-config
  namespace: monitoring
data:
  config.yaml: |
    rules:
    # Custom metrics (for workload-specific autoscaling)
    - seriesQuery: 'http_requests_total{namespace!="",pod!=""}'
      resources:
        overrides:
          namespace: {resource: "namespace"}
          pod: {resource: "pod"}
      name:
        matches: "^(.*)_total"
        as: "${1}_per_second"
      metricsQuery: |
        sum(rate(<<.Series>>{<<.LabelMatchers>>}[2m])) by (<<.GroupBy>>)

    # External metrics (for infrastructure autoscaling)
    - seriesQuery: 'rabbitmq_queue_messages{queue="tasks"}'
      resources:
        template: "queue"
      name:
        as: "rabbitmq_queue_depth"
      metricsQuery: |
        avg(rabbitmq_queue_messages{queue="tasks"}) by (queue)

# HPA using custom metric (with prometheus-adapter):
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-hpa
  namespace: prod
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-deployment
  minReplicas: 2
  maxReplicas: 50
  metrics:
  - type: Pods
    pods:
      metric:
        name: http_requests_per_second
      target:
        type: AverageValue
        averageValue: 100
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **KEDA vs prometheus-adapter** | Can compare KEDA (simpler, 50+ scalers) vs adapter (more flexible, PromQL-based) |
| **Scaling to zero** | Knows KEDA supports minReplicaCount: 0 for event-driven workloads |
| **Multiple triggers** | Understands how KEDA combines multiple trigger metrics (max wins) |
| **Authentication** | Knows how to configure trigger authentication (SASL, TLS, API keys) |

---

## 11. Pod Logging: Fluentd, Loki, Structured Logging

**Q:** "Design a pod logging pipeline for 500 microservices producing 10TB of logs per day. How do you collect, aggregate, store, and query these logs? Compare Fluentd/Fluent Bit with Loki. How do you correlate logs with metrics and traces?"

**What They're Really Testing:** Whether you understand the Kubernetes logging model — stdout/stderr collection, log shippers, and the trade-offs between Elasticsearch (full-text search) and Loki (label-based, cost-effective).

### Answer

**Kubernetes Logging Architecture:**

```
Pod → stdout/stderr → container runtime → kubelet → log file (host)
                                                         │
                                                    ┌────▼────┐
                                                    │  Agent   │ (DaemonSet)
                                                    │ Fluentd  │
                                                    │ FluentBit│
                                                    │ Logstash │
                                                    └────┬────┘
                                                         │
                                              ┌──────────┼──────────┐
                                              ▼          ▼          ▼
                                        ┌────────┐ ┌────────┐ ┌────────┐
                                        │  Loki  │ │  ES    │ │  S3    │
                                        │        │ │ (ELK)  │ │ (cold) │
                                        └────────┘ └────────┘ └────────┘
                                              │
                                              ▼
                                        ┌────────┐
                                        │ Grafana│ (query both Loki + Prometheus)
                                        └────────┘
```

**Fluent Bit (DaemonSet):**

```yaml
# Fluent Bit: lightweight log shipper (C-based, ~5MB binary)
# vs Fluentd: heavier (Ruby, ~100MB, more plugins)
# Recommendation: Fluent Bit for edge collection, Fluentd for aggregation

apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: fluent-bit
  namespace: logging
spec:
  selector:
    matchLabels:
      app: fluent-bit
  template:
    spec:
      serviceAccountName: fluent-bit
      containers:
      - name: fluent-bit
        image: cr.fluentbit.io/fluent/fluent-bit:3.0
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 256Mi
        volumeMounts:
        - name: varlog
          mountPath: /var/log              # Host logs
          readOnly: true
        - name: varlibdockercontainers
          mountPath: /var/lib/docker/containers   # Container logs
          readOnly: true
        - name: fluent-bit-config
          mountPath: /fluent-bit/etc/
      volumes:
      - name: varlog
        hostPath:
          path: /var/log
      - name: varlibdockercontainers
        hostPath:
          path: /var/lib/docker/containers
      - name: fluent-bit-config
        configMap:
          name: fluent-bit-config

---
apiVersion: v1
kind: ConfigMap
metadata:
  name: fluent-bit-config
  namespace: logging
data:
  fluent-bit.conf: |
    [SERVICE]
        flush         1
        log_level     info
        parsers_file  parsers.conf

    [INPUT]
        name              tail
        path              /var/log/containers/*.log
        parser            cri              # CRI-O log format (or docker, containerd)
        tag               kube.*
        mem_buf_limit     50MB              # Prevent memory exhaustion
        skip_long_lines   on
        db                /var/log/flb_kube.db  # Track position (for restarts)

    [FILTER]
        name                kubernetes
        match               kube.*
        kube_url            https://kubernetes.default.svc:443
        kube_token_file     /var/run/secrets/kubernetes.io/serviceaccount/token
        kube_meta_preload_cache_dir /tmp/kube_meta
        merge_log           on              # Parse structured JSON logs
        merge_log_key       log_parsed
        keep_log            on
        labels              on              # Add k8s labels to log records
        annotations         on
        use_kubelet         on              # Use kubelet API (faster, less API pressure)

    [OUTPUT]
        name            loki
        match           *
        host            loki-gateway.logging.svc
        port            3100
        labels          job=fluentbit, namespace=$namespace, pod=$pod, container=$container
        auto_kubernetes_labels on
        label_map_path  /fluent-bit/etc/labelmap.json

  labelmap.json: |
    {
      "kubernetes": {
        "namespace": "namespace",
        "pod": "pod",
        "container": "container",
        "host": "node",
        "labels": {
          "app": "k8s_app",
          "version": "k8s_version",
          "component": "k8s_component"
        }
      }
    }

  parsers.conf: |
    [PARSER]
        name        cri
        format      regex
        regex       ^(?<time>[^ ]+) (?<stream>stdout|stderr) (?<logtag>[^ ]*) (?<message>.*)$
        time_key    time
        time_format %Y-%m-%dT%H:%M:%S.%L%z
```

**Loki (Log Aggregation):**

```yaml
# Loki: Prometheus-inspired log aggregation
# - Labels-based indexing (not full-text like Elasticsearch)
# - Cheaper: 1-2x storage cost vs ES at 10x compression
# - Perfect for: logs with structured metadata (k8s labels, trace IDs)
# - Not great for: full-text search across massive unlabeled data

# Deploy Loki (single binary for small, microservices for large):
helm upgrade --install loki grafana/loki \
  --set="deploymentMode=SingleBinary" \
  --set="loki.storage.bucketNames.chunks=loki-chunks" \
  --set="loki.storage.bucketNames.ruler=loki-ruler" \
  --set="loki.storage.bucketNames.admin=loki-admin" \
  --set="loki.storage.type=s3" \
  --set="loki.storage.s3.region=us-east-1"

# Query logs in Grafana (LogQL):
# Filter by labels
{namespace="prod", app="payment-service"} |= "error" |= "timeout"
# Filter by pod name
{namespace="prod"} |~ "payment-service-[a-z0-9]*-[a-z0-9]{5}"
# Parse JSON log line
{namespace="prod"} | json | status=500 | duration > 500ms
# Rate of errors
rate({namespace="prod"} |= "5xx" [5m])
# Aggregate by container
topk(5, sum by (container) (count_over_time({namespace="prod"}[1h])))
```

**Structured Logging Best Practices:**

```python
# BAD: unstructured logging
logger.info(f"Order {order_id} processed for user {user_id}, amount ${amount}")
# → Can't filter by order_id, user_id, or amount

# GOOD: structured logging (JSON)
logger.info("Order processed", extra={
    "event": "order.processed",
    "order_id": order_id,
    "user_id": user_id,
    "amount": amount,
    "currency": "USD",
    "payment_method": "stripe",
    "processing_time_ms": time_ms,
    "trace_id": current_trace_id,       # Correlation with distributed tracing
    "span_id": current_span_id,
})

# Produces JSON log line:
# {"time": "2024-01-15T12:00:00Z", "level": "INFO",
#  "logger": "payment_service", "message": "Order processed",
#  "event": "order.processed",
#  "order_id": "ord_12345", "user_id": "usr_678", "amount": 99.99,
#  "currency": "USD", "processing_time_ms": 245,
#  "trace_id": "abc123def456"}

# Python: use structlog library
import structlog
logger = structlog.get_logger()
logger.info("order.processed", order_id=order_id, amount=amount)

# Go: use zap or slog
logger.Info("order processed",
    zap.String("order_id", orderID),
    zap.Float64("amount", amount),
    zap.Duration("processing_time", duration),
)

# Java: use Logstash encoder
"""
<appender name="JSON" class="ch.qos.logback.core.ConsoleAppender">
    <encoder class="net.logstash.logback.encoder.LogstashEncoder"/>
</appender>
"""
```

**Log Rotation & Retention:**

```yaml
# Kubernetes Docker/containerd container log rotation:
# /var/log/containers/<pod>_<namespace>_<container>-<container-id>.log

# Container runtime log rotation config:
cat /etc/containerd/config.toml
# [plugins."io.containerd.grpc.v1.cri".containerd]
#   max_container_log_line_size = 16384

# Docker daemon log rotation:
cat /etc/docker/daemon.json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",       # Rotate log files at 10MB
    "max-file": "3"           # Keep 3 rotated files
  }
}

# Or configure per-pod:
apiVersion: v1
kind: Pod
metadata:
  name: my-app
spec:
  containers:
  - name: app
    image: my-app
    resources:
      requests:
        ephemeral-storage: "1Gi"    # Ephemeral storage for logs
      limits:
        ephemeral-storage: "2Gi"
# When pod exceeds ephemeral storage → evicted (if limit enforced)
# Align with container log rotation to prevent eviction

# Loki retention:
storage:
  schema:
    config:
      configs:
      - from: "2024-01-01"
        store: tsdb            # TSDB index (more efficient than boltdb-shipper)
        object_store: s3
        schema: v13
  retention: 744h              # 31 days (or longer for compliance)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Log shipper choice** | Can compare Fluent Bit (lightweight, edge) vs Fluentd (heavy, aggregation) |
| **Loki vs ES** | Knows Loki is label-based (cheaper, Prometheus-like) vs ES is full-text |
| **Structured logging** | Emphasizes JSON/structured logs with trace IDs for correlation |
| **Resource management** | Understands ephemeral storage limits + log rotation to prevent eviction |

---

## 12. Kubernetes Events & Audit Logs

**Q:** "A pod failed to start and the reason isn't obvious from logs or describe output. Walk through how Kubernetes events and audit logs can help diagnose the issue. What's the difference between events and audit logs? How do you persist events for historical analysis?"

**What They're Really Testing:** Whether you understand the two event systems in Kubernetes — Events (ephemeral, per-object notifications) and Audit Logs (persistent, cluster-wide API call records) — and their use in debugging.

### Answer

**Kubernetes Events:**

```yaml
# Events: ephemeral records of cluster activity
# Stored in etcd, but time-limited (default: 1 hour retention)
# Events explain WHY something happened (scheduling failure, probe failure, etc.)

# View events:
kubectl get events -n prod
kubectl get events --field-selector involvedObject.name=my-pod-abc
kubectl get events --field-selector type=Warning

# Watch events in real-time:
kubectl get events -n prod --watch

# Example events for a failing pod:
LAST SEEN   TYPE      REASON                OBJECT                  MESSAGE
5m          Warning   FailedScheduling      pod/my-app-7d4f8b9c6   0/3 nodes are available:
                                                                   1 node had taint (NoSchedule)
                                                                   2 nodes had insufficient memory
3m          Normal    Pulling               pod/my-app-7d4f8b9c6   Pulling image "my-app:latest"
3m          Warning   BackOff               pod/my-app-7d4f8b9c6   Back-off restarting failed container
2m          Warning   FailedNeedsStart      pod/my-app-7d4f8b9c6   CNI network: no IP addresses available
1m          Normal    Scheduled             pod/my-app-7d4f8b9c6   Successfully assigned to node-3
30s         Warning   Unhealthy             pod/my-app-7d4f8b9c6   Liveness probe failed: HTTP probe failed

# Event structure:
{
  "metadata": {
    "name": "my-pod-abc.17d3f9c8bf9a",
    "namespace": "prod",
    "creationTimestamp": "2024-01-15T12:00:00Z",
  },
  "involvedObject": {
    "kind": "Pod",
    "namespace": "prod",
    "name": "my-pod-abc",
    "uid": "abc123-...",
    "apiVersion": "v1"
  },
  "reason": "BackOff",              # Machine-readable reason
  "message": "Back-off restarting failed container app",
  "source": {
    "component": "kubelet",
    "host": "node-3"
  },
  "firstTimestamp": "2024-01-15T11:55:00Z",
  "lastTimestamp": "2024-01-15T12:00:00Z",
  "count": 5,                        # 5 occurrences (deduplicated)
  "type": "Warning"                  # Normal or Warning
}
```

**Event Export & Persistence:**

```yaml
# Events are ephemeral (1 hour TTL). For historical analysis, export them:

# 1. event_exporter: exports events to Prometheus
# https://github.com/opsgenie/kubernetes-event-exporter
apiVersion: apps/v1
kind: Deployment
metadata:
  name: event-exporter
  namespace: monitoring
spec:
  replicas: 1
  selector:
    matchLabels:
      app: event-exporter
  template:
    spec:
      serviceAccountName: event-exporter
      containers:
      - name: event-exporter
        image: ghcr.io/opsgenie/kubernetes-event-exporter:v1.7
        args:
        - -conf=/data/config.yaml
        volumeMounts:
        - name: config
          mountPath: /data
      volumes:
      - name: config
        configMap:
          name: event-exporter-config

---
apiVersion: v1
kind: ConfigMap
metadata:
  name: event-exporter-config
data:
  config.yaml: |
    logLevel: debug
    logFormat: json
    route:
      routes:
      - match:
          - receiver: "prometheus"
            type: "prometheus"
            metrics:
              - name: "kubernetes_event_total"
                help: "Kubernetes events"
                labels:
                  - key: "reason"
                    value: "reason"
                  - key: "type"
                    value: "type"
                  - key: "namespace"
                    value: "namespace"
                  - key: "kind"
                    value: "kind"
                  - key: "name"
                    value: "name"
                increment: true
      - match:
          - receiver: "loki"
      receivers:
      - name: "prometheus"
        prometheus: {}
      - name: "loki"
        loki:
          endpoint: http://loki-gateway.logging:3100/loki/api/v1/push
          extraLabels:
            source: event-exporter

# 2. Prometheus metrics from events:
# kubernetes_event_total{reason="BackOff", type="Warning", namespace="prod"} 5
# kubernetes_event_total{reason="FailedScheduling", type="Warning"} 12
# kubernetes_event_total{reason="NodeNotReady", type="Warning"} 1

# 3. Alert on events:
- alert: KubeEventWarningHighRate
  expr: |
    rate(kubernetes_event_total{type="Warning"}[5m]) > 10
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High rate of warning events"
```

**Kubernetes Audit Logs:**

```yaml
# Audit logs: record of ALL API server requests
# Level: None, Metadata, Request, RequestResponse
# Each line is a JSON object describing the request and response

# Enable audit logging in kube-apiserver:
# --audit-log-path=/var/log/kubernetes/audit.log
# --audit-log-maxage=30
# --audit-log-maxbackup=10
# --audit-log-maxsize=100
# --audit-policy-file=/etc/kubernetes/audit-policy.yaml

# Audit policy (what to log):
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
# Log ALL requests to secrets (sensitive!)
- level: RequestResponse
  resources:
  - group: ""
    resources: ["secrets"]

# Log all requests to pods (verbose but useful)
- level: Request
  resources:
  - group: ""
    resources: ["pods"]

# Log all mutations (create, update, patch, delete)
- level: Metadata
  verbs: ["create", "update", "patch", "delete"]

# Log authentication failures
- level: RequestResponse
  nonResourceURLs:
  - /api/*
  userGroups:
  - system:unauthenticated

# Default: log nothing
- level: None

# Audit log example:
{
  "kind": "Event",
  "level": "RequestResponse",
  "auditID": "abc123-...",
  "stage": "ResponseComplete",
  "requestURI": "/api/v1/namespaces/prod/pods/my-app-abc",
  "verb": "delete",
  "user": {
    "username": "admin",
    "uid": "user-456",
    "groups": ["system:masters", "developers"]
  },
  "sourceIPs": ["10.0.1.100"],
  "objectRef": {
    "resource": "pods",
    "namespace": "prod",
    "name": "my-app-abc",
    "apiVersion": "v1"
  },
  "responseStatus": {
    "metadata": {},
    "code": 200
  },
  "requestReceivedTimestamp": "2024-01-15T12:00:00.123Z",
  "stageTimestamp": "2024-01-15T12:00:00.456Z",
  "annotations": {
    "authorization.k8s.io/decision": "allow",
    "authorization.k8s.io/reason": "RBAC: allowed by ClusterRoleBinding"
  }
}

# Audit log use cases:
# 1. Security: who deleted the production namespace?
# 2. Debugging: who created a pod with privileged: true?
# 3. Compliance: which users accessed secrets?
# 4. Capacity: what's the API request pattern (read-heavy? write-heavy?)
```

**Events vs Audit Logs:**

```yaml
Feature            | Events              | Audit Logs
-------------------|---------------------|--------------------
Purpose            | Cluster state changes| ALL API requests
Source             | Components (kubelet, | API server (kube-apiserver)
                   | scheduler, controller)|
Storage            | etcd (1h TTL)        | Log file (configurable retention)
Granularity        | High-level reasons   | Full request/response details
Volume             | Low                  | HIGH (every API call!)
PII/Secrets        | No                   | Yes (at RequestResponse level)
Performance impact | None                 | High at RequestResponse level
Use case           | Quick debugging      | Security audit, incident investigation

# When to use:
# Events: "Why did my pod crash?" (fast, targeted)
# Audit Logs: "Who deleted the namespace?" (security, compliance)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Events vs Audit** | Understands events are high-level reasons, audit logs are full API traces |
| **Event persistence** | Knows events are ephemeral (1h TTL) and must be exported for historical analysis |
| **Audit levels** | Understands Metadata vs Request vs RequestResponse and performance costs |
| **Practical debugging** | Can describe a real debugging flow using events to trace pod failures |

---

## 13. Grafana Dashboards for Kubernetes

**Q:** "Design a comprehensive Grafana dashboard for Kubernetes cluster observability. What panels do you include at the cluster level, namespace level, and pod level? How do you use template variables to drill down from cluster to pod?"

**What They're Really Testing:** Whether you understand how to organize Kubernetes monitoring into hierarchical dashboards — from cluster health down to individual pod details — with efficient queries and template variables.

### Answer

**Dashboard Hierarchy:**

```
┌─────────────────────────────────────────────────────────────┐
│  Dashboard 1: Cluster Overview                               │
│  (for SREs, cluster operators)                               │
│  - Node health, capacity, utilization                        │
│  - Component status (API, scheduler, controller-manager)     │
│  - Total pods, deployments, services                         │
│  - API server latency, request rate, error rate              │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Dashboard 2: Namespace Overview                             │
│  (for team leads, service owners)                            │
│  - Per-namespace: pod health, resource usage, error rates    │
│  - Top 10 pods by CPU/memory usage                           │
│  - Network traffic per service                               │
│  - Recent events (warnings)                                  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Dashboard 3: Pod Detail                                    │
│  (for developers debugging specific pods)                   │
│  - Resource usage vs requests/limits                         │
│  - Container restarts and reasons                            │
│  - Probe status (readiness, liveness, startup)               │
│  - Logs (Loki integration)                                  │
│  - Recent events                                            │
└─────────────────────────────────────────────────────────────┘
```

**Cluster Overview Dashboard:**

```yaml
# Template Variables:
variables:
  - name: cluster
    type: custom
    values: ["prod-us-east", "prod-eu-west", "staging"]
  - name: datasource
    type: datasource
    values: ["Prometheus"]
    default: "Prometheus"

# Row 1: Cluster Health (Stat panels)
Stat: "Nodes Up"
  query: count(kube_node_status_condition{condition="Ready", status="true"})
  threshold: < 3 = red, < 5 = yellow
  show: current value

Stat: "CPU Utilization"
  query: 100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])))
  unit: percent

Stat: "Memory Utilization"
  query: 100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)
  unit: percent

Stat: "Total Pods"
  query: count(kube_pod_info)
  show: current value

Stat: "Pending Pods"
  query: count(kube_pod_status_phase{phase="Pending"} == 1)
  colors: [green, yellow, red]
  thresholds: [0, 5, 20]

Stat: "Warning Events (1h)"
  query: sum(rate(kubernetes_event_total{type="Warning"}[1h])) * 3600

# Row 2: Node Resource Usage (Time series)
TimeSeries: "Node CPU Usage (Top 10)"
  query: topk(10, 100 - (avg by (node)(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100))

TimeSeries: "Node Memory Usage (Top 10)"
  query: topk(10, 100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))

# Row 3: API Server Health
TimeSeries: "API Server Latency (p99)"
  query: |
    histogram_quantile(0.99,
      sum(rate(apiserver_request_duration_seconds_bucket[5m])) by (le, verb)
    )

TimeSeries: "API Server Request Rate"
  query: sum(rate(apiserver_request_total[5m])) by (verb)

# Row 4: Controller Health
Stat: "Deployments with Unavailable Replicas"
  query: count(kube_deployment_status_replicas_unavailable > 0)

Stat: "PVCs Pending"
  query: count(kube_persistentvolumeclaim_status_phase{phase="Pending"} == 1)
```

**Namespace Overview Dashboard:**

```yaml
# Template Variables:
variables:
  - name: namespace
    type: query
    query: label_values(kube_namespace_status_phase{phase="Active"}, namespace)
    multi-value: true
    include-all: true

# Selected by: cluster → namespace

Stat: "Pods Running"
  query: count(kube_pod_status_phase{phase="Running", namespace="$namespace"})

Stat: "Pods Pending"
  query: count(kube_pod_status_phase{phase="Pending", namespace="$namespace"})
  colors: [green, yellow, red]
  thresholds: [0, 1, 5]

Stat: "CPU Usage / Limits"
  query: |
    sum(rate(container_cpu_usage_seconds_total{namespace="$namespace", container!=""}[5m]))
    / sum(kube_pod_container_resource_limits{namespace="$namespace", resource="cpu"})
  unit: percent

Stat: "Memory Usage / Limits"
  query: |
    sum(container_memory_working_set_bytes{namespace="$namespace", container!=""})
    / sum(kube_pod_container_resource_limits{namespace="$namespace", resource="memory"})
  unit: percent

TimeSeries: "CPU Usage by App"
  query: |
    sum by (app) (rate(container_cpu_usage_seconds_total{namespace="$namespace"}[5m]))
  legend: {{app}}

TimeSeries: "Memory Usage by App"
  query: sum by (app) (container_memory_working_set_bytes{namespace="$namespace"})

Table: "Pods with Issues"
  query: |
    kube_pod_status_phase{phase!="Running", namespace="$namespace"} == 1
  columns: ["pod", "phase", "namespace", "node"]

Table: "Recent Warning Events"
  query: |
    topk(10, sum by (reason) (rate(kubernetes_event_total{type="Warning", namespace="$namespace"}[1h])))
```

**Pod Detail Dashboard:**

```yaml
# Template Variables:
variables:
  - name: pod
    type: query
    query: label_values(kube_pod_info{namespace="$namespace"}, pod)
  - name: container
    type: query
    query: label_values(container_cpu_usage_seconds_total{pod="$pod"}, container)

# Row 1: Pod Status
Stat: "Phase"
  query: kube_pod_status_phase{pod="$pod"}
Stat: "Node"
  query: kube_pod_info{pod="$pod"}
  # Show: node label
Stat: "Age"
  query: time() - kube_pod_start_time{pod="$pod"}
  unit: seconds → duration

# Row 2: Resource Usage
TimeSeries: "CPU Usage vs Request/Limit"
  query: |
    rate(container_cpu_usage_seconds_total{pod="$pod", container="$container"}[5m])
  queries: |
    kube_pod_container_resource_requests{pod="$pod", resource="cpu"}
    kube_pod_container_resource_limits{pod="$pod", resource="cpu"}

TimeSeries: "Memory Usage vs Request/Limit"
  query: |
    container_memory_working_set_bytes{pod="$pod", container="$container"}
  queries: |
    kube_pod_container_resource_requests{pod="$pod", resource="memory"}
    kube_pod_container_resource_limits{pod="$pod", resource="memory"}

# Row 3: Probes
TimeSeries: "Probe Results (1 = failed)"
  query: |
    prober_probe_total{pod="$pod", container="$container", result="failed"}
TimeSeries: "Probe Latency"
  query: |
    prober_probe_duration_seconds{pod="$pod", container="$container"}

# Row 4: Network
TimeSeries: "Network In/Out"
  query: |
    rate(container_network_receive_bytes_total{pod="$pod"}[5m])
    rate(container_network_transmit_bytes_total{pod="$pod"}[5m])

# Row 5: Events & Logs
Logs: "Pod Logs (Loki)"
  query: |
    {pod="$pod", namespace="$namespace"}
  datasource: Loki

Events: "Recent Pod Events"
  query: |
    {namespace="$namespace", involvedObject_name="$pod"}
  datasource: Loki (via event-exporter)
```

**Dashboard Efficiency Tips:**

```yaml
# 1. Use dashboard-level $__rate_interval
#   - Prometheus auto-selects an appropriate rate interval
#   - Prevents "interval too short" or "too much data" errors
#   - Set in Dashboard Settings → Variables → __rate_interval

# 2. Use recording rules for expensive queries
#   - Pre-compute per-pod CPU/memory usage
#   - Dashboard queries the pre-computed metric (fast)

# 3. Set max data points per panel
#   - Max data points: 1000 (limits precision but speeds up)
#   - Or use downsampling

# 4. Use query caching (Grafana Enterprise or plugin)
#   - Cache frequently-used queries for 30-60s
#   - Multiple panels use same query → hit cache

# 5. Use dashboard refresh interval
#   - Cluster overview: 30s
#   - Pod detail: 10s (but only when looking at it)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Dashboard hierarchy** | Designs cluster → namespace → pod drill-down pattern |
| **Template variables** | Uses query-based variables for dynamic filtering |
| **Query efficiency** | Employs recording rules, $__rate_interval, max data points |
| **Correlation** | Integrates metrics, logs, and events in a single pod view |

---

## 14. Pod Alerting Rules & Runbooks

**Q:** "Design a set of pager-worthy alerts for Kubernetes pods. What fires a PagerDuty alert vs a Slack notification? How do you avoid alert fatigue from transient pod issues (rolling updates, node drains, batch jobs completing)?"

**What They're Really Testing:** Whether you understand how to design alerting rules that distinguish genuine problems from expected operational noise — and how to use runbooks to ensure consistent incident response.

### Answer

**Alert Severity Classification:**

```yaml
# Alert classification:
# CRITICAL (P0) → PagerDuty → On-call engineer woken up at 3 AM
# WARNING (P1)  → Slack     → Handle during business hours
# INFO (P2)     → Dashboard → No notification (visible in dashboards)

# CRITICAL alerts must be:
# - Actionable (engineer can do something)
# - Urgent (immediate response needed)
# - Symptom-based (user-facing impact)
# - Reliable (few false positives)

# WARNING alerts should be:
# - Informational (something to investigate)
# - Lead indicators (before CRITICAL triggers)
# - Allowable during maintenance
```

**Pod Alerts:**

```yaml
groups:
  - name: kubernetes-pods-critical
    interval: 30s

    rules:
    # P0: Pod is crash-looping
    - alert: KubePodCrashLooping
      expr: |
        max by (namespace, pod, container) (
          kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"}
        ) > 0
      for: 5m           # Wait 5 min to confirm it's persistent
      labels:
        severity: critical
        team: platform
      annotations:
        summary: "Pod {{ $labels.pod }} is crash-looping"
        description: |
          Pod {{ $labels.pod }} in {{ $labels.namespace }} has been in
          CrashLoopBackOff for 5 minutes.
          Container: {{ $labels.container }}
          Exit codes: use `kubectl logs {{ $labels.pod }} --previous` to see
          last crash logs.
        runbook_url: "https://runbooks.internal/pod-crash-loop"

    # P0: Pod image pull failure
    - alert: KubePodImagePullFailed
      expr: |
        kube_pod_container_status_waiting_reason{reason="ImagePullBackOff"} > 0
        or
        kube_pod_container_status_waiting_reason{reason="ErrImagePull"} > 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Pod {{ $labels.pod }} cannot pull image"
        description: "Container {{ $labels.container }} fails to pull image.
                      Check: image name, registry credentials, network."

    # P0: Pod OOMKilled repeatedly
    - alert: KubePodOOMKilledRepeatedly
      expr: |
        rate(kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}[15m]) > 2
      labels:
        severity: critical
      annotations:
        summary: "Pod {{ $labels.pod }} OOM killed {{ $value }}x in 15m"
        description: "Container exceeding memory limit. Increase memory
                      limits or fix memory leak."
        runbook_url: "https://runbooks.internal/oom-kill"

    # P0: Pod not ready for extended period
    - alert: KubePodNotReady
      expr: |
        kube_pod_status_phase{phase="Running"} != 1
        and on (pod, namespace)
        kube_pod_status_phase{phase="Pending"} == 1
      for: 15m
      labels:
        severity: critical
      annotations:
        summary: "Pod {{ $labels.pod }} not ready for 15 minutes"
        description: "Check pod events: kubectl describe pod {{ $labels.pod }}"
        runbook_url: "https://runbooks.internal/pod-not-ready"

  - name: kubernetes-pods-warning
    interval: 30s
    rules:
    # P1: Container restarts (not crash-looping, just restarting)
    - alert: KubeContainerRestartHigh
      expr: |
        rate(kube_pod_container_status_restarts_total[15m]) > 3
      labels:
        severity: warning
      annotations:
        summary: "Container {{ $labels.container }} restarting frequently"
        description: "{{ $labels.container }} in {{ $labels.pod }} restarted
                      {{ $value }} times per hour"

    # P1: CPU throttling
    - alert: KubePodCPUThrottling
      expr: |
        rate(container_cpu_cfs_throttled_seconds_total{container!=""}[5m]) > 1
        and on (container, pod, namespace)
        container_cpu_cfs_periods_total{container!=""} > 0
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "{{ $labels.container }} CPU throttled >1s/s"
        description: "Container is being throttled. Consider increasing CPU limit."

    # P1: Pod using too much memory (near limit)
    - alert: KubePodMemoryNearLimit
      expr: |
        (
          container_memory_working_set_bytes{container!=""}
          / container_spec_memory_limit_bytes{container!=""}
        ) > 0.9
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Container using 90%+ of memory limit"
        description: "{{ $labels.container }} in {{ $labels.pod }} at
                      {{ $value | humanizePercentage }} of memory limit"

    # P1: Ephemeral storage filling up
    - alert: KubePodEphemeralStorageFull
      expr: |
        (
          sum by (pod, namespace) (container_fs_usage_bytes{container!=""})
          / sum by (pod, namespace) (
            kube_pod_container_resource_limits{resource="ephemeral-storage"} > 0
            or
            kube_pod_container_resource_requests{resource="ephemeral-storage"} > 0
          )
        ) > 0.85
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Pod {{ $labels.pod }} ephemeral storage > 85%"
        description: "Pod may be evicted. Check log rotation and temp files."

    # P1: Liveness probe failing
    - alert: KubePodLivenessProbeFailing
      expr: |
        rate(prober_probe_total{probe="liveness", result="failed"}[5m]) > 0
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Liveness probe failing for {{ $labels.pod }}"
        description: "Container will be restarted if this persists"

    # P1: Readiness probe failing
    - alert: KubePodReadinessProbeFailing
      expr: |
        rate(prober_probe_total{probe="readiness", result="failed"}[5m]) > 0
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Readiness probe failing for {{ $labels.pod }}"
        description: "Pod removed from Service endpoints"

    # P1: Pending pod (can't schedule)
    - alert: KubePodPendingScheduling
      expr: |
        kube_pod_status_phase{phase="Pending"} == 1
        and on (pod)
        (
          time() - kube_pod_start_time{pod=~".+"} > 300
        )
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Pod {{ $labels.pod }} pending for >5 min"
        description: "Check scheduling constraints, resources, node capacity.
                      kubectl describe pod {{ $labels.pod }}"

    # P1: Readiness gate fail (for service mesh sidecars)
    - alert: KubePodReadinessGateFail
      expr: |
        kube_pod_status_phase{phase="Running"} == 1
        and on (pod, namespace)
        kube_pod_status_ready_condition{condition="true"} != 1
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Pod {{ $labels.pod }} running but not ready (readiness gate)"
```

**Pod Disruption Budget Alerts:**

```yaml
# PDB alerts: warn when pods can't be evicted
- alert: KubePDBBlockingDrain
  expr: |
    kube_poddisruptionbudget_status_current_healthy
    == kube_poddisruptionbudget_status_desired_healthy
    and
    kube_poddisruptionbudget_status_current_healthy > 0
  for: 30m
  labels:
    severity: warning
  annotations:
    summary: "PDB {{ $labels.poddisruptionbudget }} may block node drains"
    description: "All {{ $labels.poddisruptionbudget }} pods are healthy
                 but PDB minAvailable prevents any eviction.
                 Increase replicas or relax PDB."

- alert: KubePDBAllPodsUnavailable
  expr: |
    kube_poddisruptionbudget_status_current_healthy == 0
    and
    kube_poddisruptionbudget_status_desired_healthy > 0
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "PDB {{ $labels.poddisruptionbudget }} has 0 healthy pods"
    description: "All pods protected by this PDB are unavailable"
```

**Avoiding Alert Fatigue:**

```yaml
# Strategy 1: Use 'for' duration
# Transient blips are normal — wait before alerting
# CPU spike: Wait 5m
# Pod restart from rolling update: Wait 10m

# Strategy 2: Exclude rolling updates with annotations
# Add annotation to pods during rolling updates:
metadata:
  annotations:
    rollingupdate: "true"
# Alert with exclusion:
expr: |
  kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"}
  unless on (pod) kube_pod_annotations{annotation="rollingupdate", value="true"}

# Strategy 3: Alert on symptoms, not causes
# BAD: "Node disk usage > 80%" (100 alerts per hour, not actionable)
# GOOD: "predict_linear(node_filesystem_free_bytes[6h], 24*3600) < 0"
#       (actionable: will run out of disk in 24 hours)

# Strategy 4: Use inhibition rules
# If node is down → suppress ALL pod alerts on that node
inhibit_rules:
  - source_match:
      alertname: 'KubeNodeNotReady'
    target_match_re:
      alertname: 'KubePod.*|KubeContainer.*'
    equal: ['node']

# Strategy 5: Use grouping
# Instead of 50 alerts (one per pod instance):
# Group by service → 1 alert: "payment-service has 3 pods crash-looping"
route:
  group_by: ['namespace', 'alertname', 'severity']
  group_wait: 1m        # Wait 1 min to collect related alerts
  group_interval: 5m    # Don't re-notify for 5 min
  repeat_interval: 4h   # Re-send every 4 hours (not every 5 min!)

# Strategy 6: Use maintenance windows for known operations
# When doing node maintenance, silence node-related alerts
curl -X POST http://alertmanager:9093/api/v2/silences \
  -H 'Content-Type: application/json' \
  -d '{
    "matchers": [
      {"name": "node", "value": "node-42", "isRegex": false},
      {"name": "severity", "value": "warning", "isRegex": false}
    ],
    "startsAt": "2024-01-15T22:00:00Z",
    "endsAt": "2024-01-15T23:00:00Z",
    "createdBy": "platform-team",
    "comment": "Node maintenance: node-42"
  }'
```

**Runbook Templates:**

```yaml
# Runbook: KubePodCrashLooping
#
# 1. CHECK: What's the exit code?
#    kubectl logs <pod> --previous
#    Exit code 0: container completed (expected if Job)
#    Exit code 1: application error (check application logs)
#    Exit code 137: OOMKilled (increase memory limit)
#    Exit code 139: SIGSEGV (segfault, application bug)
#    Exit code 143: SIGTERM (graceful shutdown)
#
# 2. CHECK: Any configuration issues?
#    kubectl describe pod <pod>
#    - Secret mounted? (Error: "secret not found")
#    - ConfigMap mounted? (Error: "configmap not found")
#    - Volume mounted? (Error: "PVC not bound")
#
# 3. CHECK: Resource pressure?
#    kubectl top pod <pod> --containers
#    - Memory > limit? → OOMKilled
#    - CPU throttling? → Increase CPU limit
#
# 4. CHECK: Application logs?
#    kubectl logs <pod> -c <container> --tail=100
#    - Exception during startup?
#    - Port already in use?
#    - Database connection refused?
#
# 5. ACTIONS:
#    a. Increase resource limits if OOM
#    b. Fix application error (deploy fix)
#    c. If config issue: update ConfigMap/Secret
#    d. If transient: rollout restart (kubectl rollout restart deployment)
#
# 6. ESCALATE: If none of the above works
#    - Check cluster health: nodes, network, control plane
#    - Check image registry availability
#    - Contact: #platform-team

# Runbook: KubePodNotReady / Pending
#
# 1. CHECK scheduling:
#    kubectl describe pod <pod>
#    Look for: Events section, FailedScheduling reason
#    - "0/5 nodes available: insufficient cpu" → scale up or reduce requests
#    - "... node taint ..." → add toleration or use different node pool
#    - "0/5 nodes available: pod has unbound PVC" → check PVC status
#
# 2. CHECK node capacity:
#    kubectl get nodes -o custom-columns=NAME:.metadata.name,CPU:.status.allocatable.cpu,MEM:.status.allocatable.memory
#    Any node with free capacity?
#
# 3. CHECK taints/tolerations:
#    kubectl describe node <node>
#    Taints: node.kubernetes.io/unschedulable:NoSchedule
#    - Does pod have toleration?
#
# 4. ACTIONS:
#    a. Scale down other workloads (free resources)
#    b. Add nodes (cluster autoscaler or manual)
#    c. Remove taints (if incorrectly applied)
#    d. Fix PVC binding
#    e. Add toleration to pod
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Alert severity** | Clearly distinguishes critical (PagerDuty) vs warning (Slack) vs info (dashboard) |
| **Alert fatigue prevention** | Uses 'for' duration, inhibition rules, grouping, maintenance windows |
| **Runbook-driven** | Each alert has a runbook with concrete steps (check → diagnose → act → escalate) |
| **Symptom over cause** | Alerts on user-facing impact, not infrastructure noise |

---

## 15. eBPF Observability: Cilium Hubble & Pixie

**Q:** "Your team is debugging a mysterious performance issue — pods are slow to respond, but CPU, memory, and network metrics look normal. How would eBPF-based observability tools like Cilium Hubble or Pixie help? What can they see that traditional monitoring can't?"

**What They're Really Testing:** Whether you understand that eBPF provides kernel-level observability without application changes — seeing TCP connections, DNS queries, HTTP requests, and kernel function execution that traditional metrics can't capture.

### Answer

**eBPF Monitoring Advantages:**

```yaml
# Traditional monitoring (Prometheus, cAdvisor):
# - Application must expose /metrics
# - Counters and gauges (aggregate data)
# - Cannot see: individual TCP connections, DNS query timing,
#              syscall latency, kernel function duration

# eBPF-based monitoring:
# - No application changes required
# - Sees EVERY syscall, TCP connection, file I/O
# - Zero instrumentation overhead (sandboxed in kernel)
# - Captures: TCP handshakes, DNS queries, HTTP requests/responses,
#             SSL/TLS handshakes, database queries
```

**Cilium Hubble (Network Observability):**

```yaml
# Hubble: Cilium's network observability layer
# Provides service-dependency graph, TCP flow logs, HTTP metrics

# Install:
cilium hubble enable
cilium hubble port-forward&
hubble observe --from-pod payment-service --to-pod database

# What Hubble sees:
# - Every TCP connection (SYN, SYN-ACK, ACK, FIN, RST)
# - DNS queries and responses
# - HTTP request/response (status code, latency, method)
# - Dropped packets (network policy violations)
# - Service mesh mutual-TLS handshake status

# Hubble CLI examples:
# View all flows for a pod:
hubble observe --pod payment-service-abc

# View drops (blocked by network policy):
hubble observe --verdict DROPPED

# View HTTP requests:
hubble observe --http

# View TCP handshake times:
hubble observe --type trace:syn,syn-ack,ack

# Hubble UI (graphical service map):
# cilium hubble ui
# Shows: services, pods, connections, dropped packets, latency

# Prometheus metrics from Hubble:
# hubble_http_requests_total{source="payment", destination="orders", method="POST"}
# hubble_http_request_duration_seconds{source="payment", destination="orders"}
# hubble_tcp_handshake_time_seconds{source="payment", destination="orders"}
# hubble_drop_total{source="payment", destination="database", reason="policy denied"}

# How to use Hubble for debugging:
# Scenario: "Payment service is slow"
# 1. Hubble shows payment-service makes many TCP connections to database
# 2. Each connection shows 10ms handshake → OK
# 3. But hubble_http_request_duration_seconds shows 500ms p99
# 4. Looking at HTTP flows: database queries take 450ms
# 5. Root cause: missing database index → 450ms query time
# 6. Without Hubble: would see "payment is slow" but not WHY
```

**Pixie (Kubernetes Debugging):**

```yaml
# Pixie: eBPF-based observability for Kubernetes
# No instrumentation needed — auto-telemetry for ALL pods

# Install:
pixie deploy

# Key Pixie features:
# 1. Auto-instrumentation: HTTP, gRPC, MySQL, Postgres, Redis, DNS, TCP
# 2. Full-body request capture (sampled)
# 3. Flame graphs for CPU profiling (per-pod, per-function!)
# 4. Continuous profiling without restarting applications
# 5. Network SQL query analysis
# 6. Service dependency graph

# Pixie CLI examples:
# View HTTP requests for a namespace
px run px/http_data -n prod

# View Redis commands
px run px/redis_data

# View MySQL queries with latency
px run px/mysql_data -n prod

# Continuous CPU profiling (no application changes!)
px run px/profile -n prod -p payment-service

# What Pixie captures automatically:
# HTTP: method, path, status, latency, request/response body (sampled)
# gRPC: service, method, status, latency, request/response (sampled)
# MySQL: query, duration, rows affected
# Postgres: query, duration, rows affected
# Redis: command, key, duration
# DNS: query, response, duration
# TCP: connections, handshake time, bytes transferred
# CPU: on-CPU flame graph (sampled at 99 Hz)
# Network: flow logs with packet metadata

# Pixie for root cause analysis:
# Scenario: "Pod is slow but CPU/Memory are fine"
# 1. Pixie continuous profile shows: function parseRequest() takes 80% of CPU time
# 2. But CPU metrics show low utilization → puzzling
# 3. Pixie HTTP data shows: many requests with large payloads (100MB+)
# 4. Root cause: client sending oversized requests → JSON parsing dominates
# 5. Fix: add request size limit on the server → problem solved

# Scenario: "Database queries are slow"
# 1. Pixie MySQL script shows slow query: SELECT * FROM orders WHERE ...
# 2. Query takes 2.5s, full table scan
# 3. Missing index identified → DBA adds index → latency drops to 5ms
```

**eBPF vs Traditional Monitoring:**

```yaml
Capability                | Prometheus/cAdvisor | eBPF (Hubble/Pixie)
--------------------------|---------------------|--------------------
CPU utilization           | ✅                  | ✅ (plus flame graphs)
Memory usage              | ✅                  | ✅
Network bytes             | ✅                  | ✅ (per-flow granularity)
TCP connections           | ❌                  | ✅ (per-TCP flow)
HTTP request/response      | ✅ (if instrumented)| ✅ (auto, no changes)
HTTP request body          | ❌                  | ✅ (sampled)
DNS queries                | ❌                  | ✅ (query, response, timing)
Database queries           | ❌                  | ✅ (MySQL, Postgres, Redis)
gRPC streaming             | ❌                  | ✅
SSL/TLS handshake          | ❌                  | ✅
Kernel syscalls            | ❌                  | ✅
Packet drops               | ❌                  | ✅ (with kernel reason)
Continuous profiling       | ❌                  | ✅ (flame graphs, on-CPU)
Service dependency graph   | ❌ (KSM + metrics) | ✅ (live, dynamic)
Application changes needed | ✅ (metrics endpoint)| ❌ (zero instrumentation)

# When to use eBPF:
# - Debugging latency issues (TCP handshake, DNS, TLS)
# - Understanding service dependencies
# - Profiling production applications without modification
# - Network policy debugging (drops, denials)
# - Security: detecting unusual syscalls, network connections

# When traditional monitoring is enough:
# - Historical dashboards for capacity planning
# - SLO-based alerting (error rates, latency percentiles)
# - Resource usage monitoring (CPU, memory, disk)
# - Long-term trend analysis

# Best practice: Use BOTH
# - Prometheus/cAdvisor: dashboards, alerts, SLOs
# - eBPF (Hubble/Pixie): deep debugging, root cause analysis
# - Correlation: Prometheus alerts → Hubble/Pixie drill-down
```

**eBPF Tools Comparison:**

```yaml
Tool              | Focus                     | Installation Complexity | Resource Overhead
------------------|---------------------------|------------------------|------------------
Cilium Hubble     | Network observability     | Medium (requires Cilium)| Low (~5% CPU)
Pixie             | Full-stack observability   | Low (helm chart)        | Low (~3% CPU, ~1GB RAM)
Parallax          | Node-level debugging       | Low                     | Very low
BPFtrace          | Custom eBPF programs       | Low (CLI tool)          | Minimal (one-time use)
Falco*            | Security (syscall monitor) | Medium (DaemonSet)      | Low

# * Falco: not strictly observability, but related eBPF tool for security
#   - Detects: shell in container, unusual file access, privilege escalation
#   - Rules: "Terminal shell in container", "Write to /etc/passwd"
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **eBPF advantages** | Articulates what eBPF sees that traditional monitoring misses (TCP, DNS, HTTP body, syscalls) |
| **Hubble vs Pixie** | Knows Hubble = network-focused, Pixie = full-stack (DB queries, CPU profiling, HTTP) |
| **Zero-instrumentation** | Emphasizes that eBPF doesn't require application changes |
| **Complementary** | Understands eBPF complements (not replaces) Prometheus for deep debugging |

---

> *All 15 sections cover the full depth of Kubernetes pod lifecycle, security, monitoring, and observability — from kernel-level cgroups to eBPF-based service mesh observability, with production-ready alerts, runbooks, and dashboards.*
