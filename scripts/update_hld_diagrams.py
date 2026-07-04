"""
Update Parking Lot HIGH_LEVEL_DESIGN.md with:
1. A Mermaid sequence diagram showing the parking flow
2. A download link for the .drawio file
"""
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
filepath = os.path.join(project_root, 'low-level-design', 'parking-lot', 'HIGH_LEVEL_DESIGN.md')

with open(filepath, 'r') as f:
    content = f.read()

# Add the flow diagram and download link after the architecture section
old_marker = '---\n\n## 4. COMPONENT BREAKDOWN'

new_block = """
> **\U0001f4e5 Download:** [Parking Lot Architecture Diagram (draw.io)](parking-lot-hld.drawio) — Open in [draw.io](https://app.diagrams.net/) to edit.

---

## 2.5 PARKING FLOW

```mermaid
sequenceDiagram
    participant Driver as \U0001f697 Driver
    participant Gate as \U0001f6a7 Entry Gate
    participant EntrySvc as \U0001f5a5\ufe0f Entry Service
    participant Redis as \u26a1 Redis
    participant DB as \U0001f5c4\ufe0f PostgreSQL
    participant PaySvc as \U0001f4b3 Payment Service

    Driver->>Gate: Arrive at entry
    Gate->>EntrySvc: Request entry (ANPR capture)
    EntrySvc->>Redis: Acquire lock:gate:1
    EntrySvc->>Redis: Query nearest available spot
    Redis-->>EntrySvc: Spot A12 (Floor 1)
    EntrySvc->>DB: Create ticket (UUID, spot, plate)
    DB-->>EntrySvc: Ticket #TICK-000001
    EntrySvc->>Redis: Update spot status -> OCCUPIED
    EntrySvc-->>Gate: Open gate, display spot A12
    Gate-->>Driver: Gate opens, proceed to spot A12
    Driver->>Driver: Park at spot A12

    Note over Driver,PaySvc: Vehicle parked for X hours

    Driver->>Gate: Return to exit
    Gate->>EntrySvc: Request exit (ticket scan)
    EntrySvc->>DB: Retrieve ticket #TICK-000001
    DB-->>EntrySvc: Ticket: entry=2h ago, spot=A12
    EntrySvc->>PaySvc: Calculate fee (2h x compact rate)
    PaySvc->>PaySvc: $40.00
    PaySvc-->>EntrySvc: Fee = $40.00
    EntrySvc->>Driver: Display fee: $40.00
    Driver->>PaySvc: Process payment
    PaySvc->>DB: Record payment (idempotency key)
    PaySvc-->>Driver: Payment confirmed
    EntrySvc->>Redis: Update spot A12 -> AVAILABLE
    EntrySvc->>DB: Close ticket, record exit time
    EntrySvc-->>Gate: Open exit gate
    Gate-->>Driver: Gate opens, goodbye!
```

---

## 4. COMPONENT BREAKDOWN"""

if old_marker in content:
    content = content.replace(old_marker, new_block)
    with open(filepath, 'w') as f:
        f.write(content)
    print('Done: Parking Lot HLD updated')
else:
    print('ERROR: Marker not found')
    idx = content.find('COMPONENT BREAKDOWN')
    if idx >= 0:
        print(f'Context: {repr(content[idx-30:idx+30])}')
