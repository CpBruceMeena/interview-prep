/**
 * Elevator System - Low Level Design (Java)
 * -------------------------------------------
 * Design Principles: SOLID, State Pattern, Strategy Pattern, Observer Pattern
 *
 * Key Design Decisions:
 * - Elevator state machine using ENUM + State pattern (OCP)
 * - Request dispatching using Strategy pattern (SCAN, FCFS, Nearest-Car)
 * - Event-driven updates via Observer pattern for display/monitoring
 * - Immutable request objects for thread safety
 */

import java.util.*;
import java.util.concurrent.*;
import java.util.stream.*;

// ============================================================
// ENUMS & VALUE OBJECTS
// ============================================================

enum Direction {
    UP(1), DOWN(-1), IDLE(0);

    private final int value;
    Direction(int value) { this.value = value; }
    public int getValue() { return value; }

    public Direction opposite() {
        return switch (this) {
            case UP -> DOWN;
            case DOWN -> UP;
            case IDLE -> IDLE;
        };
    }
}

enum DoorState {
    OPEN, CLOSED, OPENING, CLOSING
}

enum ElevatorStatus {
    MOVING, STOPPED, DOOR_OPEN, DOOR_CLOSED, MAINTENANCE, OUT_OF_SERVICE
}

record Floor(int number, String label) {
    public Floor(int number) { this(number, "F" + number); }
}

record Request(int floor, Direction direction, long timestamp, UUID requestId) {
    public Request(int floor, Direction direction) {
        this(floor, direction, System.currentTimeMillis(), UUID.randomUUID());
    }
}

record TripPlan(int targetFloor, Direction direction) {}

// ============================================================
// OBSERVER INTERFACE
// ============================================================

interface ElevatorObserver {
    void onElevatorStopped(Elevator elevator, int floor);
    void onDoorStateChanged(Elevator elevator, DoorState state);
    void onFloorPassed(Elevator elevator, int floor);
    void onRequestProcessed(Request request);
    void onOverload(Elevator elevator);
    void onEmergency(Elevator elevator, String message);
}

// ============================================================
// DISPATCHING STRATEGY (Strategy Pattern - OCP/DIP)
// ============================================================

interface DispatchingStrategy {
    Elevator assignElevator(Request request, List<Elevator> elevators);
}

class NearestCarStrategy implements DispatchingStrategy {
    @Override
    public Elevator assignElevator(Request request, List<Elevator> elevators) {
        return elevators.stream()
            .filter(e -> e.getStatus() != ElevatorStatus.MAINTENANCE
                       && e.getStatus() != ElevatorStatus.OUT_OF_SERVICE)
            .min(Comparator.comparingInt(e ->
                Math.abs(e.getCurrentFloor() - request.floor())))
            .orElseThrow(() -> new IllegalStateException("No available elevators"));
    }
}

class ScanStrategy implements DispatchingStrategy {
    @Override
    public Elevator assignElevator(Request request, List<Elevator> elevators) {
        return elevators.stream()
            .filter(e -> e.getStatus() != ElevatorStatus.MAINTENANCE
                       && e.getStatus() != ElevatorStatus.OUT_OF_SERVICE)
            .filter(e -> e.getDirection() == Direction.IDLE
                       || e.getDirection() == request.direction())
            .min(Comparator.comparingInt(e ->
                Math.abs(e.getCurrentFloor() - request.floor())))
            .orElseGet(() -> new NearestCarStrategy().assignElevator(request, elevators));
    }
}

class LoadBalancingStrategy implements DispatchingStrategy {
    @Override
    public Elevator assignElevator(Request request, List<Elevator> elevators) {
        return elevators.stream()
            .filter(e -> e.getStatus() != ElevatorStatus.MAINTENANCE
                       && e.getStatus() != ElevatorStatus.OUT_OF_SERVICE)
            .min(Comparator.comparingInt(e ->
                e.getPendingRequests().size() * 5
                + Math.abs(e.getCurrentFloor() - request.floor())))
            .orElseThrow(() -> new IllegalStateException("No available elevators"));
    }
}

// ============================================================
// ELEVATOR (State Machine)
// ============================================================

class Elevator {
    private final String id;
    private final int maxCapacity;     // Max passengers
    private volatile int currentFloor;
    private volatile Direction direction;
    private volatile DoorState doorState;
    private volatile ElevatorStatus status;
    private final int minFloor, maxFloor;
    private final NavigableSet<Integer> stops;
    private final Queue<Integer> pendingStops;
    private final List<ElevatorObserver> observers;
    private final Set<Integer> requestedFloors;
    private int currentLoad;           // Number of passengers
    private final ScheduledExecutorService scheduler;
    private volatile boolean running;

