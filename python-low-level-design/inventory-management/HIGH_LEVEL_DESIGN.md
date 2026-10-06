# 🏗️ Inventory Management System — High-Level Design

> **Target Level:** Senior/Staff Engineer | **Focus:** Supply chain, stock optimization, multi-warehouse, traceability

---

## 1. SYSTEM OVERVIEW

**Purpose:** Multi-warehouse inventory management with real-time stock tracking, reorder optimization, and order fulfillment.

**Scale:** 100K SKUs, 10 warehouses, 1M stock movements/day, 50K orders/day

**Users:** Warehouse staff, Inventory managers, Procurement team, Supply chain analysts

**Use Cases:** Receive stock, Pick/pack/ship orders, Transfer between warehouses, Reorder alerts, Inventory valuation

**Constraints:** <100ms stock availability check, no overselling, FIFO costing accuracy, audit trail for all movements

---

## 2. HIGH-LEVEL ARCHITECTURE

```
┌─────────────────────────────────────────────┐
│  Warehouse Clients (Scanner, Web, Kiosk)     │
└────────────────────┬────────────────────────┘
                     │
┌────────────────────▼────────────────────────┐
│              API Gateway                      │
└──────┬──────────────────────────────────┬────┘
       │                                  │
┌──────▼──────┐                  ┌────────▼──────┐
│ Inventory   │                  │ Order          │
│ Service     │                  │ Fulfillment    │
│ (Python)    │                  │ Service        │
└──────┬──────┘                  └────────┬──────┘
       │                                  │
       └──────────────┬───────────────────┘
                      │
┌─────────────▼──────────────────▼─────────────┐
│              PostgreSQL                        │
│  - Products, Warehouses, Stock, Movements     │
│  - Conditional UPDATE for reservations        │
└────────────────┬──────────────────────────────┘
                 │
┌────────────────▼──────────────────────────────┐
│              Redis Cache                        │
│  - Product-page availability (stale-OK cache)  │
│  - Reorder alerts (pub-sub)                    │
└───────────────────────────────────────────────┘
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="../../../assets/videos/inventory-management-sequence.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Inventory Management Sequence — Order → Stock Check → Allocate → Ship → Update. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 3. KEY COMPONENTS & INTERVIEW Q&A

### Inventory Service (Python)
- Stock reservations via conditional UPDATE (no oversell)
- Multi-warehouse support
- Reorder point calculation (EOQ + safety stock)
- Movement audit trail

**🔴 Interview Question:** *"How do you prevent overselling when multiple orders hit the same product simultaneously?"*

**✅ Answer:** A conditional update, which is atomic per row and needs no version column:
```sql
UPDATE inventory_items
SET reserved_qty = reserved_qty + :q
WHERE product_id = :pid
  AND warehouse_id = :wh
  AND on_hand_qty - reserved_qty >= :q;
-- rowcount = 0  =>  insufficient stock. No retry loop: at READ COMMITTED Postgres re-evaluates the WHERE
-- against the latest committed row version after waiting on a concurrent writer's row lock.
```
Optimistic locking (`AND version = :v`) also prevents overselling, but on a hot SKU most attempts lose the version race and retry even when plenty of stock is left; the conditional update only fails when stock really is short. Multi-line orders do one such update per line inside one transaction, in `(product_id, warehouse_id)` order to avoid deadlocks, and roll back if any line updates 0 rows. A `CHECK (reserved_qty >= 0 AND reserved_qty <= on_hand_qty)` constraint makes the invariant enforceable by the database, not just by code.

---

### Order Fulfillment Service (Python)
- Nearest warehouse allocation
- Pick/pack/ship workflow
- Cross-docking support

**🔴 Interview Question:** *"How does the system decide which warehouse to fulfill from?"*

**✅ Answer:** Multi-factor scoring:
```python
def score_warehouse(warehouse, order_items, shipping_address):
    score = 0
    
    # 1. Inventory availability (required)
    available = all(
        warehouse.has_stock(item.product_id, item.quantity)
        for item in order_items
    )
    if not available:
        return -inf
    
    # 2. Distance from customer (lower is better)
    distance = geo_distance(warehouse.location, shipping_address)
    score -= distance * 0.3
    
    # 3. Operational cost (labor + shipping)
    score -= warehouse.fulfillment_cost(order_items) * 0.2
    
    # 4. Workload balance (spread orders across warehouses)
    score -= warehouse.current_backlog * 0.1
    
    return score
