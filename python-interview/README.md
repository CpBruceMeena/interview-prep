# 🐍 Python — Staff-Level Interview Questions

> **Deep-dive into Python's internals, concurrency models, memory management, and production patterns**
> *Designed for Staff/Principal Engineer interviews (10+ years experience)*

---

## 📋 What's Inside

| File | Content |
|------|---------|
| [`INTERVIEW_QUESTIONS.md`](./INTERVIEW_QUESTIONS.md) | 12 in-depth questions covering Python's core internals at staff level |
| [`MULTITHREADING_NOTES.md`](./MULTITHREADING_NOTES.md) | Threads, the GIL, free-threaded Python (3.13/3.14), subinterpreters and `InterpreterPoolExecutor`, multiprocessing start methods, synchronization patterns, and 16 interview questions |
| [`DJANGO_NOTES.md`](./DJANGO_NOTES.md) | Django 5.2 LTS / 6.0: ORM, transactions, request lifecycle, DRF, migrations, caching, Celery and the 6.0 tasks framework, async Django, production patterns, and 16 interview questions |
| [`FASTAPI_NOTES.md`](./FASTAPI_NOTES.md) | FastAPI with Pydantic v2 and Starlette 1.x: DI and `yield` scopes, lifespan, async pitfalls, security, SQLAlchemy async, WebSockets, deployment, and 13 interview questions |
| [`ASYNCIO_NOTES.md`](./ASYNCIO_NOTES.md) | Comprehensive guide to async/await, event loop internals, coroutines, tasks, streams, and production async patterns |

### Topics Covered

- **GIL & Concurrency** — GIL internals, when to use threading vs asyncio vs multiprocessing, free-threaded Python, subinterpreters (see [`MULTITHREADING_NOTES.md`](./MULTITHREADING_NOTES.md))
- **Async/Await** — Event loop internals, coroutine protocols, uvloop, structured concurrency (see [`ASYNCIO_NOTES.md`](./ASYNCIO_NOTES.md) for the full dedicated guide)
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
