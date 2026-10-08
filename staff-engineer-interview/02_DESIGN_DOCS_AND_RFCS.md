# 📝 Design Docs, RFCs and ADRs

> **Writing is the Staff engineer's main lever.** How to write a design doc people actually read, a template you can paste, how to run the review, and how to answer questions about it in an interview.

---

## Table of Contents

1. [Why docs matter](#1-why-docs-matter)
2. [When to write which document](#2-when-to-write-which-document)
3. [Design doc template](#3-design-doc-template)
4. [Writing principles](#4-writing-principles)
5. [Running the review](#5-running-the-review)
6. [ADR template](#6-adr-template)
7. [Example: a compressed design doc](#7-example-a-compressed-design-doc)
8. [Interview questions about design docs](#8-interview-questions)

---

## 1. Why docs matter

- **Cheapest place to find bugs.** Changing a paragraph costs minutes; changing a shipped system costs quarters.
- **Scales your influence.** A doc reaches people you'll never meet; a meeting doesn't.
- **Forces clear thinking.** If you can't write the trade-off, you don't understand it.
- **Creates durable context.** Six months later, "why did we do it this way?" has an answer.
- **Makes alignment asynchronous,** which is how cross-team, cross-timezone work actually happens.

---

## 2. When to write which document

| Document | Purpose | Length | Audience |
|---|---|---|---|
| **One-pager / proposal** | Decide *whether* to do something; get a go/no-go | 1 page | Leads, PM, EM |
| **Design doc** | Decide *how*; record trade-offs | 3–10 pages | Engineers on affected teams |
| **RFC** | Cross-team or org-wide standard or change; open comment period | 5–15 pages | Wide audience; decision by named approvers |
| **ADR** (Architecture Decision Record) | Record a single decision and its context permanently | ½–1 page | Future maintainers |
| **Runbook** | How to operate and fix a system | Procedural | On-call |
| **Postmortem** | Learn from an incident | 2–5 pages | Whole org |
| **Technical strategy** | Multi-year direction: diagnosis, policy, actions | 3–8 pages | Engineering leadership |

**When *not* to write a design doc:** small, reversible changes where the code review is the design review. Rule of thumb: write one when the change is **hard to reverse, touches multiple teams, or takes more than ~2 weeks of effort**.

---

## 3. Design doc template

```markdown
# <Title: noun phrase describing the system/change>

| | |
|---|---|
| Author(s) | |
| Reviewers | (named; each owns a specific concern) |
| Status | Draft / In review / Approved / Implemented / Superseded |
| Decision deadline | <date> |
| Last updated | |

## 1. Summary (TL;DR)
Three to five sentences: the problem, the proposal, the key trade-off, the ask.

## 2. Context and Problem
What's wrong today? Evidence (metrics, incidents, customer impact). Why now?

## 3. Goals and Non-Goals
Goals: measurable outcomes ("p99 < 200 ms", "cut cost by 30%").
Non-goals: what this explicitly does not do (prevents scope creep).

## 4. Background (only what readers need)
Existing architecture, constraints, terminology.

## 5. Proposed Design
- Overview diagram
- Components and responsibilities
- Data model and APIs (with examples)
- Key flows (happy path and failure paths)
- Consistency, concurrency, and failure semantics
- Security, privacy, and compliance
- Scalability: capacity estimate and bottlenecks

## 6. Alternatives Considered
For each: what it is, why it's attractive, why rejected (honestly). Include "do nothing."

## 7. Trade-offs and Risks
What we give up. Top risks, likelihood/impact, mitigations. Open questions.

## 8. Rollout and Migration Plan
Phases, feature flags, dark launch/shadow traffic, canary, rollback plan,
data migration and backfill, compatibility, deprecation of the old path.

## 9. Observability and Operations
SLIs/SLOs, dashboards, alerts, runbooks, on-call impact, capacity and cost.

## 10. Testing Strategy
Unit, integration, load, failure injection, migration verification.

## 11. Timeline and Staffing
Milestones, owners, dependencies on other teams.

## 12. Open Questions
Each with an owner and a due date.

## Appendix
Benchmarks, detailed calculations, references.
```

---

## 4. Writing principles

1. **Put the answer first.** The summary should let a busy VP decide whether to read on. Reviewers read the top and skim the rest.
2. **Write for the reader who wasn't in the room.** Define terms; link to background instead of re-explaining it.
3. **State decisions and the reasons,** not just the design. "We chose X *because* Y; we considered Z but it fails on W."
4. **Make trade-offs explicit.** A design with no stated downsides is untrustworthy.
5. **Use numbers.** Capacity, latency, cost, error budgets. "Fast" and "scalable" are not requirements.
6. **Show failure paths.** What happens when the dependency is down, the message is duplicated, the deploy is half-done?
7. **Diagrams for structure, prose for reasoning.** One good diagram beats three pages of description; but reasoning needs sentences.
8. **Be concise.** Cut background that doesn't change a decision. Length is not rigor.
9. **Separate facts, assumptions, and opinions.** Mark assumptions so reviewers can challenge them.
10. **Keep it alive.** Update status and decisions; mark superseded designs so nobody implements stale ones.

**Weak vs. strong sentence:**

| Weak | Strong |
|---|---|
| "We will use Kafka for scalability." | "We will publish order events to Kafka (partitioned by `order_id`) so consumers can scale independently and replay; the cost is one more system to operate and at-least-once delivery, so consumers must be idempotent." |
| "This might cause some latency." | "Adds ~15 ms p99 (one extra hop, measured in staging); within the 200 ms budget." |

---

## 5. Running the review

**Before:**
- **Pre-socialize** with the 2–3 people most affected. Nobody should be surprised in the formal review.
- Name reviewers and what each owns (security, data, SRE, the consuming team).
- Set a **decision deadline** and a comment window (typically 3–5 business days).

**During (if there's a meeting):**
- Don't present the doc; assume it was read. Spend the time on **open disagreements and risks**.
- Categorize feedback: **blocking** (must resolve), **should-fix**, **nit**, **question**.
- Time-box debates; if unresolved, assign an owner to run an experiment or a decision-maker to choose.
- Make it safe for the most junior person to say "I don't understand this."

**After:**
- Record decisions and changes in the doc; list unresolved items with owners.
- Convert key decisions to ADRs.
- Notify everyone who commented how their feedback was handled.
- Revisit after launch: did reality match the doc? (A short "retrospective" section builds credibility.)

**Decision rights:** Be explicit. "Consensus" is slow; "informed disagree-and-commit" is faster. Name an approver (the DRI: directly responsible individual) up front.

---

## 6. ADR template

Keep ADRs short, immutable once accepted (supersede, don't edit), and stored with the code (e.g. `docs/adr/0007-use-postgres-for-ledger.md`).

```markdown
# ADR-0007: Use PostgreSQL as the system of record for the ledger

- Status: Accepted (2026-03-14)   <!-- Proposed | Accepted | Deprecated | Superseded by ADR-00xx -->
- Deciders: <names / team>
- Context: What forces are at play? Constraints, requirements, current state.
- Decision: We will ... (one clear sentence)
- Consequences: Positive, negative, and what becomes easier or harder.
- Alternatives considered: A (why not), B (why not).
- Revisit when: <trigger, e.g. "sustained write load above 10k TPS">
```

---

## 7. Example: a compressed design doc

> **Title:** Idempotent payment submission
> **TL;DR:** Duplicate charges occurred 0.04% of the time (≈ 120/month) because clients retry on timeout. We propose requiring an `Idempotency-Key` on `POST /payments`, stored with the request fingerprint and response for 24 h. Cost: one extra write per request (~1 ms) and a new table. We reject client-side dedupe (can't be trusted) and DB unique constraints alone (can't return the original response).
>
> **Goals:** zero duplicate charges from retries; < 5 ms p99 overhead; no API break for existing clients (key optional for 60 days, then required).
> **Non-goals:** deduplicating across different keys; refunds.
>
> **Design:** `idempotency_keys(key, account_id, request_hash, status, response, created_at)` with `UNIQUE(account_id, key)`. First request inserts `status=in_progress` in the same transaction as the charge intent; concurrent duplicates see `in_progress` and get `409` with `Retry-After`; completion stores the response; a repeat with the same key and a *different* hash returns `422`.
>
> **Alternatives:** (1) Client dedupe: rejected, untrusted. (2) Exactly-once via PSP only: rejected, not all PSPs support it. (3) Do nothing: ≈ 120 duplicate charges/month, support cost ≈ X.
>
> **Risks:** key table growth (TTL job; partition by day); key reuse bugs in clients (hash check catches); hot keys (none expected).
>
> **Rollout:** shadow-log missing keys 2 weeks → soft enforce (warn header) → enforce. Rollback: flag. **Metrics:** duplicate-charge count, 409 rate, key-table size, p99 overhead.

Notice: problem quantified, decision stated, alternatives rejected for stated reasons, risks and rollout concrete, success metrics defined.

---

## 8. Interview questions

**Q1. "How do you decide something needs a design doc?"**
When the change is hard to reverse, crosses team boundaries, or costs more than a couple of weeks. A doc is a tool for finding disagreement cheaply; if nobody could plausibly disagree or the change is trivially reversible, skip it and use code review.

**Q2. "What makes a design doc good?"**
It leads with the decision and the ask, quantifies the problem, lists real alternatives with honest reasons for rejection, makes failure and rollout paths explicit, and states what we're giving up. A reader who wasn't in the room can act on it.

**Q3. "A senior engineer blocks your design in review. What do you do?"**
Understand the underlying concern (ask "what are you optimizing for?"), separate facts from preferences, test disputed assumptions with data or a small prototype, and, if unresolved, escalate to the named decision-maker with both positions written fairly. After the decision, commit fully.

**Q4. "How do you get people to read your docs?"**
Short summary on top, pre-socialize with key reviewers, ask specific people for specific feedback, set a deadline, and make comments easy. Respond to every comment; people review more when they see it matters.

**Q5. "How do you keep documentation from rotting?"**
Co-locate with code, assign owners, tie ADRs to decisions (immutable) and runbooks to services (reviewed on incidents), mark status clearly, and delete or archive superseded docs. Treat a wrong doc as worse than none.

**Q6. "Tell me about a design doc you wrote that changed the outcome."**
Pick one where review surfaced a flaw (e.g. an unconsidered failure mode), the design changed, and you can cite the avoided cost. Show the doc's role: it made disagreement cheap and early.
