# 🏗️ Elevator System — Interview Questions

## Q1: Design the dispatching algorithm for a 6-elevator bank in a 40-floor building

**Key Points:**
- SCAN algorithm is ideal: elevators continue in one direction, collecting requests
- Each elevator maintains a sorted set of pending stops per direction
- On IDLE, elevator stays at last floor (vs returning to ground)
- For high traffic: zone-based dispatching (each elevator serves a floor range)

## Q2: How do you handle peak-hour traffic (8-10 AM upward, 5-7 PM downward)?

**Answer:**
- **Morning peak:** Most elevators default to ground floor (lobby)
- **Evening peak:** Elevators distribute across upper floors
- **Directional priority:** During upward peak, DOWN requests get lower priority
- **Express zone:** Dedicate 1-2 elevators to high floors only (20-40)
- **Machine learning:** Predict traffic patterns based on historical data

## Q3: How do you prevent elevator bunching?

**Answer:**
- **Staggered departure:** Don't send all idle elevators to the same floor
- **Dispatching delay:** Add small random delay before assigning
- **Sector allocation:** Each elevator serves a specific floor range
- **Anti-bunching algorithm:** If two elevators are close, re-route one

## Q4: How would you add real-time monitoring and predictive maintenance?

**Answer:**
- **Observer pattern** for event-driven metrics collection
- Track: door cycles, motor run-time, stops per day, average wait time
- **Predictive alerts:** Unusual door timing → bearing wear; vibration pattern → rail misalignment
- **Time-series DB:** Store metrics for anomaly detection