```
The highest-scoring warehouse gets the order. This balances cost, speed, and load.

---

## 4. DATA MODEL

```sql
CREATE TABLE products (
    id UUID, sku TEXT UNIQUE, name TEXT, category TEXT,
    unit_price DECIMAL(10,2), reorder_level INT, reorder_qty INT
);
CREATE TABLE warehouses (
    id UUID, name TEXT, location TEXT, capacity INT
);
CREATE TABLE inventory_items (
    product_id UUID, warehouse_id UUID,
    on_hand_qty INT NOT NULL DEFAULT 0, reserved_qty INT NOT NULL DEFAULT 0,
    bin_location TEXT,
    PRIMARY KEY (product_id, warehouse_id),
    CHECK (reserved_qty >= 0 AND reserved_qty <= on_hand_qty)
);
CREATE TABLE reservations (
    id UUID PRIMARY KEY, order_id TEXT UNIQUE NOT NULL,   -- idempotency key
    status TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ON reservations (expires_at) WHERE status = 'ACTIVE';   -- sweeper scan
CREATE TABLE reservation_lines (
    reservation_id UUID, product_id UUID, warehouse_id UUID, qty INT NOT NULL CHECK (qty > 0),
    PRIMARY KEY (reservation_id, product_id, warehouse_id)
);
CREATE TABLE inventory_movements (                    -- append-only ledger
    id BIGSERIAL PRIMARY KEY, product_id UUID, warehouse_id UUID,
    type TEXT, delta INT, on_hand_after INT, reference TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 5. REORDER OPTIMIZATION

```python
def calculate_reorder(product, item):
    # Safety stock = Z * σ_demand * √lead_time
    safety = 1.65 * product.demand_std * math.sqrt(product.lead_time_days)
    
    # Reorder point = demand_during_lead_time + safety
    rop = (product.avg_daily_demand * product.lead_time_days) + safety
    
    # EOQ = √(2 * D * S / H)
    eoq = math.sqrt(2 * product.annual_demand * 50 / (product.unit_price * 0.2))
    
    if item.on_hand_qty <= rop:
        return {"action": "REORDER", "quantity": int(eoq)}
    return {"action": "OK"}
```

---

## 6. CONSISTENCY, IDEMPOTENCY & FAILURE MODES

**Capacity check.** 50K orders/day ≈ 0.6 orders/s on average; even a 20× peak is ~12 orders/s, each a handful of single-row updates. One Postgres primary handles this comfortably. 1M movements/day ≈ 12 inserts/s average, ~0.4 TB/year at ~1 KB/row with indexes; partition the movements table by month. The real scaling risk is not throughput but **hot rows**: a flash sale concentrates thousands of updates per second on one `(product, warehouse)` row.

| Concern | Choice |
|---------|--------|
| Source of truth for stock | Postgres row per (product, warehouse); strongly consistent writes |
| Product-page availability | Cache or read replica; may be seconds stale. Never used to decide a reservation |
| Reserve idempotency | `reservations.order_id UNIQUE`, inserted in the same transaction as the stock updates; a retry finds the row and returns it |
| Commit / release idempotency | Status transition guarded by `UPDATE reservations SET status='COMMITTED' WHERE id=:id AND status='ACTIVE'`; 0 rows → already done (return stored result) or expired |
| Events to other services | Transactional outbox: write `StockReserved` / `StockCommitted` rows in the same transaction, relay to Kafka. Consumers dedupe on event id (delivery is at-least-once) |

| Failure | What happens / mitigation |
|---------|---------------------------|
| Client times out after reserve succeeded | Retry with the same `order_id` returns the existing reservation |
| Payment succeeds, reservation already expired | Commit fails; order service re-reserves or refunds (saga compensation). Keep TTL comfortably above the payment timeout |
| Sweeper down | Reservations stay ACTIVE past TTL, stock looks unavailable; commit still rejects expired ones. Alert on `count(ACTIVE AND expires_at < now() - 5 min)` |
| Physical count lower than reserved (shrinkage) | Accept the count, flag affected reservations as short, re-allocate or notify the customer |
| Hot SKU row contention | Split stock into N bucket rows and reserve from a random one, or an atomic Redis Lua counter reconciled to the DB, or a queue that admits buyers in order |
| Deadlocks between multi-line orders | Always update rows in `(product_id, warehouse_id)` order; retry the rare abort |
| Duplicate PO creation | Reorder job computes position = available + open PO qty in one query; run it as a single scheduled job (or under an advisory lock) |

---

## 7. COST (Monthly)

| Component | Cost |
|-----------|------|
| Inventory Service | $2,000 |
| PostgreSQL (Multi-AZ) | $1,500 |
| Redis Cache | $400 |
| Warehouse scanners (IoT) | $500 amortized |
| **Total** | **$4,400** |
