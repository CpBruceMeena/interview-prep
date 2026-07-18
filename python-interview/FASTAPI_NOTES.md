# ⚡ FastAPI — Staff-Level Notes & Interview Questions

> **Deep-dive into FastAPI's internals, async patterns, Pydantic integration, dependency injection, and production deployment**
> *Designed for Staff/Principal Engineer interviews (10+ years experience)*

---

## Table of Contents

1. [FastAPI Architecture & Philosophy](#1-fastapi-architecture--philosophy)
2. [Path Operations & Routing](#2-path-operations--routing)
3. [Pydantic Models & Validation](#3-pydantic-models--validation)
4. [Dependency Injection System](#4-dependency-injection-system)
5. [Async Support & Concurrency](#5-async-support--concurrency)
6. [Middleware & Lifecycle Events](#6-middleware--lifecycle-events)
7. [Security & Authentication](#7-security--authentication)
8. [Database Integration & Sessions](#8-database-integration--sessions)
9. [Background Tasks & WebSockets](#9-background-tasks--websockets)
10. [Testing FastAPI Applications](#10-testing-fastapi-applications)
11. [Performance Optimization](#11-performance-optimization)
12. [Production Deployment](#12-production-deployment)
13. [OpenAPI & Documentation Customization](#13-openapi--documentation-customization)
14. [FastAPI Design Patterns](#14-fastapi-design-patterns)
15. [FastAPI Interview Questions](#15-fastapi-interview-questions)

---

## 1. FastAPI Architecture & Philosophy

### What Makes FastAPI Different

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
# ── WSGI (Django/Flask) ────────────────────────────────────
# Synchronous, one request per worker
# Cannot handle WebSocket natively
# Request → WSGI Server → WSGI Handler → View → Response

# ── ASGI (FastAPI/Starlette) ───────────────────────────────
# Asynchronous, supports long-lived connections
# Native WebSocket, Server-Sent Events, HTTP/2
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
# - ASGI request/response handling
# - WebSocket support
# - Background tasks
# - Middleware stack
# - Static file serving
# - Server-Sent Events
# - Streaming responses

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
from fastapi import FastAPI, Path, Query, Body

app = FastAPI()

# ── All HTTP methods ───────────────────────────────────────
@app.get("/items/{item_id}")
@app.post("/items/")
@app.put("/items/{item_id}")
@app.patch("/items/{item_id}")
@app.delete("/items/{item_id}")
@app.options("/items/{item_id}")
@app.head("/items/{item_id}")

# ── Path parameters with validation ────────────────────────
@app.get("/items/{item_id}")
async def read_item(
    item_id: int = Path(..., ge=1, le=1000, description="The item ID"),
    q: str | None = Query(None, max_length=50, pattern="^[a-zA-Z]+$"),
):
    return {"item_id": item_id, "q": q}

# ── Route ordering matters! ────────────────────────────────
# FastAPI matches routes in order of declaration.
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
    include_details: bool = Query(False),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
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
    return await db.execute("INSERT INTO items ...", item.dict())

# ── Include routers in main app ────────────────────────────
app.include_router(router)
app.include_router(admin_router, prefix="/admin")
app.include_router(api_router, prefix="/api/v1")

# ── Nested routers ─────────────────────────────────────────
# Routers can be nested for deep API structures
# /api/v1/users/{user_id}/items/{item_id}
user_router = APIRouter(prefix="/users")
item_router = APIRouter(prefix="/items")

@user_router.get("/{user_id}")
async def get_user(user_id: int): ...

@item_router.get("/{item_id}")
async def get_item(item_id: int): ...

user_router.include_router(item_router)
app.include_router(user_router, prefix="/api/v1")
```

---

## 3. Pydantic Models & Validation

### Model Definition & Advanced Features

```python
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing import Optional
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
import re

# ── Field validation ───────────────────────────────────────
class Item(BaseModel):
    model_config = ConfigDict(
        frozen=True,           # Immutable (hashable)
        from_attributes=True,  # ORM mode
        populate_by_name=True, # Allow alias usage
        extra="forbid",        # Reject unknown fields
        json_schema_extra={
            "example": {"name": "Foo", "price": 42.0}
        }
    )
    
    name: str = Field(
        ...,                    # Required field (ellipsis)
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9 ]+$",
        description="Item name",
    )
    price: float = Field(
        ..., ge=0.01, le=1000000.0,
        description="Item price",
    )
    tax: float | None = Field(None, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list, max_length=10)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # ── Field-level validators ─────────────────────────────
    @field_validator("name")
    @classmethod
    def name_must_be_proper(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name cannot be blank")
        return v.strip()
    
    # ── Model-level validators (cross-field) ────────────────
    @model_validator(mode="after")
    def check_price_with_tax(self):
        if self.tax is not None and self.tax > self.price * 0.5:
            raise ValueError("Tax cannot exceed 50% of price")
        return self

# ── Computed fields ────────────────────────────────────────
from pydantic import computed_field

class Order(BaseModel):
    items: list[Item]
    discount: float = Field(default=0.0, ge=0.0, le=1.0)
    
    @computed_field
    @property
    def subtotal(self) -> float:
        return sum(item.price for item in self.items)
    
    @computed_field
    @property
    def total(self) -> float:
        return self.subtotal * (1 - self.discount) * 1.1  # 10% tax

# ── Discriminated unions (polymorphic models) ──────────────
from typing import Annotated, Literal
from pydantic import Discriminator

class Cat(BaseModel):
    pet_type: Literal["cat"]
    meows: int

class Dog(BaseModel):
    pet_type: Literal["dog"]
    barks: int

def get_pet_discriminator(v: dict) -> str:
    if isinstance(v, dict):
        return v.get("pet_type")
    return getattr(v, "pet_type")

Pet = Annotated[Cat | Dog, Discriminator(get_pet_discriminator)]

class Zoo(BaseModel):
    pets: list[Pet]

# Usage:
# zoo = Zoo(pets=[{"pet_type": "cat", "meows": 3}, {"pet_type": "dog", "barks": 2}])
```

### Serialization & Deserialization

```python
# ── Custom JSON encoding ───────────────────────────────────
from pydantic import field_serializer
from datetime import datetime
import json

class Event(BaseModel):
    name: str
    timestamp: datetime
    
    @field_serializer("timestamp")
    def serialize_timestamp(self, dt: datetime) -> str:
        return dt.isoformat() + "Z"

# ── Custom root type ───────────────────────────────────────
class ErrorResponse(BaseModel):
    """Wraps a dict as the root of the response"""
    root: dict[str, str]
    
    def __getitem__(self, key):
        return self.root[key]

# ── Generics with Pydantic ─────────────────────────────────
from typing import Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")

class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int
    
    @model_validator(mode="after")
    def compute_pages(self):
        self.pages = (self.total + self.size - 1) // self.size
        return self

# Usage:
# @app.get("/items/", response_model=PaginatedResponse[Item])
```

---

## 4. Dependency Injection System

### Core Concepts

```python
# FastAPI's DI system is one of its most powerful features.
# Dependencies are callables that can have their own dependencies.

from fastapi import Depends, FastAPI, HTTPException, status
from typing import Annotated

app = FastAPI()

# ── Simple dependency (function) ───────────────────────────
async def get_db():
    """Yields a database session — handles cleanup via try/finally"""
    db = DatabaseSession()
    try:
        yield db
    finally:
        db.close()

# ── Dependency with parameters ─────────────────────────────
def pagination(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> tuple[int, int]:
    skip = (page - 1) * size
    return skip, size

# ── Using dependencies ─────────────────────────────────────
@app.get("/items/")
async def list_items(
    db: Annotated[DatabaseSession, Depends(get_db)],
    pagination: Annotated[tuple[int, int], Depends(pagination)],
):
    skip, limit = pagination
    return await db.fetch_all("SELECT * FROM items LIMIT $1 OFFSET $2", limit, skip)
```

### Advanced DI Patterns

```python
# ── Class-based dependencies ───────────────────────────────
class AuthDependency:
    """Class-based dependency with state"""
    
    def __init__(self, required_role: str = "user"):
        self.required_role = required_role
    
    async def __call__(self, request: Request):
        token = request.headers.get("Authorization")
        if not token:
            raise HTTPException(status_code=401)
        
        user = await verify_token(token)
        if user.role != self.required_role:
            raise HTTPException(status_code=403)
        
        return user

require_admin = AuthDependency(required_role="admin")

@app.get("/admin/")
async def admin_endpoint(user: Annotated[User, Depends(require_admin)]):
    return {"admin": user.email}

# ── Dependency with internal dependencies ─────────────────
class Pagination:
    """Dependency class that itself depends on other dependencies"""
    
    def __init__(self, page: int = 1, size: int = 20):
        self.page = page
        self.size = size
        self.skip = (page - 1) * size
    
    @classmethod
    async def from_query(
        cls,
        page: int = Query(1, ge=1),
        size: int = Query(20, ge=1, le=100),
    ):
        return cls(page=page, size=size)

@app.get("/items/")
async def list_items(p: Annotated[Pagination, Depends(Pagination.from_query)]):
    return {"skip": p.skip, "limit": p.size}

# ── Sub-dependencies (dependency graph) ────────────────────
async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Top-level auth dependency"""
    payload = decode_jwt(token)
    user = await db.get_user(payload["sub"])
    if not user:
        raise HTTPException(status_code=401)
    return user

async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Sub-dependency that depends on get_current_user"""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def get_current_active_superuser(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    """Another layer of dependency"""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return current_user

@app.get("/users/me")
async def read_own_items(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    return {"user": current_user}

# ── Dependencies with yield (context managers) ─────────────
async def get_db_session():
    """Provides a DB session with automatic cleanup"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

async def transactional(
    db: Annotated[Session, Depends(get_db_session)],
):
    """Wraps operations in a transaction"""
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

@app.post("/items/")
async def create_item(
    item: Item,
    db: Annotated[Session, Depends(transactional)],
):
    db.add(item)
    return item  # Auto-committed by the transaction dependency

# ── Global dependencies (apply to all routes) ──────────────
app = FastAPI(dependencies=[Depends(verify_api_key)])

# Or per-router:
router = APIRouter(dependencies=[Depends(rate_limiter)])

# ── Cached dependencies (singleton per request) ────────────
# FastAPI caches dependencies by default within the same request!
async def get_db():
    """Called once per request — result is cached"""
    return Database()

async def get_repo(db: Annotated[Database, Depends(get_db)]):
    """Uses the same db instance — no second call"""
    return Repository(db)

# Both depends(get_db) in get_repo and depends(get_repo) in the
# view will share the SAME db instance for the same request.
```

### DI Lifecycle & Caching

```python
# ── How FastAPI caches dependencies ────────────────────────
# FastAPI uses a DAG (Directed Acyclic Graph) for dependencies.
# Within the same request, each dependency is called only once,
# and its result is cached and reused.

# This means:
# - Multiple routes can share the same dependency without redundant calls
# - Dependencies can be called at different levels (router, app, path)
# - The cache is per-request, not global

# ── Use Depends() vs Depends for singleton vs callable ────
# Depends(some_function)  → Calls some_function each time
# Depends(SomeClass())    → Uses the SAME instance always
# Depends(SomeClass)      → Calls SomeClass() each time (new instance)

# ── Async vs Sync dependencies ─────────────────────────────
# FastAPI can mix sync and async dependencies:
def sync_dep():
    return "sync"

async def async_dep():
    return "async"

# FastAPI runs sync deps in a thread pool to avoid blocking
```

---

## 5. Async Support & Concurrency

### The Async View Model

```python
import asyncio
from fastapi import FastAPI

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

# ── When to use async ──────────────────────────────────────
# USE async for:
#   - Database queries (async ORM like SQLAlchemy 2.0 async)
#   - API calls (httpx.AsyncClient)
#   - File I/O (aiofiles)
#   - Long-running operations with asyncio.sleep
#   - WebSockets

# USE sync for:
#   - CPU-bound operations (better to use thread pool)
#   - Simple CRUD with sync libraries
#   - Legacy code

# ── The thread pool ────────────────────────────────────────
# FastAPI runs sync path operations in a thread pool.
# You can also submit work explicitly:

from concurrent.futures import ThreadPoolExecutor
import asyncio

executor = ThreadPoolExecutor(max_workers=10)

@app.post("/process")
async def process_data(data: dict):
    # Run CPU-bound work in thread pool
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        executor, cpu_intensive_task, data
    )
    return {"result": result}
```

### Concurrent Processing Patterns

```python
# ── Parallel API calls ─────────────────────────────────────
import httpx
import asyncio

@app.get("/dashboard")
async def get_dashboard():
    """Fetch multiple sources concurrently"""
    async with httpx.AsyncClient() as client:
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

# ── Pitfall 2: Shared mutable state ────────────────────────
shared_list: list = []  # 🔴 Not thread-safe!

@app.post("/add")
async def add_item(item: str):
    shared_list.append(item)  # Race condition!
    return {"items": shared_list}

# ✅ Fix: Use asyncio.Lock or database
lock = asyncio.Lock()

@app.post("/add-safe")
async def add_item_safe(item: str):
    async with lock:
        shared_list.append(item)
        return {"items": shared_list.copy()}

# ── Pitfall 3: Database connections ────────────────────────
# Don't create connections per-request without pooling
# Use connection pools (SQLAlchemy, asyncpg, aioredis)
```

---

## 6. Middleware & Lifecycle Events

### Custom Middleware

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

class RequestIDMiddleware(BaseHTTPMiddleware):
    """Adds a unique request ID to each request"""
    
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        
        return response

# ── CORS middleware ────────────────────────────────────────
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://myfrontend.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── TrustedHost middleware ─────────────────────────────────
from fastapi.middleware.trustedhost import TrustedHostMiddleware

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["example.com", "*.example.com"],
)

# ── GZip middleware ────────────────────────────────────────
from fastapi.middleware.gzip import GZipMiddleware

app.add_middleware(GZipMiddleware, minimum_size=1000)

# ── Register middleware ────────────────────────────────────
app.add_middleware(TimingMiddleware)
app.add_middleware(RequestIDMiddleware)
```

### Lifecycle Events

```python
# ── Startup and shutdown events ────────────────────────────
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager (FastAPI 2.0+).
    Replaces the deprecated on_event("startup")/on_event("shutdown").
    """
    # ── Startup ────────────────────────────────────────────
    logger.info("Starting up...")
    app.state.db = await create_database_pool()
    app.state.cache = await create_cache_client()
    app.state.ml_model = await load_ml_model()
    logger.info("Startup complete")
    
    yield  # App runs here
    
    # ── Shutdown ───────────────────────────────────────────
    logger.info("Shutting down...")
    await app.state.db.close()
    await app.state.cache.close()
    logger.info("Shutdown complete")

app = FastAPI(lifespan=lifespan)

# ── Access app state in routes ─────────────────────────────
@app.get("/health")
async def health(request: Request):
    db_ok = await request.app.state.db.health_check()
    cache_ok = await request.app.state.cache.ping()
    return {
        "database": "healthy" if db_ok else "unhealthy",
        "cache": "healthy" if cache_ok else "unhealthy",
    }
```

---

## 7. Security & Authentication

### OAuth2 with JWT

```python
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional
import secrets

# ── Password hashing ───────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

# ── JWT tokens ─────────────────────────────────────────────
SECRET_KEY = secrets.token_urlsafe(32)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Decode JWT and return current user"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = await get_user(user_id)
    if user is None:
        raise credentials_exception
    return user

# ── Token endpoint ─────────────────────────────────────────
@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    
    access_token = create_access_token(
        data={"sub": user.id, "scopes": user.scopes},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": access_token, "token_type": "bearer"}

# ── Protected endpoint ─────────────────────────────────────
@app.get("/users/me")
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user
```

### API Key Authentication

```python
from fastapi.security import APIKeyHeader, APIKeyQuery, APIKeyCookie

api_key_header = APIKeyHeader(name="X-API-Key")
api_key_query = APIKeyQuery(name="api_key")

async def verify_api_key(
    api_key_header: str = Security(api_key_header),
    api_key_query: str = Security(api_key_query),
):
    """Verify API key from header or query parameter"""
    api_key = api_key_header or api_key_query
    if not api_key:
        raise HTTPException(status_code=401, detail="API key required")
    
    key_data = await get_api_key_data(api_key)
    if not key_data:
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    return key_data

# ── Scoped API keys ────────────────────────────────────────
@dataclass
class APIKeyData:
    key: str
    user_id: str
    scopes: list[str]
    rate_limit: int  # requests per minute

async def require_scope(required_scope: str):
    """Dependency factory that requires a specific scope"""
    async def scope_checker(api_key: APIKeyData = Depends(verify_api_key)):
        if required_scope not in api_key.scopes:
            raise HTTPException(status_code=403, detail=f"Scope '{required_scope}' required")
        return api_key
    return scope_checker

# Usage:
# @app.get("/admin/data")
# async def admin_data(key: APIKeyData = Depends(require_scope("admin:read"))):
#     ...
```

---

## 8. Database Integration & Sessions

### SQLAlchemy 2.0 Async

```python
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker, AsyncAttrs
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import select, text

# ── Engine & session setup ─────────────────────────────────
DATABASE_URL = "postgresql+asyncpg://user:pass@localhost/db"
engine = create_async_engine(
    DATABASE_URL,
    echo=True,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,  # Connection health check
)
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
async def get_db() -> AsyncSession:
    """Provides a database session with automatic cleanup"""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()

# ── CRUD operations ────────────────────────────────────────
from sqlalchemy import select
from typing import Annotated

db_dep = Annotated[AsyncSession, Depends(get_db)]

class UserRepository:
    """Repository pattern for database operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)
    
    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()
    
    async def list_active(self, skip: int = 0, limit: int = 20) -> list[User]:
        result = await self.session.execute(
            select(User)
            .where(User.is_active == True)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())
    
    async def create(self, user: User) -> User:
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user
    
    async def update(self, user: User, **kwargs) -> User:
        for key, value in kwargs.items():
            setattr(user, key, value)
        await self.session.commit()
        await self.session.refresh(user)
        return user
    
    async def delete(self, user: User) -> None:
        await self.session.delete(user)
        await self.session.commit()

@app.get("/users/{user_id}")
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
async def transactional(db: AsyncSession = Depends(get_db)):
    """Dependency that manages transactions"""
    try:
        yield db
        await db.commit()
    except Exception:
        await db.rollback()
        raise
```

### Redis Integration

```python
import redis.asyncio as aioredis
from typing import Optional
import json

class CacheService:
    """Async Redis cache service"""
    
    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self.redis: Optional[aioredis.Redis] = None
    
    async def connect(self):
        self.redis = await aioredis.from_url(
            self.redis_url,
            max_connections=50,
            decode_responses=True,
        )
    
    async def disconnect(self):
        if self.redis:
            await self.redis.close()
    
    async def get(self, key: str) -> Optional[str]:
        return await self.redis.get(key)
    
    async def set(self, key: str, value: str, expire: int = 300):
        await self.redis.set(key, value, ex=expire)
    
    async def delete(self, key: str):
        await self.redis.delete(key)
    
    async def get_or_compute(
        self, key: str, compute_fn, expire: int = 300
    ):
        """Cache-aside pattern"""
        cached = await self.get(key)
        if cached:
            return json.loads(cached)
        
        value = await compute_fn()
        await self.set(key, json.dumps(value), expire)
        return value

# ── Dependency ─────────────────────────────────────────────
async def get_cache() -> CacheService:
    return request.app.state.cache
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

# ── Background tasks with dependencies ─────────────────────
async def process_upload(
    file_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """Runs after response — keeps DB session alive"""
    # Process file...
    await update_file_status(db, file_id, "completed")

@app.post("/upload")
async def upload_file(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: db_dep,
):
    file_id = str(uuid.uuid4())
    await save_file_metadata(db, file_id, file.filename)
    
    # The task receives dependencies via closure
    background_tasks.add_task(process_upload, file_id, db)
    
    return {"file_id": file_id}

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
@app.websocket("/ws/chat")
async def chat_websocket(
    websocket: WebSocket,
    token: str = Query(...),
):
    # Authenticate before accepting
    user = await verify_token(token)
    if not user:
        await websocket.close(code=4001)
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
            self.active_connections.get(room, set()).discard(websocket)
            if not self.active_connections.get(room):
                del self.active_connections[room]
    
    async def broadcast(self, room: str, message: dict):
        """Send message to all clients in a room"""
        async with self._lock:
            for ws in self.active_connections.get(room, set()).copy():
                try:
                    await ws.send_json(message)
                except WebSocketDisconnect:
                    self.active_connections[room].discard(ws)

manager = ConnectionManager()

@app.websocket("/ws/room/{room_id}")
async def room_websocket(
    websocket: WebSocket,
    room_id: str,
    user: User = Depends(get_current_user),  # Auth via query param
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
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello World"}

# ── Async tests ───────────────────────────────────────────
@pytest.mark.asyncio
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

app.dependency_overrides[get_db] = override_get_db

def test_with_mock_db():
    client = TestClient(app)
    response = client.get("/items/")
    assert response.status_code == 200

# ── Clean up overrides ────────────────────────────────────
@pytest.fixture
def client():
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()

# ── Test authentication ───────────────────────────────────
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
def test_websocket():
    client = TestClient(app)
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
    """Profile specific endpoints"""
    
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
# 1. Use selectinload/eager loading for relationships
# 2. Use only() / load_only() to select specific columns
# 3. Use limit/offset for pagination
# 4. Use connection pooling with proper pool size
# 5. Use indexing on frequently queried columns
```

### Response Compression & Caching

```python
from fastapi.responses import ORJSONResponse
import orjson

# ── Use ORJSON for faster serialization ────────────────────
app = FastAPI(default_response_class=ORJSONResponse)

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
    item = await get_item(item_id)
    item_json = item.model_dump_json()
    etag = hashlib.md5(item_json.encode()).hexdigest()
    
    if if_none_match == etag:
        return Response(status_code=304)  # Not Modified
    
    return Response(
        content=item_json,
        media_type="application/json",
        headers={"ETag": etag},
    )
```

### Async Performance Patterns

```python
# ── Process large datasets in chunks ──────────────────────
@app.get("/process-large")
async def process_large_dataset():
    """Process millions of rows without memory overflow"""
    results = []
    async for batch in fetch_large_dataset_batches(batch_size=1000):
        processed = await process_batch(batch)
        results.extend(processed)
    return {"count": len(results), "results": results[:100]}

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

```python
# ── Uvicorn (most common) ─────────────────────────────────
# uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4

# ── Gunicorn with Uvicorn workers ─────────────────────────
# gunicorn main:app \
#     --worker-class uvicorn.workers.UvicornWorker \
#     --workers 8 \
#     --bind 0.0.0.0:8000 \
#     --timeout 120 \
#     --keepalive 5 \
#     --max-requests 1000 \
#     --max-requests-jitter 50

# ── Uvicorn with Gunicorn (recommended) ──────────────────
# Run: gunicorn -k uvicorn.workers.UvicornWorker main:app

# ── Hypercorn (supports HTTP/2, WebSocket) ─────────────────
# hypercorn main:app --bind 0.0.0.0:8000 --worker-class uvloop

# ── Supervisor/Systemd for process management ─────────────
# [Unit]
# Description=FastAPI Application
# After=network.target
#
# [Service]
# User=www-data
# WorkingDirectory=/opt/app
# ExecStart=/opt/app/venv/bin/uvicorn main:app --workers 4
# Restart=always
# RestartSec=10
# Environment=PYTHONPATH=/opt/app
#
# [Install]
# WantedBy=multi-user.target
```

### Configuration Management

```python
# ── Pydantic Settings ──────────────────────────────────────
from pydantic_settings import BaseSettings
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
    secret_key: str
    access_token_expire_minutes: int = 30
    
    # External APIs
    openai_api_key: str = ""
    sentry_dsn: str = ""
    
    # Rate limiting
    rate_limit_per_minute: int = 60
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

@lru_cache()
def get_settings() -> Settings:
    """Singleton settings — cached for performance"""
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
# ── Complete production middleware ─────────────────────────
app = FastAPI(
    lifespan=lifespan,
    docs_url=None if is_production else "/docs",  # Disable in prod
    redoc_url=None if is_production else "/redoc",
)

# Security first
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Performance
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Observability
app.add_middleware(TimingMiddleware)
app.add_middleware(RequestIDMiddleware)

# Rate limiting
app.add_middleware(RateLimitMiddleware, rate_limit=settings.rate_limit_per_minute)

# ── Error handling ─────────────────────────────────────────
@app.exception_handler(ValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": exc.body},
    )

@app.exception_handler(RequestValidationError)
async def request_validation_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content={
            "detail": exc.errors(),
            "body": exc.body,
            "request_id": request.state.request_id,
        },
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "request_id": request.state.request_id,
        },
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "request_id": request.state.request_id,
        },
    )
```

---

## 13. OpenAPI & Documentation Customization

### Customizing the OpenAPI Schema

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
from dataclasses import dataclass
from typing import Optional

@dataclass
class CreateItemRequest:
    name: str
    price: float
    tax: Optional[float] = None

class ItemService:
    """Business logic for items"""
    
    def __init__(self, db: AsyncSession, cache: CacheService):
        self.db = db
        self.cache = cache
        self.repo = ItemRepository(db)
    
    async def create_item(self, request: CreateItemRequest) -> Item:
        # Business validation
        if request.price < 0:
            raise ValueError("Price cannot be negative")
        if request.tax and request.tax > request.price:
            raise ValueError("Tax exceeds price")
        
        # Create
        item = Item(**request.dict())
        created = await self.repo.create(item)
        
        # Cache
        await self.cache.set(f"item:{created.id}", created.model_dump_json())
        
        return created
    
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
@router.post("/items/")
async def create_item(
    request: CreateItemRequest,
    service: ItemService = Depends(get_item_service),
):
    try:
        item = await service.create_item(request)
        return item
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
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
def get_item_repository(
    db: AsyncSession = Depends(get_db),
) -> Repository[Item]:
    if settings.environment == "test":
        return InMemoryItemRepository()
    return PostgresItemRepository(db)
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
- **Performance:** Significantly faster — on par with Node.js and Go (Flask is slower due to WSGI)
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

- **Sync views:** FastAPI runs them in a thread pool using `run_in_executor`. They don't block the main event loop.
- **Async views:** Run directly on the event loop. Best for I/O-bound operations (DB queries, API calls, file I/O).
- **Mixing:** You can mix both. Async views should not call blocking code directly.
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
    item_id: int = Path(..., ge=1),           # Path parameter
    q: str = Query(None, max_length=50),       # Query parameter
):
    """
    Get an item by ID.
    Returns the full item object with all fields.
    """
    return await get_item_from_db(item_id)
```

This generates complete OpenAPI 3.0 JSON, which Swagger UI and ReDoc render as interactive documentation.
</details>

<details>
<summary><b>Q5: How do you handle database transactions in FastAPI?</b></summary>

**Answer:** Using dependency injection with context managers:

```python
async def get_session():
    async with async_session() as session:
        yield session

async def transactional(db = Depends(get_session)):
    """Manages transaction lifecycle"""
    try:
        yield db
        await db.commit()
    except Exception:
        await db.rollback()
        raise

@app.post("/items")
async def create_item(
    item: Item,
    db = Depends(transactional),
):
    db.add(item)
    return item  # Auto-committed
```

For nested transactions, use savepoints within the same session.
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

# Clean up
def test_with_client():
    client = TestClient(app)
    response = client.get("/items")
    assert response.status_code == 200
    app.dependency_overrides.clear()

# Or use fixture
@pytest.fixture
def client():
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
```
</details>

<details>
<summary><b>Q7: What's the difference between BackgroundTasks and Celery for async work?</b></summary>

**Answer:**

| Feature | BackgroundTasks | Celery/ARQ |
|---------|-----------------|------------|
| **Execution** | Same process, after response | Separate worker processes |
| **Persistence** | In-memory only | Backed by Redis/RabbitMQ |
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
@app.post("/generate-report")
async def generate_report():
    task = generate_report.delay(params)
    return {"task_id": task.id}
```
</details>

### Advanced

<details>
<summary><b>Q8: Design a rate-limiting system for a FastAPI application handling 100K+ req/s.</b></summary>

**Answer:**

```python
# ── Token bucket with Redis ────────────────────────────────
import time
import hashlib

class SlidingWindowRateLimiter:
    """
    Sliding window counter using Redis sorted sets.
    More accurate than fixed window, less memory than exact sliding log.
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
    
    async def is_allowed(
        self, key: str, max_requests: int, window_seconds: int = 60
    ) -> bool:
        now = time.time()
        window_start = now - window_seconds
        
        pipe = self.redis.pipeline()
        # Remove old entries
        pipe.zremrangebyscore(key, 0, window_start)
        # Count current entries
        pipe.zcard(key)
        # Add current request
        pipe.zadd(key, {str(now): now})
        # Set TTL
        pipe.expire(key, window_seconds)
        
        _, count, _, _ = pipe.execute()
        
        return count < max_requests

# ── Middleware ──────────────────────────────────────────────
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limiting middleware"""
    
    def __init__(self, app, limiter: SlidingWindowRateLimiter):
        super().__init__(app)
        self.limiter = limiter
    
    async def dispatch(self, request: Request, call_next):
        # Rate limit by API key or IP
        api_key = request.headers.get("X-API-Key")
        key = f"ratelimit:{api_key or request.client.host}"
        
        if not await self.limiter.is_allowed(key, max_requests=100):
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "retry_after": 60,
                },
                headers={"Retry-After": "60"},
            )
        
        return await call_next(request)
```

Key considerations:
- Use Redis sorted sets or sliding window counter
- Tiered limits per API key (free: 10/min, pro: 1000/min)
- Use `Retry-After` header for client-side backoff
- Distribute rate limit state across Redis cluster
- Use approximate counting (HyperLogLog) for ultra-high-scale
</details>

<details>
<summary><b>Q9: How would you implement a CQRS pattern with FastAPI?</b></summary>

**Answer:**

```python
# ── Command side (writes) ──────────────────────────────────
@router.post("/orders")
async def create_order(
    command: CreateOrderCommand,
    uow: UnitOfWork = Depends(get_uow),
    event_bus: EventBus = Depends(get_event_bus),
):
    async with uow:
        order = Order.create(command.user_id, command.items)
        uow.orders.add(order)
        
        # Publish event for read model sync
        await event_bus.publish(OrderCreatedEvent(
            order_id=order.id,
            user_id=order.user_id,
            total=order.total,
        ))
    
    return OrderResponse.from_entity(order)

# ── Query side (reads from denormalized view) ─────────────
@router.get("/orders")
async def list_orders(
    user_id: int,
    query_service: OrderQueryService = Depends(),
):
    """Reads from pre-joined materialized view"""
    return await query_service.get_user_orders(user_id)

# ── Event handler (syncs read model) ──────────────────────
@event_bus.on(OrderCreatedEvent)
async def on_order_created(event: OrderCreatedEvent):
    """Update denormalized read model"""
    async with read_session() as session:
        summary = OrderSummary(
            order_id=event.order_id,
            user_id=event.user_id,
            total=event.total,
            status="pending",
        )
        session.add(summary)
        await session.commit()
```

Benefits:
- Read queries don't touch transactional tables
- Each side can be independently optimized
- Read replicas for scaling reads
- Different storage engines for different concerns
</details>

<details>
<summary><b>Q10: How do you handle graceful shutdown in FastAPI with in-flight requests?</b></summary>

**Answer:**

```python
import signal
import asyncio
from contextlib import asynccontextmanager

class GracefulShutdown:
    """Manages graceful shutdown with in-flight request tracking"""
    
    def __init__(self):
        self.active_requests = set()
        self.shutdown_event = asyncio.Event()
        self._lock = asyncio.Lock()
    
    async def track_request(self, request_id: str):
        async with self._lock:
            self.active_requests.add(request_id)
    
    async def complete_request(self, request_id: str):
        async with self._lock:
            self.active_requests.discard(request_id)
            if self.shutdown_event.is_set() and not self.active_requests:
                self.shutdown_event.set()  # Signal ready to shut down
    
    async def wait_for_drain(self, timeout: int = 30):
        """Wait for active requests to complete"""
        try:
            await asyncio.wait_for(
                self._wait_for_empty(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Drain timeout: {len(self.active_requests)} still active")
    
    async def _wait_for_empty(self):
        while self.active_requests:
            await asyncio.sleep(0.1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    shutdown = GracefulShutdown()
    app.state.shutdown = shutdown
    
    # Register signal handlers
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda: asyncio.create_task(shutdown.wait_for_drain())
        )
    
    yield
    
    # Shutdown
    await app.state.db.disconnect()
    await app.state.cache.disconnect()
    logger.info("Shutdown complete")

# Middleware to track requests
class RequestTrackerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = str(uuid.uuid4())
        await request.app.state.shutdown.track_request(request_id)
        try:
            return await call_next(request)
        finally:
            await request.app.state.shutdown.complete_request(request_id)
```
</details>

<details>
<summary><b>Q11: Design a multi-tenant FastAPI application with tenant isolation.</b></summary>

**Answer:**

```python
# ── Tenant resolution middleware ───────────────────────────
class TenantMiddleware(BaseHTTPMiddleware):
    """Resolves tenant from subdomain or header"""
    
    async def dispatch(self, request, call_next):
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
    """Routes to tenant-specific database"""
    
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
async def set_tenant_schema(tenant: Tenant, connection):
    """Set PostgreSQL search_path to tenant schema"""
    await connection.execute(
        text(f"SET search_path TO {tenant.schema_name}, public")
    )
```
</details>

<details>
<summary><b>Q12: How do you optimize a FastAPI endpoint that streams large amounts of data?</b></summary>

**Answer:**

```python
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
    return StreamingResponse(
        stream_items(fetch_all_items()),
        media_type="application/json",
        headers={
            "Transfer-Encoding": "chunked",
            "X-Content-Type-Options": "nosniff",
        },
    )

# ── Stream CSV ─────────────────────────────────────────────
async def stream_csv(query):
    """Stream CSV with headers"""
    yield "id,name,email\n"
    async for row in query:
        yield f"{row.id},{row.name},{row.email}\n"

@app.get("/export/users")
async def export_users(format: str = "csv"):
    generators = {"csv": stream_csv, "json": stream_json}
    content_type = {"csv": "text/csv", "json": "application/json"}
    
    return StreamingResponse(
        generators[format](fetch_users()),
        media_type=content_type[format],
        headers={"Content-Disposition": f"attachment; filename=users.{format}"},
    )

# ── Compression for streaming ──────────────────────────────
# Use nginx or CDN for compression (gzip/brotli)
# Don't compress in-app for streaming responses
```
</details>

<details>
<summary><b>Q13: Explain FastAPI's response_model and how it handles type coercion.</b></summary>

**Answer:** `response_model` defines the schema FastAPI uses for serialization and documentation:

```python
@app.get("/items", response_model=list[Item])
async def list_items():
    return await get_items()  # Auto-serialized to Item schema

@app.get("/items/{id}", response_model=Item)
async def get_item(id: int):
    return await get_item(id)

# ── response_model features:
# 1. Serialization: Converts ORM/DB models to Pydantic models
# 2. Filtering: Only includes fields defined in the model
# 3. Validation: Ensures response conforms to schema
# 4. Documentation: Used in OpenAPI response schema
# 5. Response filtering:
@app.get("/items/public", response_model=ItemPublic)
async def get_public_items():
    # ItemPublic might exclude 'internal_notes' field
    return await get_items()
    # Internal fields are automatically filtered out

# ── response_model_exclude_unset ──────────────────────────
@app.get(
    "/items/{id}",
    response_model=Item,
    response_model_exclude_unset=True,  # Skip default values
)
async def get_item(id: int):
    return await get_item(id)
    # Only returns fields that were explicitly set
```

**Type coercion:** FastAPI uses Pydantic's coercion rules:
- `int` fields receive string→int conversion
- `float` fields receive string→float conversion
- `bool` fields receive "true"/"false"→bool conversion
- `datetime` fields receive ISO format string→datetime conversion
- `list[int]` receives `[1, 2, "3"]` → `[1, 2, 3]` (each element coerced)
</details>

---

> *Built for experienced Python engineers targeting Staff/Principal roles at top-tier companies*
