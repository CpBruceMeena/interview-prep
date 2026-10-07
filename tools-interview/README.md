# 🛠️ Tools & Platforms — Staff-Level Interview Questions

> *Deep-dive questions on the infrastructure tools a senior or staff backend engineer is expected to know: Kafka, Redis, Elasticsearch, MongoDB, Docker, Kubernetes, nginx, Prometheus/Grafana, Terraform, compression, and CI/CD. Each answer leads with the short version, then the mechanism, trade-offs, failure modes and likely follow-ups.*

---

## 📋 Topic Overview

```
tools-interview/
├── README.md
├── kafka/                ← 12 questions: log internals, ISR, rebalancing, exactly-once
├── redis/                ← 12 questions: data structures, persistence, clustering, sentinel
├── elasticsearch/        ← 8 questions: inverted index, sharding, query DSL, cluster mgmt
├── docker/               ← 8 questions: namespaces/cgroups, images, BuildKit, supply chain, limits, networking, hardening, PID 1
├── kubernetes/           ← 6 questions: k8s scheduler, networking, RBAC, storage, controllers, production
│   ├── INTERVIEW_QUESTIONS.md
│   ├── POD_LIFECYCLE_AND_MONITORING.md   ← 15 sections: pod lifecycle, probes, QoS, monitoring stack, alerting, eBPF
│   ├── PRODUCTION_CONTROL.md             ← 12 sections: GitOps, admission, deployment strategies, service mesh, CNI, DR
│   └── VERSIONING_MULTI_CONTAINER.md     ← versioning, DB migrations, canary deployments
├── mongodb/              ← 6 questions: document model, replica sets, aggregation, transactions
├── prometheus-grafana/   ← 8 questions: TSDB and Prometheus 3.x, relabeling, PromQL, Alertmanager, Grafana, recording rules, Thanos/Mimir, OpenTelemetry and SLOs
├── nginx/                ← 10 questions: process model, event loop, proxying and buffering, load balancing, TLS, sendfile, backpressure, config, alternatives, 502 debugging
├── compression/          ← 10 questions: gzip, deflate, zstd, brotli, HPACK/QPACK
├── terraform/            ← 8 questions: state and locking, graph, modules and tests, environments, providers, CI/CD, HCL, secrets and policy (plus OpenTofu)
└── ci-cd-deployment/     ← guide (11 sections): pipelines, deployment strategies, progressive delivery, per-language images, supply-chain security, interview questions
```

## 🎯 How to Use

1. **Pick a tool** — focus on ones you'll be discussing in your interview
2. **Read the question** — try to answer aloud with production examples
3. **Study the answer** — pay attention to the configuration details, failure modes, and trade-offs
4. **Run the examples** — the CLI commands and configuration snippets are production-realistic
5. **Connect topics** — e.g., "How does Kafka's ISR relate to Raft's log replication?"

---

## 🔗 Cross-Cutting Themes

| Theme | Appears In |
|-------|-----------|
| **Consensus & Replication** | Kafka ISR, Redis Sentinel, MongoDB replica sets, Raft |
| **Partitioning & Sharding** | Kafka partitions, Redis cluster, ES shards, MongoDB sharding |
| **Consistency Models** | Kafka acks, Redis replication, MongoDB write concern |
| **Throughput vs Durability** | Kafka flush.ms, Redis AOF/RDB, MongoDB journaling |
| **Observability** | All tools: metrics, slow logs, monitoring, debugging |

---

> *Master these tools and you'll be prepared for the deepest Staff/Principal interviews at companies that use these technologies at scale.*
