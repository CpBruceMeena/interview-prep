# 🏗️ Car Rental Platform — High-Level Design

> **Target Level:** Senior/Staff Engineer | **Focus:** Fleet management, inventory optimization, dynamic pricing

---

## 1. SYSTEM OVERVIEW

**Purpose:** Car rental platform with fleet management, online reservations, dynamic pricing, and multi-location support.

**Scale:** 1K vehicles, 50 locations, 500 reservations/day, 100K members

**Users:** Customers (renters), Branch staff, Fleet managers, Maintenance team

**Use Cases:** Search available cars, Reserve vehicle, Start rental, Return vehicle, Fleet management

**Constraints:** No double-booking, <500ms availability check, 99.9% uptime, one-way rental support

---

## 2. HIGH-LEVEL ARCHITECTURE

```
Web/Mobile App (Customer)   Admin Dashboard
      │                           │
      └─────────┬─────────────────┘
                │
        ┌───────▼───────┐
        │  API Gateway   │
        └───────┬───────┘
                │
    ┌───────────┼───────────────┐
    │           │               │
┌───▼────┐ ┌───▼────┐ ┌───▼─────┐
│Search  │ │Reserve │ │Fleet    │
│Service │ │Service │ │Mgmt Svc │
│(Python)│ │(Python)│ │(Python) │
└───┬────┘ └───┬────┘ └───┬─────┘
    │          │          │
    └──────────┼──────────┘
               │
        ┌──────▼──────┐
        │ PostgreSQL  │
        │ + Btree_gist│
        │ exclusion   │
        └─────────────┘
```

---

## 3. KEY COMPONENTS & INTERVIEW Q&A

### Search Service (Python)
- Vehicle availability by date range
- Geo-filtering by location
- Price/type/category filtering

**🔴 Interview Question:** *"How do you check vehicle availability efficiently?"*

**✅ Answer:** PostgreSQL exclusion constraint prevents double-booking:
```sql
ALTER TABLE reservations ADD CONSTRAINT no_double_booking
EXCLUDE USING gist (
    vehicle_id WITH =,
    daterange(pickup_date, return_date, '[]') WITH &&
);
```
No application logic needed — database guarantees no overlapping reservations for the same vehicle.

---

### Reservation Service (Python)
- Create/confirm/cancel reservations
- Add optional services (insurance, GPS, child seat)
- Payment pre-authorization

---

## 4. DATA MODEL

```sql
CREATE TABLE vehicles (
    id UUID, type TEXT, make TEXT, model TEXT, year INT,
    license_plate TEXT UNIQUE, daily_rate DECIMAL(8,2),
    status TEXT, location TEXT, mileage INT
);
CREATE TABLE reservations (
    id UUID, customer_id UUID, vehicle_id UUID,
    pickup_date DATE, return_date DATE,
    pickup_location TEXT, dropoff_location TEXT,
    total_amount DECIMAL(10,2), status TEXT
);
CREATE TABLE customers (
    id UUID, name TEXT, email TEXT UNIQUE, phone TEXT,
    license_number TEXT, loyalty_points INT
);
```

---

## 5. COST (Monthly)

| Component | Cost |
|-----------|------|
| API Services | $1,500 |
| PostgreSQL | $600 |
| Monitoring | $200 |
| **Total** | **$2,300** |
