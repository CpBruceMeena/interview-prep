# 🌐 Multi-LLM Architecture — Routing, Cost Management & Fallback

> **Target:** Principal Engineer | **Focus:** Production architecture for orchestrating multiple LLM providers

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
        │  GPT-4o  │      │ Claude 4 │      │DeepSeek  │
        │(Complex) │      │(Reasoning)│     │(Coding)  │
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
    model: str
    temperature: float = 0.3
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
            "model": "deepseek-coder-v3",
            "priority": 1
        },
        {
            "name": "complex_reasoning",
            "pattern": r"(analyze|compare|evaluate|why|how|explain).*(complex|trade-off|impact)",
            "model": "claude-4-sonnet",
            "temperature": 0.2,
            "priority": 2
        },
        {
            "name": "simple_qa",
            "pattern": r"^(what|when|where|who|define|tell me about)\b",
            "model": "gpt-4o-mini",
            "temperature": 0.0,
            "priority": 3
        },
        {
            "name": "creative_writing",
            "pattern": r"(write|draft|compose).*(story|email|blog|article|content)",
            "model": "gpt-4o",
            "temperature": 0.8,
            "priority": 2
        },
        {
            "name": "data_analysis",
            "pattern": r"(analyze|chart|graph|plot|report|dashboard)",
            "model": "claude-4-opus",
            "temperature": 0.1,
            "priority": 1
        }
    ]
    
    def route(self, query: str) -> RouteDecision:
        """Route query to the best model based on pattern matching."""
        for rule in sorted(self.RULES, key=lambda r: r["priority"]):
            if re.search(rule["pattern"], query, re.IGNORECASE):
                return RouteDecision(
                    model=rule["model"],
                    temperature=rule.get("temperature", 0.3),
                    reason=f"Matched rule: {rule['name']}",
                    cost_estimate=self._estimate_cost(rule["model"])
                )
        
        # Default
        return RouteDecision(
            model="gpt-4o-mini",
            temperature=0.3,
            reason="No rule matched — using default",
            cost_estimate=0.002
        )
```

### 2.2 LLM-as-Router (Intelligent Routing)

```python
class LLMRouter:
    """
    Uses a cheap LLM to classify and route queries.
    More flexible than rule-based, but adds latency and cost.
    """
    
    ROUTING_PROMPT = """Analyze this user query and respond with JSON:
{
    "complexity": "simple|medium|complex",
    "type": "code|reasoning|creative|analysis|factual|general",
    "requires_tools": true|false,
    "suggested_model": "model_name",
    "reasoning": "brief explanation"
}

Model options:
- gpt-4o-mini: Simple Q&A, factual lookups, greetings. Cost: $0.15/M tokens
- gpt-4o: General purpose, creativity, analysis. Cost: $2.50/M tokens
- claude-4-sonnet: Complex reasoning, long context, safety. Cost: $3.00/M tokens
- deepseek-coder-v3: Code generation, debugging. Cost: $0.90/M tokens
- claude-4-opus: Research, deep analysis, math. Cost: $15.00/M tokens

Query: {query}
"""
    
    def __init__(self, classifier_model: str = "gpt-4o-mini"):
        self.classifier_llm = ChatOpenAI(model=classifier_model, temperature=0)
    
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
            model=self._map_to_available_model(classification["suggested_model"]),
            temperature=self._get_temperature(classification["type"]),
            complexity=classification["complexity"],
            requires_tools=classification["requires_tools"],
            reason=classification.get("reasoning", "LLM classified"),
            cost_estimate=self._estimate_cost(classification["suggested_model"])
        )
