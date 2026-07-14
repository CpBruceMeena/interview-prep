"""
Inventory Management System - Low Level Design
-------------------------------------------------
Design Principles: SOLID, Strategy Pattern, Observer Pattern
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple
import uuid


class ProductStatus(Enum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"
    DISCONTINUED = "Discontinued"


class InventoryMovementType(Enum):
    STOCK_IN = "Stock In"
    STOCK_OUT = "Stock Out"
    RETURN = "Return"
    ADJUSTMENT = "Adjustment"
    TRANSFER = "Transfer"


class OrderStatus(Enum):
    PENDING = "Pending"
    CONFIRMED = "Confirmed"
    PROCESSING = "Processing"
    SHIPPED = "Shipped"
    DELIVERED = "Delivered"
    CANCELLED = "Cancelled"


class Warehouse:
    """Represents a physical warehouse location"""

    def __init__(self, warehouse_id: str, name: str, location: str,
                 capacity: int):
        self._warehouse_id = warehouse_id
        self._name = name
        self._location = location
        self._capacity = capacity

    @property
    def warehouse_id(self) -> str:
        return self._warehouse_id

    @property
    def name(self) -> str:
        return self._name

    def __str__(self) -> str:
        return f"{self._name} ({self._location})"


# --- Product (SRP) ---

class Product:
    """Single Responsibility: Represents a product's metadata"""

    def __init__(self, product_id: str, sku: str, name: str,
                 category: str, unit_price: float, reorder_level: int = 10,
                 reorder_quantity: int = 50):
        self._product_id = product_id
        self._sku = sku
        self._name = name
        self._category = category
        self._unit_price = unit_price
        self._reorder_level = reorder_level
        self._reorder_quantity = reorder_quantity
        self._status = ProductStatus.ACTIVE

    @property
    def product_id(self) -> str:
        return self._product_id

    @property
    def sku(self) -> str:
        return self._sku

    @property
    def name(self) -> str:
        return self._name

    @property
    def category(self) -> str:
        return self._category

    @property
    def unit_price(self) -> float:
        return self._unit_price

    @property
    def reorder_level(self) -> int:
        return self._reorder_level

    @property
    def reorder_quantity(self) -> int:
        return self._reorder_quantity

    def __str__(self) -> str:
        return f"{self._name} ({self._sku}) - ${self._unit_price:.2f}"


# --- Inventory Item (SRP) ---

class InventoryItem:
    """Tracks stock for a specific product at a specific warehouse"""

    def __init__(self, product: Product, warehouse: Warehouse,
                 quantity: int = 0, bin_location: str = ""):
        self._product = product
        self._warehouse = warehouse
        self._quantity = quantity
        self._reserved_quantity = 0
        self._bin_location = bin_location
        self._movements: List['InventoryMovement'] = []

    @property
    def product(self) -> Product:
        return self._product

    @property
    def warehouse(self) -> Warehouse:
        return self._warehouse

    @property
    def quantity(self) -> int:
        return self._quantity

    @property
    def reserved_quantity(self) -> int:
        return self._reserved_quantity

    @property
    def available_quantity(self) -> int:
        return self._quantity - self._reserved_quantity

    def add_stock(self, quantity: int, reference: str = "") -> 'InventoryMovement':
        self._quantity += quantity
        movement = InventoryMovement(self._product.product_id,
                                      self._warehouse.warehouse_id,
                                      InventoryMovementType.STOCK_IN,
                                      quantity, self._quantity, reference)
        self._movements.append(movement)
        return movement

    def remove_stock(self, quantity: int, reference: str = "") -> 'InventoryMovement':
        if self.available_quantity < quantity:
            raise ValueError(f"Insufficient stock. Available: {self.available_quantity}")
        self._quantity -= quantity
        movement = InventoryMovement(self._product.product_id,
                                      self._warehouse.warehouse_id,
                                      InventoryMovementType.STOCK_OUT,
                                      -quantity, self._quantity, reference)
        self._movements.append(movement)
        return movement

    def reserve(self, quantity: int) -> bool:
        if self.available_quantity >= quantity:
            self._reserved_quantity += quantity
            return True
        return False

    def release_reservation(self, quantity: int) -> None:
        self._reserved_quantity = max(0, self._reserved_quantity - quantity)

    def needs_reorder(self) -> bool:
        return self._quantity <= self._product.reorder_level

    def __str__(self) -> str:
        return (f"{self._product.name}: {self._quantity} units "
                f"({self.available_quantity} available) at {self._warehouse.name}")


# --- Inventory Movement (SRP) ---

class InventoryMovement:
    def __init__(self, product_id: str, warehouse_id: str,
                 movement_type: InventoryMovementType,
                 quantity: int, balance_after: int,
                 reference: str = ""):
        self._movement_id = f"MV-{uuid.uuid4().hex[:8].upper()}"
        self._product_id = product_id
        self._warehouse_id = warehouse_id
        self._type = movement_type
        self._quantity = quantity
        self._balance_after = balance_after
        self._timestamp = datetime.now()
        self._reference = reference

    @property
    def movement_id(self) -> str:
        return self._movement_id

    @property
    def product_id(self) -> str:
        return self._product_id

    @property
    def movement_type(self) -> InventoryMovementType:
        return self._type

    @property
    def quantity(self) -> int:
        return self._quantity

    @property
    def timestamp(self) -> datetime:
        return self._timestamp

    def __str__(self) -> str:
        return (f"[{self._timestamp:%H:%M}] {self._type.value}: "
                f"{abs(self._quantity)} units (Balance: {self._balance_after})")


