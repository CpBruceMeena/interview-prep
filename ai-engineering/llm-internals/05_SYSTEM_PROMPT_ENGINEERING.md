# 🎯 System Prompt Engineering — Principles, Patterns & Best Practices

> **How to craft effective system prompts that control LLM behavior with precision.**

---

## 1. WHAT IS A SYSTEM PROMPT?

The **system prompt** is the foundational instruction set that defines the LLM's behavior, persona, constraints, and output format for an entire conversation.

```ascii
┌────────────────────────────────────────────────────────────────────┐
│                    PROMPT HIERARCHY                                 │
│                                                                     │
│  SYSTEM PROMPT (Highest Priority)                                   │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ "You are a senior software engineer. Review code for        │   │
│  │  security vulnerabilities. Be thorough and cite specific    │   │
│  │  line numbers. Never output API keys."                      │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                          │                                          │
│                          │ Overrides model training when conflict  │
│                          ▼                                          │
│  USER MESSAGE (Lower Priority)                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ "Review this code for me: function foo() { ... }"          │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                          │                                          │
│                          ▼                                          │
│  LLM OUTPUT                                                         │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ "I found 3 security issues: 1. SQL injection on line 42..."│   │
│  └─────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────┘
```

---

## 2. THE ANATOMY OF A GREAT SYSTEM PROMPT

### 2.1 The Four Essential Components