    public Elevator(String id, int minFloor, int maxFloor, int maxCapacity) {
        this.id = id;
        this.minFloor = minFloor;
        this.maxFloor = maxFloor;
        this.maxCapacity = maxCapacity;
        this.currentFloor = 0;        // Ground floor
        this.direction = Direction.IDLE;
        this.doorState = DoorState.CLOSED;
        this.status = ElevatorStatus.STOPPED;
        this.stops = new ConcurrentSkipListSet<>();
        this.pendingStops = new ConcurrentLinkedQueue<>();
        this.observers = new CopyOnWriteArrayList<>();
        this.requestedFloors = ConcurrentHashMap.newKeySet();
        this.currentLoad = 0;
        this.scheduler = Executors.newSingleThreadScheduledExecutor();
        this.running = true;
    }

    // --- Public API ---

    public String getId() { return id; }
    public int getCurrentFloor() { return currentFloor; }
    public Direction getDirection() { return direction; }
    public DoorState getDoorState() { return doorState; }
    public ElevatorStatus getStatus() { return status; }
    public int getCurrentLoad() { return currentLoad; }
    public List<Integer> getPendingRequests() { return List.copyOf(stops); }

    public void addObserver(ElevatorObserver observer) {
        observers.add(observer);
    }

    public synchronized void addRequest(Request request) {
        if (status == ElevatorStatus.MAINTENANCE) {
            System.out.println("Elevator " + id + " is in maintenance. Request rejected.");
            return;
        }
        if (currentLoad >= maxCapacity) {
            notifyOverload();
            return;
        }
        stops.add(request.floor());
        requestedFloors.add(request.floor());
        notifyRequestProcessed(request);

        if (direction == Direction.IDLE) {
            direction = (request.floor() > currentFloor) ? Direction.UP : Direction.DOWN;
            startMoving();
        }
    }

    public synchronized void addInternalRequest(int floor) {
        if (floor < minFloor || floor > maxFloor) {
            System.out.println("Invalid floor: " + floor);
            return;
        }
        stops.add(floor);
        requestedFloors.add(floor);

        if (direction == Direction.IDLE) {
            direction = (floor > currentFloor) ? Direction.UP : Direction.DOWN;
            startMoving();
        }
    }

    public synchronized void openDoor() {
        if (doorState == DoorState.CLOSED) {
            doorState = DoorState.OPENING;
            notifyDoorStateChanged();
            // Simulate door opening time
            sleep(1000);
            doorState = DoorState.OPEN;
            status = ElevatorStatus.DOOR_OPEN;
            notifyDoorStateChanged();
        }
    }

    public synchronized void closeDoor() {
        if (doorState == DoorState.OPEN) {
            doorState = DoorState.CLOSING;
            notifyDoorStateChanged();
            sleep(1000);
            doorState = DoorState.CLOSED;
            status = ElevatorStatus.DOOR_CLOSED;
            notifyDoorStateChanged();
        }
    }

    public synchronized void setMaintenanceMode(boolean maintenance) {
        if (maintenance) {
            status = ElevatorStatus.MAINTENANCE;
            direction = Direction.IDLE;
            stops.clear();
        } else {
            status = ElevatorStatus.STOPPED;
        }
    }

    public void start() {
        running = true;
        scheduler.scheduleAtFixedRate(this::processNextStop, 0, 500, TimeUnit.MILLISECONDS);
    }

    public void shutdown() {
        running = false;
        scheduler.shutdown();
    }

    // --- Internal State Machine ---

    private void startMoving() {
        status = ElevatorStatus.MOVING;
        notifyElevatorStopped(this, currentFloor);
    }

    private synchronized void processNextStop() {
        if (!running || status == ElevatorStatus.MAINTENANCE) return;
        if (stops.isEmpty() && pendingStops.isEmpty()) {
            if (direction != Direction.IDLE) {
                direction = Direction.IDLE;
                status = ElevatorStatus.STOPPED;
            }
            return;
        }

        // Determine next stop based on direction
        Integer nextStop = findNextStop();
        if (nextStop == null) {
            // Change direction if no more stops in current direction
            direction = direction.opposite();
            nextStop = findNextStop();
            if (nextStop == null) {
                direction = Direction.IDLE;
                status = ElevatorStatus.STOPPED;
                return;
            }
        }

        // Move towards next stop
        int step = direction.getValue();
        int newFloor = currentFloor + step;

        if (newFloor >= minFloor && newFloor <= maxFloor) {
            currentFloor = newFloor;
            notifyFloorPassed(currentFloor);

            // Check if we need to stop at this floor
            if (requestedFloors.contains(currentFloor)) {
                stopAtCurrentFloor();
            }
        }
    }

    private Integer findNextStop() {
        if (direction == Direction.UP) {
            return stops.stream().filter(f -> f >= currentFloor).findFirst().orElse(null);
        } else if (direction == Direction.DOWN) {
            return stops.stream().filter(f -> f <= currentFloor)
                       .max(Integer::compareTo).orElse(null);
        }
        return stops.isEmpty() ? null : stops.first();
    }

    private synchronized void stopAtCurrentFloor() {
        stops.remove(currentFloor);
        requestedFloors.remove(currentFloor);

        status = ElevatorStatus.STOPPED;
        notifyElevatorStopped(this, currentFloor);

        openDoor();
        // Simulate passenger exchange
        sleep(2000);
        closeDoor();
    }

