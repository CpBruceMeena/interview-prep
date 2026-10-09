# 🧭 Study Guide: What to Read, and in What Order

The tabs at the top are numbered **1 to 8** in the order that builds understanding best. You do not have to read all of them. Pick your **target role**, adjust for your **language background**, then follow the matching track.

---

## 1. The 8 tabs and why they are in this order

| # | Tab | What it gives you | Why here |
|---|---|---|---|
| 1 | [CS Core](cs-interview/README.md) | OS, networks, databases, concurrency, distributed systems, security | Every later topic leans on these. Skipping it makes system design feel like memorised diagrams. |
| 2 | [Coding (DSA)](python-dsa/index.md) | 190 problems, 20 categories | Independent of everything else. Start early and do a little every day. |
| 3 | [Languages](golang-interview/README.md) | Runtime internals and concurrency for Python, Go and Java | Read your own language here before writing LLD code in it. |
| 4 | [Low-Level Design](python-low-level-design/LLD_INTERVIEW_PLAYBOOK.md) | Playbook plus 30 worked projects | Applies OOP, concurrency and your language to a concrete problem. |
| 5 | [System Design](system-design-interview/README.md) | Framework plus 8 case studies | Needs the CS Core theory and LLD modelling skills. |
| 6 | [Infrastructure & Cloud](aws-interview/README.md) | AWS, Kafka, Redis, Kubernetes and more | The building blocks you name in a system design answer. |
| 7 | [AI Engineering](ai-engineering/README.md) | LLM internals, RAG, MCP, agents | Builds on APIs, databases, queues and distributed systems. |
| 8 | [Staff Craft](staff-engineer-interview/README.md) | Behavioural stories, RFCs, reliability | Do it last, but **start collecting stories early**. |

---

## 2. How to work through any page

Reading is the weakest way to prepare. For every page:

1. **Skim headings first** (2 minutes) so you know the shape.
2. **Cover the answer.** Read the question, say or write your answer out loud, then compare.
3. **Run the code.** Every Python, Go and Java example is meant to be executed or modified.
4. **Write a 3-line summary** from memory: the idea, the trade-off, when you would not use it.
5. **Revisit** after 1 day, 1 week, 3 weeks. Spaced review beats a single long read.

### Use the diagrams and videos

Most pages have **Mermaid diagrams** (flows, sequences, state machines, ER schemas) and many have **animated videos** of the key mechanism. Look at the diagram *before* reading the text that follows it, and try to narrate it. If your narration disagrees with the text, that is the part to re-read.

### Low-level design projects (every project has the same 5 pages)

`index` (the problem) → `Thought Process` → **close it and try the design yourself** → `Code` → `HLD` (and `Schema` where present) → `Questions`

Read the [LLD Playbook](python-low-level-design/LLD_INTERVIEW_PLAYBOOK.md) once before any project. The Python projects are ordered **easy to hard**: stop when the projects feel routine, do not feel obliged to finish all 24.

### System design case studies

Read [Framework & Estimation](system-design-interview/00_FRAMEWORK_AND_ESTIMATION.md) first. Then for each case study: read **Requirements and Estimation only**, sketch your own design for 20 minutes, then read the rest and compare.

---

## 3. Pick your track by target role

### Backend engineer (Senior), generic

1. CS Core: OS, Networks, Databases, then Concurrency and Distributed Systems.
2. DSA a little every day alongside everything else.
3. Your language in **Languages**.
4. LLD Playbook plus a handful of projects (Parking Lot, LRU Cache, Rate Limiter, Pub-Sub, Splitwise).
5. System Design: framework plus URL Shortener, News Feed, Chat. Then Staff Craft: Behavioural.

### Staff / Principal engineer

Add depth and judgement on top of the track above.

1. CS Core in full, including the deep dives (PostgreSQL, DynamoDB, Distributed Transactions, Design Patterns).
2. System Design: **all 8** case studies, then re-do two from a blank page.
3. Infrastructure & Cloud: AWS Architecture, Kubernetes Production Control, CI/CD Deployment.
4. Staff Craft: all three guides. Write 6 to 8 behavioural stories before reading the guide, then refine them.
5. LLD: Playbook plus the harder projects (Order Matching, Job Scheduling, Search Platform).

### AI engineer / Forward Deployed Engineer

1. [Preparation Strategy](ai-engineering/AI_PREPARATION_STRATEGY.md), then [Forward Deploy Engineer Guide](ai-engineering/FORWARD_DEPLOY_ENGINEER_GUIDE.md).
2. LLM Internals → RAG → MCP → Agents, in that order (the sidebar already lists them so).
3. Backend foundations: CS Core (Databases, Distributed Systems), Redis, Kafka, Elasticsearch.
4. System Design: Chat, Typeahead, Ad Click Aggregation. Their data-pipeline thinking carries over to RAG and agent systems.
5. Staff Craft: Behavioural, because FDE loops weight customer-facing stories heavily.

### Infrastructure / SRE-leaning backend

1. CS Core: OS, Networks, Distributed Systems.
2. Infrastructure & Cloud: AWS (all), Docker → Kubernetes → Nginx → Terraform → Prometheus & Grafana → CI/CD.
3. Staff Craft: Reliability & Operations.
4. System Design: Payments Ledger, Ad Click Aggregation, File Storage.

---

## 4. Adjust for your language background

DSA solutions and 24 of the 30 LLD projects are in **Python**. Java has 3 LLD projects and Go has 3. The concepts are language-neutral, so use this as a translation guide.

### You mainly write Python

- Languages: Python page order is **Multithreading (GIL) → Async Basics → Asyncio → Django / FastAPI → Interview Questions**. Read Async Basics before the long Asyncio notes.
- Everything else reads natively. Do the Go or Java LLD projects only if the role asks for them.

### You mainly write Java

- Languages: **JVM Internals & GC → Object Handling & Memory → Spring Boot → Interview Questions**.
- DSA and most LLD code is Python, which reads close to pseudocode. Translate each solution to Java once in your head. For LLD, start with the 3 Java projects (Elevator, Hotel Booking, Meeting Scheduler), then use Python for the rest.
- Read the Python **Multithreading** page for the GIL story only if you are interviewing for polyglot roles.

### You mainly write Go

- Languages: **Language Internals → Pointers & Memory → Concurrency → Concurrency Coding Challenges → Production Services → Interview Questions**.
- Do the 3 Go LLD projects (Web Crawler, KV Store, Task Queue). They are concurrency-heavy, which is what Go interviews test.
- Python LLD pages still help for the modelling steps: Thought Process and HLD are language-neutral.

### You come from JavaScript/TypeScript, C#, C++ or another language

- Pick the page closest to your mental model: **Java** for C# or C++ readers (classes, GC, threads), **Go** for Node.js readers moving to services (goroutines map to the event loop plus workers), **Python** for anyone who wants the fastest readable syntax for DSA.
- Do the DSA in your own language. Use the Python solutions as the reference for the algorithm, not for the syntax.
- Read the [LLD Playbook](python-low-level-design/LLD_INTERVIEW_PLAYBOOK.md) and the first three Python projects in full, then write the next ones yourself in your language.

---

## 5. Habits that matter more than coverage

- **Do DSA daily**, 30 to 60 minutes, rather than in big blocks.
- **Say your design out loud.** LLD and system design are communication rounds.
- **Do timed mocks** for each round type you will face: 45 minutes for system design, 60 for LLD.
- **Keep a mistakes list.** Review it the night before.
- If a page feels too hard, **go one tab earlier** (usually CS Core) instead of pushing through.