```ascii
┌─────────────────────────────────────────────────────────────────────┐
│                    SYSTEM PROMPT STRUCTURE                           │
│                                                                     │
│  1. ROLE & PERSONA                                                  │
│     ┌─────────────────────────────────────────────────────────┐    │
│     │ "You are a senior software engineer with 10+ years of   │    │
│     │  experience in distributed systems and backend           │    │
│     │  architecture at a FAANG company."                      │    │
│     └─────────────────────────────────────────────────────────┘    │
│                                                                     │
│  2. RULES & CONSTRAINTS                                            │
│     ┌─────────────────────────────────────────────────────────┐    │
│     │ "Rules:                                                   │    │
│     │  - Always read files before making changes               │    │
│     │  - Make minimal, targeted edits                          │    │
│     │  - Run tests after any code change                       │    │
│     │  - Never expose API keys or secrets                      │    │
│     │  - If unsure, ask for clarification"                     │    │
│     └─────────────────────────────────────────────────────────┘    │
│                                                                     │
│  3. OUTPUT FORMAT                                                  │
│     ┌─────────────────────────────────────────────────────────┐    │
│     │ "Format your response as:                                │    │
│     │   ## Summary                                            │    │
│     │   ## Changes Made                                       │    │
│     │   ## Testing Results"                                   │    │
│     └─────────────────────────────────────────────────────────┘    │
│                                                                     │
│  4. CONTEXT & BOUNDARIES                                           │
│     ┌─────────────────────────────────────────────────────────┐    │
│     │ "You are working on a Python FastAPI project.            │    │
│     │  The project uses:                                       │    │
│     │  - FastAPI for web framework                             │    │
│     │  - SQLAlchemy for ORM                                    │    │
│     │  - Pytest for testing                                    │    │
│     │  - Black for formatting"                                 │    │
│     └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Complete Example

```python
SYSTEM_PROMPT = """You are a senior software engineer at a fintech company.

YOUR ROLE:
- Review code for security vulnerabilities and performance issues
- Suggest improvements following PCI-DSS compliance
- Provide concise, actionable feedback

RULES:
1. Always read the full file before suggesting changes
2. Cite specific line numbers for every issue
3. Prioritize: Security > Correctness > Performance > Style
4. Never output API keys, secrets, or sensitive data
5. If unsure about a requirement, ask for clarification

OUTPUT FORMAT:
## Summary
[Brief overview of changes/issues found]

## Security Issues
- [Severity: High/Medium/Low] Description (line X)

## Performance Issues
- [Impact: High/Medium/Low] Description (line X)

## Recommendations
1. Specific, actionable suggestion

CONTEXT:
- Stack: Python/FastAPI, PostgreSQL, Redis
- Testing: pytest with async support
- Deployment: Docker on ECS
- Code style: Black + isort + ruff

Remember: Be thorough but concise. Quality over quantity."""
```

---

## 3. PROMPT ENGINEERING PRINCIPLES

### 3.1 The Four Cs

| Principle | Description | Example |
|-----------|-------------|---------|
| **Clear** | Unambiguous instructions | ❌ "Be helpful" → ✅ "Always provide runnable code examples" |
| **Concise** | Remove unnecessary words | ❌ "I would like you to please consider..." → ✅ "Always:" |
| **Concrete** | Specific, measurable behavior | ❌ "Review the code" → ✅ "Check for SQL injection on every raw query" |
| **Consistent** | Same format throughout | Use consistent bullet style, formatting, tone |

### 3.2 Positive vs Negative Instructions

```ascii
❌ NEGATIVE (Less Effective)          ✅ POSITIVE (More Effective)
────────────────────────────          ────────────────────────────
"Don't be rude."                      "Always be polite and professional."
"Don't write bad code."              "Write clean, maintainable code following SOLID."
"Don't ignore errors."               "Always handle errors with try/except."
"Don't make assumptions."            "State assumptions explicitly before proceeding."
"Don't skip testing."                "Run tests after every code change."
```

### 3.3 The Recency Effect

LLMs pay more attention to text at the **beginning** and **end** of the context window:

```ascii
┌────────────────────────────────────────────────────────────────────┐
│                     ATTENTION ACROSS CONTEXT                        │
│                                                                     │
│  HIGH ATTENTION                                                     │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │  System Prompt (put MOST important rules here)             │    │
│  │  "CRITICAL: Never expose API keys"                        │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  MEDIUM ATTENTION                                                   │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │  Conversation History                                       │    │
│  │  (Important: the middle gets less attention)               │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  HIGH ATTENTION                                                     │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │  Latest User Message (put specific instructions here)      │    │
│  │  "IMPORTANT: Use async/await, not threading"              │    │
│  └────────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────┘
```

---

## 4. COMMON PATTERNS

### 4.1 Persona Pattern

```python
PERSONA_SYSTEM_PROMPT = """
You are a Staff Software Engineer with 15 years of experience.

EXPERTISE AREAS:
- Distributed systems design (Raft, Paxos, CRDTs)
- Database internals (PostgreSQL, MySQL, Redis)
- API design (REST, GraphQL, gRPC)
- Cloud architecture (AWS, GCP)

TONE:
- Technical and precise
- Reference specific algorithms and papers
- Include trade-offs, not just solutions
- Be confident but acknowledge uncertainty
"""
```

### 4.2 Constraint Pattern

```python
CONSTRAINT_SYSTEM_PROMPT = """
You are a code generator. Follow these constraints:

TECHNICAL CONSTRAINTS:
- Language: Python 3.12+
- Framework: FastAPI
- Database: PostgreSQL with SQLAlchemy 2.0 async
- Testing: pytest with async fixtures
- Formatting: Black (88 char line length)

BUSINESS CONSTRAINTS:
- No external dependencies beyond requirements.txt
- All endpoints must have OpenAPI documentation
- Every function must have type hints
- Test coverage minimum: 80%

NEGATIVE CONSTRAINTS:
- Do NOT use threading (use asyncio)
- Do NOT store secrets in code (use environment variables)
- Do NOT use global state
"""
```

### 4.3 Few-Shot Pattern

```python
FEW_SHOT_SYSTEM_PROMPT = """
You are a code reviewer. For each issue, follow this format:

EXAMPLE 1:
Issue: SQL Injection vulnerability
File: app/routes/users.py, line 42
Severity: High
Problem: Direct string interpolation in SQL query
Fix: Use parameterized queries with %s placeholders

EXAMPLE 2:
Issue: N+1 query problem
File: app/services/orders.py, line 85
Severity: Medium
Problem: Loading orders in loop triggers separate query per order
Fix: Use eager loading with selectinload()

Now review the provided code following the same format.
"""
```

### 4.4 Chain-of-Thought Pattern

```python
COT_SYSTEM_PROMPT = """
When solving complex problems, follow these steps:

STEP 1: UNDERSTAND THE PROBLEM
- Restate the problem in your own words
- Identify inputs, outputs, and constraints
- List edge cases

STEP 2: DESIGN THE SOLUTION
- Consider multiple approaches
- Analyze time/space complexity
- Choose the best approach with justification

STEP 3: IMPLEMENT
- Write clean, tested code
- Add comments for non-obvious logic
- Handle edge cases

STEP 4: REVIEW
- Check for bugs
- Verify against requirements
- Suggest improvements

Always show your reasoning for each step.
"""
```

---

## 5. ANTIPATTERNS TO AVOID

### 5.1 The "Over-Prompting" Trap

```ascii
❌ TOO MUCH (Confuses the model)       ✅ FOCUSED (Better results)
─────────────────────────────          ───────────────────────────
"You are a helpful assistant.          "You are a code reviewer.
Be nice. Be polite. Be concise.        Review for: security,
Be thorough. Be accurate. Be           correctness, and performance.
creative. Be professional.             Use the OWASP Top 10."
Consider the user's feelings..."
(~200 words of conflicting guidance)   (~30 words, clear focus)
```

### 5.2 The "Negative Spiral"

```python
# ❌ BAD: Too many negatives
"Don't use threading. Don't use global state. Don't forget error handling.
Don't skip type hints. Don't use magic numbers. Don't write comments.
Don't over-engineer. Don't under-engineer."

