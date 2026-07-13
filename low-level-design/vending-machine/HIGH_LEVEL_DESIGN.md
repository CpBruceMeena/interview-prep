# 🏗️ Vending Machine — High-Level Design

> **Target Level:** Senior/Staff Engineer | **Focus:** IoT, embedded systems, payment processing, inventory chain

---

## 1. SYSTEM OVERVIEW

**Purpose:** IoT-connected vending machine network with real-time inventory tracking, remote monitoring, and dynamic pricing.

**Scale:** 10,000 machines, 100K transactions/day, 1M products tracked

**Users:** End customers (buyers), Route operators (restock), Admins (pricing, analytics)

**Use Cases:** Buy product (cash/card/UPI), Remote inventory check, Restock planning, Dynamic pricing

**Constraints:** Offline operation (machine works without internet), <2s transaction time, 99.5% payment success

---

## 2. HIGH-LEVEL ARCHITECTURE

```
┌───────────────────────┐
│     Vending Machine    │
│ (Raspberry Pi/STM32)   │
│ - Coin acceptor        │
│ - Card reader          │
│ - Dispenser motors     │
│ - Display              │
└──────────┬────────────┘
           │ MQTT (offline-capable)
           │ 4G/LTE backup
┌──────────▼────────────┐
│  IoT Gateway / Edge   │
│  (Local aggregation)   │
└──────────┬────────────┘
           │ HTTPS / Kafka
┌──────────▼────────────┐
│     API Gateway        │
└──────────┬────────────┘
           │
┌─────┬─────┬─────┬─────┐
│     │     │     │     │
▼     ▼     ▼     ▼     ▼
Auth  Inven-Trans-Price Moni-
      tory  action Eng   tor
      Svc   Svc    Svc   Svc
│     │     │     │     │
└─────┴──┬──┴──┬──┴─────┘
         │     │
    ┌────▼─┐ ┌─▼────┐
    │ Redis│ │Post- │
    │Cache │ │greSQL│
    └──────┘ └──────┘
```

### 🎬 Animated Sequence Diagram

<p align="center">
  <video controls width="900" style="border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);" loop playsinline preload="metadata">
    <source src="https://cpbrucemeena.github.io/interview-prep/assets/videos/vending-machine-sequence.mp4" type="video/mp4" />
    Your browser does not support the video tag.
  </video>
  <br/>
  <em>🎬 Animated Vending Machine Sequence — Insert Money → Select Item → Dispense → Change Return. Click ▶ to play/pause. Created with <a href="https://remotion.dev">Remotion</a>.</em>
</p>

---

## 3. KEY COMPONENTS & INTERVIEW Q&A

### Machine Firmware (Python on Raspberry Pi / C on STM32)
- State machine: Idle → Selecting → Payment → Dispensing → Complete
- Local inventory tracking
- Offline transaction queue

**🔴 Interview Question:** *"How does the machine handle transactions when the internet is down?"*

**✅ Answer:**
1. **Offline mode:** Machine queues transactions locally (SQLite file)
2. **Payment:** Accept cash only when offline (card requires auth)
3. **Sync on reconnect:** When connection restores, push queued transactions to cloud
4. **Conflict resolution:** Cloud validates each transaction — if product row was restocked between offline queue and sync, adjust inventory accordingly
5. **Machine state:** Reconcile physical inventory (count after restock) vs. cloud state

---

### Inventory Service (Python)
- Real-time stock per machine
- Restock alerts (threshold-based)
- Expiry tracking for perishable items
- FIFO slot management

**🔴 Interview Question:** *"How do you optimize restock routes for 10,000 machines?"*

**✅ Answer:**
1. **Vehicle Routing Problem (VRP):** Model as capacitated VRP with time windows
2. **Priority scoring:** `restock_urgency = (reorder_level - current_stock) / daily_sell_rate`
3. **Route optimization:** Use OR-Tools or similar solver — minimize distance while respecting truck capacity
4. **Dynamic re-routing:** If machine goes offline mid-route, recalculate
5. **Seasonal prediction:** ML model predicts restock needs by day of week, weather, nearby events

---

### Transaction Service (Node.js)
- Payment gateway integration (card, UPI, cash)
- Idempotency keys for retry safety
- Refund processing

**🔴 Interview Question:** *"How do you handle partial payment or insufficient change?"*

**✅ Answer:**
1. **Insufficient change:** Machine displays "Exact change only" before starting. If user inserts more, offer refund or alternative product.
2. **Partial payment:** Not possible — all-or-nothing per transaction. Cancel button triggers full refund.
3. **Change optimization:** Greedy algorithm with available coins. If exact change impossible, offer "Donate remaining" or show message.

---

## 4. DATA MODEL

```sql
CREATE TABLE machines (
    id UUID, location TEXT, firmware_version TEXT,
    last_online TIMESTAMP, status TEXT
);
CREATE TABLE slots (
    id UUID, machine_id UUID, position INT,
    product_id UUID, quantity INT, capacity INT,
    reorder_level INT, expiry_date DATE
);
CREATE TABLE transactions (
    id UUID, machine_id UUID, slot_id UUID,
    amount DECIMAL, payment_method TEXT, status TEXT,
    created_at TIMESTAMP
);
```

---

## 5. TRADE-OFF ANALYSIS

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Machine OS | Embedded Linux | Flexibility vs. RTOS. Need Python for ML models |
| Connectivity | MQTT + 4G | MQTT is lightweight, 4G for remote locations |
| Offline mode | Local queue + sync | Must work without internet for cash payments |
| Card reader | Cloud-based auth | P2PE encryption, tokenization for PCI compliance |

---

## 6. SCALABILITY

**Bottleneck:** 10K machines × 10 transactions/min peak = 1,667 TPS

**Solution:** Kafka for transaction ingestion, batch processing for inventory updates, Redis for real-time machine status

**Availability:** 99.95% cloud, 99.9% per-machine (offline fallback)
