# 🌐 Multi-LLM Architecture — Routing, Cost Management & Fallback

> **Target:** Principal Engineer | **Focus:** Production architecture for orchestrating multiple LLM providers | **Reviewed:** October 2026

!!! tip "30-second answer"
    Put a thin **model gateway** between your app and providers. Callers ask for a *capability tier* ("small", "mid", "frontier", "code"), never a hard-coded model id; config maps tiers to concrete models per provider. The gateway routes (rules first, a cheap classifier for ambiguous cases), enforces per-tenant budgets, retries transient errors, fails over across providers behind circuit breakers, and records tokens, cost and latency per call. Every routing or fallback target must have passed the same eval suite, because a fallback that answers badly is worse than a clear error.

**Model names below are tier aliases on purpose.** Model ids, prices and context windows change every few months; keep them in config and check each provider's models and pricing pages. As of October 2026, examples per tier:

| Tier alias | Use for | Examples (illustrative, check current lineups) |
|------------|---------|-----------------------------------------------|
| `small` | Classification, routing, extraction, simple Q&A | Claude Haiku 4.5, GPT-6 Luna, small open-weight models |
| `mid` | Most agent and RAG work | Claude Sonnet 5.5, GPT-6.1 Sol |
| `frontier` | Hard reasoning, long-horizon agents, research | Claude Opus 5.5, GPT-6 Astra |
| `open` | Self-hosted / data-residency / cost floor | Open-weight families (DeepSeek, Qwen, Llama, Mistral) |

---

## 1. WHY MULTI-LLM ARCHITECTURE?

No single LLM is optimal for every task. A Multi-LLM architecture allows:

- **Cost optimization** — Use cheap models for simple tasks, expensive ones for complex
- **Quality optimization** — Route to the best model for each task type
- **Reliability** — Fallback when one provider is down
- **Latency optimization** — Fast models for real-time, slow models for batch
- **Vendor independence** — Avoid lock-in to a single provider

```
                    ┌─────────────────────────────┐
                    │     ROUTER / ORCHESTRATOR    │
                    │                              │
                    │  Complexity Analysis          │
                    │  Cost Budget Check            │
                    │  Latency Requirements         │
                    │  Fallback Chain               │
                    └──────┬──────┬──────┬──────┬──┘
                           │      │      │      │
              ┌────────────┘      │      │      └────────────┐
              ▼                   ▼      ▼                   ▼
        ┌──────────┐      ┌──────────┐      ┌──────────┐
        │Provider A│      │Provider B│      │Self-hosted│
        │(frontier)│      │  (mid)   │      │  (open)   │
        └──────────┘      └──────────┘      └──────────┘
```

---

## 2. QUERY ROUTING STRATEGIES

### 2.1 Rule-Based Routing

```python
from dataclasses import dataclass
from typing import Optional
import re

@dataclass
class RouteDecision:
    """Decision result from the router."""
    model: str                      # a tier alias, resolved to a concrete id by config
    temperature: Optional[float] = None   # many reasoning models reject sampling params
    complexity: str = "simple"
    requires_tools: bool = False
    reason: str = ""
    cost_estimate: float = 0.0
    confidence: float = 1.0


class RuleBasedRouter:
    """
    Routes queries based on explicit rules.
    Fast, deterministic, no additional LLM cost.
    """
    
    RULES = [
        {
            "name": "code_generation",
            "pattern": r"(write|generate|create|implement).*(code|function|class|api)",
            "model": "code",
            "priority": 1
        },
        {
            "name": "complex_reasoning",
            "pattern": r"(analyze|compare|evaluate|why|how|explain).*(complex|trade-off|impact)",
            "model": "mid",
            "priority": 2
        },
        {
            "name": "simple_qa",
            "pattern": r"^(what|when|where|who|define|tell me about)\b",
            "model": "small",
            "priority": 3
        },
        {
            "name": "creative_writing",
            "pattern": r"(write|draft|compose).*(story|email|blog|article|content)",
            "model": "mid",
            "temperature": 0.8,
            "priority": 2
        },
        {
            "name": "data_analysis",
            "pattern": r"(analyze|chart|graph|plot|report|dashboard)",
            "model": "frontier",
            "priority": 1
        }
    ]
    
    def route(self, query: str) -> RouteDecision:
        """Route query to the best model based on pattern matching."""
        for rule in sorted(self.RULES, key=lambda r: r["priority"]):
            if re.search(rule["pattern"], query, re.IGNORECASE):
                return RouteDecision(
                    model=rule["model"],
                    temperature=rule.get("temperature"),
                    reason=f"Matched rule: {rule['name']}",
                    cost_estimate=self._estimate_cost(rule["model"]),
                    confidence=0.9,
                )
        
        # Default: low confidence, so a hybrid router escalates to the LLM router
        return RouteDecision(
            model="small",
            reason="No rule matched — using default",
            cost_estimate=self._estimate_cost("small"),
            confidence=0.0,
        )
```

