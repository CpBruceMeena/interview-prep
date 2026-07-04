# 🐍 Django — Staff-Level Notes & Interview Questions

> **Deep-dive into Django's internals, ORM, request lifecycle, DRF, caching, async, and production patterns**
> *Designed for Staff/Principal Engineer interviews (10+ years experience)*

---

## Table of Contents

1. [Django ORM Deep Dive](#1-django-orm-deep-dive)
2. [Request Lifecycle & Middleware](#2-request-lifecycle--middleware)
3. [Django REST Framework (DRF)](#3-django-rest-framework-drf)
4. [Authentication & Authorization](#4-authentication--authorization)
5. [Database Migrations](#5-database-migrations)
6. [Caching Strategies](#6-caching-strategies)
7. [Celery & Async Tasks](#7-celery--async-tasks)
8. [Performance Optimization](#8-performance-optimization)
9. [Signals & Event-Driven Patterns](#9-signals--event-driven-patterns)
10. [Production Deployment](#10-production-deployment)
11. [Django Design Patterns](#11-django-design-patterns)
12. [Django Interview Questions](#12-django-interview-questions)

---

## 1. Django ORM Deep Dive

### QuerySet Internals

```python
# ── Lazy Evaluation ─────────────────────────────────────────
# QuerySets are lazy — they don't hit the database until evaluated.

qs = User.objects.filter(is_active=True)  # No query
qs = qs.filter(age__gte=18)              # Still no query
qs = qs.order_by('-created_at')          # Still no query
users = list(qs)                         # 🔥 Database hit!

# Evaluation triggers:
list(qs)          # ✅ Evaluate
for u in qs:      # ✅ Evaluate (if iterator exhausted)
bool(qs)          # ✅ Evaluate (checks .exists())
len(qs)           # ✅ Evaluate (unless cached)
qs[0:10]          # ✅ Evaluate (slicing)
qs.count()        # ✅ Evaluate (COUNT query)
qs.exists()       # ✅ Evaluate (LIMIT 1 query)

# ── QuerySet Caching ────────────────────────────────────────
# Once evaluated, QuerySets cache results:
qs = User.objects.filter(is_active=True)
users_1 = list(qs)  # Database hit — cached
users_2 = list(qs)  # ✅ No query — uses cached result

# ⚠️ But cache doesn't apply after slicing:
qs = User.objects.all()
users_1 = qs[0:5]   # SELECT ... LIMIT 5
users_2 = qs[0:5]   # SELECT ... LIMIT 5 (NOT cached!)

# ── Chaining vs Reevaluation ──────────────────────────────
# Each chained filter creates a NEW QuerySet (not mutable):
qs1 = User.objects.all()
qs2 = qs1.filter(age__gte=18)  # qs1 is unchanged!
# qs1 still returns ALL users
```

### N+1 Query Problem

```python
# 🔴 N+1: One query for authors, N queries for books
class Author(models.Model):
    name = models.CharField(max_length=100)

class Book(models.Model):
    author = models.ForeignKey(Author, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)

def list_books():
    books = Book.objects.all()                          # 1 query
    for book in books:
        print(book.author.name)                         # N queries!
    # Total: 1 + N queries

# ✅ FIX: select_related (JOIN for ForeignKey/OneToOne)
def list_books_eager():
    books = Book.objects.select_related('author').all()  # 1 query with JOIN
    for book in books:
        print(book.author.name)                          # ✅ No query (cached)

# ✅ FIX: prefetch_related (separate query for ManyToMany/ reverse FK)
class Library(models.Model):
    name = models.CharField(max_length=100)
    books = models.ManyToManyField(Book)

def list_libraries():
    libraries = Library.objects.prefetch_related('books').all()  # 2 queries
    for lib in libraries:
        print([book.title for book in lib.books.all()])  # ✅ No extra queries

# ── Prefetch objects for custom querysets ───────────────────
from django.db.models import Prefetch

def prefetch_with_filter():
    popular_books = Prefetch(
        'books',
        queryset=Book.objects.filter(ratings__gte=4),
        to_attr='popular_books'
    )
    libraries = Library.objects.prefetch_related(popular_books).all()
    for lib in libraries:
        print(lib.popular_books)  # ✅ Pre-filtered and cached

# ── ONLY / DEFER ───────────────────────────────────────────
# Only load specific fields:
users = User.objects.only('id', 'email', 'username')
# SELECT id, email, username FROM users

# Load everything except certain fields:
users = User.objects.defer('bio', 'avatar')
# SELECT all_fields EXCEPT bio, avatar FROM users
```

### Aggregation & Annotation

```python
from django.db.models import Count, Sum, Avg, Max, Min, Q, F, Case, When, Value, IntegerField
from django.db.models.functions import ExtractYear, TruncMonth

# ── Basic Aggregation ───────────────────────────────────────
from django.db.models import Count

# Total count of books per author
authors = Author.objects.annotate(
    book_count=Count('books'),
    total_pages=Sum('books__pages'),
    avg_rating=Avg('books__rating'),
)

for author in authors:
    print(f"{author.name}: {author.book_count} books")

# ── Conditional Annotation ─────────────────────────────────
# Books with high ratings count
authors = Author.objects.annotate(
    high_rated_books=Count('books', filter=Q(books__rating__gte=4)),
    total_books=Count('books'),
)

# ── Case/When annotations ─────────────────────────────────
authors = Author.objects.annotate(
    popularity=Case(
        When(books__ratings__gte=4, then=Value('popular')),
        When(books__ratings__gte=3, then=Value('average')),
        default=Value('unpopular'),
        output_field=IntegerField(),
    )
)

# ── F Expressions (reference fields) ───────────────────────
# Update without race conditions
Book.objects.filter(id=1).update(
    sales=F('sales') + 1,  # Atomic increment in database
    updated_at=Now(),
)

# ── Window Functions (PostgreSQL) ─────────────────────────
from django.db.models import Window, RowNumber, Rank

books = Book.objects.annotate(
    rank=Window(
        expression=RowNumber(),
        partition_by=[F('author_id')],
        order_by=F('sales').desc(),
    )
)
```

### Transactions

```python
from django.db import transaction

# ── Atomic transactions ─────────────────────────────────────
@transaction.atomic
def transfer_funds(from_id, to_id, amount):
    """Either all operations succeed, or none do."""
    from_acct = Account.objects.select_for_update().get(id=from_id)
    to_acct = Account.objects.select_for_update().get(id=to_id)
    
    if from_acct.balance < amount:
        raise ValueError("Insufficient funds")
    
    from_acct.balance -= amount
    to_acct.balance += amount
    from_acct.save()
    to_acct.save()

# ── Savepoints (nested transactions) ───────────────────────
@transaction.atomic
def process_order(order_id):
    order = Order.objects.get(id=order_id)
    
    try:
        with transaction.atomic():
            charge_payment(order)
            update_inventory(order)
    except Exception:
        # Only the payment/inventory operations revert
        # The order status change below persists
        pass
    
    order.status = 'failed'
    order.save()

# ── select_for_update (row-level locking) ──────────────────
with transaction.atomic():
    # Locks row until transaction commits — prevents race conditions
    account = Account.objects.select_for_update().get(id=account_id)
    account.balance -= amount
    account.save()
    # Lock is released when the transaction block exits

# ── Transaction hooks ───────────────────────────────────────
@transaction.atomic
def create_user_and_send_email(data):
    user = User.objects.create(**data)
    
    # This runs after the transaction commits
    transaction.on_commit(lambda: send_welcome_email(user.id))
    
    return user
```

### Advanced ORM Techniques

```python
# ── Subqueries ──────────────────────────────────────────────
from django.db.models import Subquery, OuterRef

# Books with their author's latest book date
latest_book = Book.objects.filter(
    author=OuterRef('author')
).order_by('-published_date')

authors = Author.objects.annotate(
    latest_book_date=Subquery(latest_book.values('published_date')[:1])
)

# ── CTE (Common Table Expressions) — PostgreSQL ──────────
from django.db.models import Window, RowNumber

# ── Raw SQL when ORM isn't enough ─────────────────────────
def heavy_report(start_date, end_date):
    return Book.objects.raw("""
        SELECT 
            a.id, a.name,
            COUNT(b.id) as book_count,
            AVG(b.rating) as avg_rating
        FROM books_book b
        JOIN books_author a ON b.author_id = a.id
        WHERE b.published_date BETWEEN %s AND %s
        GROUP BY a.id, a.name
        HAVING COUNT(b.id) > 5
        ORDER BY avg_rating DESC
    """, [start_date, end_date])
```

---

## 2. Request Lifecycle & Middleware

### Request Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Django Request Lifecycle                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  HTTP Request                                                    │
│      │                                                           │
│      ▼                                                           │
│  WSGI Handler (e.g., Gunicorn, uWSGI)                           │
│      │                                                           │
│      ▼                                                           │
│  Django WSGI Handler (django.core.handlers.wsgi.WSGIHandler)    │
│      │                                                           │
│      ▼                                                           │
│  Request Middleware (process_request) → returns None or Response │
│      │                                                           │
│      ▼                                                           │
│  URL Router (urls.py → resolves to view function)                │
│      │                                                           │
│      ▼                                                           │
│  View Middleware (process_view) → returns None or Response       │
│      │                                                           │
│      ▼                                                           │
│  View Function / Class-Based View                                │
│      │                                                           │
│      ├──→ Middleware (process_template_response)                 │
│      │                                                           │
│      ▼                                                           │
│  Response Middleware (process_response)                          │
│      │                                                           │
│      ▼                                                           │
│  HTTP Response                                                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Custom Middleware

```python
# ── Middleware Types ─────────────────────────────────────────
# Django supports two middleware styles:
# 1. Old-style: class with methods (process_request, process_response, etc.)
# 2. New-style: __call__ (function-style, Django 1.10+)

# ── New-style middleware (recommended) ──────────────────────
import time
import logging
from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)

class RequestTimingMiddleware:
    """Measure and log request duration"""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Pre-processing (process_request equivalent)
        request.start_time = time.perf_counter()
        
        # Get response from view
        response = self.get_response(request)
        
        # Post-processing (process_response equivalent)
        duration = time.perf_counter() - request.start_time
        response['X-Request-Duration'] = str(duration)
        
        if duration > 1.0:
            logger.warning(
                "Slow request: %s %s took %.2fs",
                request.method, request.path, duration
            )
        
        return response

# ── Process view middleware (access view function) ─────────
class PermissionEnforcementMiddleware:
    """Check permissions before view execution"""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        return self.get_response(request)
    
    def process_view(self, request, view_func, view_args, view_kwargs):
        """Called just before the view is called"""
        # Check if view requires special permission
        required_perm = getattr(view_func, 'required_permission', None)
        if required_perm and not request.user.has_perm(required_perm):
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden("Permission denied")
        
        return None  # Continue to view

# ── Exception middleware ────────────────────────────────────
class ExceptionHandlingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        return self.get_response(request)
    
    def process_exception(self, request, exception):
        """Handle unhandled exceptions"""
        logger.exception("Unhandled exception: %s", exception)
        # Could return a custom error response
        from django.http import JsonResponse
        return JsonResponse(
            {"error": "Internal server error"},
            status=500,
        )

# ── Middleware ordering ─────────────────────────────────────
# Settings:
# MIDDLEWARE = [
#     'django.middleware.security.SecurityMiddleware',       # 1st (security)
#     'django.contrib.sessions.middleware.SessionMiddleware', # 2nd (session)
#     'django.middleware.common.CommonMiddleware',            # 3rd (common)
#     'django.middleware.csrf.CsrfViewMiddleware',            # 4th (CSRF)
#     'django.contrib.auth.middleware.AuthenticationMiddleware', # 5th (auth)
#     'django.contrib.messages.middleware.MessageMiddleware',  # 6th (messages)
#     'myapp.middleware.RequestTimingMiddleware',              # Custom
# ]
```

### ORM Query Analysis Middleware

```python
from django.db import connection
import logging

logger = logging.getLogger('django.db.backends')

class QueryCountDebugMiddleware:
    """Log number of queries per request — detect N+1 in development"""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        response = self.get_response(request)
        
        num_queries = len(connection.queries)
        
        if num_queries > 20:
            logger.warning(
                "High query count (%d) for %s %s",
                num_queries, request.method, request.path
            )
            
            if request.user.is_staff:
                # Show queries in response headers for debugging
                response['X-Query-Count'] = num_queries
        
        return response
```

---

## 3. Django REST Framework (DRF)

### ViewSets & Serializers

```python
from rest_framework import viewsets, serializers, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Prefetch, Count

# ── ModelSerializer with validation ────────────────────────
class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    book_count = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = User
        fields = [
            'id', 'email', 'username', 'full_name',
            'book_count', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {
            'email': {'validators': [validate_email]},
        }
    
    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()
    
    def validate_email(self, value):
        if not value.endswith('@company.com'):
            raise serializers.ValidationError("Must use company email")
        return value
    
    def validate(self, data):
        # Cross-field validation
        if data.get('password') != data.get('password_confirm'):
            raise serializers.ValidationError("Passwords don't match")
        return data

# ── ViewSet with optimization ──────────────────────────────
class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        # Base queryset with optimization
        qs = User.objects.select_related('profile').prefetch_related(
            Prefetch(
                'books',
                queryset=Book.objects.only('id', 'title'),
            )
        )
        
        # Filtering
        if self.request.query_params.get('active'):
            qs = qs.filter(is_active=True)
        
        # Annotations
        qs = qs.annotate(book_count=Count('books'))
        
        return qs
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        user = self.get_object()
        user.is_active = True
        user.save(update_fields=['is_active'])
        return Response({'status': 'activated'})
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        return Response({
            'total_users': User.objects.count(),
            'active_users': User.objects.filter(is_active=True).count(),
        })

# ── Pagination ──────────────────────────────────────────────
from rest_framework.pagination import PageNumberPagination

class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

# ── Filtering with django-filter ────────────────────────────
from django_filters import rest_framework as filters

class BookFilter(filters.FilterSet):
    min_rating = filters.NumberFilter(field_name='rating', lookup_expr='gte')
    max_rating = filters.NumberFilter(field_name='rating', lookup_expr='lte')
    published_after = filters.DateFilter(field_name='published_date', lookup_expr='gte')
    author_name = filters.CharFilter(field_name='author__name', lookup_expr='icontains')
    
    class Meta:
        model = Book
        fields = ['genre', 'author', 'min_rating', 'max_rating']
```

### Performance Optimizations for DRF

```python
# ── 1. Select only needed fields ───────────────────────────
# DON'T:
class BookViewSet(viewsets.ModelViewSet):
    queryset = Book.objects.all()  # Loads ALL columns

# DO:
class BookViewSet(viewsets.ModelViewSet):
    queryset = Book.objects.only('id', 'title', 'author__name').select_related('author')

# ── 2. Use serializers for write, not read ─────────────────
class BookListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views"""
    class Meta:
        model = Book
        fields = ['id', 'title', 'author_name']

class BookDetailSerializer(serializers.ModelSerializer):
    """Full serializer for detail views"""
    class Meta:
        model = Book
        fields = '__all__'

class BookViewSet(viewsets.ModelViewSet):
    def get_serializer_class(self):
        if self.action == 'list':
            return BookListSerializer
        return BookDetailSerializer

# ── 3. Bulk operations ─────────────────────────────────────
# Use bulk_create and bulk_update instead of individual saves
def bulk_create_books(author, titles):
    books = [Book(author=author, title=title) for title in titles]
    return Book.objects.bulk_create(books)  # Single INSERT with N rows

# ── 4. Throttling ──────────────────────────────────────────
from rest_framework.throttling import UserRateThrottle

class BurstRateThrottle(UserRateThrottle):
    scope = 'burst'  # 60/min by default

class SustainedRateThrottle(UserRateThrottle):
    scope = 'sustained'  # 1000/day by default

# Settings:
# REST_FRAMEWORK = {
#     'DEFAULT_THROTTLE_CLASSES': [
#         'myapp.throttles.BurstRateThrottle',
#         'myapp.throttles.SustainedRateThrottle',
#     ],
#     'DEFAULT_THROTTLE_RATES': {
#         'burst': '60/minute',
#         'sustained': '1000/day',
#     },
# }

# ── 5. Caching responses ────────────────────────────────────
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers

class CachedBookViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Book.objects.select_related('author').all()
    serializer_class = BookListSerializer
    
    @method_decorator(cache_page(60 * 15))  # Cache for 15 min
    @method_decorator(vary_on_headers("Authorization"))
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
```

---

## 4. Authentication & Authorization

### Custom Authentication

```python
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.backends import BaseBackend
from rest_framework.authentication import BaseAuthentication

# ── Custom User Model (DO THIS FIRST!) ──────────────────────
class User(AbstractUser):
    """Extensible user model — always use this instead of default User"""
    email = models.EmailField(unique=True)
    organization = models.ForeignKey(
        'Organization', on_delete=models.CASCADE, null=True
    )
    role = models.CharField(
        max_length=20,
        choices=[
            ('admin', 'Admin'),
            ('editor', 'Editor'),
            ('viewer', 'Viewer'),
        ],
        default='viewer',
    )
    
    USERNAME_FIELD = 'email'  # Login with email instead of username
    REQUIRED_FIELDS = ['username']

# ── Multi-Factor Authentication Backend ─────────────────────
class EmailOrPhoneBackend(BaseBackend):
    """Authenticate with email OR phone number"""
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        # Allow login with email OR phone
        user = User.objects.filter(
            models.Q(email=username) | models.Q(phone=username)
        ).first()
        
        if user and user.check_password(password) and user.is_active:
            return user
        return None
    
    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None

# ── Token Authentication (DRF) ─────────────────────────────
from rest_framework.authtoken.models import Token
from rest_framework.authentication import TokenAuthentication

class ExpiringTokenAuthentication(TokenAuthentication):
    """Token with expiry"""
    
    def authenticate_credentials(self, key):
        try:
            token = Token.objects.select_related('user').get(key=key)
        except Token.DoesNotExist:
            raise AuthenticationFailed('Invalid token')
        
        if not token.user.is_active:
            raise AuthenticationFailed('User inactive or deleted')
        
        # Check token age (e.g., 30 days)
        if timezone.now() - token.created > timedelta(days=30):
            token.delete()
            raise AuthenticationFailed('Token has expired')
        
        return (token.user, token)
```

### Permission System

```python
from rest_framework.permissions import BasePermission

# ── Object-Level Permissions ────────────────────────────────
class IsOrganizationMember(BasePermission):
    """User must belong to same org as the object"""
    
    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False
        
        # Check if user belongs to the object's organization
        org = getattr(obj, 'organization', None)
        if org is None:
            return True  # Non-org objects are accessible
        
        return request.user.organization == org

class IsOwnerOrAdmin(BasePermission):
    """Only object owner or admin can modify"""
    
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Owner can always modify
        user = getattr(obj, 'user', None) or getattr(obj, 'author', None)
        if user == request.user:
            return True
        
        # Admin can modify anything
        return request.user.role == 'admin'

# ── Role-Based Permissions ─────────────────────────────────
class HasRole(BasePermission):
    """Check user role"""
    
    def __init__(self, allowed_roles):
        self.allowed_roles = allowed_roles
    
    def has_permission(self, request, view):
        return request.user.role in self.allowed_roles

# Usage:
# class AdminOnlyView(APIView):
#     permission_classes = [HasRole(['admin'])]

# ── Scope-Based Permissions (OAuth-style) ──────────────────
class HasScope(BasePermission):
    """Check JWT scopes"""
    
    def has_permission(self, request, view):
        if not request.auth:
            return False
        required = getattr(view, 'required_scopes', [])
        user_scopes = request.auth.get('scope', '').split()
        return all(scope in user_scopes for scope in required)
```

---

## 5. Database Migrations

### Advanced Migration Patterns

```python
# ── Data Migrations ─────────────────────────────────────────
# Generated with: python manage.py makemigrations --empty app_name

from django.db import migrations

def add_default_roles(apps, schema_editor):
    """Populate data as part of migration"""
    Role = apps.get_model('myapp', 'Role')
    
    roles = ['admin', 'editor', 'viewer']
    for role_name in roles:
        Role.objects.get_or_create(name=role_name, defaults={
            'description': f'{role_name.capitalize()} role',
        })

def reverse_roles(apps, schema_editor):
    """Reverse data migration"""
    Role = apps.get_model('myapp', 'Role')
    Role.objects.filter(name__in=['admin', 'editor', 'viewer']).delete()

class Migration(migrations.Migration):
    dependencies = [
        ('myapp', '0001_initial'),
    ]
    
    operations = [
        migrations.RunPython(add_default_roles, reverse_roles),
    ]

# ── Squashing Migrations (for performance) ─────────────────
# python manage.py squashmigrations myapp 0005
# Combines migrations 0001-0005 into a single migration

# ── Separate Databases (multiple DB support) ───────────────
class Router:
    """Route models to different databases"""
    
    def db_for_read(self, model, **hints):
        if model._meta.app_label == 'analytics':
            return 'analytics_replica'
        return 'default'
    
    def db_for_write(self, model, **hints):
        if model._meta.app_label == 'analytics':
            return 'analytics_primary'
        return 'default'
    
    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == 'analytics':
            return db == 'analytics_primary'
        return db == 'default'
```

### Migration Best Practices

```python
# ── 1. Always create a migration for EVERY model change ────
# python manage.py makemigrations
# python manage.py migrate

# ── 2. Test migrations on a copy of production data ────────
# python manage.py migrate --run-syncdb  # For development

# ── 3. Avoid RunPython in hot-path migrations ─────────────
# RunPython locks the table — use it carefully

# ── 4. Use --fake for partial migrations ──────────────────
# python manage.py migrate --fake myapp 0005
# Marks migration as applied without running it

# ── 5. Migration order in CI/CD ──────────────────────────
# manage.py migrate --plan  # Preview migrations
# manage.py migrate          # Apply them
```

---

## 6. Caching Strategies

### Cache Framework

```python
from django.core.cache import cache
from django.db.models import Q
import hashlib
import json

# ── Low-Level Cache API ─────────────────────────────────────
def get_user_stats(user_id: int) -> dict:
    cache_key = f'user_stats:{user_id}'
    stats = cache.get(cache_key)
    
    if stats is None:
        stats = compute_user_stats(user_id)
        cache.set(cache_key, stats, timeout=300)  # 5 minutes
    
    return stats

# ── Cache Versioning ────────────────────────────────────────
def invalidate_user_stats(user_id: int):
    cache.delete(f'user_stats:{user_id}')

# ── Cache with timeout and version ─────────────────────────
def get_cached_books(author_id: int, version: int = 1):
    cache_key = f'books:author:{author_id}:v{version}'
    books = cache.get(cache_key)
    
    if books is None:
        books = list(Book.objects.filter(author_id=author_id))
        cache.set(cache_key, books, timeout=60 * 15)
    
    return books

# ── Cache-Aside Pattern (Production Standard) ──────────────
class CachedManager:
    """Generic cache-aside pattern"""
    
    @staticmethod
    def get_or_compute(cache_key: str, compute_fn, timeout: int = 300):
        result = cache.get(cache_key)
        if result is not None:
            return result
        
        result = compute_fn()
        cache.set(cache_key, result, timeout)
        return result
    
    @staticmethod
    def invalidate(pattern: str):
        """Invalidate keys matching pattern (requires Redis)"""
        # With Redis:
        # for key in cache.keys(f"*{pattern}*"):
        #     cache.delete(key)
        pass

# Usage:
# def get_dashboard_data(user_id):
#     return CachedManager.get_or_compute(
#         f"dashboard:{user_id}",
#         lambda: compute_dashboard(user_id),
#         timeout=60
#     )
```

### Redis-Specific Patterns

```python
# ── Session Storage ─────────────────────────────────────────
# Settings:
# SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
# SESSION_CACHE_ALIAS = 'session'

# ── Cache Backend Configuration ─────────────────────────────
# CACHES = {
#     'default': {
#         'BACKEND': 'django.core.cache.backends.redis.RedisCache',
#         'LOCATION': 'redis://127.0.0.1:6379/1',
#         'OPTIONS': {
#             'CLIENT_CLASS': 'django_redis.client.DefaultClient',
#             'CONNECTION_POOL_CLASS': 'redis.BlockingConnectionPool',
#             'CONNECTION_POOL_CLASS_KWARGS': {
#                 'max_connections': 100,
#                 'timeout': 20,
#             },
#         },
#     },
#     'session': {
#         'BACKEND': 'django.core.cache.backends.redis.RedisCache',
#         'LOCATION': 'redis://127.0.0.1:6379/2',
#     },
# }

# ── Rate Limiting with Redis ────────────────────────────────
import time

class RedisRateLimiter:
    def __init__(self, redis_client):
        self.redis = redis_client
    
    def is_rate_limited(self, key: str, max_requests: int, window: int = 60) -> bool:
        """Sliding window rate limiter"""
        now = int(time.time())
        window_key = f"ratelimit:{key}:{now // window}"
        
        pipe = self.redis.pipeline()
        pipe.incr(window_key)
        pipe.expire(window_key, window * 2)
        current = pipe.execute()[0]
        
        return current > max_requests
```

### Cache Invalidation Strategies

```python
# ── 1. TTL-based (time-to-live) ────────────────────────────
# Simplest: set a timeout and let the cache expire
cache.set(key, value, timeout=300)

# ── 2. Write-through (update cache on write) ───────────────
def update_book(book_id, data):
    book = Book.objects.get(id=book_id)
    for attr, value in data.items():
        setattr(book, attr, value)
    book.save()
    
    # Update cache immediately
    cache.set(f'book:{book_id}', book, timeout=300)

# ── 3. Write-invalidate (clear cache on write) ────────────
def update_book_and_invalidate(book_id, data):
    Book.objects.filter(id=book_id).update(**data)
    cache.delete(f'book:{book_id}')
    
    # Also invalidate related caches
    cache.delete_pattern(f'books:author:*')  # Requires Redis

# ── 4. Version-based (bump version on schema change) ──────
CACHE_VERSION = 2  # Bump when data format changes

def get_cached_data(key):
    return cache.get(f"{key}:v{CACHE_VERSION}")

def set_cached_data(key, value):
    cache.set(f"{key}:v{CACHE_VERSION}", value, timeout=300)
```

---

## 7. Celery & Async Tasks

### Celery Setup & Patterns

```python
# ── Celery App Configuration ────────────────────────────────
# celery_app.py
from celery import Celery
from celery.schedules import crontab

app = Celery('myproject')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Settings:
# CELERY_BROKER_URL = 'redis://localhost:6379/0'
# CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
# CELERY_TASK_SERIALIZER = 'json'
# CELERY_RESULT_SERIALIZER = 'json'
# CELERY_ACCEPT_CONTENT = ['json']
# CELERY_TASK_TRACK_STARTED = True
# CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes

# ── Basic Task ──────────────────────────────────────────────
from celery import shared_task
from django.core.mail import send_mail

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    rate_limit='100/h',
)
def send_welcome_email(self, user_id: int):
    """Send welcome email with retry logic"""
    try:
        user = User.objects.get(id=user_id)
        send_mail(
            'Welcome!',
            f'Hi {user.username}, welcome to our platform!',
            'noreply@example.com',
            [user.email],
            fail_silently=False,
        )
    except User.DoesNotExist:
        logger.error(f"User {user_id} not found")
    except Exception as exc:
        raise self.retry(exc=exc)  # Retry with backoff

# ── Chain Tasks ─────────────────────────────────────────────
from celery import chain, group, chord

@shared_task
def process_image(image_id: int):
    # Step 1: Download
    return image_id

@shared_task
def resize_image(image_id: int):
    # Step 2: Resize
    return image_id

@shared_task
def upload_to_cdn(image_id: int):
    # Step 3: Upload
    return f"Image {image_id} uploaded"

# Execute tasks sequentially
result = chain(
    process_image.s(image_id),
    resize_image.s(),
    upload_to_cdn.s()
).delay()

# Execute tasks in parallel
parallel = group(
    resize_image.s(img_id) for img_id in image_ids
)

# Execute parallel then aggregate
workflow = chord(
    header=[resize_image.s(i) for i in image_ids],
    body=generate_thumbnails.s()
)

# ── Periodic Tasks (Celery Beat) ────────────────────────────
# tasks.py
@shared_task
def cleanup_expired_sessions():
    """Run daily to clean up expired sessions"""
    Session.objects.filter(expire_date__lt=timezone.now()).delete()
    logger.info("Cleaned up expired sessions")

# celery beat schedule:
from celery.schedules import crontab

app.conf.beat_schedule = {
    'cleanup-sessions-every-day': {
        'task': 'myapp.tasks.cleanup_expired_sessions',
        'schedule': crontab(hour=3, minute=0),  # 3 AM daily
    },
    'generate-reports-weekly': {
        'task': 'myapp.tasks.generate_weekly_report',
        'schedule': crontab(hour=0, minute=0, day_of_week='monday'),
    },
}
```

### Task Monitoring & Error Handling

```python
# ── Task Progress Tracking ──────────────────────────────────
@shared_task(bind=True)
def long_running_task(self, data: list):
    """Report progress during task execution"""
    total = len(data)
    
    for i, item in enumerate(data):
        # Update task state
        self.update_state(
            state='PROGRESS',
            meta={
                'current': i + 1,
                'total': total,
                'percent': int((i + 1) / total * 100),
            }
        )
        process_item(item)
    
    return {'status': 'completed', 'total': total}

# ── Task with custom retry policy ───────────────────────────
@shared_task(
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_kwargs={'max_retries': 5},
    retry_backoff=True,           # Exponential backoff
    retry_backoff_max=600,        # Max 10 minutes
    retry_jitter=True,            # Add randomness to avoid thundering herd
)
def external_api_call(self, url: str):
    """Call external API with exponential backoff retry"""
    response = requests.post(url, timeout=30)
    response.raise_for_status()
    return response.json()
```

---

## 8. Performance Optimization

### Database Optimization

```python
# ── 1. Indexing Strategy ────────────────────────────────────
class Book(models.Model):
    title = models.CharField(max_length=200, db_index=True)
    author = models.ForeignKey(Author, on_delete=models.CASCADE, db_index=True)
    published_date = models.DateField(db_index=True)
    rating = models.FloatField(default=0.0)
    
    class Meta:
        indexes = [
            # Composite index for common query pattern
            models.Index(fields=['author', 'published_date']),
            # Partial index for active books
            models.Index(
                fields=['rating'],
                name='high_rated_books_idx',
                condition=Q(rating__gte=4.0),
            ),
        ]

# ── 2. Avoid COUNT(*) on large tables ──────────────────────
# Slow: User.objects.count()  # Full table scan on large table
# Fast: Use cached counter or estimated count

# ── 3. Batch Operations ────────────────────────────────────
# Slow:
for book in books:
    book.save()

# Fast:
Book.objects.bulk_update(books, ['title', 'rating'])

# ── 4. Use Iterator for Large QuerySets ────────────────────
# Slow (loads all into memory):
for book in Book.objects.all():
    process(book)

# Fast (streams from database):
for book in Book.objects.all().iterator(chunk_size=1000):
    process(book)
```

### Query Optimization

```python
# ── Use .values() and .values_list() when you only need fields ─
# Instead of loading full model instances:
user_ids = User.objects.filter(is_active=True).values_list('id', flat=True)

# ── Use .exists() instead of .count() > 0 ─────────────────
# Slow: if Book.objects.count() > 0:
# Fast: if Book.objects.exists():

# ── Use .first() instead of [0] ───────────────────────────
# Book.objects.all()[0]   # Loads all, then takes first
# Book.objects.first()    # LIMIT 1 query

# ── Avoid len() on evaluated QuerySets ────────────────────
# books = list(Book.objects.all())
# len(books)  # Fine, but already evaluated
# Better: Book.objects.count()

# ── Use select_related and prefetch_related aggressively ──
# Profile with: django-debug-toolbar or QueryCountDebugMiddleware
```

### Caching Optimization

```python
# ── Template Fragment Caching ──────────────────────────────
{% load cache %}
{% cache 300 sidebar request.user.id %}
    {% for book in user.recommended_books %}
        <div>{{ book.title }}</div>
    {% endfor %}
{% endcache %}

# ── View Caching ───────────────────────────────────────────
from django.views.decorators.cache import cache_page

@cache_page(60 * 15)  # Cache for 15 minutes
def book_list(request):
    books = Book.objects.select_related('author').all()
    return render(request, 'books.html', {'books': books})
```

---

## 9. Signals & Event-Driven Patterns

```python
from django.db.models.signals import post_save, post_delete, pre_save, m2m_changed
from django.dispatch import receiver, Signal
from django.core.cache import cache

# ── Custom Signal ───────────────────────────────────────────
book_published = Signal()

@receiver(book_published)
def notify_subscribers(sender, book, **kwargs):
    """Send notifications when a book is published"""
    subscribers = Subscriber.objects.filter(authors=book.author)
    for subscriber in subscribers:
        send_notification.delay(subscriber.id, book.id)

# ── Cache Invalidation on Save ─────────────────────────────
@receiver(post_save, sender=Book)
def invalidate_book_cache(sender, instance, **kwargs):
    """Invalidate cache when book is updated"""
    cache.delete(f'book:{instance.id}')
    cache.delete_pattern(f'books:author:{instance.author_id}:*')

# ── Denormalized Count on Many-to-Many ─────────────────────
@receiver(m2m_changed, sender=Library.books.through)
def update_book_count(sender, instance, action, **kwargs):
    """Update denormalized book count on library"""
    if action in ['post_add', 'post_remove', 'post_clear']:
        instance.book_count = instance.books.count()
        instance.save(update_fields=['book_count'])

# ── Signal Performance Warning ─────────────────────────────
# ⚠️ Signals are SYNCHRONOUS by default!
# Heavy signal handlers block the request-response cycle.
# Use Celery for expensive signal handlers:

@receiver(post_save, sender=Book)
def process_book_async(sender, instance, created, **kwargs):
    if created:
        # Defer to Celery — doesn't block response
        generate_book_preview.delay(instance.id)
```

---

## 10. Production Deployment

### Settings Management

```python
# ── Environment-Based Settings ──────────────────────────────
import environ
import os

env = environ.Env(
    DEBUG=(bool, False),
    DATABASE_URL=(str, 'sqlite:///db.sqlite3'),
    REDIS_URL=(str, 'redis://localhost:6379/0'),
    SECRET_KEY=(str, ''),
    ALLOWED_HOSTS=(list, ['localhost']),
    CORS_ALLOWED_ORIGINS=(list, ['http://localhost:3000']),
)

# Django Settings
SECRET_KEY = env('SECRET_KEY')
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env('ALLOWED_HOSTS')

DATABASES = {
    'default': env.db(),
}

CACHES = {
    'default': env.cache(),
}

# ── Security Settings (Production) ──────────────────────────
SECURE_SSL_REDIRECT = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
```

### Production WSGI & ASGI

```python
# ── Gunicorn Configuration (gunicorn.conf.py) ───────────────
# workers = multiprocessing.cpu_count() * 2 + 1
# worker_class = 'sync'
# timeout = 120
# keepalive = 5
# max_requests = 1000
# max_requests_jitter = 50
# 
# # Run: gunicorn myproject.wsgi:application -c gunicorn.conf.py

# ── ASGI (for async Django 3.0+) ───────────────────────────
# asgi.py
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
application = get_asgi_application()

# ── Uvicorn with Gunicorn (for async views) ───────────────
# gunicorn myproject.asgi:application -k uvicorn.workers.UvicornWorker
```

### Database Connection Pooling

```python
# ── PostgreSQL with PgBouncer or Django connection pooling ──
# Settings:
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': env('DB_NAME'),
#         'USER': env('DB_USER'),
#         'PASSWORD': env('DB_PASSWORD'),
#         'HOST': env('DB_HOST'),
#         'PORT': env('DB_PORT'),
#         'CONN_MAX_AGE': 60,  # Connection persistence (seconds)
#         'OPTIONS': {
#             'pool': {
#                 'min_size': 2,
#                 'max_size': 20,
#                 'timeout': 30,
#             },
#         },
#     }
# }

# ── Connection Health Checks ───────────────────────────────
from django.db import close_old_connections, connection
from django.db.utils import OperationalError

def health_check():
    try:
        connection.ensure_connection()
        return True
    except OperationalError:
        close_old_connections()
        return False
```

---

## 11. Django Design Patterns

### Service Layer Pattern

```python
# ── Fat Models, Thin Views → Service Layer ─────────────────
# Instead of putting business logic in views or models:

# services/book_service.py
from django.db import transaction
from django.core.cache import cache
from typing import Optional

class BookService:
    """Business logic for books — keeps views thin"""
    
    @staticmethod
    @transaction.atomic
    def create_book(author, title, genre, **kwargs) -> Book:
        """Create book with validation and side effects"""
        book = Book.objects.create(
            author=author,
            title=title,
            genre=genre,
            **kwargs,
        )
        
        # Side effects
        book.publish_event()
        cache.delete(f'author_books:{author.id}')
        
        return book
    
    @staticmethod
    def get_author_books(author_id: int) -> list[Book]:
        """Get cached author books"""
        cache_key = f'author_books:{author_id}'
        books = cache.get(cache_key)
        
        if books is None:
            books = list(
                Book.objects.filter(author_id=author_id)
                .select_related('author')
                .only('id', 'title', 'published_date')
            )
            cache.set(cache_key, books, timeout=300)
        
        return books
    
    @staticmethod
    @transaction.atomic
    def update_book_rating(book_id: int, rating: float) -> Book:
        """Update rating and author's average rating"""
        book = Book.objects.select_for_update().get(id=book_id)
        book.rating = rating
        book.save(update_fields=['rating'])
        
        # Update author's average rating
        Author.objects.filter(id=book.author_id).update(
            avg_rating=Avg('books__rating')
        )
        
        cache.delete(f'book:{book_id}')
        return book

# views.py (thin!)
from rest_framework import viewsets

class BookViewSet(viewsets.ModelViewSet):
    serializer_class = BookSerializer
    permission_classes = [IsAuthenticated]
    
    def perform_create(self, serializer):
        BookService.create_book(
            author=self.request.user,
            **serializer.validated_data,
        )
```

### Repository Pattern

```python
# ── Repository Pattern for testability ──────────────────────
from abc import ABC, abstractmethod
from typing import Optional

class BookRepository(ABC):
    """Abstract repository — swap implementations for testing"""
    
    @abstractmethod
    def get_by_id(self, book_id: int) -> Optional[Book]: ...
    
    @abstractmethod
    def get_by_author(self, author_id: int) -> list[Book]: ...
    
    @abstractmethod
    def save(self, book: Book) -> Book: ...

class DjangoBookRepository(BookRepository):
    """Django ORM implementation"""
    
    def get_by_id(self, book_id: int) -> Optional[Book]:
        try:
            return Book.objects.select_related('author').get(id=book_id)
        except Book.DoesNotExist:
            return None
    
    def get_by_author(self, author_id: int) -> list[Book]:
        return list(
            Book.objects.filter(author_id=author_id)
            .select_related('author')
        )
    
    def save(self, book: Book) -> Book:
        book.save()
        return book

class InMemoryBookRepository(BookRepository):
    """In-memory implementation for testing"""
    
    def __init__(self):
        self._books = {}
        self._next_id = 1
    
    def get_by_id(self, book_id: int) -> Optional[Book]:
        return self._books.get(book_id)
    
    def get_by_author(self, author_id: int) -> list[Book]:
        return [b for b in self._books.values() if b.author_id == author_id]
    
    def save(self, book: Book) -> Book:
        if not book.id:
            book.id = self._next_id
            self._next_id += 1
        self._books[book.id] = book
        return book
```

### Manager Pattern

```python
from django.db import models

class BookQuerySet(models.QuerySet):
    """Custom QuerySet methods — chainable"""
    
    def published(self):
        return self.filter(status='published')
    
    def by_author(self, author_id: int):
        return self.filter(author_id=author_id)
    
    def high_rated(self, min_rating: float = 4.0):
        return self.filter(rating__gte=min_rating)
    
    def with_author_name(self):
        return self.select_related('author').annotate(
            author_name=models.F('author__name')
        )

class BookManager(models.Manager):
    """Custom manager — entry point for QuerySet"""
    
    def get_queryset(self):
        return BookQuerySet(self.model, using=self._db)
    
    def published(self):
        return self.get_queryset().published()
    
    def popular_books(self, limit: int = 10):
        return (
            self.get_queryset()
            .published()
            .high_rated()
            .with_author_name()
            .order_by('-rating')[:limit]
        )

class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey(Author, on_delete=models.CASCADE)
    rating = models.FloatField(default=0.0)
    status = models.CharField(max_length=20, default='draft')
    
    objects = BookManager()  # Custom manager

# Usage:
# Book.objects.popular_books()  # Chained, optimized queries
# Book.objects.published().by_author(author_id)
```

---

## 12. Django Interview Questions

### Beginner

<details>
<summary><b>Q1: What is the Django ORM? How does it differ from raw SQL?</b></summary>

**Answer:** Django ORM is an object-relational mapper that lets you interact with your database using Python code instead of raw SQL. Key differences:
- **Abstraction:** ORM abstracts away database-specific SQL dialects
- **Safety:** ORM prevents SQL injection (parameterized queries)
- **Lazy evaluation:** QuerySets are evaluated only when needed
- **Migration support:** Automatic schema migration generation
- **Trade-off:** ORM can generate inefficient queries (N+1 problem) without optimization like `select_related`/`prefetch_related`
</details>

<details>
<summary><b>Q2: What is the difference between select_related and prefetch_related?</b></summary>

**Answer:** Both prevent N+1 queries but work differently:
- **select_related:** Uses SQL JOIN to fetch related objects in the same query. Works for ForeignKey and OneToOneField (single-valued relationships).
- **prefetch_related:** Uses separate queries (one for parent, one for related) and joins in Python. Works for all relationship types including ManyToMany and reverse ForeignKey.

```python
# select_related — single JOIN query
Book.objects.select_related('author')  # SELECT ... FROM book JOIN author

# prefetch_related — two queries
Author.objects.prefetch_related('books')  # SELECT authors; SELECT books WHERE author_id IN (...)
```
</details>

<details>
<summary><b>Q3: What is the Django request-response cycle?</b></summary>

**Answer:**
1. Browser sends HTTP request
2. WSGI server (Gunicorn/uWSGI) passes to Django's WSGI handler
3. Request middleware (in order)
4. URL resolver matches URL pattern
5. View middleware (`process_view`)
6. View function executes (may use ORM, templates)
7. Response middleware (`process_response`) — in reverse order
8. Django returns HTTP response
</details>

### Intermediate

<details>
<summary><b>Q4: How do you handle database transactions in Django?</b></summary>

**Answer:**
```python
from django.db import transaction

# Decorator
@transaction.atomic
def view_func(request):
    # Everything in one transaction
    pass

# Context manager
def view_func(request):
    with transaction.atomic():
        # This block is atomic
        pass

# Savepoints (nested)
with transaction.atomic():
    # Outer transaction
    with transaction.atomic():
        # Savepoint — can rollback independently
        pass

# select_for_update (row locking)
with transaction.atomic():
    account = Account.objects.select_for_update().get(id=1)
    account.balance -= amount
    account.save()
```
</details>

<details>
<summary><b>Q5: Explain Django's signal system. When would you use it vs overriding save()?</b></summary>

**Answer:** Signals allow decoupled apps to get notified when actions occur elsewhere. Use cases:
- **Cache invalidation:** Clear cache when model saved
- **Async tasks:** Trigger Celery task after model creation
- **Cross-app communication:** One app signals another

```python
# Use signals when:
# 1. Multiple unrelated actions should happen on save
# 2. Action should happen in another app
# 3. You can't modify the sender (third-party app)

# Use save() override when:
# 1. Single, tightly-coupled action
# 2. Field validation/normalization
# 3. Simple side effect in the same app

# ⚠️ Signals are synchronous — use Celery for heavy operations
```
</details>

<details>
<summary><b>Q6: What is the N+1 query problem and how do you solve it?</b></summary>

**Answer:** N+1 queries happen when you fetch a list of objects (1 query) and then loop through them accessing a related field (N queries).

```python
# 🔴 N+1 Problem
books = Book.objects.all()  # 1 query
for book in books:
    print(book.author.name)  # N queries (one per book)

# ✅ Fix with select_related (for ForeignKey/OneToOne)
books = Book.objects.select_related('author').all()  # 1 JOIN query

# ✅ Fix with prefetch_related (for ManyToMany/reverse FK)
authors = Author.objects.prefetch_related('books').all()  # 2 queries total

# Detection: django-debug-toolbar, QueryCountDebugMiddleware
```
</details>

<details>
<summary><b>Q7: How do you implement custom permissions in Django REST Framework?</b></summary>

**Answer:**
```python
from rest_framework.permissions import BasePermission

class IsOwner(BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.user == request.user

class IsAdminOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_staff

# Usage in ViewSet:
class BookViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated, IsOwner]
    
    def get_queryset(self):
        # Filter by user for object-level permissions
        return Book.objects.filter(user=self.request.user)
```
</details>

### Advanced

<details>
<summary><b>Q8: Design a multi-tenant SaaS application using Django. How do you isolate tenant data?</b></summary>

**Answer:** Three approaches for multi-tenancy:

**1. Schema-based isolation (PostgreSQL schemas):**
- Each tenant gets a separate schema
- Best isolation, but complex connection routing
- Library: `django-tenants`

**2. Database-based isolation:**
- Each tenant gets a separate database
- Maximum isolation, hardest to manage
- Use database router per tenant

**3. Row-level isolation (most common):**
```python
class TenantMixin(models.Model):
    tenant = models.ForeignKey('Tenant', on_delete=models.CASCADE)
    
    class Meta:
        abstract = True

class Book(TenantMixin):
    title = models.CharField(max_length=200)

# Middleware to set current tenant
class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        subdomain = request.get_host().split('.')[0]
        request.tenant = Tenant.objects.get(subdomain=subdomain)
        return self.get_response(request)

# Manager to auto-filter by tenant
class TenantManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(
            tenant=get_current_tenant()
        )
```
</details>

<details>
<summary><b>Q9: How do you optimize a Django view that returns thousands of records via a REST API?</b></summary>

**Answer:**
```python
# 1. Pagination (never return all records)
class BookPagination(PageNumberPagination):
    page_size = 50
    max_page_size = 200

# 2. Selective field loading
class BookListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Book
        fields = ['id', 'title', 'author_name']  # Minimum fields

# 3. Database optimization
class BookViewSet(ModelViewSet):
    serializer_class = BookListSerializer
    pagination_class = BookPagination
    
    def get_queryset(self):
        return Book.objects.select_related('author').only(
            'id', 'title', 'author__name'
        )

# 4. Caching
@method_decorator(cache_page(60 * 5))
def list(self, request, *args, **kwargs):
    return super().list(request, *args, **kwargs)

# 5. Deferred/async processing for heavy computations
class AsyncBookView(APIView):
    def get(self, request):
        task = generate_report.delay(request.query_params)
        return Response(
            {'task_id': task.id, 'status': 'processing'},
            status=202,  # Accepted
        )
```
</details>

<details>
<summary><b>Q10: Explain Django's migration system. How do you handle a breaking migration in production?</b></summary>

**Answer:** Strategies for zero-downtime migrations:

**1. Add field with nullable=True first:**
```python
# Migration 1: Add field as nullable
class Migration(migrations.Migration):
    operations = [
        migrations.AddField(
            model_name='book',
            name='publisher',
            field=models.ForeignKey(null=True, ...),
        ),
    ]

# Deploy: code writes to new field, reads from both old and new
# Migration 2: Backfill data
# Migration 3: Make field non-nullable
# Migration 4: Remove old field
```

**2. Rename field with separate steps:**
```python
# Step 1: Add new field
# Step 2: Backfill data (RunPython)
# Step 3: Deploy code using new field
# Step 4: Remove old field
```

**3. Large table migrations:**
```python
# Use batch updates to avoid locking:
from django.db.models import Q

def batch_migration(apps, schema_editor):
    Book = apps.get_model('myapp', 'Book')
    batch_size = 1000
    
    while True:
        batch = Book.objects.filter(
            Q(new_field__isnull=True)
        )[:batch_size]
        
        if not batch:
            break
        
        for book in batch:
            book.new_field = compute_value(book)
        
        Book.objects.bulk_update(batch, ['new_field'])
```

**Key principles:**
- Always add before remove (add column, deploy, remove column)
- Avoid long-running locks on production tables
- Use `--fake` for migrations already applied
- Test all migrations on a production clone first
</details>

<details>
<summary><b>Q11: Design a high-throughput event logging system with Django. What are the bottlenecks and how do you address them?</b></summary>

**Answer:**
```python
# ── Problem: Writing millions of events per day through Django ORM

# 🔴 Bottleneck 1: Individual INSERT per event
# Slow:
Event.objects.create(type='click', user_id=1, ...)

# ✅ Solution: Bulk INSERT with raw SQL
def bulk_create_events(events: list[dict]):
    from django.db import connection
    
    values = ', '.join(
        f"('{e['type']}', {e['user_id']}, '{e['timestamp']}')"
        for e in events
    )
    
    with connection.cursor() as cursor:
        cursor.execute(f"""
            INSERT INTO analytics_event (type, user_id, timestamp)
            VALUES {values}
        """)

# 🔴 Bottleneck 2: ORM overhead per request
# ✅ Solution: Write directly to queue, process in batches
class EventService:
    @staticmethod
    def record_event(event_type, user_id, data):
        """Write to Redis queue — no database hit"""
        redis_client.lpush(
            'event_queue',
            json.dumps({
                'type': event_type,
                'user_id': user_id,
                'data': data,
                'timestamp': timezone.now().isoformat(),
            })
        )

# Celery task processes batches:
@shared_task
def process_event_queue():
    pipe = redis_client.pipeline()
    
    # Batch collect events
    events = []
    for _ in range(100):
        event = redis_client.rpop('event_queue')
        if event:
            events.append(json.loads(event))
    
    if events:
        bulk_create_events(events)

# 🔴 Bottleneck 3: Table locks on analytics queries
# ✅ Solution: Materialized views or read replicas
# Separate read/write databases
class AnalyticsRouter:
    def db_for_read(self, model, **hints):
        if model._meta.app_label == 'analytics':
            return 'analytics_replica'
        return 'default'
    
    def db_for_write(self, model, **hints):
        if model._meta.app_label == 'analytics':
            return 'analytics_primary'
        return 'default'

# 🔴 Bottleneck 4: Slow aggregation queries
# ✅ Solution: Pre-aggregate with periodic tasks
@shared_task
def hourly_aggregation():
    from django.db.models import Count
    
    # Pre-compute hourly stats
    stats = Event.objects.filter(
        created_at__gte=timezone.now() - timedelta(hours=1)
    ).values('type').annotate(count=Count('id'))
    
    # Store in summary table
    for stat in stats:
        HourlySummary.objects.create(
            event_type=stat['type'],
            count=stat['count'],
            hour=timezone.now().replace(minute=0, second=0),
        )
```
</details>

<details>
<summary><b>Q12: How do you implement CQRS (Command Query Responsibility Segregation) with Django?</b></summary>

**Answer:**
```python
# ── CQRS separates read and write paths ─────────────────────

# Write Model (Normalized, for transactions)
class Order(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, default='pending')
    total = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

# Read Model (Denormalized, for queries)
class OrderSummary(models.Model):
    """Pre-joined materialized view for read queries"""
    order_id = models.IntegerField(primary_key=True)
    user_name = models.CharField(max_length=150)
    user_email = models.EmailField()
    status = models.CharField(max_length=20)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    item_count = models.IntegerField()
    created_at = models.DateTimeField()
    
    class Meta:
        managed = False  # Managed by sync mechanism
        db_table = 'order_summary'

# ── Event → Update read model
@receiver(post_save, sender=Order)
def update_order_summary(sender, instance, **kwargs):
    """Sync write model changes to read model"""
    items = OrderItem.objects.filter(order=instance)
    
    OrderSummary.objects.update_or_create(
        order_id=instance.id,
        defaults={
            'user_name': instance.user.get_full_name(),
            'user_email': instance.user.email,
            'status': instance.status,
            'total': instance.total,
            'item_count': items.count(),
            'created_at': instance.created_at,
        }
    )

# ── Write API (Commands)
class OrderCommandView(APIView):
    def post(self, request):
        with transaction.atomic():
            order = Order.objects.create(user=request.user, ...)
            for item in request.data['items']:
                OrderItem.objects.create(order=order, **item)
            
            # Event handler automatically updates read model
            return Response({'order_id': order.id})

# ── Read API (Queries)
class OrderQueryView(APIView):
    def get(self, request):
        # Queries the denormalized table — no JOINs needed
        orders = OrderSummary.objects.filter(
            user_id=request.user.id
        ).order_by('-created_at')
        
        serializer = OrderSummarySerializer(orders, many=True)
        return Response(serializer.data)

# ── Benefits of CQRS: ──────────────────────────────────────
# 1. Read queries don't touch transactional tables
# 2. Can optimize each path independently (different indexes)
# 3. Read replicas for scaling reads
# 4. No JOINs on read path — single table queries
# 5. Can use different storage engines (Postgres for writes, Elasticsearch for reads)
```
</details>

<details>
<summary><b>Q13: Explain Django's deferred attribute loading and how it interacts with select_related?</b></summary>

**Answer:** Django uses deferred loading for related fields accessed through `select_related`:

```python
books = Book.objects.select_related('author').all()

for book in books:
    # First access to book.author triggers a query
    # (even with select_related, the data is loaded lazily into Python objects)
    print(book.author.name)  # ✅ No query — data was JOINed
    
    # But accessing book.author.bio:
    print(book.author.bio)  # ⚠️ If bio was not in select_related, this is a NEW query!

# .only() and .defer() control which columns are loaded:
books = Book.objects.select_related('author').only(
    'id', 'title', 'author__name', 'author__email'
)
# Only loads specified columns — all other accesses trigger additional queries
```

**Key insight:** `select_related` creates a JOIN in SQL, but the related object is still instantiated lazily. The JOIN data is available when you access the related field for the first time on that model instance.

**Interaction with caching:** Once a related object is accessed, it's cached on the model instance:
```python
book = Book.objects.select_related('author').first()
book.author  # First access — resolves from JOIN data
book.author  # Cached — no query
```
</details>

<details>
<summary><b>Q14: Design a rate-limiting system for a Django REST API at scale.</b></summary>

**Answer:**
```python
# ── Multi-tier rate limiting strategy ──────────────────────

# Tier 1: Global rate limiting (Nginx/Gunicorn level)
# nginx.conf:
# limit_req_zone $binary_remote_addr zone=api:10m rate=100r/s;

# Tier 2: Application-level rate limiting (DRF throttles)
from rest_framework.throttling import SimpleRateThrottle

class TieredRateThrottle(SimpleRateThrottle):
    """Rate limit based on user tier"""
    
    def get_cache_key(self, request, view):
        if request.user.is_authenticated:
            # Rate limit by user ID
            return self.cache_format % {
                'scope': self.scope,
                'ident': request.user.id,
            }
        # Rate limit anonymous by IP
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }
    
    def get_rate(self):
        """Different rates for different user tiers"""
        user = getattr(self.request, 'user', None)
        if user and user.is_authenticated:
            tier = user.subscription_tier
            rates = {
                'free': '10/minute',
                'pro': '100/minute',
                'enterprise': '10000/minute',
            }
            return rates.get(tier, self.rate)
        return '5/minute'

# Tier 3: Endpoint-specific throttling
class BurstThrottle(SimpleRateThrottle):
    scope = 'burst'
    rate = '100/minute'

class SustainedThrottle(SimpleRateThrottle):
    scope = 'sustained'
    rate = '1000/day'

# Settings:
# REST_FRAMEWORK = {
#     'DEFAULT_THROTTLE_CLASSES': [
#         'myapp.throttles.TieredRateThrottle',
#         'myapp.throttles.BurstThrottle',
#         'myapp.throttles.SustainedThrottle',
#     ],
#     'DEFAULT_THROTTLE_RATES': {
#         'burst': None,  # Overridden by TieredRateThrottle
#         'sustained': None,
#     },
# }

# Tier 4: Redis-based sliding window rate limiter
import time
import hashlib

class RedisSlidingWindowRateLimiter:
    """Sliding window counter using Redis sorted sets"""
    
    def __init__(self, redis_client):
        self.redis = redis_client
    
    def is_allowed(self, key: str, max_requests: int, window: int = 60) -> bool:
        now = time.time()
        window_start = now - window
        redis_key = f"ratelimit:{hashlib.md5(key.encode()).hexdigest()}"
        
        # Remove old entries
        self.redis.zremrangebyscore(redis_key, '-inf', window_start)
        
        # Count current entries
        current = self.redis.zcard(redis_key)
        
        if current >= max_requests:
            return False
        
        # Add current request
        self.redis.zadd(redis_key, {str(now): now})
        self.redis.expire(redis_key, window * 2)
        
        return True
```
</details>

<details>
<summary><b>Q15: How do you handle file uploads efficiently in Django at scale?</b></summary>

**Answer:**
```python
# ── Direct-to-S3 Upload Pattern ────────────────────────────
# Instead of streaming through Django (which blocks workers):

# 1. Generate presigned URL from your API
class PresignedUploadView(APIView):
    def post(self, request):
        filename = request.data['filename']
        content_type = request.data['content_type']
        
        # Generate presigned POST URL
        presigned = generate_presigned_url(
            bucket='my-bucket',
            key=f'uploads/{uuid.uuid4()}/{filename}',
            content_type=content_type,
            expiration=3600,
        )
        
        return Response(presigned)

# 2. Client uploads directly to S3
#    (no Django worker used!)

# 3. Background processing via Celery
@shared_task
def process_upload(s3_key: str, user_id: int):
    """Process uploaded file"""
    # Download from S3, process, update database
    pass

# ── Chunked Uploads for Large Files ────────────────────────
class ChunkedUploadView(APIView):
    def post(self, request, upload_id):
        chunk = request.FILES['chunk']
        chunk_number = int(request.data['chunk_number'])
        
        # Store chunk
        chunk_path = f'/tmp/{upload_id}/{chunk_number}'
        os.makedirs(os.path.dirname(chunk_path), exist_ok=True)
        
        with open(chunk_path, 'wb') as f:
            for chunk_data in chunk.chunks():
                f.write(chunk_data)
        
        return Response({'chunk_number': chunk_number})
    
    def post_complete(self, request, upload_id):
        """Reassemble chunks and upload to S3"""
        chunks = sorted(
            Path(f'/tmp/{upload_id}').glob('*'),
            key=lambda p: int(p.name)
        )
        
        # Stream to S3 without loading entire file
        s3_client.upload_fileobj(
            Fileobj=_ChunkedFileReader(chunks),
            Bucket='my-bucket',
            Key=f'uploads/{upload_id}/final.mp4',
        )
        
        # Cleanup
        shutil.rmtree(f'/tmp/{upload_id}')
        
        return Response({'status': 'uploaded'})

# ── File processing with progress tracking ─────────────────
@shared_task(bind=True)
def process_video(self, video_id: int):
    """Video processing with progress tracking"""
    from django.core.files import File
    
    video = Video.objects.get(id=video_id)
    
    # Step 1: Transcode
    self.update_state(state='PROGRESS', meta={'step': 1, 'total': 5})
    transcoded = transcode_video(video.file.path)
    
    # Step 2: Generate thumbnails
    self.update_state(state='PROGRESS', meta={'step': 2, 'total': 5})
    thumbnail = generate_thumbnail(transcoded)
    
    # Save results
    with open(transcoded, 'rb') as f:
        video.processed_file.save(f'{video.id}.mp4', File(f))
    
    return {'status': 'completed', 'video_id': video.id}
```
</details>

<details>
<summary><b>Q16: Explain Django's prefetch_related_objects() and when to use it.</summary>

**Answer:**
```python
# prefetch_related_objects() allows prefetching on already-loaded instances

# ── Use case: Prefetch after QuerySet evaluation ──────────
def get_books_and_authors():
    books = list(Book.objects.all()[:50])  # QuerySet evaluated
    
    # Now prefetch authors for these books
    from django.db.models import prefetch_related_objects
    prefetch_related_objects(books, 'author')
    
    # Now book.author is cached for all books
    return books

# ── Use case: Mixed querysets ─────────────────────────────
def mixed_prefetch():
    books = list(Book.objects.filter(published=True))
    drafts = list(Book.objects.filter(published=False))
    
    # Prefetch related data for ALL books at once
    from django.db.models import prefetch_related_objects
    prefetch_related_objects(books + drafts, 'author', 'comments')
    
    return books, drafts

# ── Performance benefit ────────────────────────────────────
# Without prefetch_related_objects:
# - 50 books each accessed individually → 50 queries
# With prefetch_related_objects:
# - 1 query to fetch all related authors
```

---

## 📊 Quick Reference: Django at a Glance

| Component | Purpose | Key Method/Class |
|-----------|---------|------------------|
| ORM | Database abstraction | `Model`, `QuerySet` |
| Migrations | Schema management | `makemigrations`, `migrate` |
| Views | Request handling | `View`, `APIView`, `ViewSet` |
| Serializers | Data transformation | `Serializer`, `ModelSerializer` |
| Middleware | Request/response pipeline | `Middleware.__call__` |
| Authentication | Identity verification | `BaseBackend`, `TokenAuthentication` |
| Permissions | Access control | `BasePermission` |
| Signals | Event-driven patterns | `Signal`, `@receiver` |
| Cache | Response/data caching | `cache.get()`, `cache.set()` |
| Celery | Async task processing | `@shared_task` |
| Forms | Input validation | `Form`, `ModelForm` |
| Admin | Admin interface | `ModelAdmin` |

---

> *Use these notes as a comprehensive reference for Django interviews. Focus on understanding trade-offs (when to use ORM vs raw SQL, when signals vs save(), etc.) — staff-level interviews are about system design and trade-offs, not syntax.*
