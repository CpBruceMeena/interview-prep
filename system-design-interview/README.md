# 🏗️ System Design Interview

> **End-to-end design practice for Staff-level rounds.** A reusable framework, an estimation cheat sheet, and eight case studies that each follow the same structure so you can compare how decisions change with the problem.

## Start here

| Step | Read | Why |
|---|---|---|
| 1 | [Framework & Estimation](00_FRAMEWORK_AND_ESTIMATION.md) | The 45-minute structure, numbers to memorize, and what "Staff" signals look like |
| 2 | Any case study below | Practice the framework on a concrete problem |
| 3 | [CS Core: Distributed Systems](../cs-interview/distributed-systems/INTERVIEW_QUESTIONS.md) | The theory the deep dives lean on (consensus, CAP, consistent hashing) |
| 4 | [Staff Craft: Reliability & Operations](../staff-engineer-interview/03_RELIABILITY_AND_OPERATIONS.md) | The "failure modes and rollout" half of every design |

## Case studies

| # | Case study | The hard part |
|---|---|---|
| 1 | [URL Shortener](01_URL_SHORTENER.md) | Collision-free code allocation, redirect hot path, click counting |
| 2 | [News Feed](02_NEWS_FEED.md) | Hybrid fan-out (celebrities), stable pagination, deletes and unfollows |
| 3 | [Chat & Messaging](03_CHAT_MESSAGING.md) | 100M concurrent connections, ordering, offline delivery |
| 4 | [Typeahead / Search Suggestions](04_TYPEAHEAD_SEARCH_SUGGESTIONS.md) | Sub-100 ms prefix lookup, offline aggregation, freshness |
| 5 | [Ad Click Aggregation](05_AD_CLICK_AGGREGATION.md) | Exactly-once-effective counting, late data, hot ads |
| 6 | [Video Streaming](06_VIDEO_STREAMING.md) | Transcoding DAG, adaptive bitrate, CDN economics |
| 7 | [File Storage & Sync](07_FILE_STORAGE_AND_SYNC.md) | Chunking and dedupe, ordered metadata, conflicts |
| 8 | [Payments Ledger](08_PAYMENTS_LEDGER.md) | Double-entry, idempotency, unknown outcomes, reconciliation |

## Every case study has the same 11 sections

Requirements → Estimation → API → Data model → High-level design → Deep dives → Failure modes → Observability & rollout → Alternatives → Follow-up questions → Common mistakes.

**How to practise:** read only sections 1–2, close the page, and design on paper for 30 minutes. Then compare your deep dives and trade-offs with section 6 and your follow-up answers with section 10.

## Related material

- Existing LLD projects that double as small design problems: [Rate Limiter](../python-low-level-design/rate-limiter/), [Notification Service](../python-low-level-design/notification-service/), [Cab Booking](../python-low-level-design/cab-booking-uber/), [Search Platform](../python-low-level-design/search-platform/).
- [Distributed Transaction Patterns](../cs-interview/distributed-systems/DISTRIBUTED_TRANSACTION_PATTERNS.md), [Data Structures for Scale](../cs-interview/data-structures-algorithms/DATA_STRUCTURES_FOR_SCALE.md).