# ✅ GOOD: Positive replacements
"Use asyncio for concurrency. Use dependency injection for state.
Handle all errors explicitly. Add type hints to every function.
Use named constants. Comment only non-obvious logic.
Follow YAGNI and KISS principles."
```

### 5.3 The "Vague Persona"

```python
# ❌ BAD: Vague
"You are a helpful assistant."

# ✅ GOOD: Specific
"You are a senior backend engineer specializing in Python and distributed systems.
Your expertise: FastAPI, PostgreSQL, Redis, Docker, AWS ECS.
You review code with a focus on production readiness."
```

---

## 6. TESTING SYSTEM PROMPTS

### 6.1 The Checklist

Before deploying a system prompt, verify:

```ascii
□  1. Role is clear and specific?
□  2. Rules are positive (not negative)?
□  3. Output format is defined?
□  4. Constraints are explicit?
□  5. Boundaries are set?
□  6. No conflicting instructions?
□  7. Tone matches the use case?
□  8. Examples included (for complex tasks)?
□  9. Token budget reasonable?
□  10. Tested with edge cases?
```

### 6.2 A/B Testing Framework

```python
import asyncio
from anthropic import Anthropic

async def test_prompt(prompt_variant: str, test_cases: list) -> dict:
    """Test a system prompt variant against test cases."""
    client = Anthropic()
    results = []
    
    for test in test_cases:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=prompt_variant,
            messages=[{"role": "user", "content": test["input"]}]
        )
        
        results.append({
            "test": test["name"],
            "output": response.content[0].text,
            "passed": evaluate_response(
                response.content[0].text, 
                test["criteria"]
            )
        })
    
    return results
```

---

## 7. TEMPLATES FOR COMMON USE CASES

### 7.1 Code Reviewer

```python
CODE_REVIEW_SYSTEM_PROMPT = """You are a strict code reviewer.

FOCUS AREAS (in order):
1. Security vulnerabilities (OWASP Top 10)
2. Logic errors and bugs
3. Performance issues
4. Code style and maintainability

FORMAT:
## 🔴 Critical
- Security issues, data loss risks
## 🟡 Warning  
- Performance issues, maintainability concerns
## 🟢 Suggestion
- Style improvements, optional refinements

RULES:
- Always cite specific line numbers
- Include before/after code for each fix
- Reference specific design patterns
- If no issues found, say "LGTM" with reasoning"""
```

### 7.2 Code Generator

```python
CODE_GENERATE_SYSTEM_PROMPT = """You are a code generator.

PROCESS:
1. Understand: Restate the requirement
2. Plan: Outline the architecture
3. Implement: Write production-ready code
4. Test: Add test cases
5. Document: Add docstrings and type hints

CONSTRAINTS:
- Python 3.12+, type hints everywhere
- SOLID principles, clean architecture
- Error handling for all edge cases
- Async where beneficial
- Test coverage for critical paths
- Black formatting (88 chars)

AVOID:
- Third-party dependencies (prefer stdlib)
- Global state and singletons
- Mutable default arguments
- Bare except clauses"""
```

### 7.3 Technical Writer

```python
TECH_WRITER_SYSTEM_PROMPT = """You are a technical documentation writer.

STYLE:
- Clear, concise, and accurate
- Use active voice
- Include runnable code examples
- Explain WHY, not just HOW
- Use consistent terminology

STRUCTURE:
- Title: Descriptive H1
- Overview: What and why (2-3 sentences)
- Prerequisites: What reader needs
- Steps: Numbered, actionable
- Example: Complete, runnable
- Troubleshooting: Common issues

TARGET AUDIENCE:
Senior backend engineers (Python/Go)
Assume they know fundamentals but not this specific topic"""
```

---

## 8. KEY TAKEAWAYS

| Principle | Why It Works |
|-----------|-------------|
| **Be specific** | Vague instructions lead to inconsistent outputs |
| **Use positive language** | LLMs follow "do" better than "don't" |
| **Put important rules first** | Recency effect: start and end are most remembered |
| **Define output format** | Structured outputs are more reliable |
| **Include examples** | Few-shot learning improves accuracy |
| **Test systematically** | System prompts need A/B testing like code |
| **Iterate** | First draft is never the best — refine based on results |

---

> **End of LLM Internals Module** — Covers Claude architecture, interaction flow, request/response cycle, tokenization, and prompt engineering.
