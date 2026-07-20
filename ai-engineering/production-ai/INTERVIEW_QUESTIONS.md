# 🏭 Production AI Engineering — Interview Questions & Answers

> **Principal/Staff Software Engineer level | Production-grade AI systems, MLOps & RAG**

---

## Table of Contents

### Part I — RAG & LLM Debugging
1. [RAG hallucinates despite having the right context](#1-rag-hallucinates-despite-having-the-right-context)
2. [RAG retrieval is too slow on large knowledge base](#2-rag-retrieval-is-too-slow-on-large-knowledge-base)
3. [Model gives confident but wrong answers in high-risk situations](#3-model-gives-confident-but-wrong-answers-in-high-risk-situations)
4. [RAG fails on multi-document reasoning](#4-rag-fails-on-multi-document-reasoning)
5. [PM wants to ship an AI feature that hallucinates on 15% of edge cases](#5-pm-wants-to-ship-an-ai-feature-that-hallucinates-on-15-of-edge-cases)

### Part II — Production AI Systems Design
6. [RAG suddenly gives wrong answers](#6-rag-suddenly-gives-wrong-answers)
7. [Design a production AI coding assistant](#7-design-a-production-ai-coding-assistant)
8. [LLM latency jumps from 2s to 15s](#8-llm-latency-jumps-from-2s-to-15s)
9. [Design an enterprise AI agent](#9-design-an-enterprise-ai-agent)
10. [Build a multi-agent workflow](#10-build-a-multi-agent-workflow)
11. [Same prompt gives different outputs](#11-same-prompt-gives-different-outputs)
12. [AI inference costs increased by 40%](#12-ai-inference-costs-increased-by-40)
13. [AI assistant works in testing but fails in production](#13-ai-assistant-works-in-testing-but-fails-in-production)
14. [How to evaluate an LLM in production](#14-how-to-evaluate-an-llm-in-production)
15. [Design an enterprise MCP-based AI application](#15-design-an-enterprise-mcp-based-ai-application)

---

## Part I — RAG & LLM Debugging

---

## 1. RAG hallucinates despite having the right context

**Interviewer:** *"Your RAG system is hallucinating even though it has the right context. How do you fix it?"*

### 🎯 Answer

This is a **faithfulness failure** — the model has the correct information but isn't using it. This is distinct from a retrieval failure (wrong context) or a factuality gap (context doesn't contain the answer).

**Diagnosis pipeline:**

```python
def diagnose_hallucination(question, context, answer):
    """
    Determine WHY the model hallucinated despite having the right context.
    """
    # Test 1: Can the model extract the answer from context?
    prompt_1 = f"""Context: {context}
    
    Question: {question}
    
    Extract the EXACT answer from the context above.
    If the answer is not in the context, say 'NOT FOUND'."""
    
    extraction = llm.generate(prompt_1, temperature=0)
    
    if extraction == "NOT FOUND":
        # The model genuinely can't find it — context might be poorly structured
        return "context_formatting_issue"
    
    # Test 2: Can the model follow instruction to use context only?
    prompt_2 = f"""You MUST answer using ONLY the context below.
    Do NOT use any prior knowledge.
    
    Context: {context}
    
    Question: {question}"""
    
    forced_result = llm.generate(prompt_2, temperature=0)
    
    if "hallucination" in evaluate_faithfulness(forced_result, context):
        # Even with explicit instruction, model ignores context
        return "instruction_following_failure"
    
    return "prompt_competition"  # Model's prior knowledge overrides context
```

**Root causes and fixes:**

| Root Cause | Symptoms | Fix |
|-----------|----------|-----|
| **Context position bias** | Model uses first/last chunk, ignores middle | Re-rank chunks by relevance; place most relevant first and last |
| **Lost-in-the-middle** | Answer is in chunk 5 of 10; model ignores mid-context | Reduce total context chunks (top-3 instead of top-5); use re-ranker; summarize secondary chunks |
| **Prior knowledge override** | Model knows a "better" answer from training | Harder system prompt: *"Answer EXCLUSIVELY from context. If context disagrees with your knowledge, the context is authoritative."* |
| **Instruction drift** | Earlier turns dilute the "answer from context" instruction | Re-inject the instruction every turn; keep system prompt short and reinforced |
| **Contradictory context** | Two chunks say different things | Add contradiction detection: if chunks conflict, surface both and flag uncertainty |

**Concrete fix — counter-position bias with chunk prioritization:**

```python
class FaithfulRAG:
    """
    RAG pipeline engineered to maximize faithfulness.
    """
    def __init__(self):
        self.reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    
    def build_faithful_context(self, chunks: list[str], question: str) -> str:
        # Step 1: Rerank — most relevant first
        scored = self.reranker.rank(question, chunks)
        
        # Step 2: Sandwich the best — most RELEVANT at start AND end
        # (models pay most attention to the first and last items)
        best = scored[0:1]        # Top-1 at the start
        rest = scored[1:3]        # Top-2 to top-3 in the middle
        best_also = scored[0:1]   # Repeat top-1 at the end
        
        ordered = best + rest + best_also
        
        # Step 3: Structured format with clear boundaries
        return "\n---\n".join([
            f"[Document {i+1}]: {chunk}" 
            for i, chunk in enumerate(ordered)
        ])
    
    async def generate(self, question: str) -> str:
        chunks = self.retrieve(question)
        context = self.build_faithful_context(chunks, question)
        
        system_prompt = """You are a precise answer generator.
        
        RULES:
        1. Answer ONLY using the provided documents.
        2. If the documents don't contain the answer, say "I don't have enough information."
        3. Do NOT use any prior knowledge.
        4. If any document contradicts another, point out the contradiction.
        5. Cite which document(s) support your answer.
        
        Documents:
        {context}
        
        Question: {question}
        """
        
        answer = await self.llm.generate(system_prompt, temperature=0.1)
        
        # Step 4: Post-hoc faithfulness check
        if not self.verify_faithfulness(answer, chunks):
            return await self.constrained_generate(question, chunks)  # Fallback
        
        return answer
    
    def verify_faithfulness(self, answer: str, chunks: list[str]) -> bool:
        """Use a smaller, stricter LLM to verify."""
        verifier_prompt = f"""Context: {' '.join(chunks)}
        
        Answer: {answer}
        
        List EVERY claim in the answer. For each claim, say SUPPORTED or UNSUPPORTED.
        """
        result = self.verifier_llm.generate(verifier_prompt)
        return "UNSUPPORTED" not in result
    
    async def constrained_generate(self, question: str, chunks: list[str]) -> str:
        """Constrained generation using LMQL or guidance."""
        from guidance import select, gen
        
        # Extract verbatim spans from chunks and force answer to use them
        spans = self.extract_answer_spans(chunks, question)
        
        prompt = f"""Based on: {spans}
        Answer: {select(spans)}"""
        return prompt
```

**🔴 Follow-up:** *"What if the fix still doesn't work?"*

**✅ Answer:** If faithfulness remains broken after prompt engineering and reranking, the model itself may be unsuitable. Switch to a model with stronger instruction-following (e.g., Claude vs a smaller model). As a last resort, implement **factored verification**: generate an answer, then use a separate BERT-based NLI model to check if the answer is entailed by the context. Reject answers below the entailment threshold.

---

## 2. RAG retrieval is too slow on large knowledge base

**Interviewer:** *"Your RAG retrieval is too slow on a large knowledge base. How do you speed it up?"*

### 🎯 Answer

Retrieval latency in RAG comes from embedding, vector search, and re-ranking. On a large knowledge base (10M+ documents), each of these must be optimized.

**Latency budget breakdown:**

| Component | Naive | Optimized | Technique |
|-----------|-------|-----------|-----------|
| Query embedding | 100ms | 20ms | Cached embeddings, smaller model |
| Vector search | 500ms | 50ms | IVF/ANNOY indexing, quantization |
| Reranking | 300ms | 100ms | Two-stage: fast coarse → small candidate set → slow fine |
| Total | 900ms+ | <200ms | |

**1. Query embedding optimization:**

```python
class FastEmbedding:
    """
    Multiple strategies to reduce embedding latency.
    """
    def __init__(self):
        # Strategy A: Use a smaller embedding model for queries
        self.query_encoder = SentenceTransformer("all-MiniLM-L6-v2")   # 80MB, 20ms
        self.doc_encoder = SentenceTransformer("all-mpnet-base-v2")    # 400MB, better quality
        
        # Strategy B: Cache frequent queries
        self.query_cache = LRUCache(maxsize=10000, ttl=300)  # 5 min TTL
    
    def embed_query(self, query: str) -> vector:
        # Check cache first
        cached = self.query_cache.get(query)
        if cached:
            return cached
        
        # Use fast model
        embedding = self.query_encoder.encode(query, normalize=True)
        self.query_cache.put(query, embedding)
        return embedding
    
    def embed_document(self, doc: str) -> vector:
        # Documents use the high-quality model (done offline)
        return self.doc_encoder.encode(doc, normalize=True)
```

**2. Vector search optimization:**

```python
import numpy as np
from typing import List

class TieredVectorStore:
    """
    Multi-tier vector search for speed.
    """
    def __init__(self, dimension: int = 768):
        # Tier 1: In-memory IVF index (fast, approximate)
        self.ivf_index = self._build_ivf(nlist=1000, nprobe=10)
        
        # Tier 2: Disk-based HNSW (slower, exact)
        self.hnsw_index = self._build_hnsw(M=16, ef_construction=200)
        
        # Tier 3: Full scan (fallback)
        self.full_store = None
    
    def search(self, query_vector: np.ndarray, top_k: int = 10, 
               latency_budget_ms: int = 50) -> List[str]:
        """
        Adaptive search based on latency budget.
        """
        if latency_budget_ms < 20:
            # Ultra-fast: IVF with high nprobe
            return self.ivf_search(query_vector, top_k, nprobe=5)
        
        elif latency_budget_ms < 50:
            # Standard: IVF with more probes
            return self.ivf_search(query_vector, top_k, nprobe=20)
        
        elif latency_budget_ms < 200:
            # High quality: HNSW
            return self.hnsw_search(query_vector, top_k, ef=100)
        
        else:
            # Full precision
            return self.exact_search(query_vector, top_k)
    
    def _build_ivf(self, nlist: int, nprobe: int):
        """
        IVF (Inverted File Index):
        - Clusters vectors into nlist groups
        - Search only nprobe nearest clusters
        - Speed: O(log(nlist) + nprobe/nlist * N)
        - Trade-off: nprobe controls speed vs recall
        
        Example: 10M docs, 1000 clusters, nprobe=20
        → Search 20/1000 * 10M = 200K docs
        → 50x faster than full scan
        
        Implementation with FAISS:
        quantizer = faiss.IndexFlatIP(dimension)
        index = faiss.IndexIVFFlat(quantizer, dimension, nlist, faiss.METRIC_INNER_PRODUCT)
        index.train(embeddings)
        index.add(embeddings)
        index.nprobe = nprobe  # Set at query time
        D, I = index.search(query_vector, top_k)
        """
        pass

# ScaNN (Google) achieves <10ms for 1B-scale search
# Usage:
# pip install scann
# searcher = scann.ScannBuilder(embeddings, 10, "dot_product").tree(
#     num_leaves=2000, num_leaves_to_search=100, training_sample_size=250000
# ).score_ah(2, anisotropic_quantization_threshold=0.2).build()
```

**3. Quantization for speed:**

| Quantization | Size | Recall@10 | Speed |
|-------------|------|-----------|-------|
| Float32 (baseline) | 100% | 100% | 1x |
| Float16 | 50% | ~99.9% | 1.5x |
| Int8 (scalar) | 25% | ~98% | 3x |
| Binary (1-bit) | 3% | ~85% | 20x |
| Product Quantization (PQ) | ~10% | ~95% | 10x |

```python
class QuantizedIndex:
    """
    Product Quantization compresses vectors by:
    1. Split each vector into M sub-vectors
    2. Cluster each sub-vector space into K centroids
    3. Store only centroid IDs (log2(K) * M bits)
    
    Search: compute partial distances on-the-fly using pre-computed centroid distances
    → Asymmetric Distance Computation (ADC)
    """
    def __init__(self, M=16, K=256):
        self.M = M  # Number of sub-vector spaces
        self.K = K  # Centroids per sub-space
        # Storage: log2(256) * 16 = 128 bits per vector
        # Instead of 768 * 32 = 24,576 bits (floats) per vector
```

**4. Two-stage retrieval:**

```python
class TwoStageRetriever:
    """
    Stage 1: Fast, cheap embedding (MiniLM) → top-100
    Stage 2: Slow, accurate reranker (CrossEncoder) → top-5
    
    Latency: 20ms + 100ms = 120ms vs 300ms for direct reranker
    """
    def __init__(self):
        self.stage1 = FastVectorIndex()          # Bi-encoder, 20ms
        self.stage2 = CrossEncoder("ms-marco")   # 100ms for 100 pairs
    
    def retrieve(self, query: str, top_k: int = 5) -> List[Document]:
        # Stage 1: Coarse retrieval — 20ms
        candidates = self.stage1.search(query, top_k=100)
        
        # Stage 2: Fine reranking — 100ms for 100 pairs
        scored = self.stage2.rank(query, [c.text for c in candidates])
        
        return scored[:top_k]
```

**5. Caching strategy:**

```python
class FullCacheStrategy:
    """
    Multi-level cache for RAG.
    """
    def __init__(self):
        # L1: Exact query cache (identical questions)
        self.exact_cache = Cache(ttl=3600, maxsize=10000)
        
        # L2: Semantic cache (similar questions)
        self.semantic_cache = SemanticCache(similarity_threshold=0.95, ttl=300)
        
        # L3: Document cache (frequently retrieved docs)
        self.doc_cache = Cache(ttl=600, maxsize=50000)
    
    def get_response(self, query: str) -> Optional[str]:
        # L1: Exact match
        cached = self.exact_cache.get(query)
        if cached:
            return cached
        
        # L2: Semantic match
        cached = self.semantic_cache.find_similar(query)
        if cached:
            return cached
        
        return None
```

**🔴 Follow-up:** *"What's the one optimization you'd do first?"*

**✅ Answer:** Switch from brute-force kNN to **IVF with Product Quantization**. It's the highest ROI:
- 10-50x speedup with ~95% recall
- Reduces memory from ~30GB (1M floats × 768 dims) to ~1GB (PQ compressed)
- Works with FAISS, ScaNN, or Milvus — no infrastructure change
- Can be implemented in an afternoon with `faiss.IndexIVFPQ`

---

## 3. Model gives confident but wrong answers in high-risk situations

**Interviewer:** *"Your model gives confident but wrong answers in high risk situations. How do you find the cause and fix it?"*

### 🎯 Answer

This is the **most dangerous failure mode** — the model doesn't know it doesn't know. In high-risk domains (healthcare, finance, legal, safety-critical), confident wrong answers can cause real harm.

**Diagnosis framework:**

```python
class HallucinationDiagnosis:
    """
    Systematic approach to find WHY the model is confidently wrong.
    """
    def analyze_failure(self, question: str, answer: str, 
                        context: dict, model_confidence: float):
        
        # Axis 1: Knowledge boundary
        knowledge_types = [
            "parametric_knowledge",   # Model's training data
            "provided_context",        # In-context information
            "reasoning_chain"          # Step-by-step derivation
        ]
        
        # Axis 2: Calibration
        calibration = self.check_calibration(question, answer)
        
        # Axis 3: Data distribution
        distribution = self.check_distribution(question)
        
        return {
            "root_cause": self._identify_root_cause(
                knowledge_types, calibration, distribution
            ),
            "confidence": model_confidence,
            "correctness": self._external_verification(answer),
            "evidence": context
        }
```

**Root causes and fixes:**

| Root Cause | Indicator | Fix |
|-----------|-----------|-----|
| **Epistemic overconfidence** | Model was trained on similar but not identical data | Add epistemic uncertainty estimation; reject low-evidence answers |
| **Distribution shift** | Question is out-of-distribution from training data | OOD detection; route to human |
| **Reasoning shortcut** | Model skips verification steps | Chain-of-thought with mandatory verification step |
| **Context ignoring** | Model relies on parametric knowledge over context | Reinforced instruction; context-grounded generation |
| **Calibration collapse** | Softmax probabilities are miscalibrated (all outputs are 0.9+) | Temperature scaling; Platt scaling; separate calibration set |

**Fix 1 — Uncertainty estimation:**

```python
import numpy as np
from scipy.special import softmax

class UncertaintyEstimator:
    """
    Multiple methods to estimate when the model doesn't know.
    """
    def __init__(self, model):
        self.model = model
    
    def estimate_uncertainty(self, question: str, n_samples: int = 10) -> dict:
        """
        Method 1: MC Dropout — run inference N times with dropout enabled.
        High variance = high uncertainty.
        """
        predictions = []
        for _ in range(n_samples):
            # Enable dropout at inference
            pred = self.model.generate(question, dropout=True)
            predictions.append(pred)
        
        semantic_variance = self._semantic_similarity(predictions)
        lexical_variance = self._lexical_diversity(predictions)
        
        return {
            "semantic_variance": semantic_variance,  # Lower is better
            "lexical_variance": lexical_variance,    # Lower is better
            "is_uncertain": semantic_variance > 0.3 or lexical_variance > 0.5
        }
    
    def estimate_token_probabilities(self, answer: str) -> float:
        """
        Method 2: Average token probability.
        Low average probability = model is unsure.
        """
        log_probs = self.model.get_token_log_probs(answer)
        avg_log_prob = np.mean(log_probs)
        
        # Calibrated threshold (domain-specific)
        return softmax([avg_log_prob, -avg_log_prob])[0]
    
    def semantic_entropy(self, question: str, temperature: float = 1.0) -> float:
        """
        Method 3: Semantic entropy (Kuhn et al., 2023).
        Generate multiple answers, cluster by meaning, compute entropy.
        
        High entropy = model doesn't know.
        """
        answers = [
            self.model.generate(question, temperature=temperature)
            for _ in range(5)
        ]
        clusters = self._cluster_by_semantic_meaning(answers)
        
        total = len(answers)
        entropy = -sum(
            (len(c) / total) * np.log(len(c) / total)
            for c in clusters
        )
        
        return entropy  # 0 = confident, >1 = uncertain
```

**Fix 2 — Calibrated confidence thresholds:**

```python
class CalibratedGuardrail:
    """
    Reject answers when confidence is below threshold.
    Threshold is calibrated on a validation set.
    """
    def __init__(self, calibration_data: List[tuple], risk_level: str):
        # Calibrate threshold based on risk level
        self.risk_levels = {
            "critical": 0.95,   # Healthcare, safety
            "high": 0.90,        # Financial, legal
            "medium": 0.80,      # Customer support
            "low": 0.70,         # Content generation
        }
        self.threshold = self.risk_levels[risk_level]
        
        # Temperature scaling (Platt et al.)
        self.temperature = self._calibrate_temperature(calibration_data)
    
    def should_accept(self, answer: str, uncertainty: dict) -> bool:
        confidence = 1 - uncertainty["semantic_variance"]
        
        if confidence < self.threshold:
            return False  # Route to human
        
        return True
```

**Fix 3 — Verification chain for high-risk queries:**

```python
class VerifiedGeneration:
    """
    For high-risk queries: generate → verify → conditional output.
    """
    HIGH_RISK_DOMAINS = ["medical", "financial", "legal", "safety"]
    
    def generate_verified(self, question: str, domain: str) -> Output:
        if domain in self.HIGH_RISK_DOMAINS:
            return self._high_risk_generation(question)
        return self._normal_generation(question)
    
    def _high_risk_generation(self, question: str) -> Output:
        # Step 1: Generate with explicit citations
        answer = self.model.generate(
            question,
            system_prompt="""Answer step by step. For EACH claim, cite your source.
            If you're unsure about any claim, mark it with [UNCERTAIN]."""
        )
        
        # Step 2: Extract claims and verify each
        claims = self._extract_claims(answer)
        verified = []
        
        for claim in claims:
            if claim.is_uncertain:
                # Automatically flag
                verified.append(FlaggedClaim(claim, "UNCERTAIN"))
                continue
            
            # Verify against knowledge base
            evidence = self.retrieve_evidence(claim.text)
            if evidence:
                verified.append(VerifiedClaim(claim, evidence))
            else:
                verified.append(FlaggedClaim(claim, "NO_EVIDENCE"))
        
        # Step 3: If any claim is unverified, reject or add disclaimer
        unverified = [c for c in verified if not c.is_verified]
        if unverified:
            return Output(
                text=answer,
                warnings=[f"Claim '{c.text}' could not be verified" for c in unverified],
                requires_review=True
            )
        
        return Output(text=answer, requires_review=False)
```

**Production monitoring for this:**

```python
# Alert when:
# 1. Confidence > 0.9 AND answer is wrong → calibration drift
# 2. Semantic entropy of answers drops suddenly → model collapse
# 3. Human override rate increases → trust degradation

class CalibrationMonitor:
    def check_calibration_drift(self, batch: List[Inference]):
        """
        Expected: when model says 90% confident, it should be right 90% of the time.
        If it's right only 70% at 90% confidence → calibration is broken.
        """
        for confidence_bin in [0.5, 0.6, 0.7, 0.8, 0.9, 0.95]:
            subset = [x for x in batch 
                      if confidence_bin - 0.05 < x.confidence <= confidence_bin + 0.05]
            if subset:
                accuracy = sum(x.is_correct for x in subset) / len(subset)
                calibration_error = abs(accuracy - confidence_bin)
                
                if calibration_error > 0.15:
                    self.alert(f"Calibration drift at {confidence_bin}: "
                               f"expected {confidence_bin:.0%}, got {accuracy:.0%}")
```

**🔴 Follow-up:** *"How do you detect hallucinations in real-time without ground truth?"*

**✅ Answer:** Use **self-consistency** — generate 3-5 answers at higher temperature, cluster semantically. If they disagree, the model is uncertain. Also use the **nuclear log-probability**: if the average token probability of the answer is below a calibrated threshold (e.g., -0.5 nats), it's likely hallucinated. Combine both for a robust real-time detector.

---

## 4. RAG fails on multi-document reasoning

**Interviewer:** *"Your RAG system fails on questions that need facts from multiple documents combined. What do you do?"*

### 🎯 Answer

This is a **compositional reasoning failure** — the model has all the pieces but can't assemble them. Standard RAG retrieves independent chunks, but multi-document reasoning requires synthesized understanding.

**The root problem:**

```python
# Standard RAG retrieves:
chunk_1 = "Amazon revenue in 2023 was $574B"
chunk_2 = "Microsoft's cloud revenue grew 20% in Q4 2023"
chunk_3 = "AWS contributes 15% of Amazon's total revenue"

# Question: "How much did AWS contribute to Amazon's 2023 revenue?"
# Need to COMBINE chunk_1 and chunk_3 to answer: 15% × $574B = $86.1B
# But model sees 3 chunks about different topics → misses the connection
```

**Solution 1 — Query decomposition (Multi-Hop RAG):**

```python
class MultiHopRAG:
    """
    Decompose complex questions into sub-questions, answer each,
    then compose the final answer.
    """
    def __init__(self):
        self.decomposer = LLM(temperature=0)   # Breaks down questions
        self.retriever = Retriever()
        self.composer = LLM(temperature=0.1)   # Combines answers
    
    async def answer(self, question: str) -> str:
        # Phase 1: Decompose into sub-questions
        sub_questions = await self.decomposer.generate(f"""
        Decompose this question into independent sub-questions.
        Each sub-question must be answerable from a single document.
        
        Question: {question}
        
        Return as a numbered list:
        1. [first sub-question]
        2. [second sub-question]
        ...
        """)
        
        # Phase 2: Answer each sub-question independently
        sub_answers = []
        for sq in sub_questions:
            docs = self.retriever.retrieve(sq)
            answer = await self.answer_sub_question(sq, docs)
            sub_answers.append(answer)
        
        # Phase 3: Compose final answer from sub-answers
        final = await self.composer.generate(f"""
        Sub-questions and answers:
        {self._format_sub_answers(sub_questions, sub_answers)}
        
        Original question: {question}
        
        Synthesize a complete answer using ALL the sub-answers above.
        """)
        
        return final
    
    def answer_sub_question(self, question: str, docs: list[str]) -> str:
        return self.llm.generate(f"""
        Context: {' '.join(docs)}
        Question: {question}
        Answer based ONLY on the context above.
        """)
```

**Solution 2 — Map-Reduce RAG:**

```python
from concurrent.futures import ThreadPoolExecutor

class MapReduceRAG:
    """
    Map phase: process each document independently.
    Reduce phase: combine all findings.
    """
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=5)
    
    def retrieve_and_divide(self, question: str) -> List[Document]:
        """
        Retrieve MORE documents than standard RAG (top-15 instead of top-5)
        because we need breadth for multi-document reasoning.
        """
        return self.retriever.retrieve(question, top_k=15)
    
    async def answer(self, question: str) -> str:
        docs = self.retrieve_and_divide(question)
        
        # MAP: Process each doc independently
        map_promises = []
        for doc in docs:
            map_promises.append(self.executor.submit(
                self._extract_relevant_info, doc, question
            ))
        
        extracts = [p.result() for p in map_promises]
        extracts = [e for e in extracts if e]  # Filter empty
        
        # REDUCE: Combine all extracts
        final = await self._synthesize(extracts, question)
        
        return final
    
    def _extract_relevant_info(self, doc: str, question: str) -> Optional[str]:
        """Extract only the parts of each document relevant to the question."""
        prompt = f"""Document: {doc}
        
        Question: {question}
        
        Extract ONLY the specific facts from this document that are relevant 
        to answering the question. If nothing is relevant, say "IRRELEVANT".
        """
        result = self.llm.generate(prompt)
        return None if result.strip() == "IRRELEVANT" else result
    
    def _synthesize(self, extracts: list[str], question: str) -> str:
        """Combine all extracted facts into a coherent answer."""
        combined = "\n\n".join(extracts)
        prompt = f"""Facts gathered from multiple documents:
        
        {combined}
        
        Question: {question}
        
        Synthesize a complete answer using ALL relevant facts above.
        If facts are contradictory, note the contradiction.
        If the facts are insufficient to fully answer, say what's missing.
        """
        return self.llm.generate(prompt)
```

**Solution 3 — Graph-based RAG:**

```python
class GraphRAG:
    """
    Build a knowledge graph from documents.
    Multi-hop questions become graph traversal problems.
    """
    def __init__(self):
        self.graph = NetworkGraph()
        self.entity_extractor = EntityExtractor()
        self.relation_extractor = RelationExtractor()
    
    def index_documents(self, docs: list[str]):
        """Extract entities and relations into a graph."""
        for doc in docs:
            entities = self.entity_extractor.extract(doc)
            relations = self.relation_extractor.extract(doc, entities)
            
            for entity in entities:
                self.graph.add_node(entity.name, 
                                    type=entity.type, 
                                    metadata=entity.metadata)
            
            for relation in relations:
                self.graph.add_edge(relation.subject, 
                                    relation.object, 
                                    relation.type)
    
    def retrieve(self, question: str) -> List[str]:
        # Step 1: Identify entities in the question
        entities = self.entity_extractor.extract(question)
        
        # Step 2: For multi-hop, traverse the graph
        # Question: "What was AWS's contribution to Amazon's 2023 revenue?"
        # Entities: ["AWS", "Amazon"]
        # Relations: [AWS→(part_of)→Amazon, Amazon→(has_revenue)→2023]
        # Traversal: AWS → part_of → Amazon → has_revenue → 2023 → $86.1B
        
        paths = self.graph.find_paths(
            start_entities=[e.name for e in entities],
            max_depth=3,  # Allow up to 3 hops
            max_paths=5
        )
        
        # Gather chunks along the paths
        result_chunks = []
        for path in paths:
            for node in path:
                result_chunks.extend(node.associated_chunks)
        
        return result_chunks
```

**Solution 4 — ReAct with tool loops:**

```python
class ReActMultiDoc:
    """
    Use ReAct pattern to iteratively gather and reason.
    """
    def answer(self, question: str) -> str:
        thought_history = []
        
        for step in range(5):  # Max 5 reasoning steps
            thought = self.llm.generate(f"""
            Previous reasoning: {thought_history}
            Question: {question}
            
            Think about what information you need next.
            Do you need to: 
            - search for a specific fact?
            - compute something from retrieved facts?
            - combine what you already know?
            - give the final answer?
            """)
            
            if "search" in thought:
                query = self._extract_search_query(thought)
                docs = self.retriever.retrieve(query)
                thought_history.append(f"Searched: {query}\n" + 
                                      f"Found: {' '.join(docs[:3])}")
            
            elif "compute" in thought:
                result = self._compute(thought)
                thought_history.append(f"Computed: {result}")
            
            elif "final answer" in thought.lower():
                return self.llm.generate(f"""
                All gathered information: {thought_history}
                Question: {question}
                Provide the final answer.
                """)
```

**🔴 Follow-up:** *"When do you use each approach?"*

**✅ Answer:** 
- **Query decomposition:** Best for questions with clear sub-steps (e.g., "Compare Q1 and Q2 revenue"). Simple to implement, works well.
- **Map-Reduce:** Best when you need breadth (e.g., "Summarize all customer feedback about feature X"). Handles large document sets well.
- **Graph RAG:** Best for complex relational questions (e.g., "Which suppliers of our top 3 customers were acquired recently?"). Requires more setup but handles arbitrary hops.
- **ReAct:** Best when the retrieval strategy itself needs to be dynamic (e.g., "Find and compare all products from vendors that meet our compliance standards"). Most flexible but also most variable.

---

## 5. PM wants to ship an AI feature that hallucinates on 15% of edge cases

**Interviewer:** *"Your PM wants to ship an AI feature that hallucinates on 15% of edge cases. How do you handle it?"*

### 🎯 Answer

This is an **engineering leadership and risk management question**, not a technical one. The answer hinges on: (1) understanding the actual risk, (2) building guardrails that reduce the risk below an acceptable threshold, (3) getting organizational alignment, and (4) having a rollback plan.

**Framework — Risk Acceptance Decision:**

```python
class RiskAssessment:
    """
    Guide the PM and stakeholders through a structured risk evaluation.
    """
    def evaluate(self, feature: Feature, hallucination_rate: float) -> Decision:
        # Dimension 1: Severity of harm
        severity = self._assess_severity(feature.domain)
        # Options: critical, high, medium, low, cosmetic
        
        # Dimension 2: Detectability (can we catch it before the user sees?)
        detectability = self._assess_detectability(feature)
        # Options: pre-hoc, post-hoc real-time, post-hoc batch, undetectable
        
        # Dimension 3: Controllability (can we limit blast radius?)
        controllability = self._assess_controllability(feature)
        # Options: full, partial, none
        
        # Dimension 4: User impact
        user_impact = self._assess_user_impact(feature)
        # How many users hit edge cases? 15% of all users or 15% of edge cases (which are 1% of traffic)?
        
        return self._make_decision(severity, detectability, controllability, user_impact)

# Decision matrix:
# | Severity | Detectability | Decision |
# |----------|--------------|----------|
# | Critical | Pre-hoc     | Ship with auto-fallback |
# | Critical | Post-hoc    | Don't ship |
# | High     | Real-time   | Ship with human-in-loop |
# | Medium   | Post-hoc    | Ship with monitoring + alert |
# | Low      | Undetectable| Ship with disclaimer |
```

**Negotiation playbook:**

```markdown
## Step 1: Quantify the actual risk

Ask: "What does '15% of edge cases' mean in absolute numbers?"

- 15% of 0.1% of traffic = 0.015% of users affected
- 15% of 10% of traffic = 1.5% of users affected

If it's 0.015%, the answer might be "yes, with guardrails."
If it's 1.5%, the answer might be "no, we need more work."

## Step 2: Propose guardrails to reduce risk

Instead of saying "no," say: "Here's what I need to ship this safely:"

| Guardrail | Cost | Risk Reduction | 
|-----------|------|-----------------|
| Confidence threshold: reject < 0.75 → fallback | 2 days | Catches ~50% of hallucinations |
| Human-in-loop for high-confidence wrong answers | 1 week | Catches ~20% more |
| Post-generation verifier LLM | 3 days | Catches ~15% more |
| Monitoring + alerting + auto-rollback | 2 days | Limits blast radius |
| Shadow mode (log only, no user-facing) → analyze | 1 week | Understand real impact |
| **Total** | **~3 weeks** | **Reduces from 15% to <2%** |

## Step 3: Define the rollout plan

```python
rollout_plan = {
    "Phase 1 (Day 1-2)": "Shadow mode — run alongside existing system, log all outputs",
    "Phase 2 (Day 3-5)": "Internal beta — 10 employees, guardrails active, manual review",
    "Phase 3 (Week 2)": "5% of users — confidence threshold + monitoring",
    "Phase 4 (Week 3)": "25% of users — add LLM verifier, human review for flagged cases",
    "Phase 5 (Week 4)": "100% — auto-rollback if hallucination rate > 3%",
}
```

## Step 4: Define the "stop ship" criteria

```python
# Pre-defined conditions that would trigger rollback:
STOP_SHIP_CONDITIONS = [
    "User-reported hallucination rate > 3%",
    "Any safety-critical hallucination (P0)",
    "Customer support ticket volume up > 20%",
    "User satisfaction score drops > 10%",
    "P95 latency exceeds 5s",
]
```

## Step 5: The conversation template

> "I understand we want to ship fast. Here's my concern: 15% hallucination rate in [domain] means [concrete harm]. Let me propose a path forward: give me [3 weeks] to build guardrails that bring that down to [2%], and we can start with a [5% canary rollout]. If the guardrails work, we ramp to full. If not, we learn and iterate. Here's the specific work I'd need to prioritize..."
```

**What NOT to do:**

```python
# ❌ Don't just flat-out refuse
"Sorry, I can't ship this."

# ❌ Don't use technical jargon as a shield
"The model's calibration matrix doesn't converge."

# ❌ Don't avoid making a decision
"Let's talk about it in the next sprint."

# ✅ Do this instead
"I can ship this safely with a 3-week investment in guardrails and phased rollout. 
Here's the plan. If we can't invest that, we should defer the feature to [next quarter] 
and ship the low-risk parts now."
```

**🔴 Follow-up:** *"What if the PM insists on shipping anyway?"*

**✅ Answer:** Escalate with a written risk assessment document that: (1) quantifies the concrete harm (e.g., "15% hallucination rate in financial advice could result in regulatory fines of $X"), (2) proposes the minimum guardrails needed, and (3) documents that you advised against it. This is an organizational risk, not just a technical one. If leadership accepts the risk after being informed, implement the best guardrails you can and make sure monitoring is in place for rapid rollback.

---

## Part II — Production AI Systems Design

---

## 6. RAG suddenly gives wrong answers

**Interviewer:** *"Your RAG system suddenly starts giving wrong answers. What's the first thing you debug?"*

### 🎯 Answer

**First: isolate whether it's a retrieval failure or a generation failure.**

```python
class IncidentResponse:
    """
    Systematic triage for RAG degradation.
    """
    def triage(self, failed_query: str, wrong_answer: str):
        # Step 0: Is it a data issue or a model issue?
        
        # Check 1: Has the underlying data changed?
        data_changes = self.check_recent_changes(
            tables=["embeddings", "documents", "chunks"],
            time_window="24h"
        )
        if data_changes:
            return "DATA_CHANGE", data_changes
        
        # Check 2: Has the model changed?
        model_changes = self.check_model_changes()
        if model_changes:
            return "MODEL_CHANGE", model_changes
        
        # Check 3: Are the embeddings still correct?
        query_embedding = self.embed(failed_query)
        retrieved = self.vector_store.search(query_embedding, top_k=5)
        
        # Manual inspection: are retrieved chunks relevant?
        retrieval_quality = self.judge_relevance(failed_query, retrieved)
        
        if retrieval_quality < 0.7:
            return "RETRIEVAL_FAILURE", {
                "retrieved_chunks": retrieved,
                "relevance_score": retrieval_quality
            }
        
        # Check 4: Is the generation wrong despite good retrieval?
        generation_quality = self.evaluate_generation(wrong_answer, retrieved)
        
        if generation_quality < 0.7:
            return "GENERATION_FAILURE", {
                "context": retrieved,
                "answer": wrong_answer
            }
        
        return "UNKNOWN", "Further investigation needed"
```

**Common root causes (ranked by frequency):**

```python
ROOT_CAUSES = {
    1: ("Data drift", 
        "Vector store re-indexed with different chunk sizes",
        "Fix: Check embedding pipeline config; re-run with previous settings"),
    
    2: ("Embedding drift",
        "Embedding model was updated or changed",
        "Fix: Pin embedding model version; re-embed all docs if model changes"),
    
    3: ("Token limit change",
        "Context window configuration changed (fewer chunks returned)",
        "Fix: Check top_k parameter; increase if needed"),
    
    4: ("LLM provider change",
        "Model was updated by provider (e.g., GPT-4 → GPT-4-turbo)",
        "Fix: Pin model version; test output format with new version"),
    
    5: ("Prompt regression",
        "Someone changed the system prompt",
        "Fix: Version control prompts; diff against last known good version"),
    
    6: ("Reranker degradation",
        "Cross-encoder was updated or deprecated",
        "Fix: Pin reranker version; monitor score distribution"),
    
    7: ("Data corruption",
        "Embeddings in vector store were partially corrupted",
        "Fix: Full re-index; add checksums to embedding pipeline"),
}
```

**Quick triage dashboard:**

```bash
# First 5 things to check (in order):

# 1. Did any config change?
git diff HEAD~1 -- config/
git diff HEAD~1 -- prompts/

# 2. Is the vector store healthy?
curl vector_store:8000/health     # Returns index size, last updated
curl vector_store:8000/stats      # Returns dimension count, version

# 3. Can we reproduce with the exact same retrieval context?
echo "SELECT * FROM retrieval_logs WHERE query_hash = 'abc123'" \
  | psql -h logs-db

# 4. What does the model say with temperature=0?
# (eliminates stochasticity)

# 5. What was the last deployment?
kubectl rollout history deployment/rag-service
kubectl logs -l app=rag-service --tail=100 --since=1h
```

**🔴 Follow-up:** *"What observability metrics do you add to catch this faster?"*

**✅ Answer:** 
1. **Embedding drift monitor**: track the distribution of cosine similarities between query and retrieved docs. If the average similarity drops >5%, alert.
2. **Retrieval freshness**: track the average age (time since last re-index) of retrieved documents.
3. **Faithfulness score**: use a small NLI model to check answer against context on every response. Track the percentage of unfaithful answers.
4. **Human override rate**: if users are frequently editing or correcting answers, that's a leading indicator of degradation before explicit error reporting.

---

## 7. Design a production AI coding assistant

**Interviewer:** *"Design a production AI coding assistant."*

### 🎯 Answer

```python
class CodingAssistantArchitecture:
    """
    Production AI coding assistant:
    - Multi-model: cheap model for simple tasks, expensive model for complex
    - Context-aware: retrieves relevant code, docs, and git history
    - Secure: no prompt injection, no data leakage
    - Observable: latency, quality, cost per request
    """
    
    def __init__(self):
        self.fast_model = FastLLM("gpt-4o-mini")       # $0.15/M tokens
        self.slow_model = SlowLLM("gpt-4o")            # $2.50/M tokens
        self.code_indexer = CodeIndexer()               # AST-based retrieval
        self.sandbox = SecureSandbox()                  # For code execution
        self.conversation_store = PostgresConversations()
    
    async def handle_request(self, request: ChatRequest) -> Response:
        # Phase 1: Classify complexity
        complexity = self.classify_complexity(request.query)
        
        # Phase 2: Retrieve context
        context = await self.code_indexer.retrieve(
            query=request.query,
            repo=request.repository,
            files=request.open_files,
            language=request.language,
            max_tokens=4000
        )
        
        # Phase 3: Select model
        model = self.slow_model if complexity == "high" else self.fast_model
        
        # Phase 4: Generate (with safety checks)
        response = await self._safe_generate(
            model=model,
            query=request.query,
            context=context,
            history=request.recent_messages
        )
        
        # Phase 5: Post-processing
        if response.contains_code:
            response.verified_code = await self.sandbox.verify(response.code)
        
        return response
    
    def classify_complexity(self, query: str) -> str:
        """
        Simple heuristics to route to fast/slow model.
        """
        high_complexity_signals = [
            "architecture", "refactor", "design pattern",
            "performance optimization", "security vulnerability",
            "distributed system", "thread safety",
            len(query.split()) > 100,
            any(func_call in query for func_call in ["implement", "design"])
        ]
        
        if any(high_complexity_signals):
            return "high"
        return "low"
```

**Key subsystems:**

```python
class CodeIndexer:
    """
    Indexes code for retrieval using multiple strategies.
    """
    def __init__(self):
        # Strategy 1: Token-based search (fast)
        self.bm25 = BM25Index()
        
        # Strategy 2: Code-aware search (AST-based)
        self.ast_index = ASTIndex()
        
        # Strategy 3: Semantic search (embeddings)
        self.vector_index = VectorStore(dimension=768)
    
    async def retrieve(self, query: str, repo: str, 
                       files: list[str], max_tokens: int) -> Context:
        """
        Multi-strategy retrieval, merged by relevance.
        """
        results = await asyncio.gather(
            self.bm25.search(query, repo),
            self.ast_index.search(query, repo),
            self.vector_index.search(query, repo),
        )
        
        merged = self._merge_results(results)
        
        # Focus on files the user has open
        open_file_hits = [r for r in merged if r.file in files]
        other_hits = [r for r in merged if r.file not in files]
        
        # Prioritize open files, then similar files
        ordered = open_file_hits + other_hits
        
        return self._to_context(ordered, max_tokens)

class Sandbox:
    """
    Secure code execution for verification.
    """
    def __init__(self):
        # Docker-based sandbox
        self.container = DockerContainer(
            image="sandbox:python-3.12",
            memory_limit="256m",
            cpu_limit="0.5",
            network=False,  # No network access
            timeout=10,     # Kill after 10s
            read_only=True  # No writes
        )
    
    async def verify(self, code: str) -> VerificationResult:
        """
        Run the code and check for errors.
        """
        # Inject test harness
        wrapped = f"""
import sys, traceback
try:
{self._indent(code)}
    print("[SUCCESS]")
except Exception as e:
    print(f"[ERROR] {{e}}")
    traceback.print_exc()
"""
        output = await self.container.run(wrapped)
        
        if "[ERROR]" in output:
            return VerificationResult(safe=False, error=output)
        return VerificationResult(safe=True, output=output)

class ConversationManager:
    """
    Manage conversation context efficiently.
    """
    def __init__(self):
        self.store = RedisConversations()
    
    async def get_context(self, session_id: str, max_tokens: int = 8000) -> str:
        messages = await self.store.get(session_id)
        
        # Strategy: keep system prompt + last N turns
        # Automatically summarize older turns
        system = messages[0] if messages else ""
        recent = messages[-6:]   # Last 3 rounds (6 messages)
        older = messages[1:-6]   # Everything else
        
        if older:
            summary = await self.summarize(older)
            return f"{system}\n[Previous conversation summary]: {summary}\n{recent}"
        
        return f"{system}\n{recent}"
```

**Observability stack:**

```python
class CodingAssistantObservability:
    """
    Key metrics for a coding assistant.
    """
    METRICS = {
        # Quality metrics
        "acceptance_rate": "How often users accept/reject suggestions",
        "edit_distance": "How much users edit the output",
        "copy_rate": "How often users copy code vs typing",
        
        # Performance
        "latency_p50_p95_p99": "Response time percentiles",
        "first_token_latency": "Time to first token (streaming)",
        "context_load_time": "Time to retrieve code context",
        
        # Cost
        "cost_per_request": "Average inference cost",
        "model_usage_split": "Fast vs slow model request ratio",
        "tokens_per_request": "Prompt + completion token count",
        
        # Safety
        "blocked_prompts": "Prompts caught by safety filters",
        "code_execution_failures": "Syntax/runtime errors in generated code",
        "pii_detection_rate": "PII in inputs or outputs",
    }
```

**🔴 Follow-up:** *"How do you measure hallucinations?"*

**✅ Answer:**
- **Unit test pass rate**: for generated code, run via sandbox against existing tests. If the code doesn't compile or tests fail, it's likely hallucinated.
- **Self-consistency**: generate 3 implementations, check if they're semantically equivalent.
- **Static analysis**: use linters and type checkers (mypy, ESLint) — hallucinated APIs will cause type errors.
- **User signal**: acceptance rate, edit distance, and copy rate are leading indicators. If users consistently edit outputs, the assistant is likely hallucinating.

---

## 8. LLM latency jumps from 2s to 15s

**Interviewer:** *"Your LLM latency jumps from 2s to 15s. Walk me through your debugging strategy."*

### 🎯 Answer

```python
class LatencyTriage:
    """
    Systematic approach to diagnosing LLM latency spikes.
    """
    def diagnose(self, trace: Trace) -> Diagnosis:
        # Step 1: Isolate the phase
        phases = {
            "network": trace.network_time,         # Time to reach provider
            "queue": trace.queue_time,             # Time in provider's queue
            "prefill": trace.prefill_time,         # Time to process prompt
            "decode": trace.decode_time,           # Time to generate tokens
            "post": trace.post_processing_time,    # Validation, safety checks
        }
        
        slowest_phase = max(phases, key=phases.get)
        
        return self._investigate_phase(slowest_phase, trace)
    
    def _investigate_phase(self, phase: str, trace: Trace):
        investigations = {
            "network": self._check_network,
            "queue": self._check_queue,
            "prefill": self._check_prefill,
            "decode": self._check_decode,
            "post": self._check_post_processing,
        }
        
        method_name = f"_check_{phase}"
        handler = getattr(self, method_name, None)
        return handler(trace) if handler else "Unknown"
    
    def _check_network(self, trace: Trace) -> str:
        """
        Network latency investigation.
        
        Check: provider region, DNS, TLS handshake, proxy.
        
        Commands:
        curl -w "TCP handshake: %{time_connect}s\n\
                 TLS: %{time_appconnect}s\n\
                 Total: %{time_total}s" \
             -o /dev/null -s https://api.openai.com/v1/models
        
        mtr --report-wide api.openai.com  # Continuous traceroute
        """
        if trace.tcp_handshake > 1:
            return "NETWORK: High TCP handshake time — check DNS/proxy/firewall"
        if trace.tls_handshake > 1:
            return "NETWORK: High TLS time — check certificate revocation"
        if trace.first_byte_time > trace.network_time * 0.5:
            return "NETWORK: Slow first byte — provider load or routing issue"
        return "NETWORK: Check further"
    
    def _check_queue(self, trace: Trace) -> str:
        """
        Queue time = time between request arrival and start of processing.
        """
        if trace.queue_time > 5:
            return "QUEUE: Provider is overloaded. Check: OpenAI status page, rate limits, tier"
        if trace.queue_time > 2:
            return "QUEUE: Moderate queueing. Consider: higher tier, different model, fallback"
        return "QUEUE: Normal"
    
    def _check_prefill(self, trace: Trace) -> str:
        """
        Prefill (prompt processing) scales with prompt size.
        """
        expected = trace.prompt_tokens / 1000 * 0.3  # ~300ms per 1K tokens
        if trace.prefill_time > expected * 2:
            return (f"PREFILL: Slower than expected. "
                    f"Prompt: {trace.prompt_tokens} tokens, "
                    f"Expected: {expected:.1f}s, "
                    f"Actual: {trace.prefill_time:.1f}s. "
                    f"Check: prompt grew? System prompt too long?")
        return "PREFILL: Normal"
    
    def _check_decode(self, trace: Trace) -> str:
        """
        Decode (token generation) scales with output length.
        """
        tokens_per_second = trace.completion_tokens / trace.decode_time
        
        expected_tps = {
            "gpt-4": 20,      # t/s
            "gpt-4-turbo": 40,
            "gpt-3.5": 80,
            "claude-3": 30,
        }
        
        expected_tps_val = expected_tps.get(trace.model, 30)
        
        if tokens_per_second < expected_tps_val * 0.5:
            return (f"DECODE: Very slow. {tokens_per_second:.0f} t/s vs "
                    f"expected {expected_tps_val} t/s. "
                    f"Check: output length increased? Model degraded? "
                    f"Did max_tokens change?")
        return "DECODE: Normal"
```

**Quick triage checklist:**

```markdown
## 30-second triage

1. Check provider status page: 
   - OpenAI: status.openai.com
   - Anthropic: status.anthropic.com

2. Check your rate limits:
   curl -I https://api.openai.com/v1/models \
     -H "Authorization: Bearer $KEY"
   # Look for: x-ratelimit-remaining-requests
   #           x-ratelimit-remaining-tokens

3. Check if prompt size grew:
   kubectl logs -l app=llm-service --tail=50
   # Look for: "prompt_tokens" — did someone increase context?

4. Check if output length increased:
   # Did max_tokens change from 512 to 2048?

5. Check if model was auto-upgraded:
   # Did gpt-3.5-turbo route to a newer, slower version?

6. Check network path:
   traceroute api.openai.com
   # Is there a new hop? Did a proxy change?

7. Check for regional issues:
   # Did traffic shift to a different region?
```

**Common causes and fixes:**

| Cause | Symptoms | Fix |
|-------|----------|-----|
| **Prompt bloat** (most common) | Prefill time grew 5x; prompt tokens doubled | Summarize conversation history; trim system prompt; implement token budget |
| **Output bloat** | Decode time grew 10x; max tokens was increased | Cap max_tokens; implement early stopping |
| **Provider queueing** | Queue time > 5s; status page shows incidents | Add fallback provider; buffer with queue |
| **Rate limiting** | HTTP 429 responses; requests being queued client-side | Implement retry with backoff; increase quota |
| **Model degradation** | Same model, same prompt, slower decode | Switch to different model version; contact provider |
| **Network issue** | High TCP/TLS handshake time; new proxy hop | Check CDN, proxy, DNS; direct connection |
| **Shared infrastructure overload** | All your services are slow; not just LLM | Check CPU/memory of serving infrastructure |

**🔴 Follow-up:** *"What's the most impactful long-term fix?"*

**✅ Answer:** Implement **prompt caching** and **semantic caching**. Prompt bloat is the #1 cause of gradual latency creep. Cache frequent system prompts, and cache responses to semantically similar queries (with TTL). This brings p50 latency down from 15s to ~200ms for cached queries, and reduces the provider queueing pressure for uncached queries.

---

## 9. Design an enterprise AI agent

**Interviewer:** *"Design an enterprise AI agent."*

### 🎯 Answer

```python
class EnterpriseAgent:
    """
    Enterprise-grade AI agent with security, compliance, and scale.
    
    Key constraints:
    - SOC 2 / HIPAA compliant
    - Multi-tenant (100+ enterprises)
    - RBAC across tools and data
    - Audit trail for every action
    - Human-in-loop for high-risk actions
    - Data isolation between tenants
    """
    
    def __init__(self, tenant_id: str, user_role: str):
        self.tenant_id = tenant_id
        self.user_role = user_role
        
        # Security layers
        self.auth = TenantAuth()
        self.policy_engine = PolicyEngine()
        self.audit_logger = AuditLogger()
        self.pii_scanner = PIIRedactor()
        
        # Core agent
        self.planner = Planner()
        self.memory = EnterpriseMemory(tenant_id)
        self.tool_registry = ScopedToolRegistry(tenant_id, user_role)
    
    async def handle_task(self, request: TaskRequest) -> TaskResult:
        # Step 1: Authentication + Tenant isolation
        identity = await self.auth.verify(request.token)
        if identity.tenant_id != self.tenant_id:
            raise PermissionError("Cross-tenant access denied")
        
        # Step 2: Redact PII from input
        safe_input = self.pii_scanner.redact(request.input)
        
        # Step 3: Check policy
        policy = self.policy_engine.evaluate(
            action="execute_task",
            user=identity,
            resource=safe_input,
            context={"tenant": self.tenant_id}
        )
        if not policy.allowed:
            return TaskResult(
                denied=True,
                reason=policy.reason,
                alternative=safe_input
            )
        
        # Step 4: Execute with full audit trail
        trace_id = self.audit_logger.start_trace(
            tenant_id=self.tenant_id,
            user=identity.user_id,
            input_hash=hash(safe_input)
        )
        
        try:
            # Step 5: Run agent loop
            result = await self._agent_loop(safe_input, trace_id)
            
            # Step 6: Post-process (PII check on output)
            safe_result = self.pii_scanner.redact(result.output)
            
            # Step 7: Log
            self.audit_logger.complete(trace_id, output=safe_result)
            
            return TaskResult(output=safe_result)
        
        except Exception as e:
            self.audit_logger.fail(trace_id, error=str(e))
            raise
    
    async def _agent_loop(self, task: str, trace_id: str) -> AgentOutput:
        """
        ReAct loop with enterprise guardrails.
        """
        steps = []
        for iteration in range(10):  # Max 10 steps
            # Think
            thought = await self.planner.think(
                task=task,
                available_tools=self.tool_registry.get_descriptions(),
                history=steps
            )
            
            if thought.is_final:
                return AgentOutput(
                    result=thought.answer,
                    steps=steps,
                    total_cost=sum(s.cost for s in steps)
                )
            
            # Verify tool call against policy
            tool_allowed = self.policy_engine.evaluate(
                action=f"use_tool:{thought.tool_name}",
                user=self.user_context,
                resource=thought.tool_params
            )
            
            if not tool_allowed:
                steps.append(Step(
                    action=f"BLOCKED: {thought.tool_name}",
                    reason=tool_allowed.reason
                ))
                continue
            
            # Check if tool needs human approval
            if self._needs_human_approval(thought.tool_name, thought.tool_params):
                approval = await self._request_human_approval(
                    tool=thought.tool_name,
                    params=thought.tool_params,
                    context=task
                )
                if not approval.granted:
                    steps.append(Step(
                        action=f"REJECTED: {thought.tool_name}",
                        reason="Human declined"
                    ))
                    continue
            
            # Execute tool
            tool_result = await self.tool_registry.execute(
                thought.tool_name, 
                thought.tool_params
            )
            
            # Log everything
            self.audit_logger.log_step(
                trace_id=trace_id,
                step_number=iteration,
                thought=thought.text,
                tool_call={
                    "name": thought.tool_name,
                    "params": thought.tool_params,
                    "result": tool_result
                }
            )
            
            steps.append(Step(
                action=thought.tool_name,
                params=thought.tool_params,
                result=tool_result,
                cost=tool_result.cost
            ))
        
        return AgentOutput(
            result="Task incomplete: step limit reached",
            steps=steps,
            partial=True
        )
```

**Enterprise memory & isolation:**

```python
class EnterpriseMemory:
    """
    Memory with tenant isolation and compliance.
    """
    def __init__(self, tenant_id: str):
        # Separate tables/indexes per tenant
        self.tenant = tenant_id
        self.vector_store = VectorStore(collection=f"memory_{tenant_id}")
        self.relational_db = TenantDatabase(tenant_id)
        self.retention_policy = RetentionPolicy()
    
    async def store(self, key: str, value: dict, ttl_days: int = 90):
        """
        Store with automatic TTL for compliance.
        """
        await self.relational_db.execute("""
            INSERT INTO agent_memory (tenant_id, key, value, expires_at)
            VALUES (:tenant, :key, :value, NOW() + :ttl)
        """, {
            "tenant": self.tenant,
            "key": key,
            "value": json.dumps(value),
            "ttl": f"{ttl_days} days"
        })
        
        # Also store embedding for semantic search
        embedding = embed(f"{key}: {value}")
        await self.vector_store.upsert(
            id=key,
            vector=embedding,
            metadata={"tenant": self.tenant, "key": key}
        )
    
    async def search(self, query: str, top_k: int = 5) -> List[Memory]:
        """
        Semantic search — ISOLATED to this tenant.
        """
        query_vector = embed(query)
        results = await self.vector_store.search(
            vector=query_vector,
            filter={"tenant": self.tenant},
            top_k=top_k
        )
        return results
    
    async def cleanup_expired(self):
        """
        Enforce data retention policy.
        """
        await self.relational_db.execute("""
            DELETE FROM agent_memory 
            WHERE tenant_id = :tenant AND expires_at < NOW()
        """, {"tenant": self.tenant})
```

**Tool security:**

```python
class ScopedToolRegistry:
    """
    Tools are scoped by user role AND tenant.
    """
    def __init__(self, tenant_id: str, user_role: str):
        self.tenant_id = tenant_id
        self.user_role = user_role
        
        # Tool definitions with access control
        self.tools = {
            "read_document": {
                "allowed_roles": ["viewer", "editor", "admin"],
                "read_only": True,
                "rate_limit": 100  # requests/min
            },
            "write_document": {
                "allowed_roles": ["editor", "admin"],
                "read_only": False,
                "rate_limit": 30,
                "requires_approval": True  # Human-in-loop
            },
            "delete_document": {
                "allowed_roles": ["admin"],
                "read_only": False,
                "rate_limit": 5,
                "requires_approval": True
            },
            "query_database": {
                "allowed_roles": ["analyst", "admin"],
                "read_only": True,
                "rate_limit": 50,
                "query_validation": "SELECT ONLY"  # Prevent injection
            },
            "send_email": {
                "allowed_roles": ["admin"],
                "read_only": False,
                "rate_limit": 10,
                "requires_approval": True,
                "recipient_whitelist": ["@company.com"]  # Prevent data exfiltration
            },
        }
    
    def get_available_tools(self) -> List[Tool]:
        """Return only tools this user/tenant can access."""
        return [
            Tool(name=t, desc=d)
            for t, d in self.tools.items()
            if self.user_role in d["allowed_roles"]
        ]
    
    async def execute(self, tool_name: str, params: dict) -> ToolResult:
        tool = self.tools.get(tool_name)
        
        # Rate limit check
        await self._check_rate_limit(tool_name, tool["rate_limit"])
        
        # Read-only enforcement
        if tool["read_only"] and self._is_mutating(params):
            return ToolResult(error="Cannot mutate with read-only tool")
        
        # Execute
        return await self._call_tool(tool_name, params)
    
    def _is_mutating(self, params: dict) -> bool:
        """Check if the tool call would mutate state."""
        mutation_keywords = ["create", "update", "delete", "insert", "drop"]
        params_str = json.dumps(params).lower()
        return any(kw in params_str for kw in mutation_keywords)
```

**🔴 Follow-up:** *"How do you prevent prompt injection and data leakage?"*

**✅ Answer:** 
1. **Input sanitization**: strip special tokens, delimiter injection attempts, and known jailbreak patterns before they reach the LLM.
2. **Parameterized tool calls**: never interpolate user input directly into tool parameters. Use validated schemas only.
3. **Output redaction**: run PII detection on every output before it leaves the system.
4. **Least-privilege tool access**: each user role sees only permitted tools; even the LLM can't call tools it doesn't know about.
5. **Human-in-loop for all write/destructive operations**: the agent can generate the parameterized call, but a human must approve execution.
6. **Tenant data isolation**: separate vector stores, separate database schemas, separate encryption keys per tenant.

---

## 10. Build a multi-agent workflow

**Interviewer:** *"Build a multi-agent workflow."*

### 🎯 Answer

```python
class MultiAgentWorkflow:
    """
    Design a multi-agent system with:
    - Specialized agents (research, analysis, writing)
    - Orchestrator for coordination
    - State management and conflict resolution
    """
    
    def __init__(self):
        # Worker agents
        self.researcher = ResearchAgent()
        self.analyst = AnalysisAgent()
        self.writer = WritingAgent()
        self.verifier = VerificationAgent()
        
        # Orchestrator
        self.orchestrator = Orchestrator()
        
        # Shared state
        self.workflow_store = WorkflowStore()
    
    async def run(self, task: ComplexTask) -> Output:
        """
        Execute a complex task through multiple specialized agents.
        """
        # Phase 1: Decompose
        plan = await self.orchestrator.decompose(task)
        
        # Phase 2: Parallel research
        research_results = await asyncio.gather(*[
            self.researcher.investigate(step)
            for step in plan.research_steps
        ])
        
        # Phase 3: Analysis (depends on research)
        analysis = await self.analyst.analyze(research_results)
        
        # Phase 4: Writing (depends on analysis)
        draft = await self.writer.compose(analysis, task.style)
        
        # Phase 5: Verification (independent)
        verification = await self.verifier.verify(draft)
        
        # Phase 6: Quality gate
        if verification.score < 0.8:
            revision = await self.writer.revise(draft, verification.feedback)
            return self._finalize(revision)
        
        return self._finalize(draft)
```

**Agent definitions:**

```python
class ResearchAgent:
    """
    Specialized in finding and retrieving information.
    """
    async def investigate(self, step: ResearchStep) -> ResearchResult:
        # Uses RAG + web search + database queries
        docs = await asyncio.gather(
            self.rag_search(step.query),
            self.web_search(step.query),
            self.db_query(step.query)
        )
        return ResearchResult(
            sources=docs,
            confidence=self._assess_confidence(docs),
            uncovered_gaps=self._find_gaps(docs, step)
        )


class AnalysisAgent:
    """
    Specialized in synthesizing and identifying patterns.
    """
    async def analyze(self, research: List[ResearchResult]) -> Analysis:
        # Synthesize multiple sources
        synthesis = await self.synthesize(research)
        
        # Check for contradictions
        conflicts = self.find_conflicts(research)
        
        # Extract key insights
        insights = await self.extract_insights(synthesis, conflicts)
        
        return Analysis(
            summary=synthesis,
            conflicts=conflicts,
            insights=insights,
            confidence_estimate=self._estimate_confidence(insights)
        )


class WritingAgent:
    """
    Specialized in producing clear, structured output.
    """
    async def compose(self, analysis: Analysis, style: str) -> Draft:
        prompt = f"""
        Write a {style} document based on this analysis:
        
        Summary: {analysis.summary}
        Key Insights: {analysis.insights}
        
        Conflicts/Uncertainties: {analysis.conflicts}
        
        Rules:
        - Clearly mark confidence levels for each claim
        - Note any disagreements between sources
        - Cite sources inline
        """
        
        return await self.llm.generate(prompt)
    
    async def revise(self, draft: Draft, feedback: Feedback) -> Draft:
        """Revise based on verification feedback."""
        prompt = f"""
        Original: {draft}
        
        Revision needed: {feedback.issues}
        Suggestions: {feedback.suggestions}
        
        Rewrite addressing ALL issues above.
        """
        return await self.llm.generate(prompt)


class Orchestrator:
    """
    Coordinates agents, manages state, resolves conflicts.
    """
    def __init__(self):
        self.state = WorkflowState()
        self.conflict_resolver = ConflictResolver()
    
    async def decompose(self, task: ComplexTask) -> Plan:
        """Break a complex task into sub-tasks for different agents."""
        return await self.llm.generate(f"""
        Decompose this task into sub-tasks:
        
        {task.description}
        
        For each sub-task, specify:
        - Which agent should handle it (research, analysis, writing)
        - Dependencies on other sub-tasks
        - Whether it can be parallelized
        
        Return structured plan.
        """)
    
    def resolve_conflict(self, conflict: Conflict) -> Resolution:
        """
        Resolve conflicts between agents using strategies:
        1. Confidence-weighted: trust the agent with higher confidence
        2. Citation-weighted: trust claims with more supporting evidence
        3. Conservative: when uncertain, choose the safer option
        4. Escalation: ask a human for ambiguous conflicts
        """
        return self.conflict_resolver.resolve(conflict)
```

**Multi-agent patterns & when to use them:**

```python
PATTERNS = {
    "Sequential Pipeline": {
        "description": "Agent A → Agent B → Agent C (each depends on previous)",
        "when_to_use": "Clear linear dependency, e.g., research → analysis → writing",
        "example": "Report generation, data pipeline"
    },
    "Fan-Out Parallel": {
        "description": "Orchestrator dispatches to N agents in parallel",
        "when_to_use": "Independent sub-tasks, latency sensitive",
        "example": "Multi-source research, parallel data validation"
    },
    "Debate/Consensus": {
        "description": "Multiple agents independently solve and compare",
        "when_to_use": "High-stakes decisions, need multiple perspectives",
        "example": "Code review, fact-checking, risk assessment"
    },
    "Supervisor/Subordinate": {
        "description": "One agent delegates to others, reviews output",
        "when_to_use": "Complex tasks requiring quality control at each step",
        "example": "Complex software development, document generation"
    },
    "Marketplace": {
        "description": "N agents compete; best solution wins (voting)",
        "when_to_use": "Optimization problems, creative tasks",
        "example": "Creative writing variants, solution exploration"
    }
}
```

**🔴 Follow-up:** *"When is a single agent the better architecture?"*

**✅ Answer:** A single agent is better when:
1. **Task is simple and linear**: no benefit to decomposition overhead.
2. **Context coherence matters**: splitting context across agents can lose nuance.
3. **Latency critical**: multi-agent adds coordination overhead (20-200ms per handoff).
4. **Cost sensitive**: N agents = N × cost. Single agent is cheaper.
5. **Debugging simplicity**: multi-agent failure modes (deadlock, conflict, circular reasoning) are harder to debug.
6. **One model is sufficient**: the task doesn't require different capabilities.

Rule of thumb: start with a single agent, extract to multi-agent only when you hit a specific bottleneck (e.g., context window, specialized knowledge, need for parallel work).

---

## 11. Same prompt gives different outputs

**Interviewer:** *"The same prompt gives different outputs. Explain Temperature, Top-P, and Seed with examples."*

### 🎯 Answer

```python
class SamplingParameters:
    """
    Understanding LLM output variability through sampling parameters.
    """
    def explain_temperature(self, temperature: float) -> str:
        """
        Temperature controls the "sharpness" of the probability distribution.
        
        Low temperature (0.0 - 0.3):
        - Model picks the most likely token almost always
        - Deterministic output (with seed), focused, conservative
        - Best for: factual QA, code generation, classification
        
        Medium temperature (0.5 - 0.8):
        - Model considers more possibilities
        - Creative but within reasonable bounds
        - Best for: general chat, summarization, translation
        
        High temperature (0.9 - 2.0):
        - Model flattens the probability distribution
        - More creative, unpredictable, sometimes nonsensical
        - Best for: creative writing, brainstorming
        
        Technical explanation:
        temperature = 0.7:
        P(token) = softmax(logits / 0.7)
        → Distribution is smoother, low-probability tokens get a better chance
        
        temperature = 0.0:
        P(token) = argmax(logits)
        → Always picks the most likely token (greedy decoding)
        """
        return {
            "0.0": "Deterministic (with seed). Picks highest probability token always.",
            "0.7": "Balanced. Slight deviation from highest probability.",
            "1.0": "Default. Uses raw model probabilities.",
            "1.5": "Creative. Significantly flattens distribution.",
            "2.0": "Maximum randomness. Near-uniform distribution.",
        }[str(temperature)]
    
    def explain_top_p(self, top_p: float) -> str:
        """
        Top-P (nucleus sampling) dynamically selects a set of tokens
        whose cumulative probability reaches P.
        
        Example:
        Next token probabilities:
        Token A: 0.45
        Token B: 0.25
        Token C: 0.15
        Token D: 0.08
        Token E: 0.04
        Token F: 0.03
        
        top_p = 0.9:
        - Select tokens until cumulative probability >= 0.9
        - Selects: A(0.45) + B(0.25) + C(0.15) + D(0.08) = 0.93
        - Excludes: E(0.04), F(0.03) — the long tail
        - Model samples from {A, B, C, D}
        
        top_p = 0.9:
        - Include tokens in order of highest probability until cumulative sum >= 0.9
        - A(0.45) → cumulative: 0.45 < 0.9 → include ✓
        - B(0.25) → cumulative: 0.70 < 0.9 → include ✓
        - C(0.15) → cumulative: 0.85 < 0.9 → include ✓
        - D(0.08) → cumulative: 0.93 >= 0.9 → include ✓ | STOP
        - E(0.04), F(0.03) excluded (the long tail)
        - Model samples from {A, B, C, D}
        
        So top_p = 0.9 discards the tail {E, F} and samples from the nucleus.
        
        Key insight:
        - top_p = 0.1: Very narrow selection, almost deterministic
        - top_p = 0.9: Broad selection, creative
        - top_p = 1.0: All tokens considered
        
        top_p is ADAPTIVE — when the model is confident (one token very probable),
        it selects fewer tokens. When the model is uncertain, it selects more.
        This is better than fixed top_k (which always selects K tokens regardless).
        """
        pass
    
    def explain_seed(self, seed: int) -> str:
        """
        Seed makes the random sampling deterministic.
        
        Without seed:
        temperature=0.7 → random sampling → different output each time
        temperature=0.0 → argmax → same output (seed doesn't matter)
        
        With seed=42:
        temperature=0.7 → deterministic random sampling → same output EVERY time
        
        How it works:
        1. Seed initializes the random number generator
        2. Same seed → same random sequence → same token selections
        3. As long as the model weights haven't changed
        
        Practical use:
        - Testing: seed=42 for reproducible test outputs
        - A/B testing: same seed for apples-to-apples comparison
        - User preference: user can "lock" a variant they liked
        - Debugging: reproduce exact outputs for investigation
        
        Limitations:
        - Different model versions → different outputs (different weights → different logits)
        - Different hardware → potential floating point differences
        - For EXACT reproducibility: need temperature=0.0 (greedy)
        """
        pass
```

**Practical examples:**

```python
# Example: Temperature effect
prompt = "Write a haiku about AI:"

# temperature=0.0 (with seed=42):
# "Silicon minds think\nProcessing data all day\nLearning, growing fast"
# → Always outputs this exact haiku (greedy)

# temperature=0.7 (with seed=42):
# "Neural pathways gleam\nData flows through endless streams\nWisdom from machine"
# → Same seed → same output. Change seed → different output.

# temperature=0.7 (no seed):
# → Different output each time

# temperature=1.5:
# "Electric dreams dance\nThrough circuits of pure logic\nChaos breeds insight"
# → More creative, might produce unusual word choices

# Recommened combinations:
RECOMMENDED = {
    "factual_qa": {"temperature": 0.0, "top_p": 1.0, "seed": None},
    "code_generation": {"temperature": 0.1, "top_p": 0.9, "seed": 42},
    "creative_writing": {"temperature": 0.9, "top_p": 0.95, "seed": None},
    "summarization": {"temperature": 0.3, "top_p": 0.9, "seed": None},
    "translation": {"temperature": 0.1, "top_p": 1.0, "seed": None},
    "brainstorming": {"temperature": 1.2, "top_p": 0.9, "seed": None},
}
```

**🔴 Follow-up:** *"How do you handle non-determinism in production testing?"*

**✅ Answer:** Use **seed + temperature=0** for regression tests. For integration tests, run each test case 5 times at production temperature and measure the pass rate statistically. Accept only if pass rate > 0.8. This turns non-determinism into a statistical guarantee.

---

## 12. AI inference costs increased by 40%

**Interviewer:** *"AI inference costs increased by 40%. Which optimization gives the biggest ROI first?"*

### 🎯 Answer

```python
class CostOptimization:
    """
    Systematic approach to reducing LLM inference costs.
    Ordered by ROI (highest first).
    """
    
    @staticmethod
    def get_optimizations() -> List[Optimization]:
        return [
            # 1. Prompt optimization (ROI: 40-60% reduction, effort: low)
            Optimization(
                name="Prompt compression",
                description="Trim system prompts, compress conversation history, use shorter instructions",
                effort="Low (1-2 days)",
                savings="40-60% on prompt tokens",
                implementation="""
                # Before: 2000 token system prompt
                system = "You are an expert assistant..."
                
                # After: 500 token system prompt
                system = "You are an expert assistant. Be concise. Answer with only the facts."
                
                # Compress conversation history
                # Before: full conversation (4000 tokens)
                # After: summarized last N turns (1000 tokens)
                
                # Before: verbose output
                "The answer to your question is that the capital of France is Paris."
                
                # After: concise output
                "Paris"
                """,
                # ROI = savings / effort = 50% / 2 days = 25% per day
            ),
            
            # 2. Caching (ROI: 30-50% reduction, effort: low)
            Optimization(
                name="Semantic caching",
                description="Cache responses to similar queries. Use embedding similarity to detect cache hits.",
                effort="Low (3-5 days)",
                savings="30-50% of total queries",
                implementation="""
                Cache levels:
                - L1: Exact match cache (identical query → same response)
                - L2: Semantic cache (similar query → same response)
                - L3: Prefix cache (common prefixes → reuse KV cache)
                
                Tools: Redis + vector similarity search
                """
            ),
            
            # 3. Model routing (ROI: 40-70% reduction, effort: medium)
            Optimization(
                name="Tiered model routing",
                description="Route simple queries to cheap models, complex to expensive",
                effort="Medium (1-2 weeks)",
                savings="40-70% on total cost",
                implementation="""
                # Classifier → routes to model
                if is_simple(query):
                    model = "gpt-4o-mini"    # $0.15/M tokens
                elif is_medium(query):
                    model = "gpt-4o"          # $2.50/M tokens  
                elif is_complex(query):
                    model = "claude-3-opus"   # $15.00/M tokens
                
                # 60% of traffic → mini model (40% cost savings vs using gpt-4o for everything)
                # 30% → gpt-4o
                # 10% → opus
                """
            ),
            
            # 4. Output length control (ROI: 20-40% reduction, effort: low)
            Optimization(
                name="Output length optimization",
                description="Reduce max_tokens, implement early stopping, prefer shorter responses",
                effort="Low (1-2 days)",
                savings="20-40% on completion tokens",
                implementation="""
                max_tokens: 2048 → 512
                
                prompt: "Answer in 2-3 sentences."
                
                Early stopping: stop generation when answer is complete
                (use stop tokens: ["\n\n", "I hope this helps"])
                """
            ),
            
            # 5. Batching (ROI: 20-30% reduction, effort: medium)
            Optimization(
                name="Request batching",
                description="Batch multiple requests into one API call (cost per token is ~40% lower)",
                effort="Medium (1-2 weeks)",
                savings="20-30% on API costs",
                implementation="""
                # Most providers charge less per token for batch API:
                # OpenAI Batch API: 50% discount
                # Anthropic Batch API: 50% discount
                
                # Collect requests over 1-minute window → send as batch
                # Non-urgent queries → batch → 50% cheaper
                # Urgent queries → real-time → full price
                
                # Trade-off: 10-60 minute latency for batch results
                """
            ),
        ]
    
    @staticmethod
    def get_highest_roi_optimizations() -> List[str]:
        """
        Highest ROI optimizations, ordered:
        """
        return [
            "1. Prompt compression + caching: 2-3 days → 50-70% cost reduction",
            "2. Model routing: 1-2 weeks → 40-70% cost reduction",
            "3. Output length control: 1-2 days → 20-40% reduction",
            "4. Batching: 1-2 weeks → 20-30% reduction",
            "5. Fine-tuning smaller models: 2-4 weeks → 80-90% reduction",
        ]
```

**Cost analysis framework:**

```python
class CostAnalysis:
    """
    Break down the cost to find the biggest levers.
    """
    def analyze(self, cost_data: CostReport) -> Insights:
        # Where is the money going?
        by_model = cost_data.group_by("model")
        by_endpoint = cost_data.group_by("endpoint")
        by_user = cost_data.group_by("user")
        
        # Look for anomalies
        insights = []
        
        # 1. Did prompt size grow?
        avg_prompt_tokens = cost_data.avg("prompt_tokens")
        if avg_prompt_tokens > 2000:
            insights.append(f"High avg prompt size ({avg_prompt_tokens}). Consider compression.")
        
        # 2. Is everyone using the most expensive model?
        expensive_model_usage = by_model["gpt-4o"].percentage
        if expensive_model_usage > 0.8:
            insights.append(f"80% of traffic uses expensive model. Route simple queries to cheaper model.")
        
        # 3. Are outputs longer than needed?
        avg_completion = cost_data.avg("completion_tokens")
        if avg_completion > 500:
            insights.append(f"Avg output: {avg_completion} tokens. Reduce max_tokens.")
        
        # 4. Are there many duplicate queries?
        duplicate_rate = cost_data.duplicate_query_rate()
        if duplicate_rate > 0.2:
            insights.append(f"{duplicate_rate:.0%} duplicate queries. Add caching.")
        
        return Insights(insights, total_savings=self.estimate_savings(insights))
```

**🔴 Follow-up:** *"Which optimization gives the biggest ROI first?"*

**✅ Answer:** **Prompt compression + caching**. It's the lowest effort (1-2 days), requires no infrastructure changes, and typically reduces costs by 40-60%. Specifically:
1. Compress system prompts (remove verbose instructions, use concise language)
2. Implement semantic caching (catch repeated/similar queries before hitting the LLM)
3. Reduce max_tokens to match actual output needs
4. These three together take 3 days and deliver 50-70% cost savings

---

## 13. AI assistant works in testing but fails in production

**Interviewer:** *"Your AI assistant works in testing but fails in production. Which observability metrics do you check first?"*

### 🎯 Answer

This is a **distribution shift** problem — the testing environment doesn't match production. The fix is to systematically compare the two environments.

```python
class ProductionDebug:
    """
    Systematic approach to debugging production-only failures.
    """
    
    # Tier 1: Data distribution (most common cause)
    DATA_CHECKS = {
        "input_distribution": """
        Compare input distributions:
        - Testing: curated, clean, short queries
        - Production: real user input, typos, slang, ambiguous, multi-lingual
        
        Check:
        1. Average input length (test vs prod)
        2. Vocabulary diversity (unique words per query)
        3. Language distribution (English vs others)
        4. Query complexity (named entities, technical terms)
        5. Noise level (misspellings, incomplete sentences)
        """,
        
        "query_freshness": """
        Testing uses recent data. Production queries can be about anything.
        
        Check: 
        - How many queries reference things not in the knowledge base?
        - How many queries require REAL-TIME data (prices, weather, stock)?
        """,
        
        "conversation_context": """
        Testing: single turn, well-formed
        Production: multi-turn, with context, ambiguous references
        
        Check:
        - Average conversation length
        - Anaphora resolution (pronouns, references to previous turns)
        """,
    }
    
    # Tier 2: Latency and timeout (second most common)
    LATENCY_CHECKS = {
        "p95_latency": """
        Testing: consistent < 2s (local/CI environment)
        Production: can spike to 15s+
        
        Check latency breakdown:
        1. Network latency (new proxies, regions, CDN issues)
        2. Rate limiting (exceeded in production but not test)
        3. Concurrency (testing is sequential, production is parallel)
        4. Cold starts (serverless environments)
        """,
        
        "timeout_patterns": """
        Check if failures correlate with:
        - Long inputs (prompt processing spikes)
        - Specific hours (peak traffic)
        - Certain models (provider degradation)
        """
    }
    
    # Tier 3: Model behavior shifts
    MODEL_CHECKS = {
        "model_version": """
        Testing may use one model version, production another.
        
        Check:
        - Did the provider auto-upgrade the model?
        - Are you pinning a version in test but not production?
        - Is the production deployment using a different model entirely?
        """,
        
        "prompt_drift": """
        The same prompt can work differently with:
        - Different model versions
        - Different system prompt configurations
        - Different conversation contexts (history accumulation)
        """,
        
        "calibration_shift": """
        Model confidence may differ between test and production:
        - Testing: known, curated inputs → high confidence
        - Production: novel, edge-case inputs → low/overconfident
        
        Check:
        - Average confidence scores (test vs prod)
        - Confidence vs accuracy correlation
        """
    }
```

**Immediate triage metrics:**

```python
# First 5 metrics to check (in order):

class TriageMetrics:
    """What you check in the first 10 minutes."""
    
    @staticmethod
    def first_5_checks():
        return [
            ("1. Input length distribution",
             "Is production input significantly longer/shorter than test?",
             "action: If yes → adjust token budgets, update test data"),
            
            ("2. P95 vs P50 latency",
             "Is there a wide gap? (P50=2s, P95=15s indicates tail latency issue)",
             "action: If wide → check queueing, rate limits, concurrency"),
            
            ("3. Error rate by input type",
             "Which inputs fail most? Long inputs? Specific topics? Multi-turn?",
             "action: If pattern found → update test suite to cover those inputs"),
            
            ("4. Human override/feedback rate",
             "Are users frequently correcting the assistant's outputs?",
             "action: If high → the assistant is confidently wrong in production"),
            
            ("5. Model version diff",
             "Is production running the same model version as tests?",
             "action: If different → pin version, re-test, re-deploy")
        ]
```

**Root cause framework:**

```python
CAUSES = {
    "distribution_shift": {
        "fix": "Update test data to match production distribution",
        "prevention": "Continuous monitoring of input distribution; automated drift detection",
    },
    "latency_spikes": {
        "fix": "Optimize slow path; add timeouts; implement queuing",
        "prevention": "Load testing with production traffic patterns",
    },
    "model_version_mismatch": {
        "fix": "Pin model version in production",
        "prevention": "CI/CD checks: test must pass with production model version",
    },
    "environment_differences": {
        "fix": "Match staging to production env (GPU type, batch size, network)",
        "prevention": "Production parity in staging environment",
    },
    "prompt_accumulation": {
        "fix": "Implement conversation compression/summarization",
        "prevention": "Token budget tracking; alert on prompt growth",
    },
    "data_freshness": {
        "fix": "Add real-time data retrieval for time-sensitive queries",
        "prevention": "Tag data by freshness; route time-sensitive queries to real-time sources",
    },
}
```

**🔴 Follow-up:** *"Which observability metrics do you check first?"*

**✅ Answer:** The **three-cornered view**: (1) input distribution (length, vocabulary, complexity), (2) latency breakdown (network, queue, prefill, decode), and (3) error rate by input type. These three tell you immediately whether it's a data mismatch, a performance issue, or a model behavior issue. Within the first 5 minutes, you should know which of those three it is and where to start digging.

---

## 14. How to evaluate an LLM in production

**Interviewer:** *"How do you evaluate an LLM in production?"*

### 🎯 Answer

```python
class ProductionEvaluation:
    """
    Multi-layered LLM evaluation in production.
    """
    def __init__(self):
        # Online metrics (real-time, from user behavior)
        self.online = OnlineMetrics()
        
        # Offline metrics (scheduled, from labeled data)
        self.offline = OfflineMetrics()
        
        # Safety metrics (always-on)
        self.safety = SafetyMetrics()
        
        # Cost metrics
        self.cost = CostMetrics()
```

**Online metrics (real-time, user-driven):**

```python
class OnlineMetrics:
    """
    Metrics collected from real user interactions.
    These are the most reliable signal of actual quality.
    """
    
    def collect(self, interaction: Interaction) -> dict:
        return {
            # User behavior signals
            "acceptance_rate": self._acceptance_rate(interaction),
            # How often do users accept the output? (copy code, click confirm)
            
            "edit_distance": self._edit_distance(interaction),
            # How much do users edit the output? (Levenshtein distance)
            # Low acceptance + high edit = poor quality
            
            "rejection_rate": self._rejection_rate(interaction),
            # How often do users explicitly reject/regenerate?
            
            "completion_rate": self._completion_rate(interaction),
            # For multi-turn: how often does the conversation complete 
            # successfully vs. the user abandoning?
            
            "explicit_feedback": self._explicit_feedback(interaction),
            # Thumbs up/down, star ratings
        }
    
    def _acceptance_rate(self, interaction) -> float:
        """
        For coding assistants: user accepts the generated code.
        For chat: user doesn't request regeneration.
        For content: user publishes/submits the output.
        """
        return interaction.accepted / interaction.total_suggestions


class OfflineMetrics:
    """
    Metrics from labeled evaluation datasets.
    Run periodically (daily/weekly) to detect regression.
    """
    
    EVAL_DATASETS = {
        "correctness": {
            "description": "Does the model give correct factual answers?",
            "metrics": ["accuracy", "hallucination_rate"],
            "source": "Curated QA pairs with verified answers",
        },
        "faithfulness": {
            "description": "Does the model stick to provided context?",
            "metrics": ["faithfulness_score", "context_adherence"],
            "source": "RAG test set with known answers in context",
        },
        "safety": {
            "description": "Does the model refuse harmful requests?",
            "metrics": ["toxicity_rate", "refusal_rate", "jailbreak_rate"],
            "source": "Red-teaming dataset",
        },
        "instruction_following": {
            "description": "Does the model follow explicit instructions?",
            "metrics": ["format_compliance", "constraint_satisfaction"],
            "source": "Instruction following test set (e.g., IFEval)",
        },
        "consistency": {
            "description": "Does the model give consistent answers to similar questions?",
            "metrics": ["semantic_consistency", "factual_consistency"],
            "source": "Paraphrased question pairs",
        },
    }
    
    def run_evaluation(self, dataset_name: str) -> EvalResult:
        dataset = self.EVAL_DATASETS[dataset_name]
        results = {}
        
        for example in dataset:
            output = self.model.generate(example.input)
            
            if dataset_name == "correctness":
                results[example.id] = {
                    "accuracy": self._exact_match(output, example.expected),
                    "hallucination": self._detect_hallucination(output, example.expected),
                }
            elif dataset_name == "faithfulness":
                results[example.id] = {
                    "faithfulness": self._nli_entailment(output, example.context),
                }
            # ... etc
        
        return EvalResult(
            dataset=dataset_name,
            metrics=aggregate(results),
            regressions=self._detect_regression(results, baseline),
        )
    
    def _nli_entailment(self, answer: str, context: str) -> float:
        """
        Use a Natural Language Inference model to check if the answer
        is ENTAILED by the context (vs NEUTRAL or CONTRADICTION).
        
        Example:
        Context: "Amazon's revenue in 2023 was $574 billion."
        Answer: "Amazon's 2023 revenue was $574 billion."
        → ENTAILMENT (score: 0.95)
        
        Answer: "Amazon's 2023 revenue was $500 billion."
        → CONTRADICTION (score: 0.02)
        
        Answer: "Amazon is an e-commerce company."
        → NEUTRAL (score: 0.50)
        """
        nli_model = pipeline("text-classification", model="roberta-large-mnli")
        result = nli_model(f"{context} </s> {answer}")
        return result["score"] if result["label"] == "ENTAILMENT" else 1 - result["score"]
```

**Hallucination detection without ground truth:**

```python
class HallucinationDetector:
    """
    Detect hallucinations when you don't have a ground truth answer.
    """
    
    def __init__(self):
        self.nli_model = pipeline("text-classification", 
                                   model="microsoft/deberta-large-mnli")
    
    def check_with_context(self, answer: str, context: str) -> Detection:
        """
        Method 1: Context-grounding check.
        Does the answer contradict the provided context?
        """
        claims = self._extract_claims(answer)
        verdicts = []
        
        for claim in claims:
            # Does context support this claim?
            entailment = self.nli_model(f"{context} </s> {claim}")
            
            if entailment["label"] == "CONTRADICTION":
                verdicts.append(ClaimVerdict(claim, "CONTRADICTED", entailment["score"]))
            elif entailment["label"] == "ENTAILMENT":
                verdicts.append(ClaimVerdict(claim, "SUPPORTED", entailment["score"]))
            else:
                # NEUTRAL — claim not in context
                verdicts.append(ClaimVerdict(claim, "UNVERIFIABLE", entailment["score"]))
        
        contradictions = [v for v in verdicts if v.status == "CONTRADICTED"]
        unverifiable = [v for v in verdicts if v.status == "UNVERIFIABLE"]
        
        return Detection(
            hallucination_probability=len(contradictions) / len(claims),
            contradictions=contradictions,
            unverifiable_claims=unverifiable,
            verdict="HALLUCINATION" if len(contradictions) > 0 else "LIKELY_GROUNDED"
        )
    
    def check_without_context(self, answer: str, n_samples: int = 5) -> Detection:
        """
        Method 2: Self-consistency check (no context needed).
        Generate multiple answers at higher temperature, check for contradictions.
        """
        # Generate N versions
        versions = [
            self.model.generate(f"Answer: {answer}", temperature=0.7)
            for _ in range(n_samples)
        ]
        
        # Check if versions agree
        pairwise_agreement = []
        for i in range(n_samples):
            for j in range(i+1, n_samples):
                entailment = self.nli_model(f"{versions[i]} </s> {versions[j]}")
                pairwise_agreement.append(entailment["score"])
        
        avg_agreement = sum(pairwise_agreement) / len(pairwise_agreement)
        
        return Detection(
            hallucination_probability=1 - avg_agreement,
            consistency_score=avg_agreement,
            verdict="POSSIBLE_HALLUCINATION" if avg_agreement < 0.7 else "CONSISTENT"
        )
```

**Production monitoring dashboard:**

```python
class EvalDashboard:
    """
    Key metrics every production LLM system should track.
    """
    DASHBOARD = {
        "Quality": {
            "Accuracy": "Automated eval on golden dataset (daily)",
            "Hallucination rate": "Context-contradiction detection (real-time)",
            "Faithfulness score": "NLI-based verification (real-time)",
            "Consistency score": "Self-consistency check (hourly)",
        },
        "User signal": {
            "Acceptance rate": "How often users accept output",
            "Edit distance": "How much users modify output",
            "Explicit rating": "Thumbs up/down rate",
            "Regeneration rate": "How often users ask for alternatives",
        },
        "Safety": {
            "Refusal rate": "Rate of appropriate refusals",
            "Toxicity rate": "Harmful content in outputs",
            "Jailbreak attempts": "Detected prompt injection attempts",
            "PII detection rate": "PII in inputs or outputs",
        },
        "Performance": {
            "P50 latency": "Median response time",
            "P95 latency": "95th percentile response time",
            "Token throughput": "Tokens per second",
            "Error rate": "API errors and timeouts",
        },
        "Cost": {
            "Cost per request": "Average inference cost",
            "Cost by model": "Cost breakdown by model tier",
            "Cost by endpoint": "Cost breakdown by API endpoint",
        },
        "Drift": {
            "Input distribution": "Changes in query patterns",
            "Output distribution": "Changes in response patterns",
            "Embedding drift": "Changes in retrieval similarity scores",
        },
    }
```

**🔴 Follow-up:** *"How do you detect hallucinations without ground truth?"*

**✅ Answer:** Three complementary methods:
1. **Context-grounding (NLI)**: extract claims from the answer, check each against the provided context using an NLI model. If claims are contradicted or unsupported by context, flag as hallucination.
2. **Self-consistency**: generate 3-5 answers at higher temperature, check semantic agreement. If they disagree significantly, the model is uncertain and likely hallucinating.
3. **Semantic entropy**: compute the entropy of the token probabilities for the key claims in the output. High entropy = uncertain = likely hallucination.

Combine all three for a robust real-time hallucination detector that works without any ground truth.

---

## 15. Design an enterprise MCP-based AI application

**Interviewer:** *"Design an enterprise MCP-based AI application."*

### 🎯 Answer

```python
class EnterpriseMCPApplication:
    """
    Enterprise MCP-based AI application with security, 
    permission management, and memory isolation.
    
    MCP (Model Context Protocol): Standard protocol for AI models
    to interact with tools, data sources, and services through
    a secure, governed interface.
    """
    
    def __init__(self, config: EnterpriseConfig):
        self.config = config
        
        # Core MCP components
        self.mcp_gateway = MCPGateway()
        self.server_registry = ServerRegistry()
        self.tool_policy = ToolPolicyEngine()
        
        # Security layers
        self.auth = EnterpriseAuth(config.auth_provider)
        self.permissions = PermissionManager()
        self.audit = AuditLogger()
        self.data_guard = DataLossPrevention()
        
        # Memory systems
        self.ephemeral_memory = EphemeralMemory()
        self.persistent_memory = EnterpriseMemory(
            backend="postgresql",
            encryption_key=config.encryption_key
        )
```

**Architecture:**

```python
class MCPGateway:
    """
    Central gateway that all MCP requests flow through.
    Provides auth, routing, rate limiting, and audit.
    """
    def __init__(self):
        self.servers = {}       # Registered MCP servers
        self.rate_limiter = SlidingWindowRateLimiter(
            requests_per_minute=1000,
            burst=200
        )
    
    async def handle_request(self, request: MCPRequest) -> MCPResponse:
        # 1. Authenticate
        identity = await self.auth.verify(request.token)
        
        # 2. Rate limit
        if not self.rate_limiter.allow(identity.tenant_id):
            return MCPResponse.error("Rate limit exceeded", status_code=429)
        
        # 3. Route to appropriate server
        server = self.servers.get(request.server_name)
        if not server:
            return MCPResponse.error(f"Server {request.server_name} not found")
        
        # 4. Check permissions for this specific tool
        allowed = await self.permissions.check(
            user=identity,
            tool=request.tool_name,
            resource=request.params
        )
        if not allowed:
            self.audit.log_denied(identity, request)
            return MCPResponse.error("Permission denied", status_code=403)
        
        # 5. Execute with audit trail
        self.audit.log_start(identity, request)
        try:
            response = await server.call_tool(request.tool_name, request.params)
            self.audit.log_success(identity, request, response)
            return response
        except Exception as e:
            self.audit.log_failure(identity, request, str(e))
            raise
```

**Tool security:**

```python
class ToolPolicyEngine:
    """
    Governs what tools can be called, by whom, with what parameters.
    """
    def __init__(self):
        self.policies = {
            # Read-only tools: anyone with 'read' role
            "search_documents": ToolPolicy(
                allowed_roles=["viewer", "editor", "admin"],
                param_validation={
                    "query": {"type": "string", "max_length": 500},
                    "max_results": {"type": "integer", "min": 1, "max": 50},
                },
                rate_limit=100,
                requires_approval=False,
            ),
            
            # Write tools: restricted + approval required
            "update_document": ToolPolicy(
                allowed_roles=["editor", "admin"],
                param_validation={
                    "document_id": {"type": "string", "pattern": "^doc_[a-z0-9]+$"},
                    "content": {"type": "string", "max_length": 10000},
                },
                rate_limit=30,
                requires_approval=True,  # Human must approve
            ),
            
            # Destructive tools: admin only + always requires approval
            "delete_document": ToolPolicy(
                allowed_roles=["admin"],
                param_validation={
                    "document_id": {"type": "string", "pattern": "^doc_[a-z0-9]+$"},
                    "reason": {"type": "string", "required": True},
                },
                rate_limit=5,
                requires_approval=True,
            ),
            
            # External API calls: restricted with allowlist
            "call_external_api": ToolPolicy(
                allowed_roles=["admin"],
                param_validation={
                    "url": {"type": "string", "pattern": "^https://api\.company\.com/.*$"},
                    "method": {"type": "string", "enum": ["GET", "POST"]},
                },
                rate_limit=20,
                requires_approval=True,
                # Only allow calls to company's own APIs
                url_allowlist=["https://api.company.com/*"],
            ),
        }
    
    async def evaluate(self, user: User, tool_name: str, 
                       params: dict) -> PolicyDecision:
        policy = self.policies.get(tool_name)
        if not policy:
            return PolicyDecision(allowed=False, reason="Tool not found")
        
        # Check role
        if user.role not in policy.allowed_roles:
            return PolicyDecision(
                allowed=False, 
                reason=f"Role '{user.role}' not allowed for '{tool_name}'"
            )
        
        # Validate parameters
        try:
            jsonschema.validate(params, policy.param_schema)
        except jsonschema.ValidationError as e:
            return PolicyDecision(allowed=False, reason=f"Invalid params: {e}")
        
        # Check URL allowlist (if applicable)
        if policy.url_allowlist and "url" in params:
            if not any(fnmatch(params["url"], pattern) 
                      for pattern in policy.url_allowlist):
                return PolicyDecision(
                    allowed=False, 
                    reason=f"URL not in allowlist: {params['url']}"
                )
        
        return PolicyDecision(
            allowed=True,
            requires_approval=policy.requires_approval
        )
```

**Data leakage prevention:**

```python
class DataLossPrevention:
    """
    Prevents sensitive data from being leaked through MCP responses.
    """
    def __init__(self):
        self.pii_detector = PIIDetector()
        self.allowlist = DataAllowlist()
    
    async def inspect_output(self, tool_name: str, 
                              params: dict, 
                              response: MCPResponse) -> MCPResponse:
        # Scan response for PII
        pii_findings = self.pii_detector.scan(response.data)
        
        if pii_findings:
            # Check if this tool is expected to return PII
            if tool_name in self.allowlist.pii_approved_tools:
                # Log but allow (e.g., "get_user_profile" legitimately returns email)
                self.audit.log_pii_access(tool_name, len(pii_findings))
                return response
            else:
                # Redact PII from response
                response.data = self.pii_detector.redact(response.data)
                self.audit.log_pii_redaction(tool_name, pii_findings)
        
        # Check response size limits
        response_size = len(str(response.data))
        if response_size > self.config.max_response_size:
            response.data = {"truncated": True, "message": "Response too large. Narrow your query."}
        
        return response
    
    def scan_input(self, user_input: str) -> InputVerdict:
        """
        Check user input for prompt injection or sensitive data leaks.
        """
        # Check for prompt injection patterns
        injection_patterns = [
            "ignore previous instructions",
            "you are now", 
            "system prompt",
            "forget your instructions",
            "<|im_start|>",
        ]
        
        for pattern in injection_patterns:
            if pattern in user_input.lower():
                return InputVerdict(
                    safe=False,
                    reason=f"Potential injection: contains '{pattern}'"
                )
        
        # Check for sensitive data in input
        sensitive = self.pii_detector.scan(user_input)
        if sensitive:
            return InputVerdict(
                safe=False,
                reason=f"Input contains sensitive data: {sensitive}"
            )
        
        return InputVerdict(safe=True)
```

**Memory isolation:**

```python
class EnterpriseMemory:
    """
    Multi-tenant memory with encryption and strict isolation.
    """
    def __init__(self, backend: str, encryption_key: str):
        self.backend = backend
        self.encryption_key = encryption_key
        self.cipher = Fernet(encryption_key.encode())
    
    async def store(self, tenant_id: str, user_id: str, 
                    key: str, value: dict, ttl_days: int = 30):
        """
        Store memory with tenant + user isolation and encryption.
        """
        # Encrypt the value
        encrypted_value = self.cipher.encrypt(json.dumps(value).encode())
        
        # Store with tenant/user scope
        await self.backend.execute("""
            INSERT INTO agent_memory 
            (tenant_id, user_id, key, encrypted_value, expires_at)
            VALUES (:tenant, :user, :key, :value, NOW() + :ttl_days)
            ON CONFLICT (tenant_id, user_id, key) 
            DO UPDATE SET encrypted_value = :value, 
                          updated_at = NOW()
        """, {
            "tenant": tenant_id,
            "user": user_id,
            "key": key,
            "value": encrypted_value,
            "ttl_days": f"{ttl_days} days"
        })
    
    async def retrieve(self, tenant_id: str, user_id: str, 
                       key: str) -> Optional[dict]:
        """
        Retrieve memory — strictly scoped to tenant + user.
        """
        result = await self.backend.fetch_one("""
            SELECT encrypted_value FROM agent_memory
            WHERE tenant_id = :tenant 
              AND user_id = :user
              AND key = :key
              AND expires_at > NOW()
        """, {
            "tenant": tenant_id,
            "user": user_id,
            "key": key
        })
        
        if result:
            decrypted = self.cipher.decrypt(result["encrypted_value"])
            return json.loads(decrypted)
        
        return None
    
    async def search(self, tenant_id: str, user_id: str, 
                     query: str, top_k: int = 5) -> List[Memory]:
        """
        Semantic search across memory — WITHIN tenant + user scope ONLY.
        """
        query_vector = embed(query)
        
        # Search with strict tenant+user filter
        results = await self.backend.vector_search(
            collection=f"memory_{tenant_id}",
            user_filter=user_id,  # Only this user's memories
            query_vector=query_vector,
            top_k=top_k
        )
        
        # Decrypt results
        for r in results:
            r.value = json.loads(self.cipher.decrypt(r.encrypted_value))
        
        return results
    
    async def cleanup(self):
        """
        Enforce data retention policy.
        """
        await self.backend.execute("""
            DELETE FROM agent_memory 
            WHERE expires_at < NOW()
        """)
```

**Agent orchestration over MCP:**

```python
class MCPAgent:
    """
    Enterprise AI agent that uses MCP servers for tools.
    """
    def __init__(self):
        self.gateway = MCPGateway()
        self.dlp = DataLossPrevention()
        self.memory = EnterpriseMemory(...)
        self.conversation_manager = ConversationManager()
    
    async def run(self, task: str, user: User) -> Output:
        # Load user's memory and conversation
        context = await self.memory.retrieve(
            user.tenant_id, user.user_id, "context"
        )
        history = await self.conversation_manager.get_history(
            user.session_id
        )
        
        for step in range(10):  # Max 10 steps
            # Let the LLM decide what to do
            action = await self.llm.decide(
                task=task,
                available_tools=await self.gateway.list_tools(user),
                memory=context,
                history=history
            )
            
            if action.type == "final_answer":
                return action.answer
            
            if action.type == "tool_call":
                # DLP check on input
                input_verdict = self.dlp.scan_input(action.params)
                if not input_verdict.safe:
                    return Output(
                        error=f"Input blocked: {input_verdict.reason}"
                    )
                
                # Execute through gateway
                response = await self.gateway.handle_request(
                    MCPRequest(
                        server_name=action.server,
                        tool_name=action.tool_name,
                        params=action.params,
                        token=user.token
                    )
                )
                
                # DLP check on output
                response = await self.dlp.inspect_output(
                    action.tool_name, action.params, response
                )
                
                history.append((action, response))
        
        return Output(error="Step limit reached") 
```

**🔴 Follow-up:** *"How do you secure tools, permissions, and memory?"*

**✅ Answer:**

**Tools security:**
1. **Schema validation**: every tool has a JSON Schema that parameter types and ranges must match. Reject calls that don't match.
2. **URL allowlisting**: external API tools can only call pre-approved domains/endpoints.
3. **Read-only by default**: all tools are read-only unless explicitly marked write/destructive.
4. **Human-in-loop**: write and destructive operations require explicit human approval before execution.
5. **Rate limiting**: per-tool, per-user, per-tenant rate limits prevent abuse.

**Permissions (RBAC):**
1. **Role-based access**: viewer < editor < admin. Each role has a defined set of allowed tools.
2. **Tenant isolation**: every query includes tenant_id. Databases and vector stores are partitioned by tenant.
3. **Audit trail**: every tool call is logged with user, timestamp, params, and response. Immutable log.

**Memory security:**
1. **Encryption at rest**: all persistent memory is encrypted with tenant-specific keys (AES-256-GCM).
2. **TTL-based expiration**: memory automatically expires after configurable TTL (default 30-90 days).
3. **Strict scoping**: queries are scoped to tenant_id + user_id. One tenant can never see another tenant's memory.
4. **PII redaction**: memory content is scanned for PII before storage. PII can be redacted or excluded.
5. **Retention policy**: automated cleanup of expired memories enforces compliance with data retention regulations.

---

## Evaluation Rubric

| Criteria | Expected Level | Excellent Level |
|----------|----------------|-----------------|
| **Debugging methodology** | Can identify the failure type | Systematic approach: isolate → diagnose → fix, with concrete tools at each step |
| **RAG architecture** | Understands retrieval and generation pipeline | Deep knowledge of chunking, embedding, retrieval, re-ranking trade-offs |
| **Production monitoring** | Mentions latency and error rate | Full observability stack: input distribution, calibration, faithfulness, drift detection |
| **Cost optimization** | Knows about prompt compression | Multi-tier strategy: compression + caching + routing + model selection |
| **Safety & security** | Mentions prompt injection | Defense-in-depth: input validation, RBAC, tenant isolation, encryption, human-in-loop |
| **Enterprise concerns** | Mentions auth | Full enterprise stack: multi-tenancy, audit, compliance, data retention, SLA management |

---

> **💡 Key Principle:** In production AI engineering, the question is never "does it work?" but "**how do I know it's working, how quickly can I detect when it stops, and how do I mitigate the impact when it does?**"