Regex routing is brittle (note `"data_analysis"` and `"complex_reasoning"` both match "analyze"). Treat it as a fast path for unambiguous traffic, and measure routing accuracy on labelled queries like any other classifier.

### 2.2 LLM-as-Router (Intelligent Routing)

```python
class LLMRouter:
    """
    Uses a cheap LLM to classify and route queries.
    More flexible than rule-based, but adds latency and cost.
    """
    
    ROUTING_PROMPT = """Classify this user query. Respond with JSON:
{
    "complexity": "simple|medium|complex",
    "type": "code|reasoning|creative|analysis|factual|general",
    "requires_tools": true|false,
    "suggested_tier": "small|mid|frontier|code",
    "reasoning": "brief explanation"
}

Tiers:
- small: simple Q&A, factual lookups, greetings, classification
- mid: general purpose, analysis, most tool use
- frontier: multi-step reasoning, research, hard math, long-horizon tasks
- code: code generation and debugging

Query: {query}
"""
    
    def __init__(self, classifier_model: str = "small"):
        # Use structured outputs / a JSON schema so the reply always parses.
        self.classifier_llm = get_chat_model(classifier_model)
    
    async def route(self, query: str) -> RouteDecision:
        """Use LLM to classify and route the query."""
        response = await self.classifier_llm.ainvoke(
            self.ROUTING_PROMPT.replace("{query}", query)
        )
        
        try:
            classification = json.loads(response.content)
        except json.JSONDecodeError:
            return self._fallback_route(query)
        
        return RouteDecision(
            model=self._map_to_available_model(classification["suggested_tier"]),
            temperature=self._get_temperature(classification["type"]),
            complexity=classification["complexity"],
            requires_tools=classification["requires_tools"],
            reason=classification.get("reasoning", "LLM classified"),
            cost_estimate=self._estimate_cost(classification["suggested_tier"])
        )
```

Routing pays off only when the router costs much less than it saves. A small-model classification call adds a few hundred milliseconds and a little cost to *every* request; it is worth it when a large share of traffic can safely go to a much cheaper tier. Alternatives: a fine-tuned small classifier or an embedding-similarity router (no generation at all), or a **cascade** (try the cheap model, escalate when a verifier rejects the answer).

### 2.3 Hybrid Routing (Recommended)

```python
class HybridRouter:
    """
    Two-stage routing:
    1. Rule-based (fast) for clear-cut cases
    2. LLM-based (smart) for ambiguous cases
    
    This balances speed and accuracy.
    """
    
    def __init__(self):
        self.rule_router = RuleBasedRouter()
        self.llm_router = LLMRouter()
    
    async def route(self, query: str) -> RouteDecision:
        # Stage 1: Try rule-based routing (0ms, $0 cost)
        decision = self.rule_router.route(query)
        
        # If it's a clear match with high confidence, use it
        if decision.confidence > 0.8:
            return decision
        
        # Stage 2: Fall back to LLM routing (200ms, ~$0.001 cost)
        llm_decision = await self.llm_router.route(query)
        
        # Merge decisions (use more conservative estimate)
        return RouteDecision(
            model=llm_decision.model,
            temperature=llm_decision.temperature,
            complexity=llm_decision.complexity,
            reason=f"Rule: {decision.reason} | LLM: {llm_decision.reason}",
            cost_estimate=max(decision.cost_estimate, llm_decision.cost_estimate)
        )
```

---

## 3. COST MANAGEMENT

### 3.1 Real-Time Cost Tracking

