# 🧠 Inventory Management LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

## Phase 0: Requirements Gathering

What's being tracked? (Product stock at warehouses.) What operations? (Stock in/out, transfer, reorder.) What defines a reorder? Multiple warehouses?

## Phase 1: Identify the Nouns

> *"A company manages products across warehouses. Stock moves in and out. When stock is low, a purchase order is auto-generated."*

| Noun | Decision | Why |
|------|----------|-----|
| Product | Regular Class | Metadata (SKU, name, price, reorder level) |
| Warehouse | Regular Class | Physical location with capacity |
| InventoryItem | Regular Class | Product + Warehouse + Quantity |
| InventoryMovement | Regular Class | Audit trail for stock changes |
| PurchaseOrder | Regular Class | Auto-generated reorder |
| ReorderStrategy | ABC | Strategy for when/how much to reorder |
| InventoryService | Facade | Main entry point |
| ProductStatus | Enum | ACTIVE, INACTIVE, DISCONTINUED |
| OrderStatus | Enum | PENDING → CONFIRMED → ... → DELIVERED |

## Phase 2: Enums First

```python
class ProductStatus(Enum):          ACTIVE, INACTIVE, DISCONTINUED
class InventoryMovementType(Enum):  STOCK_IN, STOCK_OUT, RETURN, ADJUSTMENT, TRANSFER
class OrderStatus(Enum):            PENDING, CONFIRMED, PROCESSING, SHIPPED, DELIVERED, CANCELLED
```

## Phase 3: dataclass vs `__init__`

- **`Product`**: Regular — has metadata with defaults
- **`Warehouse`**: Regular — simple, but plain class is fine
- **`InventoryItem`**: Regular — has behavior (add_stock, remove_stock, reserve)
- **`InventoryMovement`**: Regular — auto-generated IDs, timestamp
- **`PurchaseOrder`**: Regular — state transitions (confirm, receive, cancel)

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Add stock | `InventoryItem.add_stock()` | Item tracks its own quantity |
| Remove stock | `InventoryItem.remove_stock()` | Item validates available quantity |
| Reserve stock | `InventoryItem.reserve()` | Item handles reservations |
| Check reorder need | `ReorderStrategy.should_reorder()` | Strategy encapsulates the logic |
| Create purchase order | `InventoryService.check_reorder()` | Service orchestrates the flow |
| Transfer between warehouses | `InventoryService.transfer_stock()` | Service coordinates two warehouses |

## Phase 5: The Stock Tracking Model

```
Product ──(1:N)── InventoryItem ──(N:1)── Warehouse
                    │
                    └── InventoryMovement[]  (audit trail)
```

**Key insight:** `InventoryItem` is the *join* between Product and Warehouse. It's not just a Product — it's Product *at a specific Warehouse*.

## Phase 6: Strategy Pattern for Reorder

```python
class ReorderStrategy(ABC):
    def should_reorder(self, item) -> bool
    def get_reorder_quantity(self, item) -> int

class SimpleReorderStrategy(ReorderStrategy):
    # Reorder when below level, fixed quantity

class DemandBasedReorderStrategy(ReorderStrategy):
    # Reorder based on average daily consumption × 14 days
```

The system starts with simple reorder logic but can be upgraded to demand-based without changing InventoryService.

## Phase 7: Available vs Reserved Quantity

```python
@property
def available_quantity(self) -> int:
    return self._quantity - self._reserved_quantity
```

This is a **computed property** — an important pattern. `available_quantity` is never stored, always calculated from quantity and reserved_quantity.

## Phase 8: Quick Checklist

✅ **SRP:** Product, Warehouse, InventoryItem each own their data
✅ **Strategy:** Reorder strategies are swappable
✅ **Audit trail:** InventoryMovement records every change
✅ **Encapsulation:** Stock changes go through methods, not direct attribute access
