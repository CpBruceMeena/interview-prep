# 📊 Prometheus & Grafana — Staff-Level Interview Questions

> *8 questions covering Prometheus architecture, PromQL, alerting, Grafana dashboards, and observability at scale — every question expects principal engineer-level depth with production patterns.*

---

## Table of Contents

1. [Prometheus Architecture: Pull Model & Time Series](#1-prometheus-architecture-pull-model-time-series)
2. [Service Discovery & Target Configuration](#2-service-discovery-target-configuration)
3. [PromQL: Queries, Aggregations, Functions](#3-promql-queries-aggregations-functions)
4. [Alerting: Alertmanager, Routing, Silences](#4-alerting-alertmanager-routing-silences)
5. [Grafana: Dashboards, Panels, Data Sources](#5-grafana-dashboards-panels-data-sources)
6. [Recording Rules & Dashboard Efficiency](#6-recording-rules-dashboard-efficiency)
7. [High Availability: Thanos, Cortex, Mimir](#7-high-availability-thanos-cortex-mimir)
8. [Observability Strategy: Metrics, Logs, Traces](#8-observability-strategy-metrics-logs-traces)

---

## 1. Prometheus Architecture: Pull Model & Time Series

**Q:** "Design a Prometheus monitoring architecture for 10,000 microservices producing 50M time series. How does the pull model differ from push-based systems (Graphite, Datadog)? How does the TSDB store and compact data? What happens when a Prometheus server can't keep up with ingestion?"

**What They're Really Testing:** Whether you understand Prometheus's fundamental architecture — the pull model's trade-offs for service discovery, the TSDB's block-based storage and compaction, and the operational limits of a single Prometheus server.

### Answer

**Pull Model vs Push:**

```yaml
Prometheus (Pull):
  - Prometheus scrapes targets at configured intervals (scrape_interval)
  - Target must expose /metrics endpoint (HTTP)
  - Pro: targets don't need to know about Prometheus (decoupled)
  - Pro: health check built-in (failed scrape = target down)
  - Pro: easier to detect when targets disappear
  - Con: requires service discovery or static config
  - Con: must scale Prometheus to handle all targets
  - Con: can't monitor short-lived jobs (batch jobs, cron)

Push (Graphite, Datadog, Pushgateway):
  - Agents push metrics to a central aggregator
  - Pro: works for short-lived jobs (Pushgateway)
  - Pro: easier for firewalled/isolated environments
  - Con: no built-in health detection
  - Con: harder to validate data integrity
  - Con: push storms can overwhelm the aggregator

Hybrid: Prometheus + Pushgateway
  - Pushgateway: proxy for batch/short-lived jobs
  - Prometheus scrapes Pushgateway (not individual jobs)
  - Trade-off: Pushgateway becomes SPOF and aggregation bottleneck
```

**TSDB Storage Format:**

```yaml
# Prometheus TSDB (2019+): block-based storage

Data directory structure:
/data/
  ├── 01EM6Q6A1ZJY7Z3X4Y5Z6A7B8C/    # Block directory (ULID)
  │   ├── chunks/
  │   │   └── 000001                   # Actual time series data (compressed)
  │   ├── index                         # In-memory index: labels → series
  │   ├── meta.json                     # Block metadata (min/max time, stats)
  │   └── tombstones                    # Deleted series markers
  ├── 01EM6Q6A2KJY7Z3X4Y5Z6A7B8D/
  ├── ...
  └── wal/                              # Write-Ahead Log (current data)
      ├── 000001.wal
      └── 000002.wal

Block lifecycle:
  1. Ingest: data written to WAL + head block (in-memory)
  2. Head compaction: 2-hour blocks written to disk (chunks + index)
  3. Block compaction: multiple blocks merged into larger blocks
     - Level 1: 2-hour blocks → 10-hour blocks
     - Level 2: 10-hour blocks → 1-day blocks
     - Level 3: 1-day blocks → 7-day blocks
  4. Retention: blocks older than retention period are deleted

Compression ratios:
  Raw samples: 16 bytes per sample (8B timestamp + 8B value)
  After compression: ~1.3 bytes per sample (12:1 compression!)
  Uses: XOR compression for floats (Facebook Gorilla paper)
```

**When Prometheus Can't Keep Up:**

```yaml
Symptoms:
  - Scrapes: "targets down" (scrape timeout)
  - Ingestion: "WAL truncation" (can't write fast enough)
  - Queries: "query timeout" (response > query timeout)
  - Storage: out of disk space

Diagnosis:
  # Check ingestion rate
  rate(prometheus_tsdb_head_samples_appended_total[5m])
  
  # Check scrape failures
  rate(prometheus_target_scrapes_exceeded_sample_limit_total[5m])
  
  # Check WAL replay time (after crash)
  prometheus_tsdb_wal_replay_duration_seconds

Solutions (in order of preference):
  1. Increase scrape interval (15s → 30s) — reduces load by 50%
  2. Reduce metrics cardinality (drop high-cardinality labels)
  3. Increase sample_limit per scrape
  4. Add more Prometheus servers (hierarchical federation)
  5. Use Thanos/Cortex for horizontal scaling
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Pull vs Push trade-offs** | Understands why pull is preferred for long-lived services, push for batch jobs |
| **TSDB compression** | Knows Gorilla XOR compression, block-based storage, compaction levels |
| **Scaling limits** | Can identify when Prometheus is overloaded and knows remediation order |
| **WAL mechanics** | Understands WAL for crash recovery, replay time proportional to WAL size |

---

## 2. Service Discovery & Target Configuration

**Q:** "Your Kubernetes cluster has 500 pods that come and go throughout the day. How does Prometheus discover these targets? Design a scrape configuration using Kubernetes service discovery. How do you handle pod labels, annotations, and relabeling for multi-team namespaces?"

**What They're Really Testing:** Whether you understand Prometheus's service discovery mechanisms and relabeling — the most operationally complex part of running Prometheus at scale.

### Answer

**Kubernetes Service Discovery:**

```yaml
# Prometheus scrape config for Kubernetes:

scrape_configs:
  - job_name: 'kubernetes-pods'
    kubernetes_sd_configs:
      - role: pod  # Discover pods
        # Other roles: node, service, endpoints, endpointslice, ingress
    
    relabel_configs:
      # Only scrape pods with prometheus.io/scrape: "true" annotation
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      
      # Use annotation for metrics path, or default to /metrics
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
        action: replace
        target_label: __metrics_path__
        regex: (.+)
        replacement: $1
      
      # Use annotation for scrape port, or default to 8080
      - source_labels: [__address__, __meta_kubernetes_pod_annotation_prometheus_io_port]
        action: replace
        target_label: __address__
        regex: ([^:]+)(?::\d+)?;(\d+)
        replacement: $1:$2
      
      # Add useful labels from Kubernetes metadata
      - source_labels: [__meta_kubernetes_namespace]
        target_label: kubernetes_namespace
      - source_labels: [__meta_kubernetes_pod_name]
        target_label: kubernetes_pod_name
      - source_labels: [__meta_kubernetes_pod_container_name]
        target_label: kubernetes_container
      - source_labels: [__meta_kubernetes_service_name]
        target_label: kubernetes_service
      
      # Add pod labels as metric labels (with namespace prefix)
      - action: labelmap
        regex: __meta_kubernetes_pod_label_(.+)
        replacement: k8s_$1

  # Service endpoints (for services with proper endpoint scraping)
  - job_name: 'kubernetes-service-endpoints'
    kubernetes_sd_configs:
      - role: endpoints
    relabel_configs:
      - source_labels: [__meta_kubernetes_service_annotation_prometheus_io_scrape]
        action: keep
        regex: true
```

**Multi-Team Namespace Isolation:**

```yaml
# Problem: teams want different scrape configs, retention, alerting rules
# Solution: separate Prometheus instances per namespace, or use relabeling

# Approach 1: Single Prometheus with relabeling (simple)
relabel_configs:
  # Add team label from namespace annotations
  - source_labels: [__meta_kubernetes_namespace]
    regex: team-a-.*
    target_label: team
    replacement: team-a
  
  - source_labels: [__meta_kubernetes_namespace]
    regex: team-b-.*
    target_label: team
    replacement: team-b
  
  # Drop all pod labels except specific ones (reduce cardinality!)
  - action: labelmap
    regex: __meta_kubernetes_pod_label_(team|service|version|component)
    replacement: k8s_$1

# Approach 2: Prometheus per namespace (isolation)
# Run one StatefulSet per team namespace
# Each with its own scrape config, retention, alerting rules
# Cost: more resource overhead, but better isolation

# Approach 3: Hierarchical federation (best for 500+ services)
# Team-level Prometheus: scrapes their own pods
# Global Prometheus: federates aggregated metrics from team Prometheuses
# Global only stores: high-level SLOs, error budgets, team-level aggregates
```

**Relabeling Mechanics:**

```yaml
# Relabeling stages (in order):
# 1. __meta_* labels: added by service discovery
# 2. __tmp_* labels: temporary labels (used in intermediate steps)
# 3. __address__, __metrics_path__, __scheme__: target endpoint
# 4. Target labels: final labels on the scraped metrics

# Common relabeling actions:
action       | Description
-------------|-------------------------------------------------------
replace      | Replace label value (default). regex → replacement
keep         | Drop targets that don't match regex
drop         | Drop targets that match regex
hashmod      | Hash source and mod by N (for sharding)
labelmap     | Map matched labels to new names
labeldrop    | Drop labels matching regex
labelkeep    | Keep only labels matching regex (DANGER: drops __meta__!)

# Cardinality control example:
# A team uses request_id as a pod label → 1M unique values → DESTROYS TSDB!
# Solution: aggressively drop high-cardinality labels
relabel_configs:
  - action: labeldrop
    regex: k8s_(request_id|trace_id|user_id|session_id)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **SD roles** | Knows pod, service, endpoints, ingress roles and when to use each |
| **Relabeling pipeline** | Understands the order of relabeling and __meta_ → target label flow |
| **Multi-team design** | Can design namespace isolation with federation or per-team Prometheus |
| **Cardinality control** | Aggressively drops high-cardinality labels before they hit TSDB |

---

## 3. PromQL: Queries, Aggregations, Functions

**Q:** "You need to compute p99 latency across 500 microservices, grouped by service and region, averaged over 5 minutes. Write the PromQL query. Explain instant vectors vs range vectors. How does PromQL handle missing data and staleness?"

**What They're Really Testing:** Whether you understand PromQL's vector matching semantics — the difference between instant and range vectors, aggregation operators, and how staleness affects query results.

### Answer

**p99 Latency Query:**

```promql
# p99 latency by service and region, 5m average:
histogram_quantile(
  0.99,
  sum by (le, service, region) (
    rate(http_request_duration_seconds_bucket[5m])
  )
)
# Returns: {service="payment", region="us-east-1"} → 0.245
#          {service="orders",  region="us-east-1"} → 0.512

# Alternative: use summary (if available)
# Summaries give pre-computed quantiles from the client side
# Problem: can't aggregate across instances (not additive!)
# Solution: use histograms (which ARE additive via sum())
```

**Instant Vectors vs Range Vectors:**

```yaml
# Instant Vector: single value per time series at a given timestamp
http_requests_total{service="payment"}
# Returns: {service="payment", instance="10.0.1.42:8080"} → 15234

# Range Vector: multiple values over a time window
http_requests_total{service="payment"}[5m]
# Returns: {service="payment", ...} → [15234@t1, 15238@t2, 15242@t3, ...]

# Functions that expect instant vectors:
#   abs(), ceil(), floor(), label_replace(), scalar(), vector()
#   >, <, == (comparison operators)

# Functions that expect range vectors:
#   rate(), increase(), irate(), delta(), deriv(), idelta()
#   avg_over_time(), min_over_time(), max_over_time()
#   quantile_over_time(), stddev_over_time(), stdvar_over_time()

# Common mistake: using rate() on an instant vector
rate(http_requests_total)  # ERROR: needs range vector!
rate(http_requests_total[5m])  # CORRECT: 5m range vector
```

**Staleness & Missing Data:**

```yaml
# Staleness rules:
# After a target stops reporting:
#   - Last sample stays valid for 5 minutes (staleness delta)
#   - After 5 minutes: metric is marked as STALE
#   - Stale markers: special NaN value in TSDB
#   - Queries: stale time series are not returned (disappear from results)

# Effect on aggregations:
# When one instance stops reporting:
#   sum by (service) (rate(http_requests_total[5m]))
#   → Sum DROPS because that instance's series is stale
#   → False negative spike! (request rate appears to drop)

# Solution: use absent() or avg() instead of sum()
# Or: use `keep_metric_names` (Prometheus 2.45+)

# Effect on rate() during counter reset:
# If a counter resets (e.g., process restart):
#   rate(my_counter[5m])
#   → Prometheus detects the reset and adjusts
#   → rate = (last_value - first_value + reset_value) / time_window
#   → Works correctly for counter resets!

# Override staleness: lookback delta
# Prometheus has 5-minute default lookback for queries
# Query uses the last sample within 5 minutes of the query timestamp
# If no sample: series not returned in results
```

**Common PromQL Patterns:**

```promql
// Error ratio: errors / total requests
sum by (service) (rate(http_requests_total{status=~"5.."}[5m]))
  / 
sum by (service) (rate(http_requests_total[5m]))
// Returns: {service="payment"} → 0.023 (2.3% error rate)

// Resource utilization: memory usage percentage
avg by (pod) (
  container_memory_working_set_bytes / container_spec_memory_limit_bytes
) * 100

// Predict disk fill (linear regression)
predict_linear(node_filesystem_free_bytes[1h], 3600 * 24) < 0
// Alerts if disk will fill up within 24 hours

// SLO burn rate: how fast are we burning through error budget
sum by (service) (rate(http_requests_total{status=~"5.."}[1h]))
  / 
sum by (service) (rate(http_requests_total[1h]))
// Compare to SLO target (e.g., 99.9% → error budget = 0.1%)
// Burn rate = error_rate / (1 - SLO_target)
// If burn rate > 1: we're exhausting error budget faster than expected
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Vector types** | Clearly distinguishes instant vs range vectors and which functions expect each |
| **histogram_quantile** | Knows how to compute percentiles from bucket counters with sum() aggregation |
| **Staleness handling** | Understands 5-minute staleness delta, stale markers, and effect on aggregations |
| **Counter resets** | Knows rate() handles counter resets automatically via monotonicity check |

---

## 4. Alerting: Alertmanager, Routing, Silences

**Q:** "Design an alerting pipeline for 500 microservices across 3 environments. How do you reduce alert fatigue? Walk through Alertmanager's grouping, inhibition, and silencing. Design a routing tree that sends critical alerts to PagerDuty and warnings to Slack."

**What They're Really Testing:** Whether you understand Alertmanager's routing and deduplication — grouping, inhibition rules, and the difference between alert state (firing/pending) and the notification pipeline.

### Answer

**Alerting Pipeline:**

```yaml
# Flow: Prometheus → Alertmanager → Notification

# Prometheus rule (in Prometheus):
groups:
  - name: latency_alerts
    rules:
      - alert: HighErrorRate
        expr: |
          sum by (service) (rate(http_requests_total{status=~"5.."}[5m]))
            /
          sum by (service) (rate(http_requests_total[5m])) > 0.05
        for: 5m  # Must be firing for 5 minutes before alerting
        labels:
          severity: critical
          team: backend
        annotations:
          summary: "{{ $labels.service }} error rate > 5%"
          description: "Service {{ $labels.service }} has {{ $value | humanizePercentage }} error rate"
          runbook_url: "https://runbooks.team/high-error-rate"

# Alert states:
#   PENDING: expr is true, but not for duration (for: 5m)
#   FIRING: expr is true for ≥ 5m → Alertmanager receives alert
#   RESOLVED: expr is no longer true → Alertmanager receives resolution
```

**Alertmanager Configuration:**

```yaml
# /etc/alertmanager/alertmanager.yml

global:
  resolve_timeout: 5m        # Auto-resolve if Alertmanager doesn't receive updates
  slack_api_url: 'https://hooks.slack.com/services/T000/B000/XXXX'
  pagerduty_url: 'https://events.pagerduty.com/v2/enqueue'

route:
  receiver: 'default'
  group_by: ['severity', 'team', 'alertname']  # Group by these labels
  group_wait: 30s            # Wait 30s to batch alerts (deduplication window)
  group_interval: 5m         # Don't send duplicate group for 5 min
  repeat_interval: 4h        # Re-send if still firing every 4 hours
  
  routes:
    # Critical alerts → PagerDuty (immediate attention)
    - match:
        severity: critical
      receiver: pagerduty-critical
      repeat_interval: 15m   # Re-notify every 15 min for critical
      continue: true          # Continue matching (also send to Slack)
    
    # Warning alerts → Slack (during business hours)
    - match:
        severity: warning
      receiver: slack-warning
      repeat_interval: 8h
    
    # Infra alerts → separate channel
    - match:
        team: infrastructure
      receiver: pagerduty-infra
      group_by: ['alertname']  # Group by alert type only

receivers:
  - name: 'pagerduty-critical'
    pagerduty_configs:
      - routing_key: 'YOUR_PD_KEY'
        severity: critical
        description: '{{ template "pagerduty.default.description" . }}'
  
  - name: 'slack-warning'
    slack_configs:
      - channel: '#alerts-warning'
        title: '{{ template "slack.title" . }}'
        text: '{{ template "slack.text" . }}'
        send_resolved: true

  - name: 'pagerduty-infra'
    pagerduty_configs:
      - routing_key: 'YOUR_INFRA_PD_KEY'
        severity: warning

inhibit_rules:
  # If a critical alert fires, suppress all warnings for the same service
  - source_match:
      severity: critical
    target_match:
      severity: warning
    equal: ['service', 'team']
  
  # If a node is down, suppress all pod-level alerts on that node
  - source_match:
      alertname: 'NodeDown'
    target_match_re:
      alertname: '.*Pod.*|.*Container.*'
    equal: ['node']

  # If Kubernetes API is down, suppress all Kubernetes alerts
  - source_match:
      alertname: 'KubeAPIDown'
    target_match: {}
```

**Alert Fatigue Reduction:**

```yaml
# Strategy 1: Alert on symptoms, not causes
# BAD: "Disk usage > 80% on 500 nodes"
# GOOD: "predict_linear will run out of disk in 4 hours" (actionable)
# GOOD: "Error budget exhaustion rate > 2x" (business impact)

# Strategy 2: Use inhibition rules
# If node is down → suppress ALL pod alerts on that node
# If service is down → suppress ALL endpoint alerts in that service

# Strategy 3: Proper grouping
# Instead of 50 alerts for HighErrorRate (one per instance):
# Group by service → 1 alert: "payment service error rate > 5%"
# Annotate with: "Affected instances: 12/15"

# Strategy 4: Urgency tiers
# Critical: page on-call (PagerDuty, OpsGenie)
# Warning: Slack (handle during business hours)
# Info: dashboard annotation (no notification)
# Allowed downtime: scheduled maintenance suppresses alerts

# Strategy 5: Silence API for planned maintenance
# alertmanager — silence management
curl -X POST http://alertmanager:9093/api/v2/silences \
  -H 'Content-Type: application/json' \
  -d '{
    "matchers": [
      {"name": "service", "value": "payment", "isRegex": false},
      {"name": "severity", "value": "warning|info", "isRegex": true}
    ],
    "startsAt": "2024-01-15T22:00:00Z",
    "endsAt": "2024-01-16T06:00:00Z",
    "createdBy": "devops-team",
    "comment": "Scheduled maintenance: payment DB migration"
  }'
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Grouping mechanics** | Knows group_by deduplicates alerts, group_interval controls re-notification speed |
| **Inhibition rules** | Understands source → target inhibition with label matching |
| **Routing tree** | Designs multi-receiver routing with severity tiers and team-based routing |
| **Repeat intervals** | Sets shorter repeat_interval for critical (15m) vs warning (4h+) |

---

## 5. Grafana: Dashboards, Panels, Data Sources

**Q:** "Design a Grafana dashboard for a multi-service platform that 5 teams use daily. How do you organize panels, use template variables, and manage dashboard provisioning? How do you handle 1000+ queries per dashboard without overloading Prometheus?"

**What They're Really Testing:** Whether you understand Grafana as an operational tool — dashboard design principles, template variables for reuse, and performance optimization for large-scale dashboards.

### Answer

**Dashboard Design Principles:**

```yaml
# Dashboard structure for multi-service platform:

# Top row: Global health
#   - Service uptime (stat panel, one per service)
#   - Overall error rate (singlestat)
#   - Request rate (time series)
#   - Error budget remaining (gauge)
#
# Second row: Service-specific (repeated per service)
#   - Request rate by endpoint (time series)
#   - Latency p50/p95/p99 (time series)
#   - Error rate by status code (bar chart)
#   - Top 5 slowest endpoints (table)
#
# Third row: Resource utilization
#   - CPU by pod (time series)
#   - Memory by pod (time series)
#   - Network I/O (time series)
#   - Restarts (stat)
#
# Fourth row: Dependencies
#   - DB query latency (time series)
#   - Cache hit rate (time series)
#   - Queue depth (gauge)
#   - Downstream service health (state timeline)

# Template variables for reuse:
Variables:
  - Name: service
    Type: query
    Query: label_values(up, service)
    Multi-value: true
    Include all: true
  
  - Name: env
    Type: query
    Query: label_values(up{service=~\"$service\"}, env)
    Multi-value: true
  
  - Name: instance
    Type: query
    Query: label_values(up{service=~\"$service\", env=~\"$env\"}, instance)
  
  - Name: interval
    Type: interval
    Values: 30s, 1m, 5m, 15m, 30m, 1h
    Default: 5m

# Panel query using variables:
# rate(http_request_duration_seconds_count{service=~\"$service\", env=~\"$env\"}[$interval])
```

**Dashboard Provisioning (IaC):**

```yaml
# Grafana dashboards as code (YAML in version control):

# /grafana/dashboards/service-overview.yaml
apiVersion: 1

providers:
  - name: 'service-overview'
    orgId: 1
    folder: 'Services'
    type: file
    disableDeletion: false
    updateIntervalSeconds: 60  # Re-check files every 60s
    allowUiUpdates: false      # Prevent drift (IaC only)
    options:
      path: /etc/grafana/dashboards/services
      foldersFromFilesStructure: true

# Dashboard JSON (can be generated from Grafana UI → JSON model):
# $ curl -X GET http://grafana:3000/api/dashboards/uid/my-dashboard > dashboard.json
# Or use grafana-dashboard-as-code tools:
#   - grafanalib (Python)
#   - grafonnet (Jsonnet)
#   - Terraform grafana_dashboard resource
```

**Performance Optimization:**

```yaml
# Problem: 1000 queries per dashboard refresh → Prometheus CPU spike
# Dashboard refresh every 30s → 33 queries per second

# Solutions:

# 1. Use $__rate_interval (Prometheus 2.17+)
# Auto-selects appropriate rate interval based on scrape interval
# Instead of rate(metric[5m]), use rate(metric[$__rate_interval])
# Prevents: "rate interval too short" errors

# 2. Panel query optimization flags:
# - Interval: set to > scrape interval (e.g., 15s if scrape is 10s)
# - Resolution: 1/1 (full), 1/2 (half), 1/10 (aggregated)
# - Max data points: 1000 (limits resolution, faster queries)
# - Cache TTL: 60s (avoid re-querying if multiple panels use same query)

# 3. Use recorded rules for expensive queries
# In Prometheus, pre-compute:
record: service:http_request_duration_seconds:p99
expr: histogram_quantile(0.99,
  sum by (le, service) (rate(http_request_duration_seconds_bucket[5m]))
)

# Grafana queries the recorded metric (fast) instead of computing p99 live (slow)

# 4. Alerting panels: use faster queries
# Instead of: histogram_quantile(0.99, rate(...))
# Use:        avg_over_time(service_http_p99[5m])
# Pre-computed metric → 100x faster query

# 5. Enable query caching (Grafana Enterprise or plugins)
# Cache Prometheus responses for N seconds
# Reduces Prometheus query load by 50-80%
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Template variables** | Uses query-based variables for drill-down: service → env → instance |
| **Dashboard IaC** | Provisions dashboards via YAML files in version control (allowUiUpdates: false) |
| **Query optimization** | Uses recording rules for expensive queries, $__rate_interval, max data points |
| **Panel hierarchy** | Organizes from global health → service → resource → dependencies |

---

## 6. Recording Rules & Dashboard Efficiency

**Q:** "Your Prometheus queries are taking 30+ seconds to return, causing Grafana dashboards to time out. How do recording rules improve query performance? Design a recording rule strategy. When should you NOT use recording rules?"

**What They're Really Testing:** Whether you understand recording rules as a performance optimization — pre-computing expensive queries at scrape time vs computing them on-demand at query time.

### Answer

**Recording Rule Mechanics:**

```yaml
# Recording rules: pre-compute and store results during evaluation
# Evaluated every: evaluation_interval (default: 1m)
# Stored as: new time series in TSDB

# Example: pre-compute p99 latency per service
groups:
  - name: latency_recording_rules
    interval: 1m  # Evaluate every minute
    rules:
      # Pre-compute expensive histogram_quantile
      - record: service:http_request_duration_seconds:p99
        expr: |
          histogram_quantile(0.99,
            sum by (le, service) (
              rate(http_request_duration_seconds_bucket[5m])
            )
          )
      
      # Pre-compute error ratio
      - record: service:http_requests:error_ratio_5m
        expr: |
          sum by (service) (rate(http_requests_total{status=~"5.."}[5m]))
            /
          sum by (service) (rate(http_requests_total[5m]))
      
      # Pre-compute request rate per endpoint
      - record: service:http_requests:rate_5m
        expr: |
          sum by (service, endpoint) (rate(http_requests_total[5m]))

# Time series created:
# service:http_request_duration_seconds:p99{service="payment"}
#   → @t1: 0.240, @t2: 0.245, @t3: 0.238 ...
# service:http_requests:error_ratio_5m{service="payment"}
#   → @t1: 0.02, @t2: 0.015, @t3: 0.03 ...

# Querying: 30 seconds → < 100 milliseconds (300x faster!)
# Now Grafana just reads: service:http_request_duration_seconds:p99
# Instead of computing: histogram_quantile(0.99, sum by (le, service) (rate(...[5m])))
```

**When NOT to Use Recording Rules:**

```yaml
# Rule of thumb: recording rule when query takes > 1 second and is used by > 5 dashboards

# DON'T use for:
# 1. High-cardinality queries (> 100K time series)
#    Recording rule creates 100K new time series → increases TSDB size
#    Example: rate(request_duration_bucket[5m]) by (le, instance, endpoint, service, version)
#    → 50K instances × 10 le × 20 endpoints = 10M time series!
#    Solution: aggregate further (by service, not by instance)

# 2. Queries that change frequently (ad-hoc)
#    Recording rules are static — defined at startup
#    If you change the rule, old time series persist until retention expires
#    Solution: version the metric name: service:p99:v2

# 3. Very short-lived aggregations (< 5 minutes)
#    Recording rule evaluation interval: 1m minimum
#    If you need sub-minute granularity, Prometheus might not be the right tool
#    Solution: use a streaming platform (Kafka + Flink)

# 4. Queries with many label joins
#    label_replace() adds cardinality to recording rules
#    Solution: use relabeling in scrape config instead

# Storage impact:
# Without recording rules: query recomputed on every dashboard load (CPU)
# With recording rules: stored as time series in TSDB (disk + memory)
# Trade-off: CPU → disk/memory
# 
# For 100 recording rules × 10K time series each:
# CPU savings: 30s → 100ms per query (300x faster)
# Storage cost: 100 × 10K × 1.3 bytes/sample × 1 sample/min × 60 × 24 × 30
#             = ~5.6GB/month (usually worth it)
```

**Recording Rule Best Practices:**

```yaml
# Naming conventions:
# level:metric_name:operation
# level = aggregation level (service, cluster, namespace)
# metric_name = original metric name
# operation = what was done (rate, p99, avg)

# Examples:
  service:http_requests:rate_5m
  cluster:cpu_utilization:avg
  namespace:memory_usage:max

# Organization:
groups:
  - name: latency_recording_rules
    interval: 1m
    rules: [...]  # Latency-related pre-computations
  
  - name: error_rate_recording_rules
    interval: 1m
    rules: [...]  # Error-related pre-computations

# Monitoring recording rules:
# Record: prometheus_rule_evaluation_duration_seconds
# Alert if any rule evaluation takes > 10s (blocking other rules!)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Performance benefit** | Quantifies improvement: 30s → <100ms (300x faster) |
| **When NOT to use** | Understands cardinality explosion risk, storage cost, and ad-hoc query limits |
| **Naming convention** | Uses level:metric:operation format for discovery and RBAC |
| **Storage trade-off** | Can calculate storage cost vs CPU savings for recording rules |

---

## 7. High Availability: Thanos, Cortex, Mimir

**Q:** "Your Prometheus setup has a single point of failure: when the Prometheus server goes down, you lose all monitoring data and alerting. Design a highly available monitoring stack using Thanos or Grafana Mimir. Compare sidecar, receiver, and query-frontend components."

**What They're Really Testing:** Whether you understand the limitations of single-server Prometheus and can design a horizontally scalable, highly available monitoring architecture using the Thanos/Cortex/Mimir ecosystem.

### Answer

**Thanos Architecture:**

```yaml
# Thanos extends Prometheus for HA and long-term storage

┌─────────────────────────────────────────────────────────────┐
│                     Thanos Query                             │
│  (Global query layer, deduplicates across Prometheuses)      │
│  PromQL endpoint: http://thanos-query:9090                  │
└──────────────────────┬──────────────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
┌────────────────┐ ┌────────────────┐ ┌────────────────┐
│ Thanos Sidecar  │ │ Thanos Sidecar  │ │ Thanos Sidecar  │
│ (attached to    │ │ (attached to    │ │ (attached to    │
│ Prometheus-A)   │ │ Prometheus-B)   │ │ Prometheus-C)   │
│ us-east-1a      │ │ us-east-1b      │ │ us-east-1c      │
└────────┬───────┘ └────────┬───────┘ └────────┬───────┘
         │                  │                  │
         ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────────┐
│                    Object Store (S3/GCS)                     │
│  - Long-term storage for blocks (months/years)              │
│  - Thanos Store Gateway reads from object store             │
│  - Thanos Compactor merges blocks and downsampling          │
└─────────────────────────────────────────────────────────────┘

# Components:
  Thanos Sidecar:
    - Attaches to each Prometheus (sidecar deployment)
    - Uploads TSDB blocks to object store (S3, GCS)
    - Exposes Prometheus data to Thanos Query via gRPC
    - Stores 2-hour blocks (same as Prometheus block duration)
  
  Thanos Query:
    - Global PromQL endpoint (queries ALL Prometheus + Store)
    - Deduplication: if same series from 2 Prometheuses, deduplicates
    - Label dedup: removes replica label from results
    - Partial response: if one Prometheus down, returns data from others
  
  Thanos Store Gateway:
    - Reads historical data from object store
    - Presents as a single gRPC endpoint for Thanos Query
    - Caches block metadata (no need to scan S3 on every query)
  
  Thanos Compactor:
    - Downsamples data for long-term storage
    - 30s raw → 5m → 1h resolution
    - Merges small blocks into larger blocks (more efficient)
  
  Thanos Ruler:
    - Evaluates recording rules and alerting rules
    - Separate from Prometheus (can survive Prometheus outage)
    - Writes rule results to object store
```

**Grafana Mimir (Successor to Cortex):**

```yaml
# Mimir: Grafana Labs' horizontally-scalable Prometheus-compatible TSDB

┌─────────────────────────────────────────────────────────────┐
│                    Mimir Architecture                         │
│                                                              │
│  Ingestion:                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │ Distrib. │  │ Distrib. │  │ Distrib. │  (hash ring)      │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                  │
│       │              │              │                        │
│  ┌────▼─────┐  ┌────▼─────┐  ┌────▼─────┐                  │
│  │ Ingester │  │ Ingester │  │ Ingester │  (WAL + blocks)   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                  │
│       │              │              │                        │
│       └──────────────┼──────────────┘                        │
│                      ▼                                       │
│           ┌──────────────────┐                               │
│           │ Object Store (S3)│  (long-term storage)         │
│           └──────────────────┘                               │
│                      │                                       │
│  Query:              ▼                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │   Query  │  │   Query  │  │   Query  │  (stateless)      │
│  │ Frontend │  │ Frontend │  │ Frontend │                  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                  │
│       │              │              │                        │
│  ┌────▼─────┐  ┌────▼─────┐  ┌────▼─────┐                  │
│  │  Store   │  │  Store   │  │  Store   │  (reads from S3) │
│  │ Gateway  │  │ Gateway  │  │ Gateway  │                  │
│  └──────────┘  └──────────┘  └──────────┘                  │
└─────────────────────────────────────────────────────────────┘

Key differences from Thanos:
  - Mimir: monolithic deployment (all-in-one binary or microservices)
  - Thanos: composable components (mix and match)
  - Mimir: built-in alert management (Grafana Alerting)
  - Thanos: uses Prometheus Alertmanager
  - Mimir: active-active ingestion (hash ring for consistent hashing)
  - Thanos: sidecar-based (Prometheus still does the scraping)
```

**Prometheus HA Comparison:**

```yaml
Feature              | Single Prometheus | Thanos            | Mimir
---------------------|-------------------|-------------------|-------------------
SPOF                | ✅ Yes            | ❌ No            | ❌ No
Long-term storage   | ❌ (15-30d)       | ✅ (S3/Blob)     | ✅ (S3/Blob)
Global query        | ❌                | ✅                | ✅
Downsampling        | ❌                | ✅                | ✅
Deduplication       | ❌                | ✅                | ✅
Multi-tenancy       | ❌                | ❌ (limited)     | ✅
Alerting HA         | ❌                | ✅ (Thanos Ruler)| ✅ (Mimir Ruler)
Complexity          | Low              | Medium            | High
Operation cost      | 1 server          | 5+ components     | 8+ components

# Recommendation:
# < 500 targets: single Prometheus + longer retention + proper backup
# 500-5000 targets: 2 Prometheuses (HA pair) + Thanos for long-term
# 5000+ targets: Mimir for multi-tenant, or Thanos for simpler setups
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Thanos components** | Knows sidecar, query, store, compactor, ruler roles and data flow |
| **Mimir vs Thanos** | Can compare: Mimir = integrated, Thanos = composable |
| **Deduplication** | Understands how Thanos Query deduplicates replica data |
| **Downsampling** | Knows compactor downsamples raw → 5m → 1h for long-term queries |

---

## 8. Observability Strategy: Metrics, Logs, Traces

**Q:** "Design a comprehensive observability strategy for a 200-microservices platform. How do metrics, logs, and traces correlate? How do you implement distributed tracing? How do you maintain a 99.9% uptime SLO with observability as the foundation?"

**What They're Really Testing:** Whether you understand observability as an integrated discipline — the three pillars (metrics, logs, traces) and how they work together for incident response, not just dashboard decoration.

### Answer

**Three Pillars Correlation:**

```yaml
# Metrics tell you WHAT is wrong
# Logs tell you WHY it's wrong
# Traces tell you WHERE it's wrong

# Correlation strategy: common identifiers across all signals

┌─────────────────────────────────────────────────────────────┐
│                    Common Labels/Attributes                   │
│                                                              │
│  Metrics (Prometheus):                                       │
│    service, instance, endpoint, status, trace_id             │
│    http_requests_total{service="orders", status="500"}       │
│                                                              │
│  Logs (Loki/ELK):                                           │
│    Structured JSON with: timestamp, service, trace_id, msg   │
│    {"ts": "...", "service": "orders", "trace_id": "abc"}     │
│                                                              │
│  Traces (Tempo/Jaeger):                                     │
│    Distributed spans with: trace_id, span_id, parent_span   │
│    orders.checkout → payment.charge → inventory.deduct      │
│                                                              │
│  Correlation:                                                │
│    Alert fires: error rate > 5% for service "orders"        │
│    → Find related logs: {service="orders"} AND {status=500} │
│    → Find related trace: trace_id from logs → full trace    │
│    → Root cause: payment service is 500ms timeout           │
└─────────────────────────────────────────────────────────────┘
```

**Distributed Tracing Implementation:**

```yaml
# OpenTelemetry (CNCF standard, vendor-neutral)
# Traces consist of spans, each with parent span ID

# Instrumentation (auto-instrument for most languages):
# Python:
#   pip install opentelemetry-distro
#   opentelemetry-bootstrap -a install
#   export OTEL_SERVICE_NAME=payment-service
#   export OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317
#   opentelemetry-instrument python app.py

# Manual instrumentation (critical paths):
from opentelemetry import trace

def process_payment(order_id, amount):
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("process_payment") as span:
        span.set_attribute("order.id", order_id)
        span.set_attribute("payment.amount", amount)
        
        # Call downstream service with trace context
        with tracer.start_as_current_span("charge_gateway") as child:
            child.set_attribute("gateway", "stripe")
            result = stripe.charge(amount)
        
        return result

# Trace sampling strategy (critical for performance):
# Sample 100% of error traces, 1% of success traces
# Head-based: sample at request entry (simple, can miss errors)
# Tail-based: sample after request completes (captures all errors)
# 
# Tempo supports:
#   - Probabilistic: 1% of all traces
#   - Rate-limited: max 10 traces/second
#   - Always sample if: status=error, latency > p99

# Trace → Metrics bridge:
# Service graph: derive RED metrics from trace data
# Request rate, error rate, duration from traces
# No need for separate metric instrumentation!
```

**SLO-Based Alerting:**

```yaml
# SLO: Service Level Objective (e.g., 99.9% availability over 30 days)

# Implementation:
slo_definition:
  service: payment
  target: 99.9  # Three 9s
  window: 30d
  metric: http_requests_total (status=~"5.." as bad, status=~"2.." as good)

# Error budget: 100% - SLO = 0.1% = 43m 12s of allowed downtime per month

# Multi-window, multi-burn-rate alerts:
# Fast enough to catch issues, slow enough to avoid noise

alert: SLOBurnRateTooFast
expr: |
  # Burn rate > 10x (error budget exhausted in 3 days instead of 30)
  (
    sum by (service) (rate(http_requests_total{status=~"5.."}[1h]))
    /
    sum by (service) (rate(http_requests_total[1h]))
  )
  /
  (1 - 0.999)  # SLO target
  > 10

# Multi-window approach:
# Short window (1h) + long window (6h) both exceeding threshold
# Prevents false positives from short bursts

groups:
  - name: slo_alerts
    rules:
      - alert: SLOErrorBudgetBurning
        expr: |
          # Short window (1h): burn rate > 10x
          (
            sum by (service) (rate(http_requests_total{status=~"5.."}[1h]))
            /
            sum by (service) (rate(http_requests_total[1h]))
          ) / (1 - 0.999) > 10
          AND
          # Long window (6h): burn rate > 10x
          (
            sum by (service) (rate(http_requests_total{status=~"5.."}[6h]))
            /
            sum by (service) (rate(http_requests_total[6h]))
          ) / (1 - 0.999) > 10
        for: 5m
        labels:
          severity: critical
          slo: "99.9"
        annotations:
          summary: "{{ $labels.service }} SLO burn rate > 10x"

# Dashboard: error budget remaining
# 1 - (total_bad_requests / total_good_requests) * 100
# Gauge panel: green (> 50% remaining), yellow (50-20%), red (< 20%)
```

**Incident Response Integration:**

```yaml
# Observability-powered incident response:

# 1. Alert fires
# 2. Runbook link in alert annotation
# 3. Runbook: "Check dashboard for error rate, latency, and traces"
# 4. From dashboard: click on error spike → "View logs" → "View trace"
# 5. Trace shows: payment-service → gateways.stripe.com → timeout
# 6. Root cause: Stripe API latency spike
# 7. Mitigation: switch to backup provider (Stripe fallback config)
# 8. Post-incident: add runbook steps, adjust alert thresholds

# Architecture for this flow:
  Prometheus: metrics + alerting rules
       │
       ▼
  Grafana: dashboards with embedded links
       │  ├── Explore → Logs (Loki): {service="payment"} |= "error"
       │  └── Explore → Traces (Tempo): trace_id = <click from log>
       │
  Loki: aggregated logs (200 services, 5TB/day)
       │
  Tempo: distributed traces (sampled: 100% errors, 1% success)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Three pillars** | Can articulate what each pillar provides (what/why/where) and how they correlate |
| **OTel instrumentation** | Knows auto-instrumentation, manual spans for critical paths, context propagation |
| **SLO burn rate** | Designs multi-window, multi-burn-rate alerts (short + long window) |
| **Incident response** | Links alerts → dashboards → logs → traces in a single click path |

---

> *All 8 questions cover the full breadth of Prometheus & Grafana — from TSDB internals and PromQL to Thanos/Mimir HA architectures and SLO-based alerting.*