```python
@dataclass
class LLMCallRecord:
    """Record of a single LLM API call."""
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost: float
    latency_ms: int
    timestamp: datetime
    route_reason: str
    success: bool
    error: Optional[str] = None

class CostTracker:
    """Real-time cost tracking and budgeting."""
    
    def __init__(self, pricing: dict, monthly_budget: float = 10000.0):
        # pricing: {concrete_model_id: {"input": usd_per_1M, "output": usd_per_1M,
        #           "cached_input": ..., "cache_write": ...}}
        # Load from config and keep it in sync with provider pricing pages;
        # prices change too often to hard-code.
        self.pricing = pricing
        self.monthly_budget = monthly_budget
        self.current_month_cost = 0.0
        self.records: List[LLMCallRecord] = []
        self._lock = asyncio.Lock()
    
    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost for a model call."""
        pricing = self.pricing[model]   # KeyError on unknown models: never guess cheap
        return (
            (input_tokens / 1_000_000) * pricing["input"] +
            (output_tokens / 1_000_000) * pricing["output"]
        )
    
    async def track_call(self, record: LLMCallRecord):
        """Track an LLM call and check budget."""
        # In-process state is per replica. With N replicas, keep the running
        # total in a shared store (e.g. Redis INCRBYFLOAT per tenant per month)
        # and reconcile against the provider's usage/billing API daily.
        async with self._lock:
            self.current_month_cost += record.cost
            self.records.append(record)
            
            # Check budget
            if self.current_month_cost > self.monthly_budget:
                raise BudgetExceeded(
                    f"Monthly budget ${self.monthly_budget:.2f} exceeded: "
                    f"${self.current_month_cost:.2f}"
                )
    
    def get_usage_report(self) -> dict:
        """Generate usage report by model and route reason."""
        report = {
            "total_cost": self.current_month_cost,
            "total_calls": len(self.records),
            "by_model": {},
            "by_route": {},
            "daily_trend": {}
        }
        
        for record in self.records:
            # By model
            if record.model not in report["by_model"]:
                report["by_model"][record.model] = {"calls": 0, "cost": 0.0, "tokens": 0}
            report["by_model"][record.model]["calls"] += 1
            report["by_model"][record.model]["cost"] += record.cost
            report["by_model"][record.model]["tokens"] += (
                record.prompt_tokens + record.completion_tokens
            )
            
            # By route reason
            route = record.route_reason.split("|")[0].strip()
            if route not in report["by_route"]:
                report["by_route"][route] = {"calls": 0, "cost": 0.0}
            report["by_route"][route]["calls"] += 1
            report["by_route"][route]["cost"] += record.cost
        
        return report
    
    def get_optimization_recommendations(self) -> list:
        """Get recommendations for cost optimization."""
        report = self.get_usage_report()
        recommendations = []
        
        # Check for expensive models used for simple tasks
        for route, data in report["by_route"].items():
            if data["cost"] > 100 and route in ["simple_qa", "greeting"]:
                recommendations.append({
                    "type": "model_downgrade",
                    "route": route,
                    "savings_estimate": data["cost"] * 0.8,
                    "suggestion": f"Route '{route}' uses an expensive tier. Evaluate the 'small' tier on it."
                })
        
        # Check for cache opportunities
        similar_calls = self._find_similar_calls()
        if similar_calls:
            recommendations.append({
                "type": "caching",
                "savings_estimate": len(similar_calls) * 0.01,
                "suggestion": f"{len(similar_calls)} similar calls detected. Implement response caching."
            })
        
        return recommendations
```

### 3.2 Budget Allocation Strategy

```python
class BudgetAllocator:
    """
    Allocates budget across different query types and models.
    """
    
    def __init__(self, monthly_budget: float = 10000.0):
        self.monthly_budget = monthly_budget
        self.allocations = {
            "complex_reasoning": {"percentage": 0.30, "model": "mid"},
            "code_generation": {"percentage": 0.25, "model": "code"},
            "analysis": {"percentage": 0.20, "model": "mid"},
            "simple_qa": {"percentage": 0.10, "model": "small"},
            "creative": {"percentage": 0.10, "model": "mid"},
            "research": {"percentage": 0.05, "model": "frontier"},
        }
        self.spent = defaultdict(float)     # per query type, this month
    
    def can_afford(self, query_type: str, estimated_cost: float) -> bool:
        """Check if a query fits in what's LEFT of its allocation."""
        allocation = self.allocations.get(query_type)
        if not allocation:
            return False
        
        monthly_allocation = self.monthly_budget * allocation["percentage"]
        return self.spent[query_type] + estimated_cost <= monthly_allocation

    def record(self, query_type: str, actual_cost: float):
        self.spent[query_type] += actual_cost
```

---

## 4. ACCURACY CHECKING

### 4.1 LLM-as-Judge

