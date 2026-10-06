# DynamoDB — Interview Prep Notes

A complete walkthrough of Amazon DynamoDB: fundamentals, keys and partitioning, indexes, data modeling, operational features, comparisons with SQL and other NoSQL databases, limits, trade-offs, and two practical scenarios (bulk updates and high-volume reads).

## Table of contents

1. [What DynamoDB is and its building blocks](#1-what-dynamodb-is-and-its-building-blocks)
2. [Primary keys and partitioning](#2-primary-keys-and-partitioning)
3. [Reading and writing data](#3-reading-and-writing-data)
4. [Secondary indexes](#4-secondary-indexes)
5. [Data modeling and single-table design](#5-data-modeling-and-single-table-design)
6. [Capacity, consistency, transactions, Streams, TTL](#6-capacity-consistency-transactions-streams-ttl)
7. [DynamoDB vs relational databases](#7-dynamodb-vs-relational-databases)
8. [DynamoDB vs other NoSQL databases](#8-dynamodb-vs-other-nosql-databases)
9. [Limits](#9-limits)
10. [Pros, cons, and when to use it](#10-pros-cons-and-when-to-use-it)
11. [Scenario: updating 10,000 records (boto3 and PySpark)](#11-scenario-updating-10000-records)
12. [Scenario: reading 1 million records in 10 minutes](#12-scenario-reading-1-million-records-in-10-minutes)
13. [Quick revision: interview questions](#13-quick-revision-interview-questions)

---

## 1. What DynamoDB is and its building blocks

DynamoDB is AWS's **fully managed, serverless NoSQL database**: a key-value and document store. There are no servers to provision, patch, or scale.

**Core properties**

- **Predictable performance at any scale**: single-digit millisecond reads/writes by key, whether the table holds a thousand items or billions.
- **Serverless and elastic**: on-demand (pay per request, auto-scales) or provisioned (reserve throughput).
- **Highly available and durable**: every write is replicated across three Availability Zones.
- **Schemaless (mostly)**: only the primary key is defined upfront; other attributes can vary per item.

**Building blocks**

| DynamoDB | Rough SQL equivalent | Notes |
|---|---|---|
| Table | Table | Collection of items |
| Item | Row | One record, max 400 KB |
| Attribute | Column | A field; can differ between items in the same table |

**Attribute types**

- Scalar: String, Number, Binary, Boolean, Null
- Document: List, Map (nestable, like JSON)
- Set: String Set, Number Set, Binary Set

**The key mental shift**: in SQL you model data first and query it any way later. In DynamoDB you **list your access patterns first**, then design keys so each pattern is a fast key lookup. There are no joins and only key-based querying.

---

## 2. Primary keys and partitioning

The primary key **uniquely identifies an item** and **decides where it is physically stored**. It's chosen at table creation and cannot be changed.

### Two kinds of primary key

**Simple (partition key only)**: the value must be unique. Pure key-value access.

**Composite (partition key + sort key)**: the *combination* must be unique. Items sharing a partition key form an **item collection**, stored together and **sorted by sort key**.

```
Table: Orders   PK = customerId   SK = orderDate

c-101 | 2026-08-14 | 450  | DELIVERED
c-101 | 2026-09-02 | 1200 | DELIVERED
c-101 | 2026-10-01 | 300  | PENDING
c-102 | 2026-09-20 | 800  | DELIVERED
```

The sort key enables range queries within a partition: `=`, `<`, `>`, `between`, `begins_with`, ascending/descending order, and limits ("latest 5 orders").

### How partitioning works

1. DynamoDB hashes the partition key value.
2. The hash decides which **partition** (physical storage unit) holds the item.
3. Within a partition, items with the same partition key are kept sorted by sort key.

Reads hash the key again and go straight to the right partition, so lookups don't slow down as the table grows. DynamoDB adds and splits partitions automatically.

Approximate per-partition limits: **10 GB of data, 3,000 read units/sec, 1,000 write units/sec**.

### Hot partitions

Items with one partition key value start out on one partition. If most traffic hits one key, that partition throttles even if the table has spare capacity.

Good partition keys have **high cardinality** (many distinct values: userId, orderId) and **even access**. Bad choices: `status`, `country`, or "today's date" in a time-series table.

Fix for unavoidable hot keys: **write sharding**, e.g. `2026-10-06#3` with a random suffix 0–9, then read all 10 shards when needed. DynamoDB's **adaptive capacity** helps uneven traffic: it shifts capacity to hot partitions and, under sustained load, can **split a hot item collection across partitions by sort key** (not if the table has an LSI). But it reacts after the fact, and it can't rescue a single *item* that's too hot: one item never exceeds ~1,000 write / ~3,000 read units/sec.

### Rules

- Key types: String, Number, or Binary only.
- Partition key value ≤ 2,048 bytes; sort key value ≤ 1,024 bytes.
- Key attributes can't be updated; delete and re-insert instead.
- Sort keys compare as strings (UTF-8 bytes), numbers, or binary: use ISO dates (`2026-09-02`) so string order equals time order. Composite sort keys like `ORDER#2026-09-02#ORD-102` are common.

**Example: chat messages.** PK = `conversationId`, SK = `timestamp#messageId` (e.g. `2026-10-06T10:15:30.123Z#msg-789`). A timestamp alone isn't unique, and a duplicate key **silently overwrites** on PutItem. ULIDs/KSUIDs are unique and time-sortable alternatives.

---

## 3. Reading and writing data

```python
import boto3
from boto3.dynamodb.conditions import Key
table = boto3.resource("dynamodb").Table("Messages")
```

### Writes

**PutItem**: create or **fully replace** an item.

```python
table.put_item(Item={"conversationId": "conv-501",
                     "sentAt": "2026-10-06T10:15:30.123Z#msg-789",
                     "sender": "u-101", "text": "Order confirmed"})
```

**UpdateItem**: modify specific attributes; creates the item if it doesn't exist (upsert).

```python
table.update_item(
    Key={"conversationId": "conv-501", "sentAt": "2026-10-06T10:15:30.123Z#msg-789"},
    UpdateExpression="SET #t = :txt, edited = :true ADD editCount :one",
    ExpressionAttributeNames={"#t": "text"},          # 'text' is a reserved word
    ExpressionAttributeValues={":txt": "Order confirmed for Sunday", ":true": True, ":one": 1},
)
```

Update actions: `SET` (set/overwrite), `REMOVE` (delete attribute), `ADD` (atomic counter / add to set), `DELETE` (remove from set).

**DeleteItem**: remove one item by full key.

**Condition expressions**: the write succeeds only if the condition holds, otherwise `ConditionalCheckFailedException`.

```python
# Create-only (prevents silent overwrite)
table.put_item(Item=item, ConditionExpression="attribute_not_exists(sentAt)")

# Optimistic locking
table.update_item(..., ConditionExpression="version = :expected")
```

### Reads (cheapest to most expensive)

| Operation | What it does | Requires |
|---|---|---|
| **GetItem** | Fetch one item | Full primary key |
| **Query** | Fetch items from one item collection, optional sort key condition | Exact partition key value |
| **Scan** | Read the entire table | Nothing (and that's the problem) |

```python
# Latest 50 messages in a conversation
resp = table.query(
    KeyConditionExpression=Key("conversationId").eq("conv-501"),
    ScanIndexForward=False,   # newest first
    Limit=50,
)
```

### Gotchas

- **Filter expressions don't reduce cost.** They're applied *after* items are read; you pay for everything read. Only the key condition narrows what's read.
- **Pagination**: Query/Scan return at most **1 MB** per call. Use `LastEvaluatedKey` → `ExclusiveStartKey`. `Limit` caps items *evaluated*, so with a filter you may get fewer (even zero) items while more pages exist.

```python
items, kwargs = [], {"KeyConditionExpression": Key("conversationId").eq("conv-501")}
while True:
    resp = table.query(**kwargs)
    items += resp["Items"]
    if "LastEvaluatedKey" not in resp:
        break
    kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
```

### Batch and other operations

- **BatchGetItem**: up to 100 items by key, 16 MB max.
- **BatchWriteItem**: up to 25 puts/deletes; **no updates, no conditions, not atomic** (retry `UnprocessedItems`).
- **ProjectionExpression**: return selected attributes (still charged for the full item read).
- **PartiQL**: SQL-like syntax over the same operations. A `WHERE` without the partition key becomes a full Scan.

---

## 4. Secondary indexes

A secondary index is an **alternate key** for the table. DynamoDB maintains a copy of (projected) data organized by that key, updated automatically on every write. You Query the index like a table.

**Problem it solves**: table keyed by `conversationId`, but you need "all messages by user u-101". Without an index, that's a Scan + filter over the whole table.

### Global Secondary Index (GSI)

Completely different partition key and (optional) sort key.

```
Base table:      PK = conversationId   SK = sentAt
GSI "BySender":  PK = sender           SK = sentAt
```

```python
table.query(IndexName="BySender",
            KeyConditionExpression=Key("sender").eq("u-101"),
            ScanIndexForward=False, Limit=50)
```

- GSI keys **need not be unique** (uniqueness is enforced only on the base table, where writes happen).
- **Eventually consistent only.**
- Can be **added or deleted any time** (DynamoDB backfills).
- Up to **20 per table** (default quota).
- **Own capacity and partitions.** Each relevant base write also costs an index write; an under-provisioned GSI can throttle base-table writes.
- Hot-key rules apply to GSI keys too.

### Projections

- **KEYS_ONLY**: table + index keys only (cheapest).
- **INCLUDE**: keys + listed attributes.
- **ALL**: whole item (most convenient, most storage/write cost).

Non-projected attributes aren't returned from a GSI; fetch from the base table if needed.

### Sparse indexes

Items appear in an index **only if they have the index key attributes**. Set an attribute only on, say, flagged messages, and the index contains only those, making queries tiny and cheap. `REMOVE` the attribute to drop the item from the index.

### Local Secondary Index (LSI)

Same partition key, **different sort key**.

- **Only at table creation**; can't add/remove later.
- Max **5 per table**.
- Supports **strongly consistent reads**.
- Shares the table's capacity.
- **Catch**: with any LSI, each item collection (one partition key value) is capped at **10 GB**.

### GSI vs LSI

| | GSI | LSI |
|---|---|---|
| Partition key | Any attribute | Same as table |
| Sort key | Any (optional) | Different from table's (required) |
| Created | Any time | Table creation only |
| Max per table | 20 | 5 |
| Consistency | Eventual only | Eventual or strong |
| Capacity | Own | Shared |
| Size limit | None per key | 10 GB per partition key value |

**Rule of thumb**: default to GSIs. Every index costs storage and writes, so each should serve a real access pattern.

---

## 5. Data modeling and single-table design

### Process

1. List entities and relationships.
2. Write down every access pattern concretely.
3. Design table keys to serve as many patterns as possible.
4. Add GSIs for the rest.
5. Verify every pattern is a GetItem or Query. If any needs a Scan, redesign.

### Single-table design

Multiple entity types in one table, with generic key names (`PK`, `SK`) and prefixed values (`USER#`, `CONV#`). Related items share a partition key, so one Query fetches them together: **pre-joined data**.

### Worked example: chat app

Access patterns:

1. Get a user's profile
2. Get a conversation's details and members
3. Get the latest 50 messages in a conversation
4. List all conversations a user is in
5. Get all messages sent by a user

| Entity | PK | SK | GSI1PK | GSI1SK |
|---|---|---|---|---|
| User | `USER#u-101` | `PROFILE` | | |
| Conversation | `CONV#c-501` | `META` | | |
| Membership | `CONV#c-501` | `MEMBER#u-101` | `USER#u-101` | `CONV#c-501` |
| Message | `CONV#c-501` | `MSG#<timestamp>#<msgId>` | `USER#<sender>` | `MSG#<timestamp>#<msgId>` |

| # | Pattern | Operation |
|---|---|---|
| 1 | User profile | GetItem `PK=USER#u-101, SK=PROFILE` |
| 2 | Conversation + members | Query `PK=CONV#c-501`, SK between `MEMBER#` and `META` |
| 3 | Latest 50 messages | Query `PK=CONV#c-501`, SK begins_with `MSG#`, desc, limit 50 |
| 4 | User's conversations | Query GSI1 `GSI1PK=USER#u-101`, begins_with `CONV#` |
| 5 | Messages by user | Query GSI1 `GSI1PK=USER#u-101`, begins_with `MSG#`, desc |

Techniques:

- **Adjacency list**: the membership item is the many-to-many edge, grouped under the conversation in the base table and under the user in GSI1.
- **GSI overloading**: one GSI serves multiple patterns via different sort key prefixes.

### Extension: chat list sorted by recent activity

Add `lastActivityAt` to membership items and a GSI (PK = `USER#<id>`, SK = `<lastActivityAt>#<convId>`). Cost: **write fan-out** — every new message updates every member's membership item (a 200-member group = 200 updates, each changing a GSI key, i.e. a delete + insert in the index). Do it asynchronously via Streams + Lambda, and debounce (skip if bumped in the last few seconds).

### Principles

- **Denormalize** data that rarely changes to avoid extra reads.
- **Store aggregates** (e.g. `messageCount` with atomic `ADD`); there's no COUNT/SUM.
- **Hierarchical sort keys** (`ORG#acme#DEPT#eng#TEAM#api`) + `begins_with` query any level.
- Add a **`type` attribute** to every item for debugging and exports.
- **Large blobs go to S3**; store only the S3 key.
- **Never store unbounded lists in one item.** Example: comments on a post go as separate items (`PK=POST#p-901`, `SK=COMMENT#<timestamp>#<id>`), not in a list attribute. A list would hit 400 KB, every comment would rewrite the whole item (write cost scales with item size), and a viral post would hit the per-partition write ceiling.

### Trade-offs

- New access patterns may need new GSIs or data migrations.
- `PK`/`SK` with prefixes is harder to read and onboard onto.
- Ad hoc analytics need exports (S3 + Athena) or a warehouse.
- Single-table design isn't mandatory: group entities that are **fetched together**; don't force unrelated data into one table.

---

## 6. Capacity, consistency, transactions, Streams, TTL

### Capacity units

- **1 read unit** = 1 strongly consistent read/sec of up to **4 KB**, or 2 eventually consistent reads.
- **1 write unit** = 1 write/sec of up to **1 KB**.
- Transactional reads/writes cost **2×**.
- Sizes round up: a 9 KB strong read = 3 units; a 3.5 KB write = 4 units. Item size drives cost on every access.
- Query/Scan are charged on the **total size read per call**, rounded up to 4 KB (not per item). GetItem/BatchGetItem round up **per item**.

### Capacity modes

| | On-demand | Provisioned |
|---|---|---|
| Pricing | Per request | Per reserved unit/hour (+ reserved capacity discounts) |
| Scaling | Automatic | Manual or auto-scaling between min/max |
| Best for | New, spiky, unpredictable, or idle workloads | Steady, predictable traffic |
| Over limit | Brief throttling on extreme sudden spikes | `ProvisionedThroughputExceededException` |

Provisioned tables have a small burst buffer (~5 minutes of unused capacity). Advice: start on-demand, move to provisioned once traffic is steady.

### Consistency

- **Eventually consistent** (default): may be briefly stale; half the cost.
- **Strongly consistent** (`ConsistentRead=True`): latest committed write; 2× cost; **base table and LSIs only, never GSIs**.

### Transactions

`TransactWriteItems` / `TransactGetItems`: up to **100 actions, 4 MB**, across tables in one region, **all-or-nothing**. Actions: Put, Update, Delete, ConditionCheck. An item can appear in only one action per transaction. `ClientRequestToken` makes retries idempotent (for 10 minutes). Not interactive (you can't read, decide in code, then write inside one transaction).

```python
client = boto3.client("dynamodb")
client.transact_write_items(TransactItems=[
    {"Put": {"TableName": "Chat", "Item": message_item,
             "ConditionExpression": "attribute_not_exists(SK)"}},
    {"Update": {"TableName": "Chat",
                "Key": {"PK": {"S": "CONV#c-501"}, "SK": {"S": "META"}},
                "UpdateExpression": "ADD messageCount :one",
                "ExpressionAttributeValues": {":one": {"N": "1"}}}},
    {"ConditionCheck": {"TableName": "Chat",
                        "Key": {"PK": {"S": "CONV#c-501"}, "SK": {"S": "MEMBER#u-101"}},
                        "ConditionExpression": "attribute_exists(SK)"}},
])
```

### DynamoDB Streams

Log of item-level changes, retained **24 hours**. Each change appears exactly once, and changes to the **same item are in order** (there's no global ordering across items). View types: KEYS_ONLY, NEW_IMAGE, OLD_IMAGE, NEW_AND_OLD_IMAGES. Usually consumed by **Lambda**.

Uses: fan-out (e.g. chat list updates for a 500-member group), syncing to OpenSearch, analytics pipelines, notifications, audit logs, async aggregates, cascading deletes. Consumers must be **idempotent** (batches can be retried). Kinesis Data Streams is an alternative for longer retention.

**Why Streams for large fan-out**: doing it in the request is slow and risks partial failure; a transaction can't exceed 100 items.

### TTL

Attribute holding a **Unix epoch timestamp in seconds**; DynamoDB deletes expired items in the background **at no write cost**, typically within a few days of expiry. Filter out expired items in reads when precision matters. TTL deletes appear in Streams (flagged as system deletes), so you can archive before removal. Uses: sessions, OTPs, carts, rate-limit counters.

### Other features

- **Backups**: point-in-time recovery (any second in the last 35 days), on-demand backups.
- **Global Tables**: multi-region, multi-active replication. Default mode is asynchronous (eventually consistent across regions, last-writer-wins on conflicts); a **multi-region strong consistency** mode is also available, at the cost of higher write latency.
- **DAX**: in-memory cache, microsecond reads.
- **Export to S3 / Import from S3** (see sections 11–12).
- **Encryption at rest**: always on.

---

## 7. DynamoDB vs relational databases

DynamoDB trades **query flexibility** for **predictable performance at any scale with zero operations**.

| Aspect | Relational (PostgreSQL, MySQL) | DynamoDB |
|---|---|---|
| Data model | Normalized, joined at query time | Denormalized, pre-joined by shared keys |
| Schema | Fixed; migrations | Only keys fixed |
| Querying | Any SQL, any time | Keys/indexes; patterns planned upfront |
| Joins / aggregations | Yes | No |
| Constraints | FKs, unique on any column, checks | Only primary key uniqueness |
| Transactions | Full ACID, interactive, any size | ≤100 items, single call |
| Consistency | Strong by default | Eventual by default; strong optional |
| Scaling | Vertical + read replicas; sharding is hard | Horizontal, automatic |
| Latency at scale | Can degrade | Consistent |
| Operations | Instances, upgrades, failover, connections | None |
| Connections | Persistent pools (Lambda can exhaust them) | Stateless HTTP |
| Cost | Instances 24/7 | Per request or provisioned + storage |

**DynamoDB wins**: massive/unpredictable scale, predictable latency, serverless backends, simple high-volume access (sessions, carts, profiles, chat, IoT, game state).

**SQL wins**: ad hoc/evolving queries, complex relationships, reporting, integrity enforcement, early-stage products with unknown patterns.

**Unique email in DynamoDB** (SQL: `CREATE UNIQUE INDEX`): write a guard item `PK=EMAIL#<email>` in the same transaction as the user, both with `attribute_not_exists(PK)`.

**Examples**: finance dashboard with arbitrary filters → SQL. Session tokens for 5M daily users → DynamoDB (GetItem by token + TTL).

---

## 8. DynamoDB vs other NoSQL databases

NoSQL families: key-value (Redis, DynamoDB), document (MongoDB), wide-column (Cassandra, ScyllaDB), graph (Neo4j, Neptune), search (OpenSearch). DynamoDB is key-value/document with a wide-column-like key model.

**MongoDB (document)**: query/filter on any field, aggregation pipeline, `$lookup`, unique/text/geo indexes, 16 MB documents, runs anywhere. You choose a shard key and (unless on Atlas) run the cluster. Choose for flexible documents **with rich, changing queries**.

**Cassandra (wide-column)**: closest model (partition key + clustering columns ≈ PK + SK), CQL, tunable consistency, masterless multi-DC, huge write throughput, open source. Heavy operational burden. (Amazon Keyspaces is managed Cassandra-compatible.) DynamoDB descends conceptually from Amazon's 2007 Dynamo paper but is a different system.

**Redis (in-memory)**: sub-millisecond, rich structures (sorted sets, lists, pub/sub), memory-bound and costlier per GB, weaker durability. Usually complements DynamoDB as cache/leaderboard/real-time layer.

| | DynamoDB | MongoDB | Cassandra | Redis |
|---|---|---|---|---|
| Type | KV / document | Document | Wide-column | In-memory KV + structures |
| Query flexibility | Low | High | Low | Low (rich structures) |
| Latency | Single-digit ms | Low ms | Low ms | Sub-ms |
| Scaling | Automatic | Sharding | Add nodes | Clustering, memory-bound |
| Ops | None | Moderate | High | Moderate |
| Runs where | AWS only | Anywhere | Anywhere | Anywhere |

**Unique to DynamoDB**: truly serverless, pay-per-request, IAM down to item/attribute level, Streams→Lambda, native Global Tables. Downside: **AWS lock-in**.

**Example**: game leaderboard → Redis sorted sets (`ZADD`, `ZREVRANGE 0 99`); player profiles and match history → DynamoDB (also store scores there so Redis can be rebuilt). A DynamoDB leaderboard would need a constant-PK GSI sorted by score → hot partition.

---

## 9. Limits

AWS adjusts quotas occasionally; verify exact numbers in the DynamoDB "Service, account, and table quotas" docs.

**Items and keys (hard)**

- Item size **400 KB**, including attribute names.
- Partition key ≤ 2,048 bytes; sort key ≤ 1,024 bytes; types String/Number/Binary.
- Nesting depth 32; numbers up to 38 digits; no native date type.
- Primary key definition and key values are immutable.

**Operations (hard)**

- Query/Scan: **1 MB** per call.
- BatchGetItem: 100 items / 16 MB. BatchWriteItem: 25 puts/deletes / 16 MB.
- Transactions: **100 items / 4 MB**, 2× cost.
- PartiQL `BatchExecuteStatement`: 25 statements.
- Expressions: 4 KB each.

**Indexes**

- GSIs: 20/table (default, raisable). LSIs: 5, creation-time only.
- 10 GB per item collection when any LSI exists.
- No strong reads on GSIs. ≤100 projected non-key attributes across INCLUDE projections.

**Throughput**

- Per partition: ~3,000 read units/sec, ~1,000 write units/sec. A single **item** can never exceed that (~1,000 writes/sec of 1 KB). A single partition key value is held to it too, unless DynamoDB splits the item collection by sort key under sustained load (never with an LSI). Don't design around that split.
- Per-table and per-account default quotas exist (raisable).

**Features**

- Streams: 24-hour retention. TTL: deletion within days, not instant.

**Not supported at all**: joins, aggregations, ad hoc queries (become Scans), full-text search, uniqueness beyond PK, interactive transactions, foreign keys, cascading deletes.

**How limits shape design**: blobs → S3; unbounded lists → separate items; hot counters → write sharding; big fan-outs → Streams + Lambda; reporting → exports/warehouse.

---

## 10. Pros, cons, and when to use it

**Pros**: predictable latency at any scale; zero ops; automatic horizontal scaling; multi-AZ durability, PITR, Global Tables; pay-per-use (near-zero when idle); serverless-native; Streams/TTL/conditional writes; item-level IAM.

**Cons**: access patterns needed upfront; no joins/aggregations/ad hoc/full-text; steep modeling curve; integrity is the app's job; limited transactions; analytics need another system; on-demand can be costly at steady high volume; over-indexing multiplies cost; AWS lock-in; hard limits (400 KB, partition ceilings, 1 MB pages).

**Great fit**: high-traffic apps with known patterns (profiles, carts, orders, sessions, chat, notifications); Lambda backends; spiky or idle workloads; IoT/device state/game state/feature flags/tokens; event-driven systems; multi-region active-active.

**Choose something else**: unknown/fast-changing patterns (PostgreSQL); complex relational data or strict integrity (PostgreSQL/MySQL); analytics (warehouse/Athena); search (OpenSearch); flexible docs with rich queries (MongoDB); caching/leaderboards/pub-sub (Redis); avoiding lock-in or on-prem (Cassandra, ScyllaDB, MongoDB, PostgreSQL).

**Checklist** (mostly "yes" → DynamoDB):

1. Can I list my main access patterns today?
2. Are most reads "get by ID" or "items belonging to X sorted by Y"?
3. Do I value scale/serverless/predictable latency over query flexibility?
4. Can analytics and search live elsewhere?
5. Am I comfortable on AWS long-term?

---

## 11. Scenario: updating 10,000 records

### The key fact

DynamoDB has **no `UPDATE ... WHERE` across many items**. Every update targets **one item by its full primary key**. So a bulk update is always two steps:

1. **Find the keys** of the items to change (Query on the table/GSI if an access pattern exists; otherwise a parallel Scan with a filter for a one-off job).
2. **Update each item**, in parallel, with retries.

### Options for the write step

| Approach | Notes |
|---|---|
| `UpdateItem` per item, parallelized with threads | Best default. Partial updates, conditions, atomic counters all supported. |
| PartiQL `BatchExecuteStatement` | Batches up to **25 `UPDATE` statements** per call (each targets one item by full key). Fewer round trips; still not atomic; check per-statement errors. |
| `BatchWriteItem` | Only puts/deletes, so you must read each item, modify, and **write the whole item back**. Risks overwriting concurrent changes; no conditions. Avoid for updates unless items aren't being modified elsewhere. |
| Transactions | Only if groups of ≤100 items must change atomically. 2× cost. A 10k update would be 100 separate transactions, not one atomic change. |

### Capacity and time estimate

- Cost: an update consumes write units based on the **larger of the item's before/after size**. 10,000 items of ≤1 KB ≈ **10,000 write units total** (plus GSI writes if indexed attributes change).
- On-demand: no planning needed. Provisioned: make sure you have headroom, or the job gets throttled (and can starve live traffic). Rate-limit the job if needed.
- Time: one UpdateItem takes roughly 5–10 ms. Single-threaded ≈ 1–2 minutes; with 20–30 threads ≈ a few seconds. If all 10k items share **one partition key**, expect the per-partition ceiling (~1,000 writes/sec), so ≥ ~10 seconds regardless of parallelism (adaptive splitting may help on a sustained job, but don't count on it).

### Example: archive all orders created before 2026 (boto3, parallel)

```python
import threading
import boto3
from botocore.config import Config
from boto3.dynamodb.conditions import Attr
from concurrent.futures import ThreadPoolExecutor

TABLE = "Orders"
cfg = Config(retries={"max_attempts": 10, "mode": "adaptive"}, max_pool_connections=64)
_local = threading.local()

def table():
    # boto3 resources aren't thread-safe; one per thread
    if not hasattr(_local, "t"):
        _local.t = boto3.resource("dynamodb", config=cfg).Table(TABLE)
    return _local.t

# Step 1: collect keys (parallel scan; only fetch key attributes)
def scan_segment(segment, total):
    keys, kwargs = [], {
        "Segment": segment, "TotalSegments": total,
        "FilterExpression": Attr("createdAt").lt("2026-01-01") & Attr("status").ne("ARCHIVED"),
        "ProjectionExpression": "PK, SK",
    }
    while True:
        resp = table().scan(**kwargs)
        keys += resp["Items"]
        if "LastEvaluatedKey" not in resp:
            return keys
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

# Step 2: update one item (idempotent, never creates new items)
def archive(key):
    try:
        table().update_item(
            Key=key,
            UpdateExpression="SET #s = :archived",
            ConditionExpression="attribute_exists(PK) AND #s <> :archived",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":archived": "ARCHIVED"},
        )
        return "updated"
    except table().meta.client.exceptions.ConditionalCheckFailedException:
        return "skipped"   # already archived or deleted

SEGMENTS = 8
with ThreadPoolExecutor(SEGMENTS) as pool:
    keys = [k for seg in pool.map(scan_segment, range(SEGMENTS), [SEGMENTS] * SEGMENTS) for k in seg]

with ThreadPoolExecutor(32) as pool:
    results = list(pool.map(archive, keys))

print(len(keys), "candidates;", results.count("updated"), "updated")
```

Why each piece matters:

- `attribute_exists(PK)` stops UpdateItem from **creating** an item if it was deleted meanwhile (UpdateItem upserts by default).
- `#s <> :archived` makes the job **idempotent**: safe to rerun after a crash.
- Adaptive retry mode backs off automatically on throttling.
- If there's an access pattern for the selection (e.g. a GSI or a single item collection), use **Query instead of Scan** in step 1.

### Using PySpark (AWS Glue)

For **10,000 items, Spark is overkill**: the boto3 script finishes in seconds. Spark/Glue becomes worthwhile for **millions** of items, complex transformations, or joining DynamoDB data with other sources.

Approach: read with the Glue DynamoDB connector (or from an S3 export), filter/transform in Spark, then update items with `foreachPartition` using boto3 `update_item` (partial updates). The Glue **writer** connector does whole-item puts, which replace items, so use it only when you're writing complete items.

```python
from awsglue.context import GlueContext
from pyspark.context import SparkContext
from pyspark.sql import functions as F

glue = GlueContext(SparkContext.getOrCreate())

dyf = glue.create_dynamic_frame.from_options(
    connection_type="dynamodb",
    connection_options={
        "dynamodb.input.tableName": "Orders",
        "dynamodb.throughput.read.percent": "0.5",   # use at most ~50% of read capacity
        "dynamodb.splits": "40",                      # parallel scan segments
    },
)
df = (dyf.toDF()
        .filter((F.col("createdAt") < "2026-01-01") & (F.col("status") != "ARCHIVED"))
        .select("PK", "SK"))

def update_partition(rows):
    import boto3
    from botocore.config import Config
    t = boto3.resource("dynamodb",
                       config=Config(retries={"max_attempts": 10, "mode": "adaptive"})).Table("Orders")
    for r in rows:
        try:
            t.update_item(
                Key={"PK": r["PK"], "SK": r["SK"]},
                UpdateExpression="SET #s = :a",
                ConditionExpression="attribute_exists(PK) AND #s <> :a",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":a": "ARCHIVED"},
            )
        except t.meta.client.exceptions.ConditionalCheckFailedException:
            pass

df.repartition(32).foreachPartition(update_partition)   # 32 parallel writers
```

Notes:

- `dynamodb.throughput.read.percent` and the number of Spark partitions are your throttles; tune them so the job doesn't starve production traffic.
- To avoid consuming any read capacity, use **Export to S3** (requires point-in-time recovery; doesn't touch table capacity) and read the export in Spark. Glue also offers an export-based read mode for its DynamoDB connector; check current Glue docs for the option names.
- **Import from S3** only creates a **new** table, so it's for migrations/rebuilds, not in-place updates.
- Other options at large scale: Step Functions Distributed Map with Lambda workers, or EMR.

---

## 12. Scenario: reading 1 million records in 10 minutes

**Short answer: yes, comfortably.** 1M items in 600 s ≈ **1,700 items/sec**, which is modest for DynamoDB.

### Capacity math (assume 1 KB items)

- Total data ≈ 1 GB.
- Query/Scan charge by total data read: 1 GB ÷ 4 KB ≈ 250,000 units strongly consistent, **≈125,000 units eventually consistent**.
- Over 600 s ≈ **~210 read units/sec** (eventual). Even with 10 KB items it's ~2,100/sec.
- On-demand handles this easily; on provisioned, ensure the table (and its auto-scaling max) allows that rate on top of normal traffic.

### How to read it depends on the access pattern

| Situation | Approach |
|---|---|
| Whole table (or most of it) | **Parallel Scan** with `Segment` / `TotalSegments` (e.g. 8–32 workers) |
| All items under one partition key | **Query** with pagination. Single-partition reads cap at ~3,000 units/sec (≈24 MB/s eventual), still far above what's needed. To parallelize, split the sort key range (e.g. by month) into concurrent Queries. |
| 1M specific known keys | **BatchGetItem** (100 keys/call → 10,000 calls) across threads; cost rounds up per item (~0.5 unit each eventual → ~830 units/sec over 10 min) |
| Analytics / bulk processing | **Export to S3**, then Spark/Athena. No read capacity consumed, no impact on live traffic. |
| Same hot data read repeatedly | **DAX** cache in front |

### Parallel scan example

```python
from concurrent.futures import ThreadPoolExecutor
import boto3

def scan_segment(segment, total=16):
    t = boto3.resource("dynamodb").Table("Orders")
    count, kwargs = 0, {"Segment": segment, "TotalSegments": total}
    while True:
        resp = t.scan(**kwargs)
        count += len(resp["Items"])          # process items here (write to file/S3, etc.)
        if "LastEvaluatedKey" not in resp:
            return count
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

with ThreadPoolExecutor(16) as pool:
    print(sum(pool.map(scan_segment, range(16))))
```

Each Scan call returns up to 1 MB (~1,000 × 1 KB items), so 1 GB is ~1,000 calls; spread over 16 workers this typically finishes in **well under a minute to a few minutes**, depending on client CPU and network.

### Things to watch

- **Real bottleneck is often the client** (deserialization, network), not DynamoDB. Run close to the table (same region, e.g. EC2/Lambda/Glue), and use multiple workers.
- **Protect production traffic**: a big scan consumes capacity. Rate-limit, use a low `read.percent` in Glue, run off-peak, or use Export to S3.
- **Eventually consistent reads** are half the cost and fine for bulk reads.
- **Filters don't reduce cost**, so a scan that "returns 1M of 50M items" still pays for reading 50M. If that's a recurring need, add a GSI (possibly sparse) or use exports.
- **Export to S3 is not instant** (it takes minutes) but is ideal for analytics; for a live "read now" job, parallel Scan/Query is the way.

---

## 13. Quick revision: interview questions

**Why can't a chat table use just `timestamp` as the sort key?**
PK + SK must be unique; same-millisecond messages would overwrite each other. Use `timestamp#messageId` or a ULID.

**Why is Scan + filter bad for "messages by user"?**
It reads (and charges for) the whole table and gets slower as data grows. Use a GSI keyed by sender.

**Why can GSI keys be duplicated but base keys can't?**
Uniqueness is enforced where writes happen (base table). The GSI is a read-only projection; each entry also carries the base key.

**How do you sort a user's chats by recent activity?**
Store `lastActivityAt` on membership items + a GSI on (user, lastActivityAt). Cost: write fan-out per message, done asynchronously via Streams + Lambda.

**500-member group fan-out: request, transaction, or Streams?**
Streams + Lambda. In-request is slow with partial-failure risk; transactions max out at 100 items.

**Comments as a list on the post item: what breaks?**
The 400 KB item limit, plus write cost scaling with item size and single-item contention (per-partition write ceiling). Store comments as separate items under `PK=POST#id`, keep `commentCount` on the post.

**Finance dashboard with arbitrary filters vs session tokens for 5M DAU?**
SQL for the dashboard; DynamoDB (GetItem + TTL) for sessions.

**Global leaderboard + profiles + match history?**
Redis sorted sets for the leaderboard; DynamoDB for profiles and history (and durable scores to rebuild Redis).

**How do you enforce a unique email?**
Guard item `PK=EMAIL#<email>` written in the same transaction as the user, both with `attribute_not_exists(PK)`.

**How do you update 10,000 items?**
No bulk UPDATE WHERE. Find keys (Query/GSI, or parallel Scan for one-offs), then parallel `UpdateItem` (or PartiQL batches of 25) with conditional, idempotent writes and adaptive retries. Spark/Glue only pays off at millions of items.

**Can DynamoDB read 1M items in 10 minutes?**
Yes: ~1,700 items/sec, roughly 200 read units/sec for 1 KB items with eventual consistency. Use parallel Scan/Query, or Export to S3 for analytics without touching table capacity.