# --- Reorder Strategy (Strategy Pattern) ---

class ReorderStrategy(ABC):
    @abstractmethod
    def should_reorder(self, item: InventoryItem) -> bool:
        pass

    @abstractmethod
    def get_reorder_quantity(self, item: InventoryItem) -> int:
        pass


class SimpleReorderStrategy(ReorderStrategy):
    def should_reorder(self, item: InventoryItem) -> bool:
        return item.needs_reorder()

    def get_reorder_quantity(self, item: InventoryItem) -> int:
        return item.product.reorder_quantity


class DemandBasedReorderStrategy(ReorderStrategy):
    def __init__(self, lookback_days: int = 30):
        self._lookback = lookback_days

    def should_reorder(self, item: InventoryItem) -> bool:
        return item.quantity <= item.product.reorder_level

    def get_reorder_quantity(self, item: InventoryItem) -> int:
        # Calculate average daily consumption
        recent = [m for m in item._movements
                  if m.movement_type in (InventoryMovementType.STOCK_OUT,)
                  and m.timestamp > datetime.now() - timedelta(days=self._lookback)]
        if not recent:
            return item.product.reorder_quantity
        total_out = sum(abs(m.quantity) for m in recent)
        avg_daily = total_out / self._lookback
        return max(item.product.reorder_quantity, int(avg_daily * 14))  # 14 days stock


# --- Purchase Order / Reorder (SRP) ---

class PurchaseOrder:
    def __init__(self, order_id: str, product: Product, warehouse: Warehouse,
                 quantity: int, strategy: ReorderStrategy = None):
        self._order_id = order_id
        self._product = product
        self._warehouse = warehouse
        self._quantity = quantity
        self._status = OrderStatus.PENDING
        self._created_at = datetime.now()
        self._strategy = strategy or SimpleReorderStrategy()

    @property
    def order_id(self) -> str:
        return self._order_id

    @property
    def product(self) -> Product:
        return self._product

    @property
    def quantity(self) -> int:
        return self._quantity

    @property
    def status(self) -> OrderStatus:
        return self._status

    def confirm(self) -> None:
        self._status = OrderStatus.CONFIRMED

    def receive(self) -> None:
        self._status = OrderStatus.DELIVERED

    def cancel(self) -> None:
        self._status = OrderStatus.CANCELLED

    def __str__(self) -> str:
        return f"PO[{self._order_id[:8]}]: {self._product.name} x{self._quantity}"


# --- Inventory Service (Facade) ---

