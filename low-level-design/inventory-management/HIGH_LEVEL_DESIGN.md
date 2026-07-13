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
│  - Optimistic locking for stock updates       │
└────────────────┬──────────────────────────────┘
                 │
┌────────────────▼──────────────────────────────┐
│              Redis Cache                        │
│  - Stock availability (write-through)          │
│  - Reorder alerts (pub-sub)                    │
└───────────────────────────────────────────────┘
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="https://cpbrucemeena.github.io/interview-prep/assets/videos/inventory-management-sequence.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Inventory Management Sequence — Order → Stock Check → Allocate → Ship → Update. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 3. KEY COMPONENTS & INTERVIEW Q&A

### Inventory Service (Python)
- Stock CRUD with optimistic locking
- Multi-warehouse support
- Reorder point calculation (EOQ + safety stock)
- Movement audit trail

**🔴 Interview Question:** *"How do you prevent overselling when multiple orders hit the same product simultaneously?"*

**✅ Answer:** Optimistic locking with version columns:
```python
def allocate_stock(product_id, warehouse_id, quantity):
    updated = db.execute("""
        UPDATE inventory_items 
        SET reserved_qty = reserved_qty + ?,
            version = version + 1
        WHERE product_id = ? 
          AND warehouse_id = ?
          AND on_hand_qty - reserved_qty >= ?
          AND version = ?
    """, [quantity, product_id, warehouse_id, quantity, current_version])
    
    if updated == 0:
        # Either insufficient stock or concurrent update won
        raise InsufficientStockError()
```
`updated == 0` means another transaction already reserved the last unit. The calling code retries with recalculation.

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
    on_hand_qty INT DEFAULT 0, reserved_qty INT DEFAULT 0,
    bin_location TEXT, version INT DEFAULT 1,
    PRIMARY KEY (product_id, warehouse_id)
);
CREATE TABLE inventory_movements (
    id BIGSERIAL, product_id UUID, warehouse_id UUID,
    type TEXT, quantity INT, reference TEXT,
    created_at TIMESTAMP DEFAULT NOW()
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

## 6. COST (Monthly)

| Component | Cost |
|-----------|------|
| Inventory Service | $2,000 |
| PostgreSQL (Multi-AZ) | $1,500 |
| Redis Cache | $400 |
| Warehouse scanners (IoT) | $500 amortized |
| **Total** | **$4,400** |