    private void sleep(long ms) {
        try { Thread.sleep(ms); } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    // --- Observer notifications ---

    private void notifyElevatorStopped(Elevator e, int floor) {
        observers.forEach(o -> o.onElevatorStopped(e, floor));
    }

    private void notifyDoorStateChanged() {
        observers.forEach(o -> o.onDoorStateChanged(this, doorState));
    }

    private void notifyFloorPassed(int floor) {
        observers.forEach(o -> o.onFloorPassed(this, floor));
    }

    private void notifyRequestProcessed(Request request) {
        observers.forEach(o -> o.onRequestProcessed(request));
    }

    private void notifyOverload() {
        observers.forEach(o -> o.onOverload(this));
    }

    public void notifyEmergency(String message) {
        observers.forEach(o -> o.onEmergency(this, message));
    }

    @Override
    public String toString() {
        return String.format("Elevator[%s] Floor=%d Dir=%s Door=%s Status=%s Stops=%d",
            id, currentFloor, direction, doorState, status, stops.size());
    }
}

// ============================================================
// ELEVATOR CONTROLLER (Facade + Observer)
// ============================================================

class ElevatorController implements ElevatorObserver {
    private final List<Elevator> elevators;
    private final DispatchingStrategy strategy;
    private final Queue<Request> pendingRequests;
    private final ScheduledExecutorService scheduler;

    public ElevatorController(int numElevators, int minFloor, int maxFloor,
                             int capacity, DispatchingStrategy strategy) {
        this.strategy = strategy;
        this.pendingRequests = new ConcurrentLinkedQueue<>();
        this.elevators = new CopyOnWriteArrayList<>();
        this.scheduler = Executors.newSingleThreadScheduledExecutor();

        for (int i = 0; i < numElevators; i++) {
            Elevator e = new Elevator("E" + (i + 1), minFloor, maxFloor, capacity);
            e.addObserver(this);
            e.start();
            elevators.add(e);
        }

        // Process pending requests periodically
        scheduler.scheduleAtFixedRate(this::processPendingRequests, 1, 1, TimeUnit.SECONDS);
    }

    // --- External API ---

    public void requestElevator(int floor, Direction direction) {
        Request request = new Request(floor, direction);
        pendingRequests.add(request);
        System.out.println("Request: Floor=" + floor + " Direction=" + direction);
    }

    public void shutdown() {
        elevators.forEach(Elevator::shutdown);
        scheduler.shutdown();
    }

    public void displayStatus() {
        System.out.println("\n=== Elevator Status ===");
        elevators.forEach(e -> System.out.println("  " + e));
        System.out.println("Pending requests: " + pendingRequests.size());
    }

    // --- Internal ---

    private void processPendingRequests() {
        Request request;
        while ((request = pendingRequests.poll()) != null) {
            try {
                Elevator assigned = strategy.assignElevator(request, elevators);
                assigned.addRequest(request);
                System.out.println("Assigned " + assigned.getId() + " to " + request);
            } catch (IllegalStateException e) {
                System.out.println("No elevator available for " + request);
                pendingRequests.add(request); // Re-queue
            }
        }
    }

    // --- Observer callbacks ---

    @Override
    public void onElevatorStopped(Elevator elevator, int floor) {
        // Could update display boards
    }

    @Override
    public void onDoorStateChanged(Elevator elevator, DoorState state) {
        // Could trigger safety checks
    }

    @Override
    public void onFloorPassed(Elevator elevator, int floor) {
        // Could update position tracking
    }

    @Override
    public void onRequestProcessed(Request request) {
        // Could update request tracking
    }

    @Override
    public void onOverload(Elevator elevator) {
        System.out.println("WARNING: " + elevator.getId() + " is overloaded!");
        // Could send notification or dispatch another elevator
    }

    @Override
    public void onEmergency(Elevator elevator, String message) {
        System.out.println("EMERGENCY: " + elevator.getId() + " - " + message);
        elevator.setMaintenanceMode(true);
    }
}

// ============================================================
// DEMO
// ============================================================

public class ElevatorSystem {
    public static void main(String[] args) throws InterruptedException {
        System.out.println("=== Elevator System Demo ===\n");

        // Create controller with 4 elevators, floors -2 to 20, capacity 10
        DispatchingStrategy strategy = new NearestCarStrategy();
        ElevatorController controller = new ElevatorController(4, -2, 20, 10, strategy);

        // Simulate requests
        controller.requestElevator(5, Direction.UP);
        Thread.sleep(500);
        controller.requestElevator(12, Direction.DOWN);
        Thread.sleep(300);
        controller.requestElevator(3, Direction.UP);
        Thread.sleep(200);
        controller.requestElevator(15, Direction.DOWN);

        // Let system run
        Thread.sleep(5000);

        System.out.println("\n--- More Requests ---");
        controller.requestElevator(0, Direction.UP);
        controller.requestElevator(20, Direction.DOWN);
        controller.requestElevator(8, Direction.UP);

        Thread.sleep(4000);
        controller.displayStatus();

        // Shutdown
        controller.shutdown();
        System.out.println("\n=== Demo Complete ===");
    }
}