class InventoryService:
    def __init__(self):
        self._products: Dict[str, Product] = {}
        self._warehouses: Dict[str, Warehouse] = {}
        self._inventory: Dict[str, Dict[str, InventoryItem]] = {}  # product_id -> warehouse_id -> item
        self._orders: Dict[str, PurchaseOrder] = {}
        self._reorder_strategy: ReorderStrategy = SimpleReorderStrategy()
        self._low_stock_alerts: List[str] = []

    def add_product(self, sku: str, name: str, category: str,
                    unit_price: float, reorder_level: int = 10,
                    reorder_qty: int = 50) -> Product:
        pid = f"PRD-{uuid.uuid4().hex[:6].upper()}"
        product = Product(pid, sku, name, category, unit_price,
                          reorder_level, reorder_qty)
        self._products[pid] = product
        return product

    def get_product(self, product_id: str) -> Optional[Product]:
        return self._products.get(product_id)

    def search_products(self, query: str) -> List[Product]:
        q = query.lower()
        return [p for p in self._products.values()
                if q in p.name.lower() or q in p.sku.lower() or q in p.category.lower()]

    def add_warehouse(self, name: str, location: str, capacity: int) -> Warehouse:
        wid = f"WH-{uuid.uuid4().hex[:6].upper()}"
        warehouse = Warehouse(wid, name, location, capacity)
        self._warehouses[wid] = warehouse
        return warehouse

    def add_stock(self, product_id: str, warehouse_id: str,
                  quantity: int, bin_location: str = "") -> InventoryItem:
        product = self._products.get(product_id)
        warehouse = self._warehouses.get(warehouse_id)
        if not product or not warehouse:
            raise ValueError("Product or warehouse not found")

        if product_id not in self._inventory:
            self._inventory[product_id] = {}

        if warehouse_id not in self._inventory[product_id]:
            item = InventoryItem(product, warehouse, 0, bin_location)
            self._inventory[product_id][warehouse_id] = item
        else:
            item = self._inventory[product_id][warehouse_id]

        item.add_stock(quantity, "Initial stock")
        return item

    def get_inventory(self, product_id: str,
                      warehouse_id: Optional[str] = None) -> List[InventoryItem]:
        if product_id not in self._inventory:
            return []
        if warehouse_id:
            item = self._inventory[product_id].get(warehouse_id)
            return [item] if item else []
        return list(self._inventory[product_id].values())

    def remove_stock(self, product_id: str, warehouse_id: str,
                     quantity: int, reference: str = "") -> InventoryMovement:
        item = self._inventory.get(product_id, {}).get(warehouse_id)
        if not item:
            raise ValueError("Inventory item not found")
        return item.remove_stock(quantity, reference)

    def transfer_stock(self, product_id: str, from_warehouse: str,
                       to_warehouse: str, quantity: int) -> Tuple[InventoryMovement, InventoryMovement]:
        """Transfer stock between warehouses"""
        self.remove_stock(product_id, from_warehouse, quantity,
                          f"Transfer to {to_warehouse}")

        # Add to destination
        if product_id not in self._inventory:
            self._inventory[product_id] = {}
        if to_warehouse not in self._inventory[product_id]:
            product = self._products[product_id]
            wh = self._warehouses[to_warehouse]
            self._inventory[product_id][to_warehouse] = InventoryItem(product, wh)

        movement_in = self._inventory[product_id][to_warehouse].add_stock(
            quantity, f"Transfer from {from_warehouse}")
        print(f"  Transferred {quantity} units of {self._products[product_id].name}")
        return (None, movement_in)

    def check_reorder(self) -> List[PurchaseOrder]:
        """Check all inventory items and create reorder POs if needed"""
        orders = []
        for pid, warehouses in self._inventory.items():
            for wid, item in warehouses.items():
                if self._reorder_strategy.should_reorder(item):
                    qty = self._reorder_strategy.get_reorder_quantity(item)
                    oid = f"PO-{uuid.uuid4().hex[:8].upper()}"
                    po = PurchaseOrder(oid, item.product, item.warehouse, qty)
                    self._orders[oid] = po
                    orders.append(po)
                    self._low_stock_alerts.append(
                        f"Reorder: {item.product.name} at {item.warehouse.name}"
                    )
                    print(f"  📋 Auto-generated PO: {po}")
        return orders

    def get_low_stock_products(self) -> List[InventoryItem]:
        """Get all items that need reordering"""
        low = []
        for warehouses in self._inventory.values():
            for item in warehouses.values():
                if item.needs_reorder():
                    low.append(item)
        return low

    def get_inventory_value(self) -> float:
        """Calculate total inventory value"""
        total = 0.0
        for warehouses in self._inventory.values():
            for item in warehouses.values():
                total += item.quantity * item.product.unit_price
        return total

    def set_reorder_strategy(self, strategy: ReorderStrategy) -> None:
        self._reorder_strategy = strategy


# --- Demo ---

def demo():
    print("=== Inventory Management System ===")
    print("=" * 50)

    inv = InventoryService()

    # Add products
    laptop = inv.add_product("LAP-001", "Gaming Laptop Pro", "Electronics", 1200.0, 5, 20)
    phone = inv.add_product("PHN-001", "Smartphone X", "Electronics", 800.0, 10, 30)
    headphones = inv.add_product("HPH-001", "Wireless Headphones", "Audio", 150.0, 15, 50)
    print(f"\nProducts added:")
    for p in [laptop, phone, headphones]:
        print(f"  {p}")

    # Add warehouses
    wh1 = inv.add_warehouse("Main Warehouse", "Bangalore", 10000)
    wh2 = inv.add_warehouse("East Distribution", "Kolkata", 5000)
    print(f"\nWarehouses: {wh1}, {wh2}")

    # Add stock
    inv.add_stock(laptop.product_id, wh1.warehouse_id, 25, "Aisle-1, Rack-A")
    inv.add_stock(phone.product_id, wh1.warehouse_id, 50, "Aisle-2, Rack-B")
    inv.add_stock(headphones.product_id, wh1.warehouse_id, 8, "Aisle-3, Rack-C")  # Below reorder

    inv.add_stock(laptop.product_id, wh2.warehouse_id, 10, "Aisle-1, Rack-A")
    inv.add_stock(phone.product_id, wh2.warehouse_id, 20, "Aisle-2, Rack-B")

    # Transfer stock
    print("\n--- Stock Transfer ---")
    inv.transfer_stock(laptop.product_id, wh1.warehouse_id, wh2.warehouse_id, 5)

    # Check inventory
    print("\n--- Inventory Status ---")
    for pid in [laptop.product_id, phone.product_id, headphones.product_id]:
        items = inv.get_inventory(pid)
        for item in items:
            print(f"  {item}")
            if item.needs_reorder():
                print(f"    ⚠️ Below reorder level ({item.product.reorder_level})!")

    # Check reorder
    print("\n--- Auto-Reorder Check ---")
    inv.set_reorder_strategy(DemandBasedReorderStrategy(30))
    orders = inv.check_reorder()

    print(f"\n--- Summary ---")
    print(f"  Total inventory value: ${inv.get_inventory_value():.2f}")
    print(f"  Low stock items: {len(inv.get_low_stock_products())}")
    print(f"  Auto-generated POs: {len(orders)}")


if __name__ == "__main__":
    demo()
