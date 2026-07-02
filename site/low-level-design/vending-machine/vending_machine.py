"""
Vending Machine System - Low Level Design
------------------------------------------
Design Principles: SOLID, State Pattern, Strategy Pattern
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Optional


class Coin(Enum):
    PENNY = (0.01, "Penny")
    NICKEL = (0.05, "Nickel")
    DIME = (0.10, "Dime")
    QUARTER = (0.25, "Quarter")
    HALF_DOLLAR = (0.50, "Half Dollar")

    def __init__(self, value: float, name: str):
        self._value = value
        self._name = name

    @property
    def value(self) -> float:
        return self._value

    @property
    def display_name(self) -> str:
        return self._name


class Note(Enum):
    ONE = (1.0, "One Dollar")
    FIVE = (5.0, "Five Dollars")
    TEN = (10.0, "Ten Dollars")
    TWENTY = (20.0, "Twenty Dollars")

    def __init__(self, value: float, name: str):
        self._value = value
        self._name = name

    @property
    def value(self) -> float:
        return self._value

    @property
    def display_name(self) -> str:
        return self._name


class PaymentMethod(Enum):
    CASH = "Cash"
    CARD = "Card"
    MOBILE = "Mobile Payment"


# --- Product (SRP) ---

class Product:
    """Single Responsibility: Represents a product"""

    def __init__(self, product_id: str, name: str, price: float, category: str = "General"):
        self._product_id = product_id
        self._name = name
        self._price = price
        self._category = category

    @property
    def product_id(self) -> str:
        return self._product_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def price(self) -> float:
        return self._price

    @property
    def category(self) -> str:
        return self._category

    def __str__(self) -> str:
        return f"{self._name} (${self._price:.2f})"


# --- Inventory (SRP) ---

class Inventory:
    """Single Responsibility: Manages product stock"""

    def __init__(self):
        self._products: Dict[str, Product] = {}
        self._stock: Dict[str, int] = {}

    def add_product(self, product: Product, quantity: int) -> None:
        self._products[product.product_id] = product
        self._stock[product.product_id] = self._stock.get(product.product_id, 0) + quantity

    def get_product(self, product_id: str) -> Optional[Product]:
        return self._products.get(product_id)

    def is_available(self, product_id: str) -> bool:
        return self._stock.get(product_id, 0) > 0

    def dispense(self, product_id: str) -> Optional[Product]:
        if not self.is_available(product_id):
            return None
        self._stock[product_id] -= 1
        return self._products.get(product_id)

    def get_quantity(self, product_id: str) -> int:
        return self._stock.get(product_id, 0)

    def display_products(self) -> None:
        print("\n=== Available Products ===")
        for pid, product in self._products.items():
            qty = self._stock.get(pid, 0)
            status = f"In Stock ({qty})" if qty > 0 else "SOLD OUT"
            print(f"  [{pid}] {product.name:20s} ${product.price:.2f} - {status}")


# --- Payment Strategy (Strategy Pattern - OCP/DIP) ---

class PaymentStrategy(ABC):
    """Interface Segregation: Specific to payment processing"""

    @abstractmethod
    def process_payment(self, amount: float) -> bool:
        pass

    @abstractmethod
    def refund(self, amount: float) -> bool:
        pass


class CashPayment(PaymentStrategy):
    def __init__(self):
        self._inserted_amount = 0.0
        self._coin_mechanism = CoinMechanism()

    def insert_coin(self, coin: Coin) -> None:
        self._inserted_amount += coin.value
        self._coin_mechanism.add_coin(coin)
        print(f"  Inserted {coin.display_name}. Total: ${self._inserted_amount:.2f}")

    def insert_note(self, note: Note) -> None:
        self._inserted_amount += note.value
        print(f"  Inserted {note.display_name}. Total: ${self._inserted_amount:.2f}")

    @property
    def current_balance(self) -> float:
        return self._inserted_amount

    def process_payment(self, amount: float) -> bool:
        if self._inserted_amount >= amount:
            self._inserted_amount -= amount
            return True
        return False

    def refund(self, amount: float) -> bool:
        self._inserted_amount += amount
        return True

    def get_change(self) -> float:
        change = self._inserted_amount
        self._inserted_amount = 0.0
        if change > 0:
            print(f"  Returning change: ${change:.2f}")
        return change


class CardPayment(PaymentStrategy):
    def __init__(self, card_number: str):
        self._card_number = card_number
        self._authorized = False

    def process_payment(self, amount: float) -> bool:
        print(f"  Processing card payment of ${amount:.2f}...")
        # Simulate card processing
        self._authorized = True
        return True

    def refund(self, amount: float) -> bool:
        print(f"  Refunding ${amount:.2f} to card {self._card_number[-4:]}")
        return True


class MobilePayment(PaymentStrategy):
    def __init__(self, provider: str, phone: str):
        self._provider = provider
        self._phone = phone

    def process_payment(self, amount: float) -> bool:
        print(f"  Processing {self._provider} payment of ${amount:.2f}...")
        return True

    def refund(self, amount: float) -> bool:
        print(f"  Refunding ${amount:.2f} via {self._provider}")
        return True


class CoinMechanism:
    """Handles coin operations"""

    def __init__(self):
        self._coins: Dict[Coin, int] = {}

    def add_coin(self, coin: Coin, count: int = 1) -> None:
        self._coins[coin] = self._coins.get(coin, 0) + count

    def has_change(self, amount: float) -> bool:
        # Simple check - could use greedy algorithm
        return self._get_total() >= amount

    def dispense_change(self, amount: float) -> Dict[Coin, int]:
        change: Dict[Coin, int] = {}
        remaining = amount
        # Greedy algorithm for change making
        for coin in sorted([c for c in Coin], key=lambda c: c.value, reverse=True):
            while remaining >= coin.value and self._coins.get(coin, 0) > 0:
                change[coin] = change.get(coin, 0) + 1
                self._coins[coin] -= 1
                remaining = round(remaining - coin.value, 2)
        if remaining > 0:
            # Refund coins if insufficient change
            for coin, count in change.items():
                self._coins[coin] = self._coins.get(coin, 0) + count
            raise ValueError("Insufficient change available")
        return change

    def _get_total(self) -> float:
        return sum(coin.value * count for coin, count in self._coins.items())


# --- Display (SRP / Observer) ---

class VendingDisplay:
    """Single Responsibility: Handles all display/output"""

    @staticmethod
    def show_welcome() -> None:
        print("\n=== Vending Machine ===")
        print("Select a product or press 'q' to quit")

    @staticmethod
    def show_insufficient_funds(product_name: str, price: float, balance: float) -> None:
        print(f"  Insufficient funds for {product_name}: ${price:.2f} needed, ${balance:.2f} available")

    @staticmethod
    def show_dispense(product_name: str) -> None:
        print(f"  🥤 Dispensing: {product_name}!")

    @staticmethod
    def show_transaction_complete() -> None:
        print("  ✅ Transaction complete. Thank you!")

    @staticmethod
    def show_refund(amount: float) -> None:
        print(f"  💰 Refund issued: ${amount:.2f}")


# --- Vending Machine States (State Pattern) ---

class VendingState(ABC):
    """Abstract state - Open/Closed for new states"""

    def __init__(self, machine: 'VendingMachine'):
        self._machine = machine

    @abstractmethod
    def select_product(self, product_id: str) -> None:
        pass

    @abstractmethod
    def insert_coin(self, coin: Coin) -> None:
        pass

    @abstractmethod
    def insert_note(self, note: Note) -> None:
        pass

    @abstractmethod
    def dispense_product(self) -> None:
        pass

    @abstractmethod
    def cancel_transaction(self) -> None:
        pass


class IdleState(VendingState):
    def select_product(self, product_id: str) -> None:
        product = self._machine._inventory.get_product(product_id)
        if not product:
            print(f"  Product not found: {product_id}")
            return
        if not self._machine._inventory.is_available(product_id):
            print(f"  {product.name} is sold out")
            return
        self._machine._selected_product = product
        self._machine._current_balance = 0.0
        self._machine._payment_strategy = CashPayment()
        print(f"  Selected: {product.name} - ${product.price:.2f}")
        print(f"  Please insert money")
        self._machine._state = self._machine._waiting_for_money_state

    def insert_coin(self, coin: Coin) -> None:
        print("  Please select a product first")

    def insert_note(self, note: Note) -> None:
        print("  Please select a product first")

    def dispense_product(self) -> None:
        print("  Please select a product first")

    def cancel_transaction(self) -> None:
        print("  No transaction to cancel")


class WaitingForMoneyState(VendingState):
    def select_product(self, product_id: str) -> None:
        print("  Already selected a product. Insert money or cancel.")

    def insert_coin(self, coin: Coin) -> None:
        self._machine._payment_strategy.insert_coin(coin)
        self._machine._current_balance = self._machine._payment_strategy.current_balance
        self._check_balance()

    def insert_note(self, note: Note) -> None:
        self._machine._payment_strategy.insert_note(note)
        self._machine._current_balance = self._machine._payment_strategy.current_balance
        self._check_balance()

    def _check_balance(self) -> None:
        if self._machine._current_balance >= self._machine._selected_product.price:
            self._machine._state = self._machine._ready_to_dispense_state
            print(f"  ✅ Sufficient funds! Press 'dispense' to receive your {self._machine._selected_product.name}")
        else:
            needed = self._machine._selected_product.price - self._machine._current_balance
            print(f"  💵 Need ${needed:.2f} more")

    def dispense_product(self) -> None:
        print("  Insufficient funds. Insert more money or cancel.")

    def cancel_transaction(self) -> None:
        if self._machine._current_balance > 0:
            self._machine._payment_strategy.refund(self._machine._current_balance)
            self._machine._current_balance = 0.0
        self._machine._selected_product = None
        self._machine._state = self._machine._idle_state
        print("  Transaction cancelled")


class ReadyToDispenseState(VendingState):
    def select_product(self, product_id: str) -> None:
        print("  Complete current transaction first or cancel")

    def insert_coin(self, coin: Coin) -> None:
        print("  Already have sufficient funds. Dispense or cancel.")

    def insert_note(self, note: Note) -> None:
        print("  Already have sufficient funds. Dispense or cancel.")

    def dispense_product(self) -> None:
        self._machine._payment_strategy.process_payment(self._machine._selected_product.price)
        product = self._machine._inventory.dispense(self._machine._selected_product.product_id)
        VendingDisplay.show_dispense(product.name)

        # Return change
        change = self._machine._current_balance - product.price
        if change > 0:
            try:
                self._machine._payment_strategy.get_change()
            except ValueError as e:
                print(f"  ⚠️ {e}")
                # Still dispensed the product

        self._machine._selected_product = None
        self._machine._current_balance = 0.0
        self._machine._state = self._machine._idle_state
        VendingDisplay.show_transaction_complete()

    def cancel_transaction(self) -> None:
        self._machine._payment_strategy.refund(self._machine._current_balance)
        self._machine._current_balance = 0.0
        self._machine._selected_product = None
        self._machine._state = self._machine._idle_state
        print("  Transaction cancelled. Money refunded.")


# --- Vending Machine (Facade) ---

class VendingMachine:
    """Facade for the entire vending machine system"""

    def __init__(self):
        self._inventory = Inventory()
        self._display = VendingDisplay()

        # States
        self._idle_state = IdleState(self)
        self._waiting_for_money_state = WaitingForMoneyState(self)
        self._ready_to_dispense_state = ReadyToDispenseState(self)
        self._state = self._idle_state

        self._selected_product: Optional[Product] = None
        self._current_balance = 0.0
        self._payment_strategy: PaymentStrategy = CashPayment()

    @property
    def inventory(self) -> Inventory:
        return self._inventory

    def select_product(self, product_id: str) -> None:
        self._state.select_product(product_id)

    def insert_coin(self, coin: Coin) -> None:
        self._state.insert_coin(coin)

    def insert_note(self, note: Note) -> None:
        self._state.insert_note(note)

    def dispense(self) -> None:
        self._state.dispense_product()

    def cancel(self) -> None:
        self._state.cancel_transaction()

    def show_products(self) -> None:
        self._inventory.display_products()


# --- Demo ---

def setup_vending_machine() -> VendingMachine:
    machine = VendingMachine()

    # Add products
    machine.inventory.add_product(Product("A1", "Coke", 1.50, "Drinks"), 10)
    machine.inventory.add_product(Product("A2", "Pepsi", 1.50, "Drinks"), 8)
    machine.inventory.add_product(Product("A3", "Water", 1.00, "Drinks"), 15)
    machine.inventory.add_product(Product("B1", "Chips", 1.25, "Snacks"), 12)
    machine.inventory.add_product(Product("B2", "Chocolate Bar", 1.75, "Snacks"), 10)
    machine.inventory.add_product(Product("C1", "Gum", 0.75, "Candy"), 20)
    machine.inventory.add_product(Product("C2", "Mints", 0.50, "Candy"), 25)

    return machine


def demo():
    machine = setup_vending_machine()

    # Interactive demo
    print("=== Vending Machine Demo ===")
    machine.show_products()

    # Simulate a purchase
    print("\n--- Customer 1 ---")
    machine.select_product("A1")
    machine.insert_coin(Coin.QUARTER)
    machine.insert_coin(Coin.QUARTER)
    machine.insert_coin(Coin.QUARTER)
    machine.insert_coin(Coin.QUARTER)
    machine.dispense()

    print("\n--- Customer 2 (Insufficient funds, then cancel) ---")
    machine.select_product("B2")
    machine.insert_coin(Coin.DIME)
    machine.cancel()

    print("\n--- Customer 3 ---")
    machine.select_product("C1")
    machine.insert_note(Note.ONE)
    machine.dispense()


if __name__ == "__main__":
    demo()
