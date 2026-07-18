# 🐍 Python — Staff-Level Interview Questions

> **Deep-dive into Python's internals, concurrency models, memory management, and production patterns**
> *Designed for Staff/Principal Engineer interviews (10+ years experience)*

---

## 📋 What's Inside

| File | Content |
|------|---------|
| [`INTERVIEW_QUESTIONS.md`](./INTERVIEW_QUESTIONS.md) | 12 in-depth questions covering Python's core internals at staff level |
| [`DJANGO_NOTES.md`](./DJANGO_NOTES.md) | Deep-dive into Django's ORM, request lifecycle, DRF, caching, async, and production patterns |
| [`FASTAPI_NOTES.md`](./FASTAPI_NOTES.md) | Deep-dive into FastAPI's async patterns, Pydantic integration, DI system, WebSockets, and production deployment |

### Topics Covered

- **GIL & Concurrency** — GIL internals, when to use threading vs asyncio vs multiprocessing, subinterpreters
- **Async/Await** — Event loop internals, coroutine protocols, uvloop, structured concurrency
- **Metaclasses & Descriptors** — Class creation protocols, `__init_subclass__`, `__set_name__`, descriptor protocol
- **Memory Management** — CPython allocator, reference cycles, GC generations, `__slots__`
- **Type System** — `Protocol`, `@overload`, `TypeVar` with constraints, variance, `Self`
- **C Extensions** — PyObject, reference counting, `ctypes` vs `Cython` vs `cffi`
- **Data Model** — `__dunder__` protocols, context managers, async generators
- **Import System** — `sys.modules`, `finders`/`loaders`, circular imports, namespace packages
- **Performance** — Profiling strategies, JIT alternatives (PyPy, Numba), GIL-free experiments
- **Production Patterns** — Dependency injection, configuration management, plugin architectures
- **Packaging** — `pyproject.toml`, build systems, ABI compatibility, platform wheels

---

### How to Use

1. **Read each question** and try to answer before looking at the expected answer
2. **Study the code examples** — they demonstrate production-quality patterns
3. **Understand the trade-offs** — staff-level interviews are about why, not what
4. **Run the code snippets** to internalize the concepts

---

> *Built for experienced Python engineers targeting Staff/Principal roles at top-tier companies*
