# Inventory Management System - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** Supply chain, reorder point optimization, multi-warehouse, traceability

---

## Question 1: Core Design
**Interviewer:** *"Design an inventory management system — products, warehouses, stock levels, movements."*

### 🎯 Expected Answer

**Domain Model:**
```python
class Product:    # SKU, Name, Category, UnitPrice, ReorderLevel
class Warehouse:  # ID, Name, Location, Capacity
class InventoryItem:  # Product + Warehouse + Quantity + ReservedQty
    @property
    def available_quantity(self) -> int:
        return self._quantity - self._reserved_quantity

class InventoryMovement:  # Audit trail for every stock change
    # product_id, warehouse_id, type (IN/OUT/ADJUST/TRANSFER),
    # quantity, reference (PO#, Order#), timestamp
```

**Why `available_quantity = on_hand - reserved`?** This separates "what we physically have" from "what we can promise." When an order comes in, we `reserve()` stock (decrement available) without physically moving it. The physical move happens at shipment. This prevents overselling during the fulfillment gap.

---

## Question 2: Reorder Point Logic
**Interviewer:** *"Design an intelligent reorder system that prevents stockouts."*

### 🎯 Answer

**Economic Order Quantity (EOQ):**
```python
def eoq(demand_rate, ordering_cost, holding_cost):
    """
    EOQ = sqrt(2 * D * S / H)
    D = annual demand, S = cost per order, H = holding cost per unit/year
    """
    return math.sqrt(2 * demand_rate * ordering_cost / holding_cost)
```

**Safety Stock Calculation:**
```python
def safety_stock(average_demand, demand_std_dev, lead_time_days, service_level=0.95):
    """
    Z-score for 95% service level = 1.65
    SS = Z * σ_d * √LT
    """
    z = {0.90: 1.28, 0.95: 1.65, 0.99: 2.33}[service_level]
    return z * demand_std_dev * math.sqrt(lead_time_days)
```

**Combined Reorder Point:**
```python
reorder_point = (average_daily_demand * lead_time_days) + safety_stock
```

**Why this matters:** Too little safety stock → stockouts (lost sales). Too much → carrying cost (wasted capital). The Z-score lets you tune this: 95% service level means 5% chance of stockout.

---

## Question 3: Stock Movement & Traceability

**Every movement is an immutable audit record:**
```python
class InventoryMovement:
    def __init__(self, product_id, warehouse_id, movement_type, 
                 quantity, balance_after, reference, timestamp):
        # Immutable — never modified after creation
        self._movement_id = str(uuid.uuid4())
        self._timestamp = datetime.utcnow()
        # ... 
```

**FIFO costing:**
```python
def costing_fifo(inventory, quantity_to_sell):
    """Cost of goods sold using FIFO"""
    cost = 0
    remaining = quantity_to_sell
    for receipt in sorted(inventory.receipts, key=lambda r: r.date):
        if remaining <= 0: break
        take = min(remaining, receipt.remaining_qty)
        cost += take * receipt.unit_cost
        remaining -= take
        receipt.remaining_qty -= take
    return cost
```

---

## Question 4: Inventory Valuation Methods

| Method | How | Pros | Cons |
|--------|-----|------|------|
| **FIFO** | First cost in = first cost out | Matches physical flow | Lower taxes (inflation) |
| **Weighted Avg** | Average cost per unit | Smooth values | Lag in cost changes |
| **Standard** | Predetermined cost | Simple, variance tracking | Needs regular updates |

---

## Question 5: Order Fulfillment Pipeline

```python
class FulfillmentService:
    def fulfill(self, order):
        # 1. Check availability
        for item in order.items:
            if not self._inventory.available(item.product_id) >= item.quantity:
                raise InsufficientStockError(item.product_id)
        
        # 2. Reserve stock
        for item in order.items:
            self._inventory.reserve(item.product_id, item.quantity)
        
        # 3. Pick from nearest warehouse
        warehouse = self._find_nearest_warehouse(order.shipping_address, order.items)
        
        # 4. Generate picklist
        picklist = self._generate_picklist(warehouse, order.items)
        
        # 5. Pack & Ship (handled by warehouse system)
        
        # 6. Release reservation
        for item in order.items:
            self._inventory.release_reservation(item.product_id, item.quantity)
            
        return "Fulfilled"
```

---

## Question 6: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | ReorderStrategy | Simple vs demand-based reorder |
| **Observer** | Low-stock alerts | Trigger notifications at threshold |
| **Facade** | InventoryService | Unified interface |
| **Factory** | Product/Warehouse | Config-driven creation |
| **Command** | Stock movements | Audit trail, undo support |
