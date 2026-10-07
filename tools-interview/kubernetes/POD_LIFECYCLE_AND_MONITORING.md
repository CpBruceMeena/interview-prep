# 🐳 Pod Lifecycle, Monitoring & Observability — Staff-Level Deep Dive

> *Deep-dive into Kubernetes pod internals, lifecycle management, production monitoring, and observability — every section expects principal engineer-level depth with production incident experience.*

> **Prerequisites:** This file builds on the foundational Kubernetes content in [`INTERVIEW_QUESTIONS.md`](./INTERVIEW_QUESTIONS.md) (scheduler, networking, RBAC, storage, controllers) and Docker fundamentals in [`../docker/INTERVIEW_QUESTIONS.md`](../docker/INTERVIEW_QUESTIONS.md) (container runtime, namespaces, cgroups, images). The companion file [`PRODUCTION_CONTROL.md`](./PRODUCTION_CONTROL.md) covers GitOps, admission controllers, deployment strategies, and service mesh.
>
> **Docker monitoring** (dockerd metrics, `docker stats`, Docker events, container health) is covered in the Docker-specific sections of [`../docker/INTERVIEW_QUESTIONS.md`](../docker/INTERVIEW_QUESTIONS.md) Q1 and Q2.

---

## Table of Contents

1. [Pod Lifecycle: Phase, Conditions & Container States](#1-pod-lifecycle-phase-conditions-container-states)
2. [Init Containers, Sidecars & Ephemeral Containers](#2-init-containers-sidecars-ephemeral-containers)
3. [Probes: Startup, Readiness & Liveness in Production](#3-probes-startup-readiness-liveness-in-production)
4. [Pod QoS Classes & Resource Management](#4-pod-qos-classes-resource-management)
5. [Pod Priority, Preemption & Disruption Budgets](#5-pod-priority-preemption-disruption-budgets)
6. [Pod Security: Standards, Contexts & Admission](#6-pod-security-standards-contexts-admission)
7. [Kubernetes Monitoring Stack: kubelet, cAdvisor, Metrics Server](#7-kubernetes-monitoring-stack-kubelet-cadvisor-metrics-server)
8. [kube-state-metrics & Node Exporter](#8-kube-state-metrics-node-exporter)
9. [Prometheus Operator: ServiceMonitor, PodMonitor & Rules](#9-prometheus-operator-servicemonitor-podmonitor-rules)
10. [Custom Metrics, KEDA & Event-Driven Autoscaling](#10-custom-metrics-keda-event-driven-autoscaling)
11. [Pod Logging: Fluentd, Loki, Structured Logging](#11-pod-logging-fluentd-loki-structured-logging)
12. [Kubernetes Events & Audit Logs](#12-kubernetes-events-audit-logs)
13. [Grafana Dashboards for Kubernetes](#13-grafana-dashboards-for-kubernetes)
14. [Pod Alerting Rules & Runbooks](#14-pod-alerting-rules-runbooks)
15. [eBPF Observability: Cilium Hubble & Pixie](#15-ebpf-observability-cilium-hubble-pixie)

---

## 1. Pod Lifecycle: Phase, Conditions & Container States

**Q:** "A pod is stuck in `Pending` for 10 minutes. Walk through every possible reason and how to diagnose each one. Then explain the full state machine: pod phases, pod conditions, and container states."

**What They're Really Testing:** Whether you understand the complete Kubernetes pod state machine — the difference between pod-level and container-level state, and can systematically debug any pod lifecycle issue.

### Answer

!!! tip "30-second answer"
    `Pending` means the pod is accepted but either **not scheduled yet** (check the `PodScheduled` condition and scheduler events: insufficient requests headroom, taints, affinity, unbound or wrong-zone PVC, quota) or **scheduled but containers not created yet** (image pull, volume attach/mount, CNI sandbox setup, init containers). `kubectl describe pod` events tell you which half you're in within seconds. Phase is a coarse summary; conditions and per-container states carry the real signal.

**Pod Phases (High-Level Lifecycle):**

```
           ┌──────────┐
           │ Pending  │ ◄── Accepted; not scheduled yet, or images/volumes/init still in progress
           └────┬─────┘
                │
                ▼
           ┌──────────┐
    ┌──────│ Running  │◄────── Bound to a node, all containers created,
    │      └────┬─────┘        at least one running (or starting/restarting)
    │           │
    │      ┌────▼─────┐
    │      │ Succeeded│◄────── All containers terminated with exit 0, won't restart
    │      └──────────┘        (only reachable with restartPolicy Never/OnFailure)
    │
    │      ┌──────────┐
    └─────►│  Failed  │◄────── All containers terminated, at least one failed,
           └──────────┘        and it won't be restarted

           ┌──────────┐
           │ Unknown  │◄────── State can't be obtained (usually node unreachable)
           └──────────┘

A Deployment pod (restartPolicy: Always) whose container keeps crashing stays in
phase Running; "CrashLoopBackOff" is a container waiting reason, not a phase.
"Terminating" in kubectl output is also not a phase: it means deletionTimestamp is set.
```

**Why is my pod Pending? (diagnosis order)**

| Symptom in `kubectl describe pod` | Cause | Fix |
|---|---|---|
| `FailedScheduling: Insufficient cpu/memory` | Sum of **requests** doesn't fit any node | Lower requests, add nodes (check autoscaler logs: max size, instance availability) |
| `node(s) had untolerated taint` | Taints (GPU, dedicated, control-plane) | Add toleration or target other nodes |
| `didn't match Pod's node affinity/selector` | Label typo, zone pinning | Fix selector or label nodes |
| `pod has unbound immediate PersistentVolumeClaims` / `volume node affinity conflict` | PVC can't bind, or the disk lives in another zone | `WaitForFirstConsumer` StorageClass; check provisioner |
| `didn't satisfy existing pods anti-affinity` / topology spread | Hard spread rules with too few domains | Use `ScheduleAnyway` or add capacity in the missing zone |
| No events, pod has no `nodeName` | Scheduler down, or `schedulerName` points at a scheduler that doesn't exist; scheduling gates (`spec.schedulingGates`) not removed | Check scheduler, remove gate |
| Scheduled, then `FailedMount` / `FailedAttachVolume` | CSI attach/mount problem, RWO volume still attached elsewhere | Check VolumeAttachment, old node |
| Scheduled, `FailedCreatePodSandBox` | CNI out of IPs / misconfigured | Check CNI pods, subnet/ENI capacity |
| `ResourceQuota exceeded` | Never even created as a pod; the ReplicaSet shows `FailedCreate` | Raise quota or add requests (quota requires them) |

**Pod Conditions (Detailed Status):**

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/k8s-pod-lifecycle.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — Pod Lifecycle State Machine — Pending → Running → Succeeded/Failed with container states. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>



```yaml
# Conditions are individual status signals, each with True/False/Unknown
# A pod can have multiple conditions simultaneously

# Example: a pod whose readiness probe is failing
conditions:
  - type: PodScheduled              # Bound to a node?
    status: "True"
  - type: PodReadyToStartContainers # Sandbox + networking created by the runtime/CNI?
    status: "True"
  - type: Initialized               # All init containers done (sidecars started)?
    status: "True"
  - type: ContainersReady           # All containers passing readiness?
    status: "False"
    reason: ContainersNotReady
    message: "containers with unready status: [app]"
  - type: Ready                     # ContainersReady AND all readinessGates true
    status: "False"                 # → pod removed from Service EndpointSlices
    reason: ContainersNotReady
# The probe failure itself shows up as an event:
#   Warning  Unhealthy  Readiness probe failed: HTTP probe failed with statuscode: 503
# readinessGates let external controllers (e.g. AWS LB controller) add conditions
# that must also be True before the pod counts as Ready.
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

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/k8s-container-states.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — Container States — Waiting → Running → Terminated with common failure reasons. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>



| Reason | Meaning | Diagnosis |
|--------|---------|-----------|
| `ContainerCreating` | Container is being created (image pull, volume mount, sandbox) | Check events for `FailedMount`, `FailedCreatePodSandBox`, slow pulls |
| `PodInitializing` | Init containers running | `kubectl logs <pod> -c <init-container>` |
| `ImagePullBackOff` | Image pull failed (backing off) | Check image name, registry credentials, network |
| `ErrImagePull` | Image pull failed (initial attempt) | `kubectl describe pod <pod>` for events |
| `CrashLoopBackOff` | Container starts and crashes repeatedly | Check logs, exit codes, resource limits |
| `CreateContainerConfigError` | Referenced ConfigMap/Secret/key missing | Check the names in `env`/`envFrom`/volumes |
| `CreateContainerError` | Runtime failed to create the container | Check volume mounts, security context, command |
| `InvalidImageName` | Image name is invalid | Check image:tag syntax |

**CrashLoopBackOff Deep Dive:**

```bash
# Diagnosis commands
kubectl get pods -o wide                    # Check node and pod IP
kubectl describe pod <pod>                  # Events, conditions, container states
kubectl logs <pod> -c <container> --previous # Logs from the PREVIOUS (crashed) instance
kubectl logs <pod> --all-containers         # Logs from all containers

# CrashLoopBackOff backoff progression (kubelet defaults):
# 10s → 20s → 40s → 80s → 160s → 300s (capped at 5 min)
# Resets after the container runs 10 minutes without crashing.
# Since 1.32/1.33 there are alpha gates to tune this (per-node max, faster default decay).

# Common causes:
# 1. OOMKilled: container exceeded memory limit
#    → kubectl describe pod | grep -A5 "State:"
#    Check: Last State: Terminated / Reason: OOMKilled / Exit Code: 137
#
# 2. Missing config: configmap or secret not mounted
#    → Container can't read configuration → panics → crashes
#    Check: env vars, volume mounts in describe output
#
# 3. App error on startup (bad flag, failed migration, can't bind port)
#    → Exit code 1 (or whatever the app returns); read logs --previous
#    Exit 137 = SIGKILL (OOM or liveness kill), 143 = SIGTERM, 126/127 = command not executable/found
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
    # If migration fails → kubelet retries this init container with backoff
    # (Init:CrashLoopBackOff). Caveat: with 10 replicas, 10 pods race to migrate.
    # Prefer a pre-deploy Job (Helm hook / Argo sync wave) or a migration lock.

  containers:
  - name: main-app                       # Runs after both init containers succeed
    image: my-app:v1.2.3
    ports:
    - containerPort: 8080

# Key behaviors:
# - Init containers can have different images and resource requests than main
# - Init containers can hold tools/secrets the main image shouldn't (least privilege)
# - If an init container fails: with restartPolicy Always/OnFailure the kubelet retries
#   it with backoff; with restartPolicy Never the whole pod goes Failed
# - Init containers must be idempotent: they re-run if the pod sandbox is recreated
# - Init containers with restartPolicy: Always are native sidecars (GA in 1.33)
```

**Init Container Use Cases:**

```yaml
# 1. Wait for dependencies (database, cache, service mesh)
# 2. Run schema migrations
# 3. Generate configuration files from templates
# 4. Pre-populate shared volumes (emptyDir)
# 5. Check license keys or security policies
# 6. Download model files for ML inference

# Resource considerations (scheduler's "effective request"):
# - Init containers run one at a time, so the init part = the LARGEST single
#   init container request (plus any sidecars already started before it)
# - Pod effective request = max(sum of app containers + sidecars, init part)
# - So a 4Gi migration init container makes the whole pod need 4Gi to schedule
```

**Native Sidecar Containers (beta and on by default in 1.29, GA in 1.33):**

```yaml
# A sidecar is an initContainer with restartPolicy: Always.
# It starts in init order, then keeps running alongside the main containers.

apiVersion: v1
kind: Pod
metadata:
  name: app-with-sidecar
spec:
  initContainers:
  - name: logging-sidecar                # Sidecar (runs alongside)
    image: fluent/fluent-bit:3.2
    restartPolicy: Always                # ← This makes it a sidecar!
    # Optional startupProbe: the next init container waits until it succeeds
    volumeMounts:
    - name: logs
      mountPath: /var/log/app

  - name: wait-for-db                    # True init (runs first)
    image: busybox:1.36
    command: ['sh', '-c', 'until nc -z db 5432; do sleep 2; done']

  containers:
  - name: main-app
    image: my-app:v1.2.3
    volumeMounts:
    - name: logs
      mountPath: /var/log/app

# What native sidecars guarantee:
# - Start order: the next init container starts once the sidecar is STARTED
#   (and its startupProbe passed, if set), so the mesh proxy is up before the app
# - Restarted independently if they crash, even in restartPolicy: Never pods
# - Don't block Job completion: the Job finishes when the main containers exit
# - Shutdown: main containers get SIGTERM first; sidecars are stopped afterwards in
#   reverse start order, so the proxy/log shipper outlives the app
# - Support probes, unlike regular init containers

# Old pattern (sidecar as a regular container) problems it fixes:
# - Proxy not ready when the app starts → app's first calls fail
# - Jobs never complete because the proxy keeps running
# - Proxy killed at the same time as the app → in-flight requests dropped
```

**Ephemeral Containers (Debugging):**

```bash
# Ephemeral containers (GA in 1.25) are added to a RUNNING pod via the
# ephemeralcontainers subresource. No ports, probes or resources; never restarted;
# can't be removed (they stay until the pod is deleted).
# Ideal for distroless images that have no shell.

# Debug a running pod:
kubectl debug -it my-app-7d4f8b9c6-abc12 \
  --image=nicolaka/netshoot:latest \
  --target=main-app \
  --profile=netadmin         # adds NET_ADMIN/NET_RAW for tcpdump
# Every container already shares the pod's network namespace;
# --target additionally shares main-app's PROCESS namespace (see its PIDs, /proc/<pid>/root)

# Debug a node (creates a pod on the node, host filesystem mounted at /host):
kubectl debug node/ip-10-0-1-42 -it \
  --image=ubuntu:24.04 --profile=sysadmin

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
| **Sidecar patterns** | Understands native sidecars (GA 1.33): startup ordering, Job completion, shutdown after the app |
| **Ephemeral containers** | Knows `kubectl debug` for non-invasive troubleshooting |
| **Use case distinction** | Can articulate when to use each: init for setup, sidecar for support, ephemeral for debug |

---

## 3. Probes: Startup, Readiness & Liveness in Production

**Q:** "Your deployment has 10 replicas, but during a rolling update, traffic is routed to pods before they're ready — causing 502 errors for 15 seconds. How do you fix this? Design a probe strategy for a JVM application that takes 90 seconds to warm up, has occasional GC pauses, and should be restarted if it deadlocks."

**What They're Really Testing:** Whether you understand the three probe types and their distinct roles — startup (slow boot), readiness (traffic routing), and liveness (self-healing) — and can design a probe strategy for real application behaviors.

### Answer

!!! tip "30-second answer"
    502s during a rollout come from two windows. **Start:** a pod gets traffic before it can serve, fixed by an honest readiness probe (and a startup probe so a slow JVM isn't killed while booting). **Stop:** the old pod gets SIGTERM while load balancers and kube-proxy on other nodes still route to it, because endpoint removal and SIGTERM happen **in parallel**. Fix that with a `preStop` delay (5-15s) plus an app that drains in-flight requests on SIGTERM, all within `terminationGracePeriodSeconds`. Liveness is only for deadlocks; it never checks dependencies.

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
livenessProbe:
  initialDelaySeconds: 10
  periodSeconds: 10
  failureThreshold: 3
# No startupProbe: liveness starts after 10s and kills the container at ~40s,
# before the 90s boot finishes → restart loop forever (CrashLoopBackOff).
# (Readiness failing never restarts anything; it only withholds traffic.)
# Raising initialDelaySeconds to 120 "works" but delays detection of real deadlocks
# for every restart.
# ✅ Fix: startupProbe with failureThreshold × periodSeconds > worst-case boot

# 🔴 ANTI-PATTERN 4: Too aggressive liveness
livenessProbe:
  periodSeconds: 2      # Too frequent!
  failureThreshold: 1   # Too sensitive!
# Every GC pause, every slow request triggers restart
# ✅ Fix: 30s period, 3 failure threshold

# 🔴 ANTI-PATTERN 5: Not setting timeoutSeconds
# Default timeout is 1 second — too short for many apps
# ✅ Fix: Set timeoutSeconds to 3-5 seconds

# 🔴 ANTI-PATTERN 6: Readiness checks a SHARED dependency
# DB blips → every replica turns unready at once → Service has zero endpoints →
# clients get connection errors instead of fast, explicit 503s from your app.
# ✅ Fix: readiness reflects THIS pod's ability to serve (warmed up, not overloaded,
#    not shutting down). Handle shared-dependency outages in the app (circuit breaker,
#    degraded responses). Check a dependency in readiness only if pods can fail it
#    independently (e.g. a per-pod connection pool).
```

**Graceful termination: the other half of zero-downtime rollouts**

```
kubectl delete / rollout / drain sets deletionTimestamp. Then IN PARALLEL:

 Control plane path                         Kubelet path (on the pod's node)
 ───────────────────                        ───────────────────────────────
 EndpointSlice controller marks the pod     1. Run preStop hook (if any)
 endpoint ready=false, terminating=true     2. After preStop returns, send SIGTERM
   ↓ (watch propagation, ~0.1-2s+)             to PID 1 of each container
 kube-proxy on every node removes it        3. Wait for exit until the grace period
 Ingress/Gateway controllers, cloud LBs        (terminationGracePeriodSeconds, default
 and mesh proxies stop sending to it           30s, counted from the START of preStop)
   (cloud LB target deregistration can      4. SIGKILL anything still running
    take several seconds more)              5. Native sidecars are stopped after the
                                               main containers
```

- **Race:** if the app exits on SIGTERM immediately, requests still routed by slower components hit a closed socket → 502/connection reset. A `preStop` sleep holds SIGTERM until routing has converged.
- **Use the native sleep action** (`lifecycle.preStop.sleep.seconds`, GA in v1.34) instead of `exec: sleep`, so distroless images without a shell work.
- **The app must still handle SIGTERM**: stop accepting, finish in-flight requests, close keep-alive connections, then exit. PID 1 must actually receive the signal (use `exec` form in the Dockerfile or `tini`; a shell wrapper swallows it).
- **Budget:** `terminationGracePeriodSeconds` ≥ preStop sleep + longest request drain + margin. If preStop overruns the grace period, the kubelet gives a one-time 2s extension and then kills.
- **Long-lived connections** (WebSockets, gRPC streams) need the server to send GOAWAY/close and clients to reconnect; set a longer grace period for them.

```yaml
spec:
  terminationGracePeriodSeconds: 45
  containers:
  - name: app
    lifecycle:
      preStop:
        sleep:
          seconds: 10      # let endpoint removal propagate before SIGTERM
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
| **Termination ordering** | Knows endpoint removal and SIGTERM race; uses preStop + SIGTERM draining within the grace period |

---

## 4. Pod QoS Classes & Resource Management

**Q:** "You have three pods on a node: one with guaranteed QoS, one burstable, one best-effort. The node runs out of memory. Which pod gets killed first? Walk through the OOM kill order. How do you design resource requests/limits to ensure critical workloads survive?"

**What They're Really Testing:** Whether you understand the Kubernetes QoS model — how requests and limits map to QoS classes, and the OOM kill order when nodes are under memory pressure.

### Answer

!!! tip "30-second answer"
    Two different killers act. The **kubelet** evicts pods before the node runs out (node-pressure eviction): it ranks pods by whether usage **exceeds requests**, then by **priority**, then by how far over requests they are. So BestEffort pods (request 0) go first in practice and a Guaranteed pod within its requests is evicted last. If memory runs out faster than the kubelet reacts, the **kernel OOM killer** picks a process by `oom_score`, which the kubelet biases per QoS (`oom_score_adj` 1000 for BestEffort, -997 for Guaranteed). Separately, any container exceeding its own memory **limit** is OOM-killed by its cgroup regardless of QoS. Protect critical pods with memory request = limit, accurate requests, PriorityClass, and enough `kube-reserved`/`system-reserved`.

**QoS Classes Defined:**

```yaml
# QOS CLASS: Guaranteed
# Conditions: EVERY container (incl. init/sidecars) sets CPU and memory limits,
# and requests equal limits (if requests are omitted they default to the limits)
resources:
  requests:
    cpu: 1
    memory: 1Gi
  limits:
    cpu: 1          # Same as request
    memory: 1Gi     # Same as request
# → cgroup: CPU weight from 1 core of request (cpu.shares=1024 on v1, mapped to
#   cpu.weight on v2), CFS quota of 1 core, memory.max=1Gi
# → Eligible for exclusive CPUs with the static CPU manager policy (integer CPUs)
# → Last to be evicted, oom_score_adj = -997

# QOS CLASS: Burstable
# Conditions: not Guaranteed, and at least one container has a CPU or memory
# request or limit
resources:
  requests:
    cpu: 500m       # Base reservation
    memory: 512Mi
  limits:
    cpu: 2          # Can burst up to 2 cores
    memory: 1Gi     # Can burst up to 1Gi
# → cgroup: CPU weight from 500m request, quota of 2 cores, memory.max=1Gi
# → Can use idle node resources up to its limits
# → Evicted when usage exceeds its requests under node pressure

# QOS CLASS: BestEffort (NO requests or limits set)
# Conditions: No resource requests or limits
resources: {}   # Empty!
# → Lowest CPU weight (cpu.shares=2), no memory limit
# → Any usage is "above request" (request = 0), so evicted first under pressure
# → oom_score_adj = 1000
# → Scheduler reserves nothing for it, so it can overcommit nodes
```

**OOM Kill Order Under Memory Pressure:**

```
Three different mechanisms, in the order they usually fire:

A. Container exceeds its OWN memory limit
   → cgroup OOM inside that container, regardless of QoS or node state
   → container restarted, reason OOMKilled, exit code 137

B. Node-pressure eviction by the kubelet (memory.available < evictionHard, default 100Mi;
   optional evictionSoft with grace periods)
   Ranking of pods to evict:
     1. Is the pod's usage above its requests?   (above → evicted first)
     2. Pod priority                            (lower → evicted first)
     3. Usage minus requests                    (bigger overshoot → first)
   Net effect: BestEffort first (request 0), then Burstable pods over their requests,
   then pods within requests, Guaranteed last. Evicted pods are Failed (reason Evicted),
   and PDBs and terminationGracePeriodSeconds are NOT honoured for hard thresholds.

C. Kernel OOM killer (node ran out before the kubelet could evict)
   - Kills the process with the highest oom_score ≈ (share of node memory used × 1000)
     + oom_score_adj. The kubelet sets oom_score_adj per QoS:
       Guaranteed:  -997
       BestEffort:  1000
       Burstable:   min(max(2, 1000 - (1000 × memoryRequest / nodeMemoryCapacity)), 999)
   - So a Burstable pod with a small request relative to node size is a likely victim.
```

**Resource Management Design Patterns:**

```yaml
# Pattern 1: Reserve for critical workloads (Guaranteed)
apiVersion: v1
kind: Pod
metadata:
  name: critical-payment-processor
spec:
  priorityClassName: high-priority   # (the old critical-pod annotation was removed in 1.16)
  containers:
  - name: app
    image: registry.example.com/payments:2.3.1
    resources:
      requests:
        cpu: 2
        memory: 4Gi
      limits:
        cpu: 2
        memory: 4Gi

---
# → Guaranteed QoS + high priority = survives eviction

# Pattern 2: Burstable for elastic workloads
apiVersion: v1
kind: Pod
metadata:
  name: elastic-worker
spec:
  containers:
  - name: worker
    image: registry.example.com/worker:1.0.0
    resources:
      requests:
        cpu: 500m
        memory: 256Mi
      limits:
        cpu: 4
        memory: 1Gi

---
# → Gets baseline 500m/256Mi, bursts to 4 CPU / 1Gi when available
# → Memory above 256Mi is "borrowed": first in line for eviction under pressure.
#   A large memory limit/request gap is how nodes get overcommitted.

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

---
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

# A multi-threaded app hits the quota fast: 8 busy threads with a 2-core limit burn the
# 200ms quota in 25ms of each 100ms period, then stall for 75ms → p99 latency spikes even
# though average CPU looks fine.
# Guaranteed QoS does NOT avoid this: requests == limits still means a CFS quota.

# Throttling-aware design:
# - Common practice: set CPU requests, omit CPU limits (CPU is compressible; requests
#   still guarantee each pod its proportional share under contention)
# - Keep limits where you need tenant isolation, and size them for bursts
# - For latency-critical pods: Guaranteed with INTEGER CPUs + kubelet
#   cpuManagerPolicy: static → exclusive cores, no sharing
# - Tell the runtime its real CPU count (GOMAXPROCS via automaxprocs on older Go;
#   Go 1.25+ and modern JVMs read the cgroup limit themselves)
# - Monitor: rate(container_cpu_cfs_throttled_periods_total[5m])
#            / rate(container_cpu_cfs_periods_total[5m])
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
# - Unlike CPU, memory is NOT compressible: set memory request = limit for anything
#   important, so the scheduler reserves what the pod can actually use
# - Size from observed peak (container_memory_working_set_bytes, VPA recommendations)
#   plus 20-30% headroom for GC/surges
# - Tell the runtime its limit: -XX:MaxRAMPercentage=75 for JVM, GOMEMLIMIT for Go
# - Since v1.35, CPU and memory requests/limits can be changed in place without
#   restarting the pod (In-Place Pod Resize, GA); VPA's InPlaceOrRecreate uses this
# - cgroup v2 is required in practice: since v1.35 the kubelet refuses to start on
#   cgroup v1 nodes by default (failCgroupV1: true)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **QoS classes** | Knows the exact conditions for each class (request = limit, request < limit, no request) |
| **Eviction order** | Separates container-limit OOM, kubelet node-pressure eviction (usage vs requests, then priority) and kernel OOM (oom_score_adj) |
| **CPU throttling** | Understands CFS quota throttling, why Guaranteed doesn't avoid it, and the "no CPU limits" trade-off |
| **Resource planning** | Uses LimitRange + ResourceQuota for namespace governance |

---

## 5. Pod Priority, Preemption & Disruption Budgets

**Q:** "Your cluster is overloaded. A high-priority batch job needs to schedule, but all resources are consumed by lower-priority web servers. How does Kubernetes preempt lower-priority pods? How do PodDisruptionBudgets protect critical workloads during voluntary disruptions like node maintenance?"

**What They're Really Testing:** Whether you understand the Kubernetes priority and preemption system — how PriorityClass controls scheduling order, how preemption evicts lower-priority pods, and how PDBs limit disruption.

### Answer

!!! tip "30-second answer"
    If the batch job's PriorityClass is higher than the web servers', the scheduler's PostFilter step finds a node where deleting the fewest, lowest-priority pods makes room, nominates that node, and deletes the victims with their normal grace period. PDBs are only **best effort** for preemption. PDBs fully apply to the **Eviction API** (drains, Cluster Autoscaler/Karpenter consolidation, descheduler): an eviction that would drop healthy pods below the budget gets HTTP 429 and is retried. They don't cover node failures, node-pressure evictions, direct deletes, or a Deployment's own rolling update. In this scenario the real design question is whether batch should ever outrank user-facing web; usually it shouldn't, and batch should get its own capacity or a queue like Kueue.

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

# Priority ranges:
# > 1,000,000,000: reserved for built-ins: system-cluster-critical (2,000,000,000)
#                  and system-node-critical (2,000,001,000). Use these for CoreDNS, CNI, etc.
# ≤ 1,000,000,000: user-defined classes (negative values allowed)
# Pods with no class get the globalDefault class, or 0 if none.
# preemptionPolicy: Never → pod is queued ahead of lower priorities but never evicts anyone
#                           (good for "important but not urgent" batch)
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
# - Only pods with LOWER priority are candidates
# - Prefers nodes/victims that violate no PDB; if impossible, it violates them anyway
#   (PDBs are best effort for preemption)
# - Then: lowest highest-victim priority, fewest victims, latest start time
# - Preemption ignores inter-pod affinity of lower-priority pods on OTHER nodes, so
#   a pod with affinity to a lower-priority pod may still not fit afterwards

# What victims see:
# - Event "Preempted" and pod condition DisruptionTarget=True,
#   reason PreemptionByScheduler (useful in alerts)
# - The pod is deleted, not moved; its controller creates a replacement, which is
#   still low priority and goes Pending (and drives node autoscaling)
# - The preemptor waits with status.nominatedNodeName set; another higher-priority
#   pod can take that space first
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
# - Preemption (best effort only, see above)
# - Kubelet node-pressure eviction
# - kubectl delete pod / direct deletes (only the Eviction API checks PDBs)
# - The Deployment's own rolling update (maxUnavailable governs that)

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

---
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
#   - status.disruptionsAllowed = currentHealthy - 3 = 2
#   - If 2 pods are already unhealthy (crashing): disruptionsAllowed = 0 → drains BLOCK

# Unhealthy pods blocking drains forever was a classic outage-during-upgrade cause.
# Fix (GA in 1.31):
spec:
  unhealthyPodEvictionPolicy: AlwaysAllow   # pods that aren't Ready can always be evicted
  # default IfHealthyBudget: unready pods only evictable while the budget is intact
```

**PDB Design Patterns:**

```yaml
# Pattern 1: Critical stateful services (keep majority)
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: kafka-broker-pdb
spec:
  maxUnavailable: 1            # One broker at a time
  selector:
    matchLabels:
      app: kafka-broker

---
# With replication.factor=3 and min.insync.replicas=2, losing 1 broker keeps every
# partition writable; losing 2 brokers that share a partition makes it reject acks=all
# writes. So the budget is "1 broker at a time" regardless of cluster size.
# Same logic for quorum systems (etcd, ZooKeeper, Raft): maxUnavailable 1 for 3 or 5 members.

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

---
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

---
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

# Tier 1: Cluster infrastructure → use built-in system-cluster-critical /
#         system-node-critical (don't invent your own)
  # Pods: CoreDNS, CNI agents, CSI node plugins, kube-proxy
  # PDB: maxUnavailable 1 for Deployments like CoreDNS (DaemonSets aren't drained)

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

# Behavior when capacity runs out:
# - Scheduling (preemption): a Pending production pod evicts test, then batch pods
# - Node memory pressure (kubelet eviction): pods above their requests go first,
#   lower priority first; production pods within requests survive
# - Cluster autoscaler adds nodes for the evicted, now-Pending lower tiers
#   (unless their priority is below its expendable cutoff, default -10)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Preemption mechanics** | Knows victim selection algorithm (lowest priority, fewest pods) |
| **PDB scope** | Knows PDBs gate the Eviction API only (not deletes, node failure, node-pressure eviction or rolling updates), and are best effort for preemption |
| **PDB calculation** | Explains disruptionsAllowed = healthy - minAvailable, and unhealthyPodEvictionPolicy |
| **Priority design** | Designs multi-tier priority with corresponding PDB strategies |

---

## 6. Pod Security: Standards, Contexts & Admission

**Q:** "Your security team requires that all pods in production must: run as non-root, drop all capabilities except NET_BIND_SERVICE, use read-only root filesystem, and have seccomp profile set to RuntimeDefault. How do you enforce this across 500 pods without modifying every deployment? Design a Pod Security Standards strategy."

**What They're Really Testing:** Whether you understand the three layers of pod security — SecurityContext (pod-level), Pod Security Standards (namespace-level), and Admission Controllers (cluster-level) — and can design a defense-in-depth approach.

### Answer

!!! tip "30-second answer"
    Label production namespaces with Pod Security Admission `restricted` (start in `warn`/`audit`, then `enforce`). That covers non-root, drop ALL capabilities (only `NET_BIND_SERVICE` may be added back), no privilege escalation and seccomp `RuntimeDefault`. It does **not** cover `readOnlyRootFilesystem`, and PSA never mutates, so it can't fix 500 deployments for you. Add a policy engine (Kyverno, Gatekeeper, or built-in ValidatingAdmissionPolicy / MutatingAdmissionPolicy) to require read-only root filesystems and to **mutate in** secure defaults, then fix workloads team by team using the audit results.

**Pod Security Standards (PSA — Pod Security Admission):**

```yaml
# Pod Security Standards, enforced by the built-in Pod Security Admission controller.
# PodSecurityPolicy (policy/v1beta1) was removed in 1.25; PSA is GA since 1.25.

# Namespace enforcement labels:
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    pod-security.kubernetes.io/enforce: restricted      # REJECT violating pods
    pod-security.kubernetes.io/enforce-version: v1.37   # pin; default is "latest"
    pod-security.kubernetes.io/audit: restricted        # annotate audit log events
    pod-security.kubernetes.io/warn: restricted         # warning shown to kubectl user

# Level differences:
# PRIVILEGED: no restrictions (CNI, CSI node plugins, log/metrics agents needing host access)
# BASELINE: blocks known privilege escalations
#   - Forbids: privileged, hostNetwork/hostPID/hostIPC, hostPath volumes, hostPorts,
#     adding capabilities beyond the default set, unsafe sysctls, procMount Unmasked,
#     setting seccomp/AppArmor to Unconfined, custom SELinux user/role
# RESTRICTED: baseline plus
#   - runAsNonRoot: true (and runAsUser ≠ 0)
#   - capabilities: drop ALL; may add back only NET_BIND_SERVICE
#   - allowPrivilegeEscalation: false
#   - seccompProfile: RuntimeDefault or Localhost, set explicitly
#   - volume types limited to configMap, secret, emptyDir, PVC, projected, ephemeral, ...
# NOT in any level: readOnlyRootFilesystem, image registry rules, resource limits
#   → use Kyverno / Gatekeeper / ValidatingAdmissionPolicy for those
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
    image: registry.example.com/secure-app:1.0.0
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
      # procMount: Default (the default) keeps sensitive /proc paths masked/read-only;
      # Unmasked disables that and is forbidden by baseline

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
# 1. runAsNonRoot: true (pod or every container) and no runAsUser: 0
# 2. allowPrivilegeEscalation: false (every container)
# 3. capabilities.drop: ["ALL"] (every container), adds limited to NET_BIND_SERVICE
# 4. seccompProfile.type: RuntimeDefault or Localhost (pod or every container)
# readOnlyRootFilesystem: true is recommended hardening, enforced only by your own policy
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
    image: registry.example.com/java-app:1.0.0
    securityContext:
      runAsNonRoot: true
      readOnlyRootFilesystem: true        # Need writable volume for temp
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]                     # Port 8080 needs no capability (only <1024 does)
    volumeMounts:
    - name: tmp
      mountPath: /tmp                     # JVM writes hsperfdata, temp files, native libs here
    - name: logs
      mountPath: /var/log/app
  volumes:
  - name: tmp
    emptyDir: {}
  - name: logs
    emptyDir: {}
  # Result: app writes to /tmp (ephemeral) and /var/log/app → security compliant

---
# Node.js (temp directory for npm modules)
apiVersion: v1
kind: Pod
metadata:
  name: node-app
spec:
  containers:
  - name: node-app
    image: registry.example.com/node-app:1.0.0
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

---
# Nginx (needs to bind to port 80, write logs)
apiVersion: v1
kind: Pod
metadata:
  name: nginx
spec:
  containers:
  - name: nginx
    # The official nginx image starts as root and fails runAsNonRoot; the unprivileged
    # variant runs as UID 101 and listens on 8080.
    image: nginxinc/nginx-unprivileged:1.27
    securityContext:
      capabilities:
        drop: ["ALL"]                    # 8080 needs no NET_BIND_SERVICE
      readOnlyRootFilesystem: true
      runAsNonRoot: true
      allowPrivilegeEscalation: false
    volumeMounts:
    - name: nginx-cache
      mountPath: /var/cache/nginx        # Nginx writes temp/cache files here
    - name: nginx-tmp
      mountPath: /tmp                    # PID file in the unprivileged image
  volumes:
  - name: nginx-cache
    emptyDir: {}
  - name: nginx-tmp
    emptyDir: {}
```

**Seccomp, AppArmor & SELinux:**

```yaml
# SECCOMP (Secure Computing Mode): Filter system calls
# Approaches:
#   1. RuntimeDefault: let container runtime manage (Docker/containerd default)
#   2. Localhost: custom seccomp profile

# Custom profiles (type: Localhost) are JSON files on each node, referenced by path
# relative to the kubelet's seccomp dir. Workflow: run with a logging profile
# (defaultAction SCMP_ACT_LOG), record the syscalls actually used (the Security
# Profiles Operator automates this), then ship an allow-list profile with
# defaultAction SCMP_ACT_ERRNO. Hand-written allow-lists break on library upgrades,
# so most teams stop at RuntimeDefault, which already blocks dozens of dangerous
# syscalls (mount, kexec_load, reboot, ptrace in many runtimes, ...).

# APPARMOR: path-based MAC (Ubuntu/Debian). GA in 1.30 as a securityContext field;
#           the old container.apparmor.security.beta.kubernetes.io annotation is deprecated.
# SELinux: label-based MAC (RHEL/Fedora/Bottlerocket).

# For restricted compliance:
securityContext:
  seccompProfile:
    type: RuntimeDefault      # Must be set explicitly for restricted
  appArmorProfile:
    type: RuntimeDefault      # Field replaces the annotation (1.30+)
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
    pod-security.kubernetes.io/enforce-version: v1.37
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted

---
# Before flipping enforce, see what would break (server-side dry run prints warnings):
#   kubectl label --dry-run=server --overwrite ns --all \
#     pod-security.kubernetes.io/enforce=restricted

# Step 2: System namespaces stay privileged
apiVersion: v1
kind: Namespace
metadata:
  name: kube-system
  labels:
    pod-security.kubernetes.io/enforce: privileged    # CNI, CSI, kube-proxy

# Step 3: Exceptions. PSA has NO per-pod override label or annotation.
# Options: put the workload in its own namespace with a lower level, or configure
# exemptions (usernames, runtimeClassNames, namespaces) in the API server's
# PodSecurity AdmissionConfiguration. Kyverno/Gatekeeper allow finer exceptions.

# Step 4: Policy engine for what PSA can't do
# - Require readOnlyRootFilesystem, approved registries, signed images, limits
# - MUTATE secure defaults into pods (Kyverno mutate, or MutatingAdmissionPolicy)
#   so the 500 existing manifests don't all need edits on day one
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
│  │  │  /metrics/resource          │   │  ← Resource metrics │
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

### 🎬 Animated Sequence Diagram
<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/k8s-monitoring-stack.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Sequence — Kubernetes Monitoring Stack — kubelet → cAdvisor → Metrics Server → HPA/kubectl top. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>



```yaml
# metrics-server: the simplest, most essential monitoring component
# Installed as a Deployment, scrapes kubelet /metrics/resource every 15s (default)
# and serves the metrics.k8s.io API through API aggregation (promoted to v1 in v1.37)

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
# 3. metrics-server scrapes all kubelets every 15s (--metric-resolution)
# 4. metrics-server aggregates and serves via Resource Metrics API
# 5. HPA, kubectl top, VPA consume from Resource Metrics API

# Limitations:
# - No network/disk metrics
# - No container restart counts
# - No filesystem usage
# - Only current values held in memory (no history): it's an autoscaling feed,
#   not a monitoring system. Use Prometheus for dashboards and alerts.
# - If metrics-server is down, HPA can't compute Resource metrics and stops scaling

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
    metadata:
      labels:
        k8s-app: metrics-server
    spec:
      containers:
      - name: metrics-server
        image: registry.k8s.io/metrics-server/metrics-server:v0.7.2
        args:
        # --kubelet-insecure-tls skips kubelet cert verification: only for dev/kind;
        # in production give kubelets serving certs signed by the cluster CA
        - --kubelet-preferred-address-types=InternalIP,Hostname,ExternalIP
        - --metric-resolution=15s        # Scrape interval (15s is the default)
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
container_cpu_cfs_periods_total{container="app"}
container_cpu_cfs_throttled_periods_total{container="app"}   # ratio to periods = throttling %
container_cpu_cfs_throttled_seconds_total{container="app"}

# ── Memory ──
container_memory_usage_bytes{container="app", pod="my-app-abc"}    # includes page cache
container_memory_working_set_bytes{container="app"}   # usage minus inactive file cache:
                                                      # what the OOM killer and kubelet eviction
                                                      # look at, and what kubectl top shows
container_memory_rss{container="app"}                 # anonymous memory
container_memory_cache{container="app"}
container_oom_events_total{container="app"}           # OOM kills seen by cAdvisor
container_memory_failures_total{container="app"}      # page FAULTS (pgfault/pgmajfault),
                                                      # NOT OOMs, despite the name

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
# - OOM detection: kube-state-metrics last_terminated_reason="OOMKilled" + restart count,
#   or cAdvisor container_oom_events_total
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
                   probe_type="Readiness", result="successful"} 10
prober_probe_total{container="app", pod="my-app", namespace="prod",
                   probe_type="Readiness", result="failed"} 2

# Key metrics:
prober_probe_total                                       # Count of probe results
prober_probe_duration_seconds{probe_type="Readiness"}    # Probe latency histogram

# Alert queries:
# Readiness failures per second, per pod
rate(prober_probe_total{result="failed", probe_type="Readiness"}[5m]) > 0.05
# Probes getting slow (close to timeoutSeconds = about to start failing)
histogram_quantile(0.99, sum by (le, pod) (rate(prober_probe_duration_seconds_bucket[5m]))) > 2
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Metrics sources** | Can differentiate kubelet metrics, cAdvisor, and metrics-server by endpoint and use case |
| **metrics-server role** | Knows it's for Resource Metrics API (HPA, kubectl top), not detailed monitoring |
| **cAdvisor depth** | Knows specific metric names: container_memory_working_set_bytes (what OOM/eviction use), throttled periods ratio |
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

# Events: KSM does NOT export Events. Ship them with an event exporter
# (kubernetes-event-exporter, Grafana Alloy/OTel k8sobjects receiver) — see §12.

# Alert examples using KSM:
# 1. Pod in CrashLoopBackOff:
kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"} > 0
# 2. Deployment with unavailable replicas:
kube_deployment_status_replicas_unavailable > 0
# 3. PVC stuck in Pending:
kube_persistentvolumeclaim_status_phase{phase="Pending"} > 0
# 4. Node not ready (add `for: 5m` in the rule):
kube_node_status_condition{condition="Ready", status="true"} == 0
# 5. HPA at max replicas (can't scale further):
kube_horizontalpodautoscaler_status_current_replicas == kube_horizontalpodautoscaler_spec_max_replicas
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

# Collectors: toggle with --collector.<name> / --no-collector.<name>.
# Most useful ones are on by default (cpu, meminfo, diskstats, filesystem, netdev,
# netstat, conntrack, loadavg, pressure (PSI), sockstat, textfile, ...).
# Commonly turned on explicitly: systemd, processes, interrupts, tcpstat.
# Check `node_exporter --help` for the exact defaults of your version.

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
    metadata:
      labels:
        app: node-exporter
    spec:
      hostPID: true                          # Access host process info
      hostNetwork: true                       # Access host network stats
      tolerations:
      - operator: Exists                      # run on every node, tainted ones too
      containers:
      - name: node-exporter
        image: quay.io/prometheus/node-exporter:v1.9.1
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

    # Pod-level alerts (OOM, image pull, restarts, throttling, probes, Pending) are
    # collected in §14 with their severities and runbooks.

    - alert: KubeDeploymentReplicasMismatch
      expr: |
        kube_deployment_spec_replicas != kube_deployment_status_replicas_available
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Deployment {{ $labels.deployment }} replicas mismatch"
        description: "{{ $labels.namespace }}/{{ $labels.deployment }} has had unavailable replicas for 10m"

    - alert: KubePersistentVolumeUsageCritical
      expr: |
        kubelet_volume_stats_available_bytes / kubelet_volume_stats_capacity_bytes < 0.05
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "PV usage critical for {{ $labels.persistentvolumeclaim }}"

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
  version: v3.5.0                        # Prometheus 3.x (3.5 is an LTS release)
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

!!! tip "30-second answer"
    HPA only reads three aggregated APIs: `metrics.k8s.io` (metrics-server: CPU/memory), `custom.metrics.k8s.io` (per-object metrics) and `external.metrics.k8s.io` (things outside the cluster, like queue depth). Something must serve those APIs. **prometheus-adapter** translates PromQL into them; **KEDA** serves `external.metrics.k8s.io` from 70+ built-in scalers (RabbitMQ, Kafka, SQS, Prometheus...) and creates the HPA for you. KEDA also handles **0 ↔ 1** (activation) itself, which plain HPA only gained as a beta feature in v1.37. For a RabbitMQ queue, use KEDA with `QueueLength` and a per-replica target, a `TriggerAuthentication` for credentials, and size `maxReplicaCount` against what the downstream (DB) can absorb.

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
# KEDA: Event-driven autoscaling — scale based on external event sources.
# KEDA IS an external metrics adapter, plus an operator that writes the HPA for you.

# KEDA architecture:
# 1. ScaledObject (CRD): target + triggers (Kafka, RabbitMQ, Prometheus, SQS, cron, ...)
# 2. KEDA operator: creates/owns an HPA (keda-hpa-<name>); scales 0 → 1 when a
#    trigger is "active" and 1 → 0 after cooldownPeriod with no activity
# 3. KEDA metrics server: serves external.metrics.k8s.io to that HPA (1 ↔ N scaling)
# 4. ScaledJob (CRD): instead of scaling a Deployment, spawns one Job per batch of
#    messages (good for long-running tasks that must not be killed by scale-in)

# KEDA vs prometheus-adapter:
# - KEDA: 70+ scalers, scale to zero, auth handled by TriggerAuthentication
# - prometheus-adapter: everything must first be a Prometheus series; good when you
#   already have the metric in Prometheus and only need custom.metrics.k8s.io
# - Only ONE service can own external.metrics.k8s.io in a cluster, so KEDA and another
#   external adapter can't both serve it
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
  maxReplicaCount: 20                 # Cap at what the downstream DB can absorb
  pollingInterval: 15                 # Check queue every 15 seconds
  triggers:
  - type: rabbitmq
    metadata:
      protocol: amqp
      queueName: tasks
      mode: QueueLength               # Or: MessageRate (publish rate)
      value: "10"                     # TARGET per replica: replicas ≈ ceil(queueLength / 10)
    authenticationRef:
      name: rabbitmq-auth             # TriggerAuthentication pulling "host" (amqp URL) from a Secret

---
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
      lagThreshold: "100"             # Target average lag per replica
      # Replicas are capped at the topic's partition count by default (extra consumers
      # in a group would sit idle)
      offsetResetPolicy: latest
    authenticationRef:
      name: keda-kafka-auth           # SASL/SCRAM authentication

---
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
      # The query must return a SINGLE value (total RPS), not one series per pod
      query: |
        sum(rate(http_requests_total{namespace="prod", handler="api"}[2m]))
      threshold: "100"               # Target 100 RPS per replica → replicas ≈ total/100

---
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
    metricType: Utilization          # (metadata.type is deprecated)
    metadata:
      value: "70"                    # Target 70% CPU utilization
  - type: prometheus
    metadata:
      serverAddress: http://prometheus.monitoring:9090
      query: sum(rate(http_requests_total{service="my-app"}[2m]))
      threshold: "200"
  # cpu/memory triggers can't scale to zero (no pods → no CPU metric)

---
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
  cooldownPeriod: 300                 # 1 → 0 only after 5 min with no active trigger
  triggers:
  - type: rabbitmq
    metadata:
      queueName: batch-tasks
      mode: QueueLength
      value: "5"                      # Target 5 messages per replica (1 → N)
      activationValue: "0"            # Active (0 → 1) when queue length > 0
    authenticationRef:
      name: rabbitmq-auth
# Trade-off: the first message waits for a cold start (image pull + boot), so scale
# to zero suits batch/async work, not latency-sensitive APIs.
# Since v1.37 plain HPA can also use minReplicas: 0 (beta) with Object/External metrics.
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

---
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
    rules:                     # → custom.metrics.k8s.io
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

    externalRules:             # → external.metrics.k8s.io
    - seriesQuery: 'rabbitmq_queue_messages{queue!=""}'
      resources:
        overrides:
          namespace: {resource: "namespace"}
      name:
        as: "rabbitmq_queue_depth"
      metricsQuery: |
        sum(<<.Series>>{<<.LabelMatchers>>}) by (queue)

---
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
| **KEDA vs prometheus-adapter** | Knows KEDA is itself an external metrics adapter (70+ scalers) vs adapter (PromQL-based); only one external metrics server per cluster |
| **Scaling to zero** | Knows KEDA handles 0↔1 (activation, cooldownPeriod) and HPA 1↔N; HPA scale-to-zero is beta since v1.37; cold-start trade-off |
| **Multiple triggers** | Understands how KEDA combines multiple trigger metrics (max wins) |
| **Authentication** | Knows how to configure trigger authentication (SASL, TLS, API keys) |

---

## 11. Pod Logging: Fluentd, Loki, Structured Logging

**Q:** "Design a pod logging pipeline for 500 microservices producing 10TB of logs per day. How do you collect, aggregate, store, and query these logs? Compare Fluentd/Fluent Bit with Loki. How do you correlate logs with metrics and traces?"

**What They're Really Testing:** Whether you understand the Kubernetes logging model — stdout/stderr collection, log shippers, and the trade-offs between Elasticsearch (full-text search) and Loki (label-based, cost-effective).

### Answer

!!! tip "30-second answer"
    Apps log structured JSON to stdout. The container runtime (containerd/CRI-O) writes each container's stream to `/var/log/pods/...` in CRI format and the kubelet rotates those files. A DaemonSet agent (Fluent Bit, Vector, Grafana Alloy or the OTel Collector) tails them, adds Kubernetes metadata, and ships to a buffer or aggregator, then to storage. 10 TB/day is about 115 MB/s on average, several times that at peak, so you need a buffer (Kafka) between agents and the backend, sampling or dropping of debug logs at the edge, and object-storage-backed storage: Loki (indexes only labels, cheap) or Elasticsearch/OpenSearch (full-text index, fast arbitrary search, 5-10× the cost). Correlate by putting `trace_id` in every log line and linking Grafana's Loki ↔ Tempo ↔ Prometheus (exemplars).

**Kubernetes Logging Architecture:**

```
Pod → stdout/stderr → runtime shim (containerd / CRI-O) writes
      /var/log/pods/<ns>_<pod>_<uid>/<container>/0.log   (symlinked from /var/log/containers)
      kubelet rotates it (containerLogMaxSize 10Mi, containerLogMaxFiles 5 by default)
                                                         │
                                                    ┌────▼────┐
                                                    │  Agent   │ (DaemonSet)
                                                    │ FluentBit│
                                                    │ Vector   │
                                                    │ Alloy /  │
                                                    │ OTel Col │
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
# Fluent Bit: lightweight log shipper (C, low memory footprint)
# vs Fluentd: heavier (Ruby + C, large plugin ecosystem)
# Common pattern: Fluent Bit on every node; Fluentd/Vector/Kafka as the aggregation tier
# Since dockershim was removed (1.24), nodes run containerd or CRI-O: logs are in CRI
# format under /var/log/pods, not Docker JSON under /var/lib/docker/containers.

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
    metadata:
      labels:
        app: fluent-bit
    spec:
      serviceAccountName: fluent-bit
      tolerations:
      - operator: Exists                   # collect from every node
      containers:
      - name: fluent-bit
        image: cr.fluentbit.io/fluent/fluent-bit:4.0
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 256Mi
        volumeMounts:
        - name: varlog
          mountPath: /var/log              # /var/log/containers + /var/log/pods
        - name: fluent-bit-config
          mountPath: /fluent-bit/etc/
      volumes:
      - name: varlog
        hostPath:
          path: /var/log                   # writable: tail's position DB lives here
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
        multiline.parser  cri              # CRI format (containerd and CRI-O); joins
                                           # partial lines split by the runtime
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
        use_kubelet         on              # Get pod metadata from the local kubelet instead of
                                            # the API server (needs hostNetwork or node IP access)

    [OUTPUT]
        name            loki
        match           *
        host            loki-gateway.logging.svc
        port            3100
        # Keep Loki labels LOW-cardinality (namespace, app, container). Unbounded values
        # (trace IDs, user IDs, request IDs) as labels create a stream per value and
        # wreck Loki performance; pod names churn on every rollout, so many teams keep
        # them as structured metadata. Filter on those at query time instead.
        labels          job=fluentbit, namespace=$kubernetes['namespace_name'], app=$kubernetes['labels']['app'], container=$kubernetes['container_name']
        line_format     json

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
# - Indexes only labels; log lines are compressed chunks in object storage (S3/GCS)
# - Much cheaper to ingest and store than a full-text index; queries brute-force scan
#   the chunks selected by labels and time range (parallelised by queriers)
# - Good for: "show me errors for app X in the last hour", label-scoped grep
# - Weak at: needle-in-haystack search across everything over long time ranges
#   (Elasticsearch/OpenSearch's inverted index wins there)
# - Promtail is deprecated (EOL early 2026); Grafana Alloy is its replacement

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
# Regex match on the log LINE (not a label)
{namespace="prod", app="payment-service"} |~ "timeout|deadline exceeded"
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
# Container log files (CRI runtimes):
# /var/log/containers/<pod>_<namespace>_<container>-<container-id>.log
#   → symlink to /var/log/pods/<ns>_<pod>_<uid>/<container>/<restart>.log

# Rotation is done by the KUBELET for CRI runtimes (Docker's daemon.json log-opts
# only mattered in the dockershim era). KubeletConfiguration:
containerLogMaxSize: 10Mi        # default
containerLogMaxFiles: 5          # default
# A noisy pod writing faster than the agent reads can lose lines at rotation: watch
# the agent's lag/drop metrics.

# Container logs count toward the pod's ephemeral-storage usage:
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
# Pod exceeding its ephemeral-storage limit (logs + emptyDir + writable layer) → evicted

# Loki schema + retention (retention is enforced by the compactor):
schema_config:
  configs:
  - from: "2024-01-01"
    store: tsdb                # TSDB index (replaces boltdb-shipper)
    object_store: s3
    schema: v13
    index:
      prefix: index_
      period: 24h
compactor:
  retention_enabled: true
  delete_request_store: s3
limits_config:
  retention_period: 744h       # 31 days (per-tenant overrides possible)
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
# Events: ephemeral records of cluster activity, written by components
# (scheduler, kubelet, controllers) through the API server.
# Stored in etcd with a TTL (kube-apiserver --event-ttl, default 1h).
# Best effort: they can be rate-limited, deduplicated or dropped. Don't build
# correctness on them.

# View events (kubectl events sorts by time, unlike kubectl get events):
kubectl events -n prod --for pod/my-pod-abc
kubectl events -n prod --types=Warning
kubectl get events -n prod --sort-by=.lastTimestamp

# Watch events in real-time:
kubectl get events -n prod --watch

# Example events for a failing pod (oldest first):
LAST SEEN   TYPE      REASON                   OBJECT                    MESSAGE
6m          Warning   FailedScheduling         pod/my-app-7d4f8b9c6-x1   0/3 nodes are available: 1 node(s) had
                                                                         untolerated taint, 2 Insufficient memory
4m          Normal    Scheduled                pod/my-app-7d4f8b9c6-x1   Successfully assigned prod/... to node-3
4m          Warning   FailedCreatePodSandBox   pod/my-app-7d4f8b9c6-x1   ... failed to assign an IP address
3m          Normal    Pulling                  pod/my-app-7d4f8b9c6-x1   Pulling image "my-app:1.4.2"
1m          Warning   Unhealthy                pod/my-app-7d4f8b9c6-x1   Liveness probe failed: HTTP probe failed
30s         Warning   BackOff                  pod/my-app-7d4f8b9c6-x1   Back-off restarting failed container

# Event structure:
{
  "metadata": {
    "name": "my-pod-abc.17d3f9c8bf9a",
    "namespace": "prod",
    "creationTimestamp": "2024-01-15T12:00:00Z"
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
# Events are ephemeral (1 hour TTL). For historical analysis, export them.
# Options: kubernetes-event-exporter (the maintained fork is resmoio/
# kubernetes-event-exporter; the opsgenie repo is archived), Grafana Alloy's
# loki.source.kubernetes_events, or the OTel Collector k8s_events/k8sobjects receivers.
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
    metadata:
      labels:
        app: event-exporter
    spec:
      serviceAccountName: event-exporter   # needs get/list/watch on events
      containers:
      - name: event-exporter
        image: ghcr.io/resmoio/kubernetes-event-exporter:v1.7
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
    logLevel: info
    logFormat: json
    route:
      routes:
      - match:
        - receiver: "loki"           # send every event to Loki
    receivers:
    - name: "loki"
      loki:
        url: http://loki-gateway.logging:3100/loki/api/v1/push
        streamLabels:
          source: event-exporter

---
# Alert on events with a Loki ruler (LogQL metric query), e.g. warning-event spikes:
- alert: KubeEventWarningHighRate
  expr: |
    sum by (namespace) (
      count_over_time({source="event-exporter"} | json | type="Warning" [5m])
    ) > 50
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High rate of warning events in {{ $labels.namespace }}"
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

# Audit policy (what to log). Rules are evaluated in order; FIRST match wins.
apiVersion: audit.k8s.io/v1
kind: Policy
omitStages: ["RequestReceived"]     # halve the volume: log only when done
rules:
# Secrets/ConfigMaps/tokens: Metadata ONLY. Request/RequestResponse would write
# secret values into the audit log.
- level: Metadata
  resources:
  - group: ""
    resources: ["secrets", "configmaps", "serviceaccounts/token"]

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
# 4. Capacity: which client is hammering the API server with LISTs?
# On managed clusters (EKS, GKE, AKS) you enable audit logs through the provider and
# read them in its log service; you can't set the policy file yourself.
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
  query: sum(kube_node_status_condition{condition="Ready", status="true"})   # series are 0/1: sum, don't count
  threshold: < 3 = red, < 5 = yellow
  show: current value

Stat: "CPU Utilization"
  query: 100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])))
  unit: percent

Stat: "Memory Utilization"
  query: 100 * (1 - sum(node_memory_MemAvailable_bytes) / sum(node_memory_MemTotal_bytes))
  unit: percent

Stat: "Total Pods"
  query: count(kube_pod_info)
  show: current value

Stat: "Pending Pods"
  query: count(kube_pod_status_phase{phase="Pending"} == 1)
  colors: [green, yellow, red]
  thresholds: [0, 5, 20]

Stat: "Warning Events (1h)"          # Loki datasource (events exported, see §12)
  query: sum(count_over_time({source="event-exporter"} | json | type="Warning" [1h]))

# Row 2: Node Resource Usage (Time series)
TimeSeries: "Node CPU Usage (Top 10)"
  query: topk(10, 100 - (avg by (node)(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100))

TimeSeries: "Node Memory Usage (Top 10)"
  query: topk(10, 100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))

# Row 3: API Server Health
TimeSeries: "API Server Latency (p99)"
  query: |
    histogram_quantile(0.99,
      sum(rate(apiserver_request_duration_seconds_bucket{verb!~"WATCH|CONNECT"}[5m])) by (le, verb)
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
  query: sum(kube_pod_status_phase{phase="Running", namespace=~"$namespace"})

Stat: "Pods Pending"
  query: sum(kube_pod_status_phase{phase="Pending", namespace=~"$namespace"})
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

# cAdvisor series carry namespace/pod/container but NOT pod labels like "app";
# join with kube_pod_labels (KSM) to group by app:
TimeSeries: "CPU Usage by App"
  query: |
    sum by (label_app) (
      rate(container_cpu_usage_seconds_total{namespace="$namespace", container!=""}[$__rate_interval])
      * on (namespace, pod) group_left (label_app) kube_pod_labels{namespace="$namespace"}
    )
  legend: "{{label_app}}"

Table: "Pods with Issues"
  query: |
    kube_pod_status_phase{phase!="Running", namespace="$namespace"} == 1
  columns: ["pod", "phase", "namespace", "node"]

Logs: "Recent Warning Events"          # Loki datasource, events shipped by an exporter
  query: |
    {source="event-exporter"} | json | type="Warning" | involvedObject_namespace="$namespace"
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
TimeSeries: "Probe failures per minute"
  query: |
    sum by (probe_type) (rate(prober_probe_total{pod="$pod", container="$container", result="failed"}[$__rate_interval])) * 60
TimeSeries: "Probe Latency p99"
  query: |
    histogram_quantile(0.99, sum by (le, probe_type) (
      rate(prober_probe_duration_seconds_bucket{pod="$pod", container="$container"}[$__rate_interval])))

# Row 4: Network
TimeSeries: "Network In/Out"
  query: |
    rate(container_network_receive_bytes_total{pod="$pod"}[5m])
    rate(container_network_transmit_bytes_total{pod="$pod"}[5m])

# Row 5: Events & Logs
Logs: "Pod Logs (Loki)"
  query: |
    {namespace="$namespace", container="$container"} | pod="$pod"   # pod as structured metadata
  datasource: Loki

Logs: "Recent Pod Events"
  query: |
    {source="event-exporter"} | json | involvedObject_name="$pod"
  datasource: Loki (via event-exporter)
```

**Dashboard Efficiency Tips:**

```yaml
# 1. Use Grafana's built-in $__rate_interval in rate()/increase()
#   - Grafana computes it from the panel's step and the datasource's scrape interval
#     (at least 4× scrape interval), so rate() never gets fewer than 2 samples
#   - Hard-coded [1m] with a 30s scrape gives gaps; [1h] on a 6h panel hides spikes

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
      # restarts in the last 15m, counted only while the last termination was an OOM
      expr: |
        (increase(kube_pod_container_status_restarts_total[15m]) > 2)
        and ignoring (reason)
        (kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1)
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
        sum by (namespace, pod) (
          kube_pod_status_phase{phase=~"Pending|Unknown|Failed"}
        ) > 0
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
        increase(kube_pod_container_status_restarts_total[1h]) > 3
      labels:
        severity: warning
      annotations:
        summary: "Container {{ $labels.container }} restarting frequently"
        description: "{{ $labels.container }} in {{ $labels.pod }} restarted
                      {{ $value }} times in the last hour"

    # P1: CPU throttling
    - alert: KubePodCPUThrottling
      expr: |
        sum by (namespace, pod, container) (rate(container_cpu_cfs_throttled_periods_total{container!=""}[5m]))
        / sum by (namespace, pod, container) (rate(container_cpu_cfs_periods_total{container!=""}[5m]))
        > 0.25
      for: 15m
      labels:
        severity: warning
      annotations:
        summary: "{{ $labels.container }} throttled in >25% of CFS periods"
        description: "Raise or remove the CPU limit, or fix the hot path (see §4)."

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
        rate(prober_probe_total{probe_type="Liveness", result="failed"}[5m]) > 0
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Liveness probe failing for {{ $labels.pod }}"
        description: "Container will be restarted if this persists"

    # P1: Readiness probe failing
    - alert: KubePodReadinessProbeFailing
      expr: |
        rate(prober_probe_total{probe_type="Readiness", result="failed"}[5m]) > 0
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
        and on (namespace, pod)
        kube_pod_status_scheduled{condition="false"} == 1
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Pod {{ $labels.pod }} pending for >5 min"
        description: "Check scheduling constraints, resources, node capacity.
                      kubectl describe pod {{ $labels.pod }}"

    # P1: Running but not Ready (failing readiness probe or readiness gate)
    - alert: KubePodRunningNotReady
      expr: |
        kube_pod_status_phase{phase="Running"} == 1
        and on (pod, namespace)
        kube_pod_status_ready{condition="false"} == 1
      for: 15m
      labels:
        severity: warning
      annotations:
        summary: "Pod {{ $labels.pod }} running but not Ready for 15m"
```

**Pod Disruption Budget Alerts:**

```yaml
# PDB alerts: warn when pods can't be evicted
- alert: KubePDBBlockingDrain
  expr: |
    kube_poddisruptionbudget_status_pod_disruptions_allowed == 0
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

# Strategy 2: Alert on the WORKLOAD, not on every pod blip during rollouts
# Pods restarting or unready during a rollout are normal. Page when the rollout itself
# is stuck (Progressing=False after progressDeadlineSeconds) or availability is low:
expr: |
  kube_deployment_status_condition{condition="Progressing", status="false"} == 1
# and exclude Job pods from pod-level alerts (they're expected to terminate):
#   ... unless on (namespace, pod) kube_pod_owner{owner_kind="Job"}

# Strategy 3: Page on symptoms, ticket on causes
# PAGE: SLO burn-rate alerts (error rate / latency on user-facing endpoints)
# TICKET: causes such as "disk will fill in 24h":
#   predict_linear(node_filesystem_avail_bytes[6h], 24*3600) < 0
# BAD: static "disk > 80%" pages (noisy, often not actionable)

# Strategy 4: Use inhibition rules
# If node is down → suppress pod alerts on that node
# (pod alerts need a "node" label for this: join with kube_pod_info in the rule)
inhibit_rules:
  - source_matchers:
      - alertname = "KubeNodeNotReady"
    target_matchers:
      - alertname =~ "KubePod.*|KubeContainer.*"
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
#    (kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[*].lastState}')
#    Exit code 0: process exited "successfully" but restartPolicy Always restarts it
#                 → wrong workload type (should be a Job) or entrypoint not blocking
#    Exit code 1: application error (check application logs)
#    Exit code 137: SIGKILL. Reason OOMKilled → memory; otherwise liveness kill or
#                   grace period expired
#    Exit code 139: SIGSEGV (segfault, application bug)
#    Exit code 143: SIGTERM (killed by kubelet, e.g. liveness failure, and exited cleanly)
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
# - Low overhead (verified programs run in-kernel, no context switch per event),
#   but not zero: per-packet/per-syscall hooks cost CPU at high rates
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
# - L3/L4 by default (pure eBPF): every flow with identities, TCP flags, verdicts
# - Dropped packets with the reason (policy denied, no route, ...)
# - L7 (HTTP method/path/status/latency, DNS, Kafka) ONLY for traffic that goes through
#   Cilium's L7 proxy (Envoy), i.e. selected by an L7 network policy / visibility config
# - It does NOT parse database protocols (Postgres, MySQL) or see inside TLS

# Hubble CLI examples:
# View all flows for a pod:
hubble observe --pod payment-service-abc

# View drops (blocked by network policy):
hubble observe --verdict DROPPED

# View HTTP requests:
hubble observe --http

# View new connections (SYN) and resets:
hubble observe --tcp-flags SYN
hubble observe --tcp-flags RST

# Hubble UI (graphical service map):
# cilium hubble ui
# Shows: services, pods, connections, dropped packets, latency

# Prometheus metrics from Hubble:
# hubble_http_requests_total{source="payment", destination="orders", method="POST"}
# hubble_http_request_duration_seconds{source="payment", destination="orders"}
# hubble_tcp_flags_total{flag="RST", ...}
# hubble_drop_total{reason="POLICY_DENIED", ...}
# hubble_dns_queries_total / hubble_dns_responses_total{rcode="NXDomain"}

# How to use Hubble for debugging:
# Scenario: "Payment service is slow, CPU/memory normal"
# 1. hubble_http_request_duration_seconds: p99 500ms only on calls to orders-service
# 2. hubble observe --to-pod orders-service --verdict DROPPED: intermittent drops,
#    reason POLICY_DENIED from a recently tightened NetworkPolicy on one port
# 3. Clients retry after a timeout → latency spikes, no CPU signal anywhere
# 4. Without flow data you'd see "payment is slow" but not WHY
```

**Pixie (Kubernetes Debugging):**

```yaml
# Pixie: eBPF-based observability for Kubernetes
# No instrumentation needed — auto-telemetry for ALL pods

# Install (CLI or Helm). Pixie is a CNCF sandbox project (donated by New Relic):
px deploy

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
# 1. px/dns_data shows each outbound call to api.partner.com issuing 4 lookups:
#    the ndots:5 search-domain expansion, one of which times out at CoreDNS
# 2. That adds ~200ms to every request; nothing shows in CPU/memory metrics
# 3. Fix: trailing dot / lower ndots in dnsConfig, NodeLocal DNSCache

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
Tool                 | Focus                                   | Notes
---------------------|-----------------------------------------|------------------------------
Cilium Hubble        | Network flows, drops, L7 via proxy      | Requires Cilium as the CNI
Pixie                | Protocol tracing, profiling, in-cluster | Short in-memory retention;
                     | data (HTTP, gRPC, SQL, DNS)             | needs memory per node
Grafana Beyla / OTel | Auto-instrumented RED metrics + traces  | Exports standard OTel data
  eBPF Instrumentation |                                       | to your existing backends
Inspektor Gadget     | kubectl-native ad-hoc tracing gadgets   | Good for one-off debugging
bpftrace             | Custom one-liners on a node             | Needs node access
Falco / Tetragon     | Runtime SECURITY (syscall/process rules)| Detection, not observability:
                     |                                         | "shell in container", etc.

# Measure overhead in your own environment; it depends on traffic rate and which
# hooks/protocol parsers are enabled.
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
