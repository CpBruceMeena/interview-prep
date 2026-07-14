# Elevator System — Java Implementation

> Java implementation of a multi-car Elevator System following SOLID principles and design patterns.

## 📦 Core Implementation

### Key Abstractions

| Interface/Class | Responsibility | Pattern |
|----------------|---------------|---------|
| `DispatchingStrategy` | Assigns requests to elevators | Strategy |
| `ElevatorObserver` | Reacts to elevator events | Observer |
| `Elevator` | State machine for single car | State Machine |
| `ElevatorController` | Manages fleet of elevators | Facade |

### Dispatching Strategies

```java
// Strategy Pattern - interchangeable dispatching algorithms

interface DispatchingStrategy {
    Elevator assignElevator(Request request, List<Elevator> elevators);
}

class NearestCarStrategy implements DispatchingStrategy {
    // Assign the closest available elevator
    public Elevator assignElevator(Request request, List<Elevator> elevators) {
        return elevators.stream()
            .filter(e -> e.getStatus() != ElevatorStatus.MAINTENANCE)
            .min(Comparator.comparingInt(e ->
                Math.abs(e.getCurrentFloor() - request.floor())))
            .orElseThrow();
    }
}

class ScanStrategy implements DispatchingStrategy {
    // Assign elevator moving in the same direction (SCAN algorithm)
    public Elevator assignElevator(Request request, List<Elevator> elevators) {
        return elevators.stream()
            .filter(e -> e.getStatus() != ElevatorStatus.MAINTENANCE)
            .filter(e -> e.getDirection() == Direction.IDLE
                       || e.getDirection() == request.direction())
            .min(Comparator.comparingInt(e ->
                Math.abs(e.getCurrentFloor() - request.floor())))
            .orElseGet(() -> new NearestCarStrategy().assignElevator(request, elevators));
    }
}

class LoadBalancingStrategy implements DispatchingStrategy {
    // Assign elevator with fewest pending requests
    public Elevator assignElevator(Request request, List<Elevator> elevators) {
        return elevators.stream()
            .min(Comparator.comparingInt(e ->
                e.getPendingRequests().size() * 5
                + Math.abs(e.getCurrentFloor() - request.floor())))
            .orElseThrow();
    }
}
```

### Elevator State Machine

```java
enum Direction { UP, DOWN, IDLE }
enum DoorState { OPEN, CLOSED, OPENING, CLOSING }
enum ElevatorStatus { MOVING, STOPPED, DOOR_OPEN, MAINTENANCE }

class Elevator {
    // CONCURRENT STATE:
    private final NavigableSet<Integer> stops;    // Pending stops
    private volatile int currentFloor;
    private volatile Direction direction;
    private volatile ElevatorStatus status;
    private volatile DoorState doorState;
    private int currentLoad;

    // PROCESS FLOW:
    public synchronized void addRequest(Request request) {
        if (status == ElevatorStatus.MAINTENANCE) return;
        if (currentLoad >= maxCapacity) { notifyOverload(); return; }

        stops.add(request.floor());
        if (direction == Direction.IDLE) {
            direction = (request.floor() > currentFloor)
                ? Direction.UP : Direction.DOWN;
            startMoving();
        }
    }

    private synchronized void processNextStop() {
        if (stops.isEmpty()) {
            direction = Direction.IDLE;
            return;
        }
        Integer nextStop = findNextStop();
        if (nextStop == null) {
            direction = direction.opposite(); // Reverse direction (SCAN)
            nextStop = findNextStop();
        }
        // Move floor-by-floor toward next stop
        currentFloor += direction.getValue();
        if (requestedFloors.contains(currentFloor)) {
            stopAtCurrentFloor();
        }
    }
}
```

## ▶️ How to Run

```bash
cd java-low-level-design/elevator-system
javac ElevatorSystem.java
java ElevatorSystem
```

## 🧩 Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | DispatchingStrategy | Interchangeable SCAN / Nearest / Load-Balancing |
| **State** | Elevator lifecycle | MOVING → STOPPED → DOOR_OPEN → DOOR_CLOSED |
| **Observer** | ElevatorObserver | Display boards, monitoring, safety systems |
| **Facade** | ElevatorController | Unified interface over elevator fleet |
| **Command** | Request objects | Immutable, queueable, traceable |