```python
class AccuracyChecker:
    """
    Uses a separate LLM to verify the primary LLM's output.
    """
    
    JUDGE_PROMPT = """You are an accuracy judge. Evaluate the following response.

Query: {query}
Response: {response}
Tool Results: {tool_results}

Score each dimension (0-1):
1. factuality: Does the response stick to verified facts?
2. completeness: Does it address all parts of the query?
3. hallucination: Does it contain any unsupported claims?
4. relevance: Is the response directly relevant?

Respond with JSON:
{
    "factuality": 0.0-1.0,
    "completeness": 0.0-1.0, 
    "hallucination_free": 0.0-1.0,
    "relevance": 0.0-1.0,
    "overall_score": 0.0-1.0,
    "issues": ["issue1", "issue2"],
    "verdict": "pass|fail|review"
}
"""
    
    def __init__(self, judge_model: str = "mid"):
        # Prefer a judge from a different model family than the one being
        # judged (models tend to favour their own outputs), and validate the
        # judge's scores against human labels before trusting thresholds.
        self.judge = get_chat_model(judge_model)
        self.thresholds = {
            "pass": 0.8,
            "review": 0.6,
        }
    
    async def check(self, query: str, response: str, 
                    tool_results: list = None) -> AccuracyVerdict:
        """Check the accuracy of an agent's response."""
        judge_input = self.JUDGE_PROMPT.replace("{query}", query)
        judge_input = judge_input.replace("{response}", response)
        judge_input = judge_input.replace("{tool_results}", str(tool_results))
        
        result = await self.judge.ainvoke(judge_input)
        
        try:
            scores = json.loads(result.content)
        except json.JSONDecodeError:
            return AccuracyVerdict(overall_score=0.5, verdict="review")
        
        if scores["overall_score"] >= self.thresholds["pass"]:
            verdict = "pass"
        elif scores["overall_score"] >= self.thresholds["review"]:
            verdict = "review"
        else:
            verdict = "fail"
        
        return AccuracyVerdict(
            overall_score=scores["overall_score"],
            factuality=scores["factuality"],
            completeness=scores["completeness"],
            hallucination_free=scores["hallucination_free"],
            relevance=scores["relevance"],
            issues=scores.get("issues", []),
            verdict=verdict
        )
```

### 4.2 Cross-Model Validation

```python
class CrossModelValidator:
    """
    Validates critical answers by running them through multiple models.
    Only for high-stakes queries (financial, medical, legal).
    """
    
    # Different providers/families: models from one family share failure modes.
    VALIDATION_MODELS = ["provider_a:mid", "provider_b:mid", "open:large"]
    
    async def validate(self, query: str, primary_response: str) -> ValidationResult:
        """Run the same query through multiple models and compare."""
        results = []
        
        for model in self.VALIDATION_MODELS:
            llm = self._get_llm(model)
            response = await llm.ainvoke(
                f"Answer this query concisely: {query}"
            )
            results.append({
                "model": model,
                "response": response.content,
                "tokens": self._count_tokens(response.content)
            })
        
        # Compare responses
        agreements = self._calculate_agreements(primary_response, results)
        
        return ValidationResult(
            query=query,
            primary_response=primary_response,
            secondary_responses=results,
            agreement_score=agreements["average"],
            disagreements=agreements["disagreements"],
            verdict="verified" if agreements["average"] > 0.8 else "needs_review"
        )
    
    def _calculate_agreements(self, primary: str, 
                              secondaries: list) -> dict:
        """Calculate semantic agreement between responses."""
        primary_embedding = embed(primary)
        
        similarities = []
        for secondary in secondaries:
            sec_embedding = embed(secondary["response"])
            similarity = cosine_similarity(primary_embedding, sec_embedding)
            similarities.append({
                "model": secondary["model"],
                "similarity": similarity,
                "agrees": similarity > 0.7
            })
        
        return {
            "average": sum(s["similarity"] for s in similarities) / len(similarities),
            "disagreements": [s for s in similarities if not s["agrees"]]
        }
```

Caveat: embedding similarity measures topic overlap, so "the dose is 5 mg" and "the dose is 50 mg" look like agreement. For high-stakes checks, extract the key claims or values and compare them directly, or ask a judge model whether the answers *agree on the facts*. And agreement is not correctness: several models can share the same wrong belief.

---

## 5. FALLBACK MECHANISMS

### 5.1 Fallback Chain

