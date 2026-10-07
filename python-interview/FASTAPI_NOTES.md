# ⚡ FastAPI — Staff-Level Notes & Interview Questions

> **Deep-dive into FastAPI's internals, async patterns, Pydantic integration, dependency injection, and production deployment**
> *Current as of October 2026: FastAPI 0.14x, Pydantic 2.x, Starlette 1.x, Python 3.10+. Version-specific behaviour is marked.*

---

## Table of Contents

1. [FastAPI Architecture & Philosophy](#1-fastapi-architecture-philosophy)
2. [Path Operations & Routing](#2-path-operations-routing)
3. [Pydantic Models & Validation](#3-pydantic-models-validation)
4. [Dependency Injection System](#4-dependency-injection-system)
5. [Async Support & Concurrency](#5-async-support-concurrency)
6. [Middleware & Lifecycle Events](#6-middleware-lifecycle-events)
7. [Security & Authentication](#7-security-authentication)
8. [Database Integration & Sessions](#8-database-integration-sessions)
9. [Background Tasks & WebSockets](#9-background-tasks-websockets)
10. [Testing FastAPI Applications](#10-testing-fastapi-applications)
11. [Performance Optimization](#11-performance-optimization)
12. [Production Deployment](#12-production-deployment)
13. [OpenAPI & Documentation Customization](#13-openapi-documentation-customization)
14. [FastAPI Design Patterns](#14-fastapi-design-patterns)
15. [FastAPI Interview Questions](#15-fastapi-interview-questions)

---

## 1. FastAPI Architecture & Philosophy

### What Makes FastAPI Different

!!! tip "30-second answer"
    FastAPI is a thin layer over **Starlette** (ASGI routing, requests/responses, middleware, websockets) and **Pydantic v2** (validation and serialisation in Rust via `pydantic-core`). It reads your type hints once at startup to build three things: a validator per endpoint, a dependency-injection graph, and the OpenAPI schema. It's "fast" because it's async and does validation in compiled code. Your own handler code and database usually dominate latency, and one blocking call inside an `async def` stalls the whole worker.

```python
# FastAPI is built on three pillars:
# 1. Starlette (ASGI framework) — async request handling, WebSocket support
# 2. Pydantic (data validation) — type-driven validation, serialization
# 3. OpenAPI (API documentation) — auto-generated docs from Python types

# ── Minimal Example ─────────────────────────────────────────
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="My API", version="1.0.0")

class Item(BaseModel):
    name: str
    price: float
    is_offer: bool = False

@app.get("/")
async def read_root():
    return {"message": "Hello World"}

@app.post("/items/")
async def create_item(item: Item):
    return {"item_name": item.name, "item_price": item.price}
```

### ASGI vs WSGI — The Key Difference

```python
# ── WSGI (Flask, classic Django) ───────────────────────────
# app(environ, start_response) -> iterable of bytes. One request per
# worker THREAD for its whole duration; no protocol for websockets.
# Request → WSGI Server → WSGI Handler → View → Response

# ── ASGI (FastAPI/Starlette, Django under ASGI) ────────────
# async app(scope, receive, send). One event loop multiplexes many
# connections; long-lived connections (WebSocket, SSE, streaming) are
# first-class. HTTP/2 depends on the SERVER (Hypercorn/Granian yes,
# Uvicorn is HTTP/1.1; usually the load balancer terminates HTTP/2 anyway).
# Request → ASGI Server → ASGI App (scope, receive, send) → Response

# The ASGI protocol:
# async def app(scope: dict, receive: callable, send: callable):
#     """
#     scope: Connection metadata (method, path, headers, etc.)
#     receive: Async callable to receive events (HTTP request body, WebSocket messages)
#     send: Async callable to send events (HTTP response, WebSocket messages)
#     """
#     assert scope['type'] == 'http'
#     body = await receive()
#     await send({
#         'type': 'http.response.start',
#         'status': 200,
#         'headers': [(b'content-type', b'application/json')],
#     })
#     await send({
#         'type': 'http.response.body',
#         'body': json.dumps({"hello": "world"}).encode(),
#     })
```

### Starlette Foundation

```python
# FastAPI is a thin layer on top of Starlette.
# Everything Starlette does, FastAPI inherits:

from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles

# Starlette provides:
# - ASGI request/response handling, routing
# - WebSocket support
# - Background tasks
# - Middleware stack
# - Static file serving
# - Streaming responses (SSE is built on these)
# - Lifespan (startup/shutdown). Starlette 1.0 (March 2026) removed the
#   old on_startup/on_shutdown/on_event APIs; FastAPI keeps a deprecated
#   @app.on_event shim, but new code uses lifespan.

# FastAPI adds:
# - OpenAPI/Swagger auto-generation
# - Pydantic integration (request/response models)
# - Dependency injection system
# - Automatic validation
# - Better developer experience (type hints → docs)
```

---

## 2. Path Operations & Routing

### Path Operation Decorators

```python
from typing import Annotated
from fastapi import FastAPI, Path, Query, Body

app = FastAPI()

# ── All HTTP methods ───────────────────────────────────────
# @app.get / .post / .put / .patch / .delete / .options / .head / .trace
# and @app.api_route(path, methods=[...]) for several at once.

# ── Path parameters with validation (Annotated style, recommended) ──
@app.get("/items/{item_id}")
async def read_item(
    item_id: Annotated[int, Path(ge=1, le=1000, description="The item ID")],
    q: Annotated[str | None, Query(max_length=50, pattern="^[a-zA-Z]+$")] = None,
):
    return {"item_id": item_id, "q": q}
# Annotated keeps the real default as a normal Python default, so the
# function is still callable outside FastAPI, and one alias like
# ItemId = Annotated[int, Path(ge=1)] can be reused across endpoints.
# The older form `item_id: int = Path(..., ge=1)` still works.

# ── Route ordering matters! ────────────────────────────────
# Starlette matches routes in order of declaration; first match wins.
# More specific routes must come before parameterized ones:

@app.get("/users/me")           # Must come first
async def get_current_user():
    return {"user": "current"}

@app.get("/users/{user_id}")    # Parameterized route
async def get_user(user_id: int):
    return {"user_id": user_id}

# ── Multiple path/query parameters ─────────────────────────
@app.get("/items/{item_id}/reviews/{review_id}")
async def get_review(
    item_id: int,
    review_id: int,
    include_details: bool = False,                     # plain default = query param
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 10,
):
    skip = (page - 1) * size
    # ...
```

### Router Organization

```python
# ── APIRouter for modular organization ─────────────────────
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(
    prefix="/items",
    tags=["items"],
    dependencies=[Depends(get_db)],  # Router-level dependencies
    responses={404: {"description": "Not found"}},
)

@router.get("/")
async def list_items(db=Depends(get_db)):
    return await db.fetch_all("SELECT * FROM items")

@router.post("/")
async def create_item(item: Item, db=Depends(get_db)):
    # Router prefix means path is /items/
    return await db.execute("INSERT INTO items ...", item.model_dump())  # .dict() is the deprecated v1 name

# ── Include routers in main app ────────────────────────────
app.include_router(router)
app.include_router(admin_router, prefix="/admin")
app.include_router(api_router, prefix="/api/v1")

# ── Nested routers ─────────────────────────────────────────
# Prefixes concatenate: app prefix + user_router prefix + item_router prefix.
user_router = APIRouter(prefix="/users")
item_router = APIRouter(prefix="/{user_id}/items")   # path params can live in prefixes

@user_router.get("/{user_id}")
async def get_user(user_id: int): ...                 # GET /api/v1/users/{user_id}

@item_router.get("/{item_id}")
async def get_item(user_id: int, item_id: int): ...   # GET /api/v1/users/{user_id}/items/{item_id}

user_router.include_router(item_router)   # include children BEFORE including the parent in the app
app.include_router(user_router, prefix="/api/v1")
```

---

## 3. Pydantic Models & Validation

### Model Definition & Advanced Features

!!! tip "Pydantic v2 in one paragraph"
    Validation and serialisation run in `pydantic-core` (Rust). The class definition is compiled once into a core schema, so `model_validate`/`model_dump` are typically several times to 10×+ faster than v1. The API renames to know: `.dict()`→`model_dump()`, `.json()`→`model_dump_json()`, `parse_obj`→`model_validate`, `class Config`→`model_config = ConfigDict(...)`, `orm_mode`→`from_attributes`, `@validator`→`@field_validator`, `@root_validator`→`@model_validator`, `__root__`→`RootModel`. FastAPI 0.126 dropped Pydantic v1 and 0.128 removed the temporary `pydantic.v1` compatibility (around the turn of 2026), so current FastAPI is v2-only. Pydantic v1 itself doesn't support Python 3.14.

```python
from datetime import datetime, UTC
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import (BaseModel, ConfigDict, Field, computed_field,
                      field_validator, model_validator)

class Item(BaseModel):
    model_config = ConfigDict(
        frozen=True,            # immutable; hashable only if every field is hashable
        from_attributes=True,   # validate from ORM objects (was orm_mode)
        extra="forbid",         # reject unknown fields → 422 (default "ignore")
        str_strip_whitespace=True,
        json_schema_extra={"examples": [{"name": "Foo", "price": "42.00"}]},
    )

    name: Annotated[str, Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9 ]+$")]
    price: Annotated[Decimal, Field(gt=0, le=1_000_000, decimal_places=2)]   # money: Decimal, not float
    tax_rate: Annotated[Decimal, Field(ge=0, le=1)] | None = None
    tags: tuple[str, ...] = ()                     # tuple keeps a frozen model hashable
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # utcnow() is deprecated

    @field_validator("name")
    @classmethod
    def not_reserved(cls, v: str) -> str:
        if v.lower() in {"admin", "null"}:
            raise ValueError("reserved name")       # ValueError → 422 with field location
        return v

    @model_validator(mode="after")                  # cross-field, runs on the built model
    def tax_needs_price(self):
        if self.tax_rate is not None and self.price < 1:
            raise ValueError("tax_rate not allowed below 1.00")
        return self

class Order(BaseModel):
    items: list[Item]
    discount: Annotated[Decimal, Field(ge=0, le=1)] = Decimal("0")

    @computed_field                                 # included in model_dump() and the schema
    @property
    def total(self) -> Decimal:
        subtotal = sum((i.price for i in self.items), Decimal("0"))
        return (subtotal * (1 - self.discount)).quantize(Decimal("0.01"))

# ── Discriminated unions: O(1) dispatch on a tag field ─────
class Cat(BaseModel):
    pet_type: Literal["cat"]
    meows: int

class Dog(BaseModel):
    pet_type: Literal["dog"]
    barks: int

Pet = Annotated[Cat | Dog, Field(discriminator="pet_type")]

class Zoo(BaseModel):
    pets: list[Pet]

Zoo(pets=[{"pet_type": "cat", "meows": 3}, {"pet_type": "dog", "barks": 2}])
# Without a discriminator Pydantic tries each member ("smart" mode) and
# reports errors for all of them. A callable Discriminator(fn) also
# works, but then every member must be tagged: Annotated[Cat, Tag("cat")].

# ── Strict vs lax ──────────────────────────────────────────
# Lax (default): "42" → 42 for int fields, "true" → True for bool.
# Strict: ConfigDict(strict=True) or Annotated[int, Strict()] rejects
# type mismatches. Useful for internal contracts where "42" means a bug.
```

### Serialization & Deserialization

```python
from datetime import datetime, UTC
from pydantic import BaseModel, RootModel, computed_field, field_serializer

class Event(BaseModel):
    name: str
    timestamp: datetime          # aware datetimes already serialise as ISO 8601 with offset

    @field_serializer("timestamp")
    def as_utc_z(self, dt: datetime) -> str:
        # Normalise to UTC and use "Z"; appending "Z" to dt.isoformat() on an
        # aware datetime would produce an invalid "+00:00Z"
        return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")

# ── Root models (v1's __root__) ────────────────────────────
class Tags(RootModel[list[str]]):
    pass

Tags(["a", "b"]).model_dump()          # ['a', 'b']

# ── Generic models ─────────────────────────────────────────
class Page[T](BaseModel):              # PEP 695 syntax (3.12+); Generic[T] also works
    items: list[T]
    total: int
    page: int
    size: int

    @computed_field
    @property
    def pages(self) -> int:
        return (self.total + self.size - 1) // self.size

# @app.get("/items/", response_model=Page[Item])
# Page[Item] is a distinct model with its own OpenAPI schema ("Page_Item_").

# ── Performance tips ───────────────────────────────────────
# - Validate JSON directly: Model.model_validate_json(raw_bytes) skips the
#   intermediate dict and is the fastest path.
# - For non-model types, build a TypeAdapter(list[Item]) ONCE at import time;
#   creating one per request rebuilds the schema.
# - model_construct() skips validation for trusted data (e.g. from your own DB).
```

---

## 4. Dependency Injection System

!!! tip "30-second answer"
    A dependency is any callable whose parameters FastAPI can resolve: request data, or other dependencies. At startup FastAPI builds a graph per endpoint. Per request it resolves the graph, **caches each dependency's result for that request** (unless `use_cache=False`), runs sync dependencies in the thread pool, and treats `yield` dependencies as context managers. A `yield` dependency's teardown runs **after the response is sent** by default; pass `Depends(scope="function")` (0.12x+) to close it before the response goes out. Overrides via `app.dependency_overrides` make the same graph testable.

### Core Concepts

```python
from typing import Annotated
from fastapi import Depends, FastAPI, HTTPException, Query, status

app = FastAPI()

# ── yield dependency: setup, hand over, teardown ───────────
async def get_db():
    async with async_session() as session:   # closes the session on exit
        yield session

# ── Dependency with its own parameters (query params here) ─
def pagination(
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> tuple[int, int]:
    return (page - 1) * size, size

# ── Reusable Annotated aliases: the idiomatic style ───────
DB = Annotated[AsyncSession, Depends(get_db)]
Page = Annotated[tuple[int, int], Depends(pagination)]

@app.get("/items/")
async def list_items(db: DB, page: Page):
    offset, limit = page
    result = await db.execute(select(ItemRow).offset(offset).limit(limit))
    return result.scalars().all()
```

### Advanced DI Patterns

```python
from fastapi import Request, Security
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# ── Class instance as a parameterised dependency ───────────
class RequireRole:
    def __init__(self, role: str):          # configured once, at import time
        self.role = role

    async def __call__(self, user: Annotated[User, Depends(get_current_user)]) -> User:
        if self.role not in user.roles:      # called per request
            raise HTTPException(status.HTTP_403_FORBIDDEN)
        return user

@app.get("/admin/")
async def admin_endpoint(user: Annotated[User, Depends(RequireRole("admin"))]):
    return {"admin": user.email}

# ── Sub-dependencies (a chain) ─────────────────────────────
async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], db: DB) -> User:
    payload = decode_jwt(token)                 # raises 401 on failure
    user = await db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    return user

async def get_active_user(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Inactive user")
    return user

CurrentUser = Annotated[User, Depends(get_active_user)]

@app.get("/users/me")
async def read_me(user: CurrentUser):
    return user

# ── Transactions: commit in the endpoint/service, not after yield ─
# With the default scope="request", code after `yield` runs AFTER the
# response is sent. A dependency that commits there can return 200 to
# the client and then fail to commit. Either commit explicitly before
# returning, or declare the dependency with scope="function".
async def transactional(db: DB):
    try:
        yield db
        await db.commit()               # runs before the response with scope="function"
    except Exception:
        await db.rollback()
        raise                           # always re-raise from a yield dependency

Tx = Annotated[AsyncSession, Depends(transactional, scope="function")]

@app.post("/items/", status_code=201)
async def create_item(payload: ItemIn, db: Tx) -> ItemOut:
    row = ItemRow(**payload.model_dump())   # ORM row, not the Pydantic model
    db.add(row)
    await db.flush()                        # get the PK before commit
    return ItemOut.model_validate(row)      # committed before the response is sent

# ── App- and router-level dependencies (run, value discarded) ─
app = FastAPI(dependencies=[Depends(verify_api_key)])
router = APIRouter(dependencies=[Depends(rate_limiter)])
```

### DI Lifecycle & Caching

| Behaviour | Detail |
|---|---|
| Per-request cache | The same dependency used in several places in one request is called **once**; all users get the same value. Opt out with `Depends(dep, use_cache=False)` |
| Not a singleton | Nothing is cached *across* requests. For process-wide objects (engine, HTTP client, settings), create them in **lifespan** and read them from `request.app.state`, or use `@lru_cache` on a getter |
| Sync dependencies | Run in the thread pool, like sync endpoints. A trivial sync dependency still costs a thread hop, so make cheap ones `async def` |
| `yield` teardown | Default `scope="request"`: after the response is sent. `scope="function"`: right after the endpoint returns, before the response. Exceptions raised in the endpoint are re-thrown at the `yield`; **re-raise** them if you catch them, or they vanish into a 500 with no log |
| `Depends(SomeClass)` | Calls `SomeClass(...)` per request, resolving its `__init__` params as dependencies |
| `Depends(instance)` | Calls `instance.__call__(...)` per request; the instance itself is shared |
| Overrides | `app.dependency_overrides[real] = fake` swaps any node in the graph, sub-dependencies included |

---

## 5. Async Support & Concurrency

### The Async View Model

```python
import asyncio
from fastapi import FastAPI, Request

app = FastAPI()

# ── Path operations can be sync or async ───────────────────
@app.get("/sync")
def sync_endpoint():
    """Runs in a thread pool — doesn't block the event loop"""
    return {"message": "sync"}

@app.get("/async")
async def async_endpoint():
    """Runs on the event loop — use for I/O-bound operations"""
    await asyncio.sleep(0.1)
    return {"message": "async"}

# ── The rule ───────────────────────────────────────────────
# async def → only if EVERYTHING it awaits is non-blocking (asyncpg,
#             SQLAlchemy async, httpx.AsyncClient, redis.asyncio).
# def       → if it calls ANY blocking library (requests, psycopg2,
#             boto3, sync SQLAlchemy). FastAPI runs it in a worker thread.
# Getting this wrong in the async direction is the #1 FastAPI outage:
# one requests.get() inside async def freezes every request on that worker.

# ── The thread pool ────────────────────────────────────────
# Sync endpoints and sync dependencies run via anyio.to_thread.run_sync
# (Starlette's run_in_threadpool). The default limiter allows 40
# concurrent threads per process; once they're busy, further sync
# requests queue even though the event loop is idle. Raise it at startup
# if you're sure the downstream (e.g. DB pool) can take it:
#   anyio.to_thread.current_default_thread_limiter().total_tokens = 100

# ── CPU-bound work ─────────────────────────────────────────
# Threads don't help pure-Python CPU work (GIL). Use a process pool
# created in lifespan, or better, a task queue so the API stays responsive.
from concurrent.futures import ProcessPoolExecutor
import asyncio

@app.post("/process")
async def process_data(data: dict, request: Request):
    pool: ProcessPoolExecutor = request.app.state.cpu_pool    # created in lifespan
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(pool, cpu_intensive_task, data)
    return {"result": result}
```

### Concurrent Processing Patterns

```python
# ── Parallel API calls ─────────────────────────────────────
import httpx
import asyncio

@app.get("/dashboard")
async def get_dashboard():
    """Fetch multiple sources concurrently.
    In production, create ONE AsyncClient in lifespan and reuse it:
    a client per request throws away connection pooling and TLS sessions."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(2.0)) as client:
        # Create tasks
        user_task = client.get("https://api.example.com/user")
        orders_task = client.get("https://api.example.com/orders")
        recommendations_task = client.get("https://api.example.com/recommendations")
        
        # Run concurrently
        user_resp, orders_resp, recs_resp = await asyncio.gather(
            user_task, orders_task, recommendations_task,
            return_exceptions=True,
        )
        
        return {
            "user": user_resp.json() if not isinstance(user_resp, Exception) else None,
            "orders": orders_resp.json() if not isinstance(orders_resp, Exception) else None,
            "recommendations": recs_resp.json() if not isinstance(recs_resp, Exception) else None,
        }

# ── Rate-limited concurrent calls ──────────────────────────
import asyncio

class ConcurrencyLimiter:
    """Limits concurrent API calls with a semaphore"""
    
    def __init__(self, max_concurrent: int = 5):
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    async def limited_call(self, client: httpx.AsyncClient, url: str):
        async with self.semaphore:
            resp = await client.get(url)
            return resp.json()
    
    async def fetch_all(self, urls: list[str]):
        async with httpx.AsyncClient() as client:
            tasks = [self.limited_call(client, url) for url in urls]
            return await asyncio.gather(*tasks)

# ── Streaming responses ────────────────────────────────────
from fastapi.responses import StreamingResponse

async def generate_large_csv():
    """Stream a large CSV without loading into memory"""
    yield "id,name,email\n"
    async for batch in fetch_user_batches():
        for user in batch:
            yield f"{user.id},{user.name},{user.email}\n"

@app.get("/users/export")
async def export_users():
    return StreamingResponse(
        generate_large_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"},
    )
```

### Avoiding Common Pitfalls

```python
# ── Pitfall 1: Blocking the event loop ────────────────────
@app.get("/wrong")
async def wrong():
    """🔴 This BLOCKS the event loop for 5 seconds"""
    import time
    time.sleep(5)  # Never use time.sleep() in async views!
    return {"message": "after 5 seconds"}

@app.get("/right")
async def right():
    """✅ This properly yields control"""
    await asyncio.sleep(5)
    return {"message": "after 5 seconds"}

# ── Pitfall 2: In-process state ────────────────────────────
counter = {"n": 0}

@app.post("/hit")
async def hit():
    counter["n"] += 1          # No await in between: atomic on the event loop
    return counter             # BUT each worker process has its own copy,
                               # and it's lost on restart. Use Redis/DB.

# Where races DO appear in async code: read, then await, then write.
@app.post("/withdraw")
async def withdraw(amount: int):
    balance = await get_balance()          # other requests run during awaits...
    await set_balance(balance - amount)    # ...so this is a lost update.
    # Fix in the data store (UPDATE ... SET balance = balance - $1 WHERE
    # balance >= $1), not with an asyncio.Lock, which only covers one process.
    # Sync (def) endpoints run in threads, so there module state needs a
    # threading.Lock as well.

# ── Pitfall 3: Database connections ────────────────────────
# Create engines/pools ONCE (lifespan), never per request. Pool size is
# per process: workers × pool_size must fit under the DB's max_connections.

# ── Pitfall 4: Fire-and-forget tasks ───────────────────────
# asyncio.create_task(coro()) without keeping a reference can be
# garbage-collected mid-flight, and its exceptions are never seen. Keep
# references (a set + add_done_callback(discard)), use BackgroundTasks,
# or a task queue.
```

---

## 6. Middleware & Lifecycle Events

### Custom Middleware

!!! warning "Order and `BaseHTTPMiddleware`"
    - `app.add_middleware()` **wraps** the current stack, so the **last one added is the outermost** (first to see the request). Put CORS outermost, so error responses also get CORS headers, and put cheap rejections (trusted host, rate limit) near the outside.
    - `BaseHTTPMiddleware` (the `dispatch(request, call_next)` style) is convenient but costs extra per request and buffers the plumbing between layers. For hot paths, or anything that touches streaming responses, write **pure ASGI middleware** (below). Starlette's own docs recommend that for performance-sensitive middleware.

```python
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
import time
import logging

logger = logging.getLogger(__name__)

# ── Timing middleware ──────────────────────────────────────
class TimingMiddleware(BaseHTTPMiddleware):
    """Measures and logs request duration"""
    
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        
        response = await call_next(request)
        
        duration = time.perf_counter() - start
        response.headers["X-Request-Duration"] = f"{duration:.4f}s"
        
        if duration > 1.0:
            logger.warning(
                "Slow request: %s %s took %.4fs",
                request.method, request.url.path, duration,
            )
        
        return response

# ── Request ID middleware ─────────────────────────────────
import uuid

class RequestIDMiddleware:
    """Pure ASGI middleware: no BaseHTTPMiddleware overhead, works with
    streaming responses, sets a contextvar for logging."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        incoming = headers.get(b"x-request-id", b"").decode()
        # Only trust a well-formed ID from your own edge; otherwise mint one
        request_id = incoming if 8 <= len(incoming) <= 64 else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id   # request.state.request_id
        token = request_id_ctx.set(request_id)                     # a ContextVar for log records

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_ctx.reset(token)

# ── CORS middleware ────────────────────────────────────────
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://myfrontend.com"],  # with credentials, never "*"
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# CORS is enforced by BROWSERS only; it is not an auth mechanism.

# ── TrustedHost middleware ─────────────────────────────────
from fastapi.middleware.trustedhost import TrustedHostMiddleware

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["example.com", "*.example.com"],
)

# ── GZip middleware ────────────────────────────────────────
from fastapi.middleware.gzip import GZipMiddleware

app.add_middleware(GZipMiddleware, minimum_size=1000)

# ── Register middleware (last added = outermost) ───────────
app.add_middleware(TimingMiddleware)
app.add_middleware(RequestIDMiddleware)   # outermost of these two: ID exists before timing logs
```

### Lifecycle Events

```python
# ── Lifespan: the only startup/shutdown API to use ─────────
# Added in FastAPI 0.93 (2023). @app.on_event("startup"/"shutdown") is
# deprecated, and Starlette 1.0 (March 2026) removed its own on_startup/
# on_shutdown/on_event. Pick lifespan; don't mix it with on_event handlers.
from contextlib import asynccontextmanager
from typing import TypedDict
import httpx

class State(TypedDict):
    http: httpx.AsyncClient
    engine: AsyncEngine

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: runs once per WORKER PROCESS, before it accepts traffic.
    # If it raises, the worker fails to start (fail fast on bad config).
    engine = create_async_engine(settings.database_url, pool_size=10, pool_pre_ping=True)
    http = httpx.AsyncClient(timeout=5)
    try:
        # Yielding a dict exposes it as request.state.<key> in every request
        # (Starlette "lifespan state"); app.state.x = ... also works.
        yield State(http=http, engine=engine)
    finally:
        # Shutdown: runs after the server stops accepting connections and
        # in-flight requests finish (or the graceful timeout expires).
        await http.aclose()
        await engine.dispose()

app = FastAPI(lifespan=lifespan)

@app.get("/health/ready")
async def ready(request: Request):
    async with request.state.engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok"}
# Keep /health/live dependency-free: a DB outage should take pods out of
# rotation (readiness), not restart them all (liveness).
```

**Probe next:** with 4 workers, lifespan runs 4 times, so you get 4 pools and 4 copies of an ML model in memory. Size the DB pool per process. For big models, load before forking (Gunicorn `preload_app`) or run one larger process per container. `TestClient` only runs lifespan when used as a context manager (`with TestClient(app) as c:`).

---

## 7. Security & Authentication

### OAuth2 with JWT

```python
from datetime import datetime, timedelta, UTC
from typing import Annotated

import jwt                                    # PyJWT; python-jose is unmaintained
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash               # Argon2 by default; passlib is unmaintained
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash("dummy-password")

# Secret comes from config. secrets.token_urlsafe() at import time would
# give every worker a different key and log everyone out on each deploy.
SECRET_KEY = settings.jwt_secret
ALGORITHM = "HS256"            # RS256/EdDSA when other services verify tokens
ACCESS_TOKEN_TTL = timedelta(minutes=15)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def create_access_token(user_id: int, scopes: list[str]) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),   # PyJWT 2.10+ rejects a non-string "sub"
        "scopes": scopes,
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL,
        "iss": "https://auth.example.com",
        "aud": "orders-api",
    }
    return jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)

async def authenticate_user(db, username: str, password: str):
    user = await get_user_by_email(db, username)
    if user is None:
        password_hash.verify(password, DUMMY_HASH)   # same timing for unknown users
        return None
    if not password_hash.verify(password, user.hashed_password):
        return None
    return user

async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], db: DB) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, SECRET_KEY,
            algorithms=[ALGORITHM],        # pin it: never trust the token's "alg" header
            audience="orders-api", issuer="https://auth.example.com",
        )
    except InvalidTokenError:              # bad signature, expired, wrong aud/iss...
        raise unauthorized
    user = await db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise unauthorized
    return user

@app.post("/token")
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DB):
    user = await authenticate_user(db, form.username, form.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    return {"access_token": create_access_token(user.id, user.scopes), "token_type": "bearer"}

@app.get("/users/me")
async def read_users_me(user: Annotated[User, Depends(get_current_user)]):
    return user
```

**What interviewers probe on JWTs:** a JWT can't be revoked before `exp`. Keep access tokens short-lived (5-15 min), use rotating refresh tokens stored server-side, and keep a denylist (by `jti`) only if you must kill sessions instantly. Don't put secrets or PII in claims: they are signed, not encrypted. In most companies the API **verifies** tokens issued by an identity provider (Auth0, Cognito, Keycloak, Entra) against its JWKS, and doesn't mint them itself.

### API Key Authentication

```python
import hashlib
from dataclasses import dataclass
from fastapi import Security
from fastapi.security import APIKeyHeader

# auto_error=False: a missing header returns None instead of an immediate
# 403, so the dependency decides (and can fall back to another scheme).
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
# Avoid API keys in query strings: they end up in access logs and browser history.

@dataclass
class APIKeyData:
    key_id: str
    user_id: str
    scopes: list[str]
    rate_limit: int  # requests per minute

async def verify_api_key(api_key: Annotated[str | None, Security(api_key_header)]) -> APIKeyData:
    if not api_key:
        raise HTTPException(status_code=401, detail="API key required")
    # Store only a hash of each key, and look it up by that hash
    digest = hashlib.sha256(api_key.encode()).hexdigest()
    key_data = await get_api_key_by_hash(digest)
    if key_data is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return key_data

def require_scope(required: str):          # plain def: Depends() needs the inner function
    async def checker(key: Annotated[APIKeyData, Depends(verify_api_key)]) -> APIKeyData:
        if required not in key.scopes:
            raise HTTPException(status_code=403, detail=f"Scope '{required}' required")
        return key
    return checker

# @app.get("/admin/data")
# async def admin_data(key: Annotated[APIKeyData, Depends(require_scope("admin:read"))]): ...
```

---

## 8. Database Integration & Sessions

### SQLAlchemy 2.0 Async

```python
from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker, AsyncAttrs
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import select, text

# ── Engine & session setup ─────────────────────────────────
DATABASE_URL = "postgresql+asyncpg://user:pass@localhost/db"
engine = create_async_engine(          # create in lifespan in real apps
    DATABASE_URL,
    echo=False,           # echo=True logs every statement: dev only
    pool_size=10,         # PER PROCESS: workers x (pool_size + max_overflow) <= DB limit
    max_overflow=5,
    pool_timeout=5,       # fail fast instead of queueing requests for 30 s
    pool_pre_ping=True,   # check liveness on checkout (one round trip)
    pool_recycle=1800,    # recycle before LB/DB idle timeouts kill connections
)
# expire_on_commit=False: after commit, attributes stay loaded. With async
# you can't lazy-load on attribute access (it would need an await), so
# expired attributes would raise MissingGreenlet.
async_session = async_sessionmaker(engine, expire_on_commit=False)

class Base(AsyncAttrs, DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    name: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True)

# ── Dependency for DB session ──────────────────────────────
async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:   # closes (and rolls back if uncommitted) on exit
        yield session

# ── CRUD operations ────────────────────────────────────────
from sqlalchemy import select
from typing import Annotated

db_dep = Annotated[AsyncSession, Depends(get_db)]

class UserRepository:
    """Repository for queries. It doesn't commit: the caller (service or
    unit of work) owns the transaction, so two repo calls can share one."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)
    
    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()
    
    async def list_active(self, after_id: int = 0, limit: int = 20) -> list[User]:
        # Keyset pagination: stable and O(limit) at any depth, unlike OFFSET
        result = await self.session.scalars(
            select(User)
            .where(User.is_active.is_(True), User.id > after_id)
            .order_by(User.id)
            .limit(limit)
        )
        return list(result)

    async def add(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()      # INSERT now, so user.id is populated
        return user

    async def delete(self, user: User) -> None:
        await self.session.delete(user)

# Relationships: async SQLAlchemy can't lazy-load. Eager-load what the
# response needs, e.g. select(User).options(selectinload(User.orders)),
# or use AsyncAttrs: `await user.awaitable_attrs.orders`.

@app.get("/users/{user_id}", response_model=UserOut)   # never return ORM rows unfiltered
async def get_user(
    user_id: int,
    db: db_dep,
):
    repo = UserRepository(db)
    user = await repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

# ── Raw SQL with connection pooling ────────────────────────
from asyncpg import Pool, create_pool

class DatabaseService:
    """Direct asyncpg connection pool for raw SQL"""
    
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: Pool | None = None
    
    async def connect(self):
        self.pool = await create_pool(self.dsn, min_size=5, max_size=20)
    
    async def disconnect(self):
        if self.pool:
            await self.pool.close()
    
    async def fetch_all(self, query: str, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)
    
    async def execute(self, query: str, *args):
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)

# ── Transaction management ─────────────────────────────────
# See §4: commit before the response is sent, either explicitly in the
# service (`async with session.begin(): ...`) or with a
# Depends(..., scope="function") dependency.
```

### Redis Integration

```python
import json
import redis.asyncio as redis
from fastapi import Request

class CacheService:
    def __init__(self, url: str):
        # from_url() is synchronous: it builds a client and a lazy pool,
        # and connects on first command. Don't await it.
        self.redis = redis.from_url(url, max_connections=50, decode_responses=True)

    async def close(self):
        await self.redis.aclose()          # close() is deprecated in redis-py 5

    async def get_or_compute(self, key: str, compute_fn, ttl: int = 300):
        cached = await self.redis.get(key)
        if cached is not None:             # "" or "0" are valid cached values
            return json.loads(cached)
        value = await compute_fn()
        await self.redis.set(key, json.dumps(value), ex=ttl)
        return value

# Created in lifespan: app.state.cache = CacheService(settings.redis_url)
def get_cache(request: Request) -> CacheService:
    return request.app.state.cache

Cache = Annotated[CacheService, Depends(get_cache)]
```

---

## 9. Background Tasks & WebSockets

### Background Tasks

```python
from fastapi import BackgroundTasks, FastAPI

app = FastAPI()

# ── Simple background task ─────────────────────────────────
def write_log(message: str):
    with open("log.txt", "a") as f:
        f.write(f"{message}\n")

@app.post("/send-email")
async def send_email(
    email: str,
    background_tasks: BackgroundTasks,
):
    """
    Returns immediately — email is sent in background.
    Background tasks run after the response is sent.
    """
    background_tasks.add_task(send_email_task, email)
    return {"message": "Email queued"}

# ── Background tasks and DB sessions ───────────────────────
# Depends() does NOT work in task functions; they're plain callables.
# Don't hand them the request's session either: it belongs to the
# request's dependency lifecycle. Open a fresh session inside the task.
async def process_upload(file_id: str):
    async with async_session() as db, db.begin():
        await update_file_status(db, file_id, "completed")

@app.post("/upload", status_code=202)
async def upload_file(file: UploadFile, background_tasks: BackgroundTasks, db: db_dep):
    file_id = str(uuid.uuid4())
    await save_file_metadata(db, file_id, file.filename)
    await db.commit()                     # commit BEFORE the task can look for the row
    background_tasks.add_task(process_upload, file_id)
    return {"file_id": file_id}

# How BackgroundTasks run: in the same process, after the response body
# is sent, on the same event loop (sync functions go to the thread pool).
# Not durable: a deploy, crash or OOM loses them, and nothing retries.

# ── Task queue for heavy work ──────────────────────────────
# BackgroundTasks are for LIGHT work only.
# For heavy work, use Celery/Huey/ARQ:

@app.post("/heavy-task")
async def heavy_task(data: dict):
    task = heavy_processing.delay(data)
    return {"task_id": task.id, "status": "queued"}

@app.get("/task-status/{task_id}")
async def get_task_status(task_id: str):
    task = heavy_processing.AsyncResult(task_id)
    return {"status": task.status, "result": task.result}
```

### WebSocket Support

```python
from fastapi import WebSocket, WebSocketDisconnect, WebSocketException
from fastapi.responses import HTMLResponse
from typing import Set
import json

# ── Simple WebSocket ──────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        logger.info("Client disconnected")

# ── WebSocket with auth ────────────────────────────────────
# Browsers can't set an Authorization header on a WebSocket. Options: a
# cookie session, a short-lived single-use ticket in the query string
# (it ends up in access logs, so make it expire in seconds), or an auth
# message as the first frame after accept.
@app.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket, ticket: str):
    user = await redeem_ws_ticket(ticket)      # single use, ~30 s TTL
    if not user:
        # Closing before accept() rejects the handshake (HTTP 403)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    await websocket.accept()
    await websocket.send_json({"type": "connected", "user": user.email})
    
    try:
        while True:
            data = await websocket.receive_json()
            # Process message
            response = await process_message(user, data)
            await websocket.send_json(response)
    except WebSocketDisconnect:
        await handle_disconnect(user)

# ── Connection manager pattern ────────────────────────────
class ConnectionManager:
    """Manages active WebSocket connections"""
    
    def __init__(self):
        self.active_connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()
    
    async def connect(self, room: str, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            if room not in self.active_connections:
                self.active_connections[room] = set()
            self.active_connections[room].add(websocket)
    
    async def disconnect(self, room: str, websocket: WebSocket):
        async with self._lock:
            conns = self.active_connections.get(room)
            if conns is not None:
                conns.discard(websocket)
                if not conns:
                    del self.active_connections[room]
    
    async def broadcast(self, room: str, message: dict):
        """Send to every client in a room, concurrently, WITHOUT holding
        the lock during I/O (one slow client must not stall the room)."""
        async with self._lock:
            targets = list(self.active_connections.get(room, ()))
        results = await asyncio.gather(
            *(asyncio.wait_for(ws.send_json(message), timeout=2) for ws in targets),
            return_exceptions=True,
        )
        for ws, res in zip(targets, results):
            if isinstance(res, Exception):         # dead or too slow: drop it
                await self.disconnect(room, ws)

manager = ConnectionManager()

# ⚠️ This manager is per PROCESS. With N workers or pods, users in the
# same room land on different processes. Fan out through Redis pub/sub
# (or NATS/Kafka): each process subscribes to the rooms it hosts and
# broadcasts locally. Also plan for reconnects (clients resume from a
# last-seen message ID) and use sticky sessions only as an optimisation.

@app.websocket("/ws/room/{room_id}")
async def room_websocket(
    websocket: WebSocket,
    room_id: str,
    user: Annotated[User, Depends(get_ws_user)],  # a WebSocket-aware auth dep (ticket/cookie)
):
    await manager.connect(room_id, websocket)
    await manager.broadcast(
        room_id,
        {"type": "join", "user": user.email},
    )
    
    try:
        while True:
            data = await websocket.receive_json()
            data["user"] = user.email
            await manager.broadcast(room_id, data)
    except WebSocketDisconnect:
        await manager.disconnect(room_id, websocket)
        await manager.broadcast(
            room_id,
            {"type": "leave", "user": user.email},
        )
```

---

## 10. Testing FastAPI Applications

### TestClient & Async Tests

```python
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
import pytest

# ── Sync tests with TestClient ────────────────────────────
def test_read_main():
    # `with` runs lifespan startup/shutdown; a bare TestClient(app) does NOT,
    # so anything created in lifespan (pools, clients) would be missing.
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello World"}

# ── Async tests (when the test itself must await things) ───
# Needs an async test runner: pytest-asyncio (@pytest.mark.asyncio) or
# AnyIO's pytest plugin (@pytest.mark.anyio). ASGITransport does NOT run
# lifespan; wrap the app with asgi-lifespan's LifespanManager if needed.
@pytest.mark.anyio
async def test_async_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/async")
    assert response.status_code == 200

# ── Test with dependency overrides ────────────────────────
from app.dependencies import get_db

# Mock database
class MockDB:
    async def fetch_all(self, query, *args):
        return [{"id": 1, "name": "Test"}]

async def override_get_db():
    yield MockDB()

# ── Overrides belong in a fixture, so they're always cleaned up ──
@pytest.fixture
def client():
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

def test_with_mock_db(client):
    response = client.get("/items/")
    assert response.status_code == 200

# Staff-level testing advice: mocking the DB tests your mocks. Prefer a
# real Postgres (testcontainers or a CI service), one transaction per test
# rolled back at the end, and override only true externals (payment
# provider, email) at the dependency boundary.

# ── Test authentication ───────────────────────────────────
# Faster: override get_current_user to return a fixture user, and test
# the login flow once, separately.
def test_authenticated_endpoint(client):
    # Login
    login_response = client.post("/token", data={
        "username": "test@example.com",
        "password": "testpass",
    })
    token = login_response.json()["access_token"]
    
    # Use token
    response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

# ── Test WebSocket ─────────────────────────────────────────
def test_websocket(client):
    with client.websocket_connect("/ws") as websocket:
        websocket.send_text("Hello")
        data = websocket.receive_text()
        assert data == "Echo: Hello"

# ── Test file upload ───────────────────────────────────────
def test_upload(client):
    response = client.post(
        "/upload",
        files={"file": ("test.txt", b"file content", "text/plain")},
    )
    assert response.status_code == 200
```

---

## 11. Performance Optimization

### Profiling & Bottleneck Detection

```python
# ── Middleware for profiling ───────────────────────────────
import cProfile
import io
import pstats

class ProfileMiddleware(BaseHTTPMiddleware):
    """Profile specific endpoints (dev only).
    ⚠️ cProfile isn't async-aware: it measures the event-loop thread, so
    other requests' work interleaves into the profile and awaited time is
    misattributed. pyinstrument (async mode) is better per request; py-spy
    (sampling, attach to the PID, no code change) is better in production."""
    
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/slow"):
            profiler = cProfile.Profile()
            profiler.enable()
            response = await call_next(request)
            profiler.disable()
            
            s = io.StringIO()
            ps = pstats.Stats(profiler, stream=s).sort_stats("cumtime")
            ps.print_stats(20)
            
            logger.info("Profile for %s:\n%s", request.url.path, s.getvalue())
        else:
            response = await call_next(request)
        
        return response

# ── Database query optimization ────────────────────────────
# 1. selectinload/joinedload for relationships (lazy loads fail in async anyway)
# 2. load_only() to select specific columns
# 3. Keyset pagination for deep pages; OFFSET scans and discards rows
# 4. Pool sized per process; watch pool wait time, not just DB CPU
# 5. Indexes for the actual WHERE/ORDER BY; check EXPLAIN ANALYZE
```

### Response Compression & Caching

```python
# ── Serialization: declare a response model / return type ──
# Recent FastAPI serialises straight to JSON bytes with Pydantic (Rust)
# when an endpoint has a response_model or return annotation. That's
# the fast path, and ORJSONResponse/UJSONResponse are now DEPRECATED.
# Returning raw dicts without a model goes through jsonable_encoder,
# which is slower.
@app.get("/items/{item_id}")
async def get_item(item_id: int) -> ItemOut:      # return type = response model
    return await load_item(item_id)

# ── Cache headers ─────────────────────────────────────────
from fastapi.responses import Response

@app.get("/static-data")
async def static_data(response: Response):
    """Immutable data — cache for 1 hour"""
    response.headers["Cache-Control"] = "public, max-age=3600, immutable"
    return {"data": compute_static_data()}

@app.get("/dynamic-data")
async def dynamic_data(response: Response):
    """Changes every minute — cache for 30s"""
    response.headers["Cache-Control"] = "public, max-age=30"
    return {"data": compute_dynamic_data()}

# ── ETags for conditional requests ────────────────────────
import hashlib

@app.get("/items/{item_id}")
async def get_item_with_etag(
    item_id: int,
    if_none_match: str | None = Header(None),
):
    item = await load_item(item_id)
    body = item.model_dump_json()
    etag = f'"{hashlib.sha256(body.encode()).hexdigest()[:32]}"'   # ETags are quoted strings

    # If-None-Match may hold several tags or "*", possibly weak (W/"...")
    if if_none_match and (if_none_match.strip() == "*" or etag in
                          [t.strip().removeprefix("W/") for t in if_none_match.split(",")]):
        return Response(status_code=304, headers={"ETag": etag})

    return Response(content=body, media_type="application/json", headers={"ETag": etag})
# Hashing the body still costs the DB read and serialisation; a stored
# version column (updated_at / row version) as the ETag skips both.
```

### Async Performance Patterns

```python
# ── Process large datasets in chunks ──────────────────────
@app.get("/process-large")
async def process_large_dataset():
    """Process millions of rows with bounded memory: keep aggregates,
    not rows. (Accumulating every result in a list defeats batching.)"""
    count, sample = 0, []
    async for batch in fetch_large_dataset_batches(batch_size=1000):
        processed = await process_batch(batch)
        count += len(processed)
        if len(sample) < 100:
            sample.extend(processed[: 100 - len(sample)])
    return {"count": count, "sample": sample}
# If this takes more than a few seconds, it's a job, not a request:
# enqueue it and return 202 + a status URL.

# ── Use asyncio.gather for independent tasks ───────────────
@app.get("/aggregated")
async def get_aggregated():
    """Fetch multiple independent data sources in parallel"""
    async def fetch_users():
        await asyncio.sleep(0.1)
        return [{"id": 1, "name": "Alice"}]
    
    async def fetch_orders():
        await asyncio.sleep(0.2)
        return [{"id": 1, "total": 100}]
    
    users, orders = await asyncio.gather(
        fetch_users(), fetch_orders(),
    )
    return {"users": users, "orders": orders}
```

---

## 12. Production Deployment

### ASGI Servers

!!! tip "30-second answer"
    On **Kubernetes/containers**, run **one Uvicorn process per container** (no `--workers`) and let the orchestrator scale replicas and restart crashes; set CPU requests to about one core. On a **VM or bare metal**, run several worker processes per box: `uvicorn --workers N` (Uvicorn has supervised its own workers since 0.30), `fastapi run --workers N`, or Gunicorn with `-k uvicorn_worker.UvicornWorker`. One process uses one core for Python code, so N ≈ cores. Unlike WSGI, async workers don't need `2 × cores + 1`.

```bash
# ── FastAPI CLI (wraps Uvicorn) ───────────────────────────
fastapi run main.py --port 8000 --workers 4        # production defaults (no reload)

# ── Uvicorn directly ──────────────────────────────────────
# --proxy-headers/--forwarded-allow-ips: trust X-Forwarded-* only from the LB
# --timeout-graceful-shutdown: keep below k8s terminationGracePeriodSeconds
# --timeout-keep-alive: longer than the LB idle timeout
# --limit-max-requests: recycle workers to cap slow leaks
uvicorn main:app --host 0.0.0.0 --port 8000 \
    --workers 4 \
    --proxy-headers --forwarded-allow-ips="10.0.0.0/8" \
    --timeout-graceful-shutdown 25 \
    --timeout-keep-alive 75 \
    --limit-max-requests 10000

# ── Gunicorn as the process manager ───────────────────────
# uvicorn.workers.UvicornWorker is deprecated; use the uvicorn-worker package
gunicorn main:app -k uvicorn_worker.UvicornWorker -w 4 \
    --bind 0.0.0.0:8000 --graceful-timeout 25 --max-requests 10000 --max-requests-jitter 1000

# ── Alternatives ──────────────────────────────────────────
# Hypercorn: HTTP/2 and HTTP/3 support. Granian: Rust server, fast, own worker model.
# uvloop and httptools are used automatically when installed (uvicorn[standard]).
```

**Why the keep-alive detail matters:** if the app closes an idle connection at the same moment the load balancer reuses it, the client gets a 502. Make the server's keep-alive timeout **longer** than the LB's idle timeout (AWS ALB defaults to 60 s).

**Graceful shutdown on Kubernetes:** on SIGTERM, Uvicorn stops accepting connections, waits for in-flight requests (up to `--timeout-graceful-shutdown`), then runs lifespan shutdown. Endpoints are removed from the Service asynchronously, so add a short `preStop` sleep (5-10 s) so the pod stops receiving new traffic *before* it stops listening.

### Configuration Management

```python
# ── Pydantic Settings ──────────────────────────────────────
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    """Environment-based configuration with validation"""
    
    # Application
    app_name: str = "FastAPI App"
    debug: bool = False
    environment: str = "production"
    
    # Database
    database_url: str
    database_pool_size: int = 20
    database_max_overflow: int = 10
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # Auth
    secret_key: SecretStr          # repr shows '**********', so it won't leak into logs
    access_token_expire_minutes: int = 30

    # External APIs
    openai_api_key: SecretStr | None = None
    sentry_dsn: str = ""
    
    # Rate limiting
    rate_limit_per_minute: int = 60
    
    model_config = SettingsConfigDict(
        env_file=".env",              # local dev only; real env vars take precedence
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    # Missing required fields (database_url, secret_key) raise at startup:
    # fail fast instead of on the first request that needs them.

@lru_cache
def get_settings() -> Settings:
    """One Settings per process; override get_settings in tests."""
    return Settings()

# ── Dependency ─────────────────────────────────────────────
@app.get("/info")
async def info(settings: Settings = Depends(get_settings)):
    return {
        "app_name": settings.app_name,
        "environment": settings.environment,
    }
```

### Production Middleware Stack

```python
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

app = FastAPI(
    lifespan=lifespan,
    docs_url=None if is_production else "/docs",   # or keep docs behind auth
    redoc_url=None if is_production else "/redoc",
)

# add_middleware WRAPS the stack: the LAST added is the OUTERMOST.
# Add innermost first:
app.add_middleware(GZipMiddleware, minimum_size=1000)            # innermost: compresses the final body
app.add_middleware(TimingMiddleware)
app.add_middleware(RateLimitMiddleware, limit=settings.rate_limit_per_minute)
app.add_middleware(RequestIDMiddleware)                           # ID exists for every log line below
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
# Outermost: handled errors (4xx, HTTPException) also get CORS headers.
# Unhandled exceptions are turned into 500s by ServerErrorMiddleware, which
# sits OUTSIDE all user middleware, so those responses carry no CORS headers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Error handling: one consistent error shape ─────────────
def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)   # may be unset if a middleware failed early

@app.exception_handler(RequestValidationError)              # bad request input → 422
async def request_validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(exc.errors()), "request_id": _rid(request)},
        # Don't echo exc.body back: it may contain passwords or PII
    )

@app.exception_handler(StarletteHTTPException)   # Starlette's class also catches routing 404/405
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "request_id": _rid(request)},
        headers=getattr(exc, "headers", None),   # keep WWW-Authenticate etc.
    )

@app.exception_handler(Exception)                # catch-all → 500, never leak internals
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception", extra={"request_id": _rid(request)})
    return JSONResponse(status_code=500,
                        content={"detail": "Internal server error", "request_id": _rid(request)})

# Note: a pydantic ValidationError raised INSIDE your code (e.g. validating
# a downstream response) is a server bug → 500, not a client 422. FastAPI
# raises ResponseValidationError when your return value fails response_model.
```

---

## 13. OpenAPI & Documentation Customization

### Customizing the OpenAPI Schema

FastAPI generates **OpenAPI 3.1** (since 0.99, mid-2023), which aligns with JSON Schema 2020-12. Some older client generators only understand 3.0, so check your codegen before you upgrade.

```python
from fastapi import FastAPI, APIRouter
from fastapi.openapi.utils import get_openapi

# ── Custom metadata ────────────────────────────────────────
app = FastAPI(
    title="My API",
    description="""
    ## My API Description
    
    This is a **production-grade** API with full documentation.
    
    ### Features
    * User authentication
    * CRUD operations
    * Real-time WebSocket updates
    """,
    version="2.0.0",
    terms_of_service="https://example.com/terms",
    contact={
        "name": "API Support",
        "url": "https://example.com/support",
        "email": "support@example.com",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    openapi_tags=[
        {
            "name": "users",
            "description": "Operations with users",
        },
        {
            "name": "items",
            "description": "Manage items",
        },
    ],
)

# ── Complete OpenAPI customization ─────────────────────────
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title="Custom API",
        version="3.0.0",
        description="Custom OpenAPI schema",
        routes=app.routes,
    )
    
    # Add security scheme
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        },
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
        },
    }
    
    # Apply globally
    openapi_schema["security"] = [{"BearerAuth": []}]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# ── Route-specific responses ───────────────────────────────
@app.get(
    "/items/{item_id}",
    response_model=Item,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "Item not found",
        },
        422: {
            "model": ValidationErrorResponse,
            "description": "Validation error",
        },
    },
    tags=["items"],
    summary="Get an item",
    description="Retrieve a specific item by ID",
)
async def get_item(item_id: int):
    ...
```

---

## 14. FastAPI Design Patterns

### Service Layer Pattern

```python
# ── Separating business logic from routes ─────────────────
# services/item_service.py
# The service knows nothing about HTTP: it raises domain errors, and an
# exception handler maps them to status codes in one place.
class DomainError(Exception): ...
class ValidationFailed(DomainError): ...

class CreateItemRequest(BaseModel):
    name: str
    price: Decimal
    tax: Decimal | None = None

class ItemService:
    """Business logic for items"""
    
    def __init__(self, db: AsyncSession, cache: CacheService):
        self.db = db
        self.cache = cache
        self.repo = ItemRepository(db)
    
    async def create_item(self, request: CreateItemRequest) -> Item:
        # Business rules (shape/type rules already ran in Pydantic)
        if request.tax is not None and request.tax > request.price:
            raise ValidationFailed("Tax exceeds price")

        created = await self.repo.add(ItemRow(**request.model_dump()))
        await self.db.commit()                         # the service owns the transaction
        item = Item.model_validate(created)            # needs from_attributes=True

        # Cache after commit; a failure here must not fail the request
        await self.cache.set(f"item:{item.id}", item.model_dump_json())
        return item
    
    async def get_item(self, item_id: int) -> Optional[Item]:
        # Try cache first
        cached = await self.cache.get(f"item:{item_id}")
        if cached:
            return Item.model_validate_json(cached)
        
        # Fallback to DB
        item = await self.repo.get_by_id(item_id)
        if item:
            await self.cache.set(f"item:{item_id}", item.model_dump_json())
        
        return item

# routes/items.py
def get_item_service(db: DB, cache: Cache) -> ItemService:
    return ItemService(db, cache)

@router.post("/items/", status_code=201)
async def create_item(
    request: CreateItemRequest,
    service: Annotated[ItemService, Depends(get_item_service)],
) -> Item:
    return await service.create_item(request)

@app.exception_handler(ValidationFailed)
async def on_validation_failed(request: Request, exc: ValidationFailed):
    return JSONResponse(status_code=422, content={"detail": str(exc)})
```

### Repository Pattern

```python
from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Optional

T = TypeVar("T", bound=BaseModel)

class Repository(ABC, Generic[T]):
    """Abstract repository interface"""
    
    @abstractmethod
    async def get_by_id(self, id: int) -> Optional[T]: ...
    
    @abstractmethod
    async def list(self, skip: int = 0, limit: int = 20) -> list[T]: ...
    
    @abstractmethod
    async def create(self, entity: T) -> T: ...
    
    @abstractmethod
    async def update(self, id: int, data: dict) -> Optional[T]: ...
    
    @abstractmethod
    async def delete(self, id: int) -> bool: ...

class PostgresItemRepository(Repository[Item]):
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_by_id(self, id: int) -> Optional[Item]:
        result = await self.session.execute(
            select(ItemModel).where(ItemModel.id == id)
        )
        if model := result.scalar_one_or_none():
            return Item.model_validate(model)
        return None
    # ... etc

class InMemoryItemRepository(Repository[Item]):
    """For testing"""
    def __init__(self):
        self._items: dict[int, Item] = {}
        self._next_id = 1
    
    async def get_by_id(self, id: int) -> Optional[Item]:
        return self._items.get(id)
    
    async def create(self, entity: Item) -> Item:
        entity.id = self._next_id
        self._items[self._next_id] = entity
        self._next_id += 1
        return entity
    # ... etc

# ── Dependency ─────────────────────────────────────────────
def get_item_repository(db: DB) -> Repository[Item]:
    return PostgresItemRepository(db)

# Tests swap it without any `if environment == "test"` branch in prod code:
# app.dependency_overrides[get_item_repository] = lambda: InMemoryItemRepository()
```

### Unit of Work Pattern

```python
class UnitOfWork:
    """Coordinates multiple repositories in a single transaction"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.users = UserRepository(db)
        self.orders = OrderRepository(db)
        self.items = ItemRepository(db)
    
    async def commit(self):
        await self.db.commit()
    
    async def rollback(self):
        await self.db.rollback()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            await self.commit()
        else:
            await self.rollback()

@router.post("/orders/")
async def create_order(
    request: CreateOrderRequest,
    uow: UnitOfWork = Depends(get_uow),
):
    async with uow:
        user = await uow.users.get_by_id(request.user_id)
        if not user:
            raise HTTPException(status_code=404)
        
        order = await uow.orders.create(...)
        await uow.items.update_stock(...)
    
    return order
```

---

## 15. FastAPI Interview Questions

### Beginner

<details>
<summary><b>Q1: What is FastAPI and how is it different from Flask?</b></summary>

**Answer:** FastAPI is a modern, fast web framework for building APIs with Python based on Starlette (ASGI) and Pydantic. Key differences from Flask:

- **Async-first:** Built on ASGI, supports async/await natively (Flask is WSGI/sync)
- **Auto-documentation:** Automatic OpenAPI/Swagger docs from Python type hints
- **Validation:** Built-in request/response validation via Pydantic (Flask needs separate libraries)
- **Performance:** Higher throughput than Flask for I/O-bound work, because one async worker can serve many concurrent requests. The "as fast as Node and Go" claim comes from framework micro-benchmarks; in real services the DB and your code dominate. Flask 2.0+ also supports `async def` views, but each request still occupies a WSGI worker.
- **Dependency Injection:** Built-in DI system (Flask uses global `request` object)
- **WebSocket support:** Native WebSocket support (Flask needs extensions)
- **Type safety:** Full type hint support with IDE autocomplete
</details>

<details>
<summary><b>Q2: Explain FastAPI's dependency injection system. How does it work?</b></summary>

**Answer:** FastAPI's DI system resolves dependencies using a DAG (Directed Acyclic Graph):

```python
# Dependencies are callables that can depend on other dependencies
async def get_db():
    db = DatabaseSession()
    try:
        yield db
    finally:
        db.close()

async def get_repo(db = Depends(get_db)):
    return Repository(db)

# FastAPI resolves the graph: get_repo → get_db
@app.get("/items")
async def list_items(repo = Depends(get_repo)):
    return await repo.list_all()
```

Key features:
- **Automatic resolution:** FastAPI builds and resolves the dependency graph
- **Caching:** Within the same request, each dependency is called only once
- **Lifecycle control:** Support for sync/async, `yield` for cleanup
- **Overrideable:** Dependencies can be overridden for testing
- **Hierarchical:** App-level, router-level, and path-level dependencies
</details>

<details>
<summary><b>Q3: What's the difference between sync and async path operations in FastAPI?</b></summary>

**Answer:** FastAPI supports both sync and async path operations:

```python
@app.get("/sync")
def sync_view():
    # Runs in a thread pool — doesn't block the event loop
    return {"hello": "world"}

@app.get("/async")
async def async_view():
    # Runs on the event loop — use for I/O
    await asyncio.sleep(0.1)
    return {"hello": "world"}
```

- **Sync views (`def`):** run in AnyIO's worker thread pool (`anyio.to_thread.run_sync`), 40 threads per process by default. They don't block the event loop, but concurrency is capped at the pool size.
- **Async views (`async def`):** run on the event loop. Best when every I/O call is awaited (async DB driver, httpx). One blocking call (`requests`, `time.sleep`, sync DB driver, heavy CPU) stalls **every** request on that worker.
- **Rule:** if in doubt, `def` is the safe default; `async def` is a promise that you never block. Inside `async def`, push unavoidable blocking calls to `await anyio.to_thread.run_sync(fn)` or `asyncio.to_thread(fn)`.

**Probe next:** "How would you find a blocking call in production?" Turn on asyncio debug mode (`PYTHONASYNCIODEBUG=1` logs callbacks slower than 100 ms), watch event-loop lag metrics, and take `py-spy dump` stack samples, or on 3.14 `python -m asyncio pstree <pid>`.
</details>

### Intermediate

<details>
<summary><b>Q4: How does FastAPI generate OpenAPI documentation from Python types?</b></summary>

**Answer:** FastAPI uses Python type hints and Pydantic models to auto-generate OpenAPI specs:

1. **Route parameters** → OpenAPI path parameters
2. **Query parameters** → OpenAPI query parameters with type/validation
3. **Request body (Pydantic models)** → OpenAPI requestBody schema
4. **Response model** → OpenAPI response schema
5. **Docstrings** → OpenAPI operation descriptions
6. **Field metadata** → OpenAPI constraints (min, max, pattern)

```python
@app.get("/items/{item_id}", response_model=Item)
async def get_item(
    item_id: Annotated[int, Path(ge=1)],                       # Path parameter
    q: Annotated[str | None, Query(max_length=50)] = None,     # Query parameter
):
    """
    Get an item by ID.
    Returns the full item object with all fields.
    """
    return await get_item_from_db(item_id)
```

This generates OpenAPI 3.1 JSON (since FastAPI 0.99), which Swagger UI and ReDoc render as interactive documentation. Pydantic produces the JSON Schemas for the models, and they appear under `components/schemas`. Gotcha: input and output schemas for the same model can differ (fields with defaults are required in output), so FastAPI emits `Model-Input`/`Model-Output` unless you set `separate_input_output_schemas=False`.
</details>

<details>
<summary><b>Q5: How do you handle database transactions in FastAPI?</b></summary>

**30-second answer:** one `AsyncSession` per request from a `yield` dependency. The commit must happen **before the response is sent**: either explicitly in the service layer, or in a dependency declared with `Depends(..., scope="function")`. With the default `scope="request"`, code after `yield` runs after the response has gone out, so a failed commit still returns 200 to the client.

```python
async def get_session():
    async with async_session() as session:
        yield session

async def transactional(db: Annotated[AsyncSession, Depends(get_session)]):
    try:
        yield db
        await db.commit()
    except Exception:
        await db.rollback()
        raise

Tx = Annotated[AsyncSession, Depends(transactional, scope="function")]

@app.post("/items", status_code=201)
async def create_item(item: ItemIn, db: Tx) -> ItemOut:
    row = ItemRow(**item.model_dump())      # ORM object, not the Pydantic model
    db.add(row)
    await db.flush()                         # assigns row.id; still uncommitted
    return ItemOut.model_validate(row)       # commit happens before the response is sent
```

**Probe next:**
- *Savepoints:* `async with db.begin_nested():` lets you roll back part of the work.
- *Side effects:* publish events or enqueue tasks only after commit; for guaranteed delivery, use an outbox row written in the same transaction.
- *Long transactions:* never hold one open across an outbound HTTP call. It pins a pooled connection and holds locks.
</details>

<details>
<summary><b>Q6: Explain FastAPI's dependency override system for testing.</b></summary>

**Answer:** FastAPI's `app.dependency_overrides` dict allows replacing dependencies during testing:

```python
# Production
async def get_db():
    async with real_db_session() as session:
        yield session

# Test
async def override_get_db():
    async with test_db_session() as session:
        yield session

# Override
app.dependency_overrides[get_db] = override_get_db

# Use a fixture so overrides are always removed, even if the test fails
@pytest.fixture
def client():
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:        # `with` also runs lifespan
        yield c
    app.dependency_overrides.clear()

def test_list_items(client):
    assert client.get("/items").status_code == 200
```

Overrides match by the **original callable's identity**, so override the exact function used in `Depends(...)`, not a re-import or a wrapper. They apply anywhere in the graph, including sub-dependencies and router-level dependencies.
</details>

<details>
<summary><b>Q7: What's the difference between BackgroundTasks and Celery for async work?</b></summary>

**Answer:**

| Feature | BackgroundTasks | Celery/ARQ |
|---------|-----------------|------------|
| **Execution** | Same process, after response | Separate worker processes |
| **Persistence** | In-memory only | Backed by Redis/RabbitMQ |
| **Durability** | Lost on deploy, crash or OOM | Survives restarts (with `acks_late`) |
| **Retries** | None | Built-in with backoff |
| **Monitoring** | None | Flower, Prometheus |
| **Scheduling** | No | Periodic tasks (Celery Beat) |
| **Use case** | Light post-response work (logging, email) | Heavy async tasks (report generation, video processing) |

```python
# BackgroundTasks — lightweight, same process
@app.post("/notify")
async def notify(background_tasks: BackgroundTasks):
    background_tasks.add_task(send_email, "user@example.com")
    return {"message": "Email queued"}

# Celery — production task queue
@app.post("/reports", status_code=202)
async def create_report(params: ReportParams):
    task = generate_report_task.delay(params.model_dump())
    return {"task_id": task.id, "status_url": f"/reports/{task.id}"}
```

Celery's client API is sync. `.delay()` does a quick broker write that is usually acceptable, but under load push it to a thread, or use an async-native queue (ARQ, Taskiq, SAQ). Rule of thumb: if losing the work on a deploy is acceptable and it takes under a second, use `BackgroundTasks`; otherwise use a queue.
</details>

### Advanced

<details>
<summary><b>Q8: Design a rate-limiting system for a FastAPI application handling 100K+ req/s.</b></summary>

**30-second answer:** at 100K req/s, don't do a Redis round trip per request for every request in Python. Rate-limit **at the edge** (API gateway, Envoy, nginx, CDN/WAF) for per-IP and coarse limits. In the app, enforce per-tenant/API-key limits with an **atomic** Redis script (token bucket or sliding-window counter), sharded by key across a Redis Cluster. Optionally keep a local in-process allowance that syncs to Redis periodically, trading exactness for no per-request network hop.

```python
import time
import redis.asyncio as redis
from starlette.responses import JSONResponse

# Token bucket in Lua: atomic, O(1) memory per key, allows bursts up to capacity
TOKEN_BUCKET = """
local key = KEYS[1]
local rate, capacity, now = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
local b = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(b[1]) or capacity
local ts = tonumber(b[2]) or now
tokens = math.min(capacity, tokens + (now - ts) * rate)
local allowed = tokens >= 1
if allowed then tokens = tokens - 1 end
redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', key, math.ceil(capacity / rate * 1000) + 1000)
return {allowed and 1 or 0, tostring(tokens)}
"""

class TokenBucketLimiter:
    def __init__(self, client: redis.Redis):
        self._script = client.register_script(TOKEN_BUCKET)

    async def allow(self, key: str, rate_per_s: float, burst: int) -> tuple[bool, float]:
        allowed, remaining = await self._script(keys=[f"rl:{{{key}}}"],   # {hash tag} for Cluster
                                                args=[rate_per_s, burst, time.time()])
        return bool(allowed), float(remaining)

class RateLimitMiddleware:                      # pure ASGI: cheap on the hot path
    def __init__(self, app, limiter: TokenBucketLimiter):
        self.app, self.limiter = app, limiter

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        api_key = headers.get(b"x-api-key", b"").decode()
        key = api_key or (scope.get("client") or ("unknown",))[0]  # client IP is correct only with --proxy-headers
        try:
            ok, remaining = await self.limiter.allow(key, rate_per_s=10, burst=20)
        except redis.RedisError:
            ok, remaining = True, 0             # fail OPEN; the edge limit is the backstop
        if not ok:
            resp = JSONResponse({"detail": "Rate limit exceeded"}, status_code=429,
                                headers={"Retry-After": "1"})
            return await resp(scope, receive, send)
        await self.app(scope, receive, send)
```

Key considerations:
- **Atomicity:** read-count-then-write from Python with separate commands lets concurrent requests all pass. A `MULTI` pipeline queues ZADD *before* you see the count, so rejected requests still consume quota. Use one Lua script.
- **Clock:** the script trusts the app server's clock; use `redis.call('TIME')` inside the script if servers' clocks drift.
- **Tiers:** look up the plan's rate by API key (cache it in memory for a minute).
- **Headers:** `429` + `Retry-After`; optionally `RateLimit-Limit`/`RateLimit-Remaining` (IETF draft).
- **Hot keys:** one huge tenant concentrates load on one Redis shard. Split its key into N sub-buckets, each with 1/N of the rate.
</details>

<details>
<summary><b>Q9: How would you implement a CQRS pattern with FastAPI?</b></summary>

**30-second answer:** commands go through the domain model and the primary DB. Each command writes its state change **and an outbox event in the same transaction**. A relay (a poller, or CDC with Debezium) publishes the events, and projectors update read models (a denormalised table, Elasticsearch, a cache). Queries hit only the read models. The cost is eventual consistency and more moving parts, so justify it with a real read/write asymmetry.

```python
# ── Command side ────────────────────────────────────────────
@router.post("/orders", status_code=202)
async def create_order(command: CreateOrderCommand, db: Tx):
    order = Order.create(command.user_id, command.items)
    db.add(order)
    await db.flush()                                 # order.id assigned
    db.add(OutboxEvent(                              # same transaction as the order
        aggregate_id=order.id,
        type="OrderCreated",
        payload={"order_id": order.id, "user_id": order.user_id, "total": str(order.total)},
    ))
    return {"order_id": order.id}
    # Publishing to Kafka directly here would be a dual write: the commit
    # can succeed and the publish fail (or the reverse) → read model drifts.

# ── Relay (separate process) ───────────────────────────────
# SELECT ... FROM outbox WHERE published_at IS NULL ORDER BY id
#   FOR UPDATE SKIP LOCKED LIMIT 100 → publish → mark published.
# At-least-once: consumers must be idempotent.

# ── Projector (consumer) ───────────────────────────────────
async def on_order_created(event: dict):
    async with read_session() as s, s.begin():
        await s.execute(
            insert(OrderSummary)
            .values(order_id=event["order_id"], user_id=event["user_id"],
                    total=event["total"], status="pending")
            .on_conflict_do_nothing(index_elements=["order_id"])   # idempotent replay
        )

# ── Query side ─────────────────────────────────────────────
@router.get("/orders")
async def list_orders(user: CurrentUser, q: Annotated[OrderQueries, Depends()]):
    return await q.for_user(user.id)            # reads the denormalised table only
```

Trade-offs to state: read-your-own-writes needs handling (return the new state from the command, or read from the write side briefly); projections must be rebuildable by replaying events; ordering is only guaranteed per aggregate (partition by `aggregate_id`).
</details>

<details>
<summary><b>Q10: How do you handle graceful shutdown in FastAPI with in-flight requests?</b></summary>

**30-second answer:** mostly, let the server do it and configure it correctly. On SIGTERM, Uvicorn (and Gunicorn) **stop accepting new connections, let in-flight requests finish** up to a timeout, then run your lifespan shutdown code. Your job: (1) make the platform stop routing traffic first, (2) set timeouts that nest correctly, (3) release resources in lifespan, (4) handle long-lived connections (websockets, SSE) and background work explicitly. Don't install your own SIGTERM handler: it replaces the server's.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.draining = False
    app.state.http = httpx.AsyncClient()
    yield
    # Runs AFTER uvicorn has stopped accepting and drained HTTP requests
    await app.state.http.aclose()
    await engine.dispose()

@app.get("/health/ready")
async def ready(request: Request):
    # A preStop hook can flip this (e.g. POST /internal/drain) so the
    # load balancer marks the pod unready before SIGTERM arrives.
    if request.app.state.draining:
        return JSONResponse({"status": "draining"}, status_code=503)
    return {"status": "ok"}
```

**Timeline on Kubernetes**

```mermaid
sequenceDiagram
    participant K as Kubelet
    participant E as Endpoints and LB
    participant P as Pod (uvicorn)
    K->>E: remove pod from Service endpoints (asynchronous)
    K->>P: preStop hook (sleep 5-10 s while the LB catches up)
    K->>P: SIGTERM
    P->>P: stop accepting, finish in-flight (timeout-graceful-shutdown)
    P->>P: lifespan shutdown (close pools and clients)
    K->>P: SIGKILL if terminationGracePeriodSeconds is exceeded
```

**Settings that must nest:** `preStop sleep` + `--timeout-graceful-shutdown` + lifespan cleanup < `terminationGracePeriodSeconds` (default 30 s).

**What isn't covered automatically:**
- **WebSockets/SSE:** they never "finish". Track them and close them with code 1001 (going away) on shutdown so clients reconnect elsewhere.
- **BackgroundTasks** still running are lost if the grace period ends, which is another reason durable work belongs in a queue.
- **Consumers** (Kafka, SQS loops started in lifespan): stop polling, finish the current batch, commit offsets, then exit.
</details>

<details>
<summary><b>Q11: Design a multi-tenant FastAPI application with tenant isolation.</b></summary>

**30-second answer:** resolve the tenant **from the authenticated identity** (a claim in the token), not from a header the client can change. Carry it in a dependency or ContextVar, and enforce isolation at the data layer: row-level `tenant_id` plus PostgreSQL Row-Level Security for most SaaS, schema- or database-per-tenant for enterprise or regulated tiers. The same trade-off table as in the Django notes applies (rows: cheapest, weakest; DB per tenant: strongest, most operational cost).

**Answer:**

```python
# ── Tenant resolution middleware ───────────────────────────
class TenantMiddleware(BaseHTTPMiddleware):
    """Resolves tenant from subdomain or header"""
    
    async def dispatch(self, request, call_next):
        # ⚠️ A raw X-Tenant-ID header is client-controlled. Only accept it
        # if auth later verifies the user belongs to that tenant; better,
        # take the tenant from a verified token claim.
        tenant_id = request.headers.get("X-Tenant-ID")
        subdomain = request.url.hostname.split(".")[0]
        
        if tenant_id:
            tenant = await get_tenant_by_id(tenant_id)
        else:
            tenant = await get_tenant_by_subdomain(subdomain)
        
        if not tenant:
            return JSONResponse(status_code=404, content={"detail": "Tenant not found"})
        
        request.state.tenant = tenant
        return await call_next(request)

# ── Dynamic database connection per tenant ────────────────
class TenantDatabaseRouter:
    """Routes to tenant-specific database.
    ⚠️ One pool per tenant per worker: 200 tenants × 8 workers × 5 conns
    = 8,000 connections. Bound the cache (LRU with dispose() on evict),
    or put PgBouncer in front and use small pools."""

    _engines: dict[str, AsyncEngine] = {}
    
    async def get_engine(self, tenant: Tenant) -> AsyncEngine:
        if tenant.id not in self._engines:
            self._engines[tenant.id] = create_async_engine(
                tenant.database_url,
                pool_size=5,
                max_overflow=2,
            )
        return self._engines[tenant.id]
    
    async def get_session(self, tenant: Tenant) -> AsyncSession:
        engine = await self.get_engine(tenant)
        return AsyncSession(engine, expire_on_commit=False)

# ── Dependency ─────────────────────────────────────────────
async def get_tenant_db(request: Request) -> AsyncSession:
    router = request.app.state.tenant_router
    tenant = request.state.tenant
    async with await router.get_session(tenant) as session:
        yield session

# ── Shared database with row-level isolation ───────────────
class TenantMixin:
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"))
    
    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()

class TenantAwareQuery:
    """Automatically filters by tenant"""
    
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id
    
    def __call__(self, model):
        return select(model).where(model.tenant_id == self.tenant_id)

# ── Schema-based isolation (PostgreSQL) ────────────────────
import re
_SCHEMA_RE = re.compile(r"^tenant_[a-z0-9_]{1,40}$")

async def set_tenant_schema(tenant: Tenant, session: AsyncSession):
    # Identifiers can't be bound parameters, so validate strictly:
    # an f-string with an unchecked name is SQL injection.
    if not _SCHEMA_RE.fullmatch(tenant.schema_name):
        raise ValueError("bad schema name")
    # SET LOCAL lasts only for this transaction. A plain SET would stick
    # to the pooled connection and leak into the NEXT tenant's request.
    await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))

# ── Row-Level Security: the DB enforces the filter ─────────
# CREATE POLICY tenant_isolation ON orders
#   USING (tenant_id = current_setting('app.tenant_id')::bigint);
# ALTER TABLE orders ENABLE ROW LEVEL SECURITY;  -- and FORCE for the table owner
# Per request, inside the transaction:
#   await session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
# (true = transaction-local, so it's safe with pooling.)
```
</details>

<details>
<summary><b>Q12: How do you optimize a FastAPI endpoint that streams large amounts of data?</b></summary>

**Answer:**

```python
from typing import Literal
from fastapi.responses import StreamingResponse
import orjson

# ── Stream JSON array without loading all into memory ─────
async def stream_items(db_query):
    """Stream JSON array — memory efficient for millions of rows"""
    yield "["
    first = True
    async for row in db_query:
        if not first:
            yield ","
        yield orjson.dumps(row).decode()
        first = False
    yield "]"

@app.get("/large-dataset")
async def get_large_dataset():
    # Don't set Transfer-Encoding yourself: the server chunks automatically
    # when there's no Content-Length (and HTTP/2 forbids that header).
    return StreamingResponse(stream_items(fetch_all_items()), media_type="application/json")

# Better format for huge exports: NDJSON (one JSON object per line).
# Clients can parse it incrementally, and a truncated stream is detectable.

# ── Stream CSV ─────────────────────────────────────────────
async def stream_csv(query):
    """Stream CSV with headers"""
    yield "id,name,email\n"
    async for row in query:
        yield f"{row.id},{row.name},{row.email}\n"

@app.get("/export/users")
async def export_users(fmt: Literal["csv", "json"] = "csv"):   # validated: no KeyError → 500
    generators = {"csv": stream_csv, "json": stream_items}
    content_type = {"csv": "text/csv", "json": "application/json"}

    return StreamingResponse(
        generators[fmt](fetch_users()),
        media_type=content_type[fmt],
        headers={"Content-Disposition": f"attachment; filename=users.{fmt}"},
    )
# Use the csv module (csv.writer over an io.StringIO per batch), not
# f-strings: names containing commas or quotes break hand-built CSV.

# ── The source must stream too ─────────────────────────────
# SQLAlchemy: `await session.stream(select(User).execution_options(yield_per=1000))`,
# or a server-side cursor (asyncpg conn.cursor()). A plain .all() loads every
# row first and defeats the point. Remember the DB connection is held for
# the whole download: cap concurrent exports, or write the file to object
# storage in a background job and return a presigned URL.

# ── Compression for streaming ──────────────────────────────
# Let the proxy/CDN compress (gzip/brotli). Compressing in the app costs
# worker CPU and can buffer the stream.
```
</details>

<details>
<summary><b>Q13: Explain FastAPI's response_model and how it handles type coercion.</b></summary>

**30-second answer:** the response model (from `response_model=` or, preferably, the return annotation) is a **contract and a filter**. FastAPI validates your return value against it, drops fields the model doesn't declare (so an ORM row's `hashed_password` never leaks), serialises it to JSON with Pydantic, and documents it in OpenAPI. A return value that doesn't match raises `ResponseValidationError` → 500, because that's a server bug, not a client error.

```python
class ItemPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)   # accept ORM objects
    id: int
    name: str

@app.get("/items/{item_id}")
async def get_item(item_id: int, db: DB) -> ItemPublic:      # return type = response model
    return await db.get(ItemRow, item_id)   # ORM row: extra columns are filtered out

# When the declared return type differs from what you return
# (e.g. you return a dict or a Response), use response_model= explicitly:
@app.get("/items", response_model=list[ItemPublic])
async def list_items(db: DB):
    return (await db.scalars(select(ItemRow).limit(50))).all()

# ── Trimming output ────────────────────────────────────────
@app.patch("/items/{item_id}", response_model=ItemPublic, response_model_exclude_unset=True)
async def patch_item(item_id: int, patch: ItemPatch, db: DB): ...
# exclude_unset: omit fields never explicitly set (not "fields equal to their default";
# that's response_model_exclude_defaults). exclude_none drops None values.
```

**Input coercion (Pydantic v2, lax mode by default):**

| Input | Field type | Result |
|---|---|---|
| `"42"` | `int` | `42` |
| `"4.2"` | `int` | **error** |
| `4.0` / `4.2` | `int` | `4` / **error** (v2 rejects a fractional part; v1 silently truncated `4.2` to `4`) |
| `"true"`, `"yes"`, `"1"`, `"on"` | `bool` | `True` |
| `"2026-10-07T12:00:00Z"` | `datetime` | aware `datetime` |
| `[1, "2"]` | `list[int]` | `[1, 2]` |
| `123` | `str` | **error** (v2 doesn't coerce numbers to strings by default) |

Query and path parameters arrive as strings, so lax coercion is what makes `?page=2` work. For JSON bodies where `"42"` signals a client bug, use `ConfigDict(strict=True)` or `Annotated[int, Strict()]`.
</details>

---

> *Built for experienced Python engineers targeting Staff/Principal roles at top-tier companies*