```

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
    
    # Current API pricing (per 1M tokens)
    PRICING = {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "claude-4-sonnet": {"input": 3.00, "output": 15.00},
        "claude-4-opus": {"input": 15.00, "output": 75.00},
        "deepseek-coder-v3": {"input": 0.90, "output": 3.60},
        "deepseek-v4-flash": {"input": 0.40, "output": 1.60},
    }
    
    def __init__(self, monthly_budget: float = 10000.0):
        self.monthly_budget = monthly_budget
        self.current_month_cost = 0.0
        self.records: List[LLMCallRecord] = []
        self._lock = asyncio.Lock()
    
    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost for a model call."""
        pricing = self.PRICING.get(model, self.PRICING["gpt-4o-mini"])
        return (
            (input_tokens / 1_000_000) * pricing["input"] +
            (output_tokens / 1_000_000) * pricing["output"]
        )
    
    async def track_call(self, record: LLMCallRecord):
        """Track an LLM call and check budget."""
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
                    "suggestion": f"Route '{route}' uses expensive model. Switch to gpt-4o-mini."
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
            "complex_reasoning": {"percentage": 0.30, "model": "claude-4-sonnet"},
            "code_generation": {"percentage": 0.25, "model": "deepseek-coder-v3"},
            "analysis": {"percentage": 0.20, "model": "gpt-4o"},
            "simple_qa": {"percentage": 0.10, "model": "gpt-4o-mini"},
            "creative": {"percentage": 0.10, "model": "gpt-4o"},
            "research": {"percentage": 0.05, "model": "claude-4-opus"},
        }
    
    def can_afford(self, query_type: str, estimated_cost: float) -> bool:
        """Check if a query can be processed within budget."""
        allocation = self.allocations.get(query_type)
        if not allocation:
            return False
        
        monthly_allocation = self.monthly_budget * allocation["percentage"]
        return estimated_cost <= monthly_allocation
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
    
    def __init__(self, judge_model: str = "gpt-4o"):
        self.judge = ChatOpenAI(model=judge_model, temperature=0)
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
    
    VALIDATION_MODELS = [
        "gpt-4o",
        "claude-4-sonnet",
        "deepseek-coder-v3"
    ]
    
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

---

## 5. FALLBACK MECHANISMS

### 5.1 Fallback Chain

```python
class FallbackChain:
    """
    Hierarchical fallback when a model fails.
    Tries progressively cheaper fallback models.
    """
    
    FALLBACK_CHAINS = {
        "claude-4-opus": ["claude-4-sonnet", "gpt-4o", "gpt-4o-mini"],
        "claude-4-sonnet": ["gpt-4o", "gpt-4o-mini", "deepseek-coder-v3"],
        "gpt-4o": ["gpt-4o-mini", "claude-4-sonnet"],
        "deepseek-coder-v3": ["gpt-4o", "gpt-4o-mini"],
        "gpt-4o-mini": ["deepseek-v4-flash"],  # Last resort
    }
    
    def __init__(self):
        self.circuit_breakers = {}  # Track failing models
        self.failure_counts = defaultdict(int)
    
    async def execute_with_fallback(
        self, route_decision: RouteDecision, query: str
    ) -> FallbackResult:
        """Execute with automatic fallback on failure."""
        chain = self.FALLBACK_CHAINS.get(
            route_decision.model, 
            [route_decision.model, "gpt-4o-mini"]
        )
        
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
            
            except Exception as e:
                errors.append(f"{model}: {str(e)}")
                self._record_failure(model)
                continue
        
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
        
        # Step 2: Check budget
        if not await self._check_budget(route):
            route.model = "gpt-4o-mini"  # Downgrade to cheapest
        
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
                    model="claude-4-sonnet",
                    temperature=0.1,
                    complexity="complex"
                )
                retry_result = await self.fallback.execute_with_fallback(
                    retry_route, query
                )
                if retry_result.success:
                    result = retry_result
        
        # Step 5: Track cost
        await self.cost_tracker.track_call(LLMCallRecord(
            model=result.model_used,
            prompt_tokens=result.prompt_tokens or 0,
            completion_tokens=result.completion_tokens or 0,
            cost=self.cost_tracker.calculate_cost(
                result.model_used,
                result.prompt_tokens or 0,
                result.completion_tokens or 0
            ),
            latency_ms=result.latency_ms,
            timestamp=datetime.utcnow(),
            route_reason=route.reason
        ))
        
        return {
            "response": result.response,
            "model_used": result.model_used,
            "cost": result.cost,
            "latency_ms": result.latency_ms,
            "accuracy_score": accuracy.overall_score if context.get("check_accuracy") else None
        }
```

---

## 7. COMPARISON MATRIX

| Model | Best For | Cost (Input/M) | Cost (Output/M) | Latency | Context Window |
|-------|----------|----------------|-----------------|---------|---------------|
| **GPT-4o** | General, creative | $2.50 | $10.00 | Medium | 128K |
| **GPT-4o-mini** | Simple Q&A, cheap | $0.15 | $0.60 | Fast | 128K |
| **Claude 4 Sonnet** | Reasoning, analysis | $3.00 | $15.00 | Medium | 200K |
| **Claude 4 Opus** | Research, complex | $15.00 | $75.00 | Slow | 200K |
| **DeepSeek Coder V3** | Code generation | $0.90 | $3.60 | Fast | 128K |
| **DeepSeek V4 Flash** | Fast inference | $0.40 | $1.60 | Very Fast | 64K |

---

> **Next:** [Agent Deployment on ECS](09_AGENT_DEPLOYMENT_ECS.md) → Production deployment architecture using AWS ECS