```python
class FallbackChain:
    """
    Hierarchical fallback when a model fails.
    Tries progressively cheaper fallback models.
    """
    
    # Each chain starts with the primary. Prefer "same tier, other provider"
    # before "lower tier, same provider": an outage is usually per provider.
    FALLBACK_CHAINS = {
        "frontier": ["provider_a:frontier", "provider_b:frontier", "provider_a:mid"],
        "mid":      ["provider_a:mid", "provider_b:mid", "provider_a:small"],
        "small":    ["provider_a:small", "provider_b:small", "open:small"],
        "code":     ["provider_a:mid", "provider_b:mid"],
    }
    
    def __init__(self):
        self.circuit_breakers = {}  # Track failing models
        self.failure_counts = defaultdict(int)
    
    async def execute_with_fallback(
        self, route_decision: RouteDecision, query: str
    ) -> FallbackResult:
        """Execute with automatic fallback on failure."""
        chain = self.FALLBACK_CHAINS[route_decision.model]
        
        errors = []
        for model in chain:
            # Check circuit breaker
            if self._is_circuit_open(model):
                errors.append(f"{model}: circuit breaker open")
                continue
            
            try:
                llm = self._get_llm(model, route_decision.temperature)
                response = await asyncio.wait_for(
                    llm.ainvoke(query),
                    timeout=self._get_timeout(model)
                )
                
                # Success — record it
                self._record_success(model)
                return FallbackResult(
                    response=response.content,
                    model_used=model,
                    attempted_models=chain[:chain.index(model) + 1],
                    errors=errors,
                    success=True
                )
            
            except (TimeoutError, RateLimitError, ServerError, ConnectionError) as e:
                # Only availability failures should fall through the chain.
                errors.append(f"{model}: {str(e)}")
                self._record_failure(model)
                continue
            # A 400 (bad request, context too long, policy refusal) will fail
            # the same way on the next model, or worse, succeed with different
            # semantics: let it propagate instead of burning the whole chain.
        
        # All models failed
        return FallbackResult(
            response=None,
            model_used=None,
            attempted_models=chain,
            errors=errors,
            success=False,
            error_message="All fallback models failed"
        )
    
    def _is_circuit_open(self, model: str) -> bool:
        """Check if circuit breaker is open for a model."""
        if model not in self.circuit_breakers:
            return False
        
        breaker = self.circuit_breakers[model]
        if breaker["state"] == "open":
            if time.time() - breaker["opened_at"] > 60:  # Try again after 60s
                breaker["state"] = "half-open"
                return False
            return True
        return False
    
    def _record_failure(self, model: str):
        """Record a model failure."""
        self.failure_counts[model] += 1
        if self.failure_counts[model] >= 5:  # Open circuit after 5 failures
            self.circuit_breakers[model] = {
                "state": "open",
                "opened_at": time.time()
            }
    
    def _record_success(self, model: str):
        """Record a model success."""
        self.failure_counts[model] = 0
        if model in self.circuit_breakers:
            self.circuit_breakers[model]["state"] = "closed"
```

### 5.2 Graceful Degradation

```python
async def handle_with_degradation(
    query: str, route_decision: RouteDecision, cost_tracker: CostTracker
) -> dict:
    """
    Graceful degradation strategy:
    1. Try preferred model
    2. On failure, try cheaper model
    3. On second failure, try cached/static response
    4. On third failure, return error gracefully
    """
    fallback = FallbackChain()
    
    # Attempt 1: Preferred model
    result = await fallback.execute_with_fallback(route_decision, query)
    
    if result.success:
        return {
            "response": result.response,
            "model": result.model_used,
            "quality": "full"
        }
    
    # Attempt 2: Cached response (if available)
    cache_key = hashlib.md5(query.encode()).hexdigest()
    cached = await cache.get(cache_key)
    if cached:
        return {
            "response": cached,
            "model": "cache",
            "quality": "cached"
        }
    
    # Attempt 3: Static fallback
    return {
        "response": (
            "I'm currently experiencing high demand. "
            "Please try your query again in a few minutes."
        ),
        "model": "static",
        "quality": "degraded"
    }
```

---

### 5.3 What Makes Cross-Provider Fallback Hard

- **Different APIs and features:** message formats, tool-call shapes, structured-output support, prompt caching and system-prompt handling differ. Hide them behind one internal interface (a gateway such as LiteLLM, Portkey or a cloud AI gateway, or your own adapter layer).
- **Prompts are tuned per model.** A prompt optimized for one model can underperform on another; keep per-model prompt variants and evaluate each fallback path.
- **Caches don't transfer.** Prompt caches are per provider and per model, so a failover starts cold (slower and pricier for a while).
- **Data and compliance:** the fallback provider must be approved for the same data (region, retention, zero-data-retention terms).
- **Thundering herd:** when a primary fails over, the secondary receives all its traffic at once; make sure you have the rate-limit headroom there.

---

## 6. PRODUCTION ARCHITECTURE

```python
class MultiLLMOrchestrator:
    """
    Complete multi-LLM orchestration system.
    """
    
    def __init__(self, config: dict):
        self.router = HybridRouter()
        self.cost_tracker = CostTracker(
            monthly_budget=config.get("monthly_budget", 10000)
        )
        self.accuracy_checker = AccuracyChecker()
        self.fallback = FallbackChain()
        self.models = self._init_models(config)
    
    async def process(self, query: str, context: dict = None) -> dict:
        """Process a query through the multi-LLM pipeline."""
        
        # Step 1: Route the query
        route = await self.router.route(query)
        
        context = context or {}
        accuracy = None

        # Step 2: Check budget
        if not await self._check_budget(route):
            route.model = "small"  # Downgrade (or reject: decide per product)
        
        # Step 3: Execute with fallback
        result = await self.fallback.execute_with_fallback(route, query)
        
        if not result.success:
            return self._build_error_response(query, result.errors)
        
        # Step 4: Check accuracy (for high-stakes queries only)
        if route.complexity in ("complex", "medium"):
            accuracy = await self.accuracy_checker.check(
                query, result.response
            )
            
            if accuracy.verdict == "fail":
                # Automatic retry with better model
                retry_route = RouteDecision(
                    model="frontier",
                    complexity="complex"
                )
                retry_result = await self.fallback.execute_with_fallback(
                    retry_route, query
                )
                if retry_result.success:
                    result = retry_result
        
        # Step 5: Track cost (of EVERY call made, including the judge and any
        # retry, not just the final one)
        cost = self.cost_tracker.calculate_cost(
            result.model_used, result.prompt_tokens or 0, result.completion_tokens or 0
        )
        await self.cost_tracker.track_call(LLMCallRecord(
            model=result.model_used,
            prompt_tokens=result.prompt_tokens or 0,
            completion_tokens=result.completion_tokens or 0,
            cost=cost,
            latency_ms=result.latency_ms,
            timestamp=datetime.now(UTC),
            route_reason=route.reason,
            success=True,
        ))
        
        return {
            "response": result.response,
            "model_used": result.model_used,
            "cost": cost,
            "latency_ms": result.latency_ms,
            "accuracy_score": accuracy.overall_score if accuracy else None,
        }
```

---

## 7. COMPARISON MATRIX

Compare tiers by their *relative* properties; look up exact prices and limits on the providers' pages when you need them.

| Tier | Relative cost per token | Latency | Typical context window (Oct 2026) | Watch out for |
|------|------------------------|---------|-----------------------------------|---------------|
| `small` | 1x (baseline) | Fastest | ~200K+ | Weaker multi-step reasoning and tool selection |
| `mid` | Several times `small` | Medium | Up to ~1M on current Claude/GPT models | Default for agents; check effort/reasoning settings |
| `frontier` | Several times `mid` | Slowest, long reasoning turns | Up to ~1M | Cost explodes in agent loops; use for planning, not every step |
| `open` (self-hosted) | GPU cost, not per token | Depends on your hardware | Model-dependent | You own scaling, safety filters and upgrades |

Levers that often matter more than the per-token list price: **prompt caching** (cached input is typically billed at a fraction of normal input), **batch APIs** (roughly half price for async work), **reasoning effort** settings, and the number of agent turns a model needs to finish the task. Compare models on **cost per successfully completed task** from your own evals.

### 7.1 What Interviewers Probe Next

- **"How do you know the cheap route isn't hurting quality?"** Shadow-score a sample of cheap-route answers with a stronger judge, and track per-route task success and escalation rates.
- **"Provider A is down. Walk me through the next 60 seconds."** Breakers open after N availability failures, traffic shifts to the same tier on provider B, alerts fire, caches are cold so cost and latency rise, and half-open probes restore A gradually.
- **"How do you upgrade a model?"** Pin exact model ids (not floating aliases) in config, run the eval suite on the candidate, canary a slice of traffic with per-version metrics, then switch. Re-tune prompts: new models often need less prescriptive prompting.

---

> **Next:** [Agent Deployment on ECS](09_AGENT_DEPLOYMENT_ECS.md) → Production deployment architecture using AWS ECS
