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
 * - Emergency handling with priority overrides
 * - Maintenance scheduling with downtime tracking
 */

import java.time.*;
import java.time.format.DateTimeFormatter;
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
    OPEN, CLOSED, OPENING, CLOSING, OBSTRUCTED
}

enum ElevatorStatus {
    MOVING, STOPPED, DOOR_OPEN, DOOR_CLOSED,
    MAINTENANCE, OUT_OF_SERVICE, EMERGENCY_STOP,
    FIRE_MODE, POWER_FAILURE
}

enum EmergencyType {
    FIRE_ALARM, POWER_FAILURE, MEDICAL_EMERGENCY,
    EARTHQUAKE, BOMB_THREAT
}

record Floor(int number, String label) {
    public Floor(int number) { this(number, "F" + number); }

    public boolean isBasement() { return number < 0; }
    public boolean isGroundFloor() { return number == 0; }
    public boolean isTopFloor(int maxFloor) { return number == maxFloor; }
}

record Request(int floor, Direction direction, long timestamp, UUID requestId) {
    public Request(int floor, Direction direction) {
        this(floor, direction, System.currentTimeMillis(), UUID.randomUUID());
    }

    public boolean isUrgent() { return false; } // Base requests are not urgent
}

record UrgentRequest(int floor, Direction direction, EmergencyType type,
                     long timestamp, UUID requestId) {
    public UrgentRequest(int floor, Direction direction, EmergencyType type) {
        this(floor, direction, type, System.currentTimeMillis(), UUID.randomUUID());
    }

    public boolean isFireRelated() {
        return type == EmergencyType.FIRE_ALARM;
    }
}

record MaintenanceRecord(LocalDateTime scheduledAt, String technician,
                         String description, Duration estimatedDuration) {
    public boolean isOverdue() {
        return LocalDateTime.now().isAfter(scheduledAt);
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
    void onOverload(Elevator elevator, int currentLoad, int capacity);
    void onEmergency(Elevator elevator, EmergencyType type, String message);
    void onMaintenanceRequired(Elevator elevator, String reason);
    void onDoorObstructed(Elevator elevator);
    void onVIPModeActivated(Elevator elevator, boolean active);
    void onStatisticsUpdated(Elevator elevator, ElevatorStats stats);
}

// ============================================================
// STATISTICS COLLECTOR
// ============================================================

record ElevatorStats(long totalTrips, long totalFloorsPassed,
                     long totalDoorCycles, double avgWaitTimeMs,
                     long emergencyStops, long maintenanceHours,
                     double uptimePercentage, long energyConsumptionKwh) {

    public String formattedReport() {
        return String.format("""
            ╔══════════════════════════════════╗
            ║       ELEVATOR STATISTICS         ║
            ╠══════════════════════════════════╣
            ║ Trips:          %10d       ║
            ║ Floors Passed:  %10d       ║
            ║ Door Cycles:    %10d       ║
            ║ Avg Wait:       %10.2f ms   ║
            ║ Emergencies:    %10d       ║
            ║ Maint Hours:    %10d       ║
            ║ Uptime:         %10.2f%%    ║
            ║ Energy:         %10d kWh   ║
            ╚══════════════════════════════════╝""",
            totalTrips, totalFloorsPassed, totalDoorCycles,
            avgWaitTimeMs, emergencyStops, maintenanceHours,
            uptimePercentage * 100, energyConsumptionKwh);
    }
}

class StatisticsCollector {
    private final AtomicLong totalTrips = new AtomicLong(0);
    private final AtomicLong totalFloorsPassed = new AtomicLong(0);
    private final AtomicLong totalDoorCycles = new AtomicLong(0);
    private final AtomicLong totalWaitTimeMs = new AtomicLong(0);
    private final AtomicLong emergencyStops = new AtomicLong(0);
    private final AtomicLong maintenanceMinutes = new AtomicLong(0);
    private final AtomicLong energyConsumption = new AtomicLong(0);
    private final AtomicLong totalRequests = new AtomicLong(0);
    private volatile long startTime = System.currentTimeMillis();

    public void recordTrip() { totalTrips.incrementAndGet(); }
    public void recordFloorPassed() { totalFloorsPassed.incrementAndGet(); }
    public void recordDoorCycle() { totalDoorCycles.incrementAndGet(); }
    public void recordWaitTime(long ms) { totalWaitTimeMs.addAndGet(ms); }
    public void recordEmergency() { emergencyStops.incrementAndGet(); }
    public void recordMaintenance(long minutes) { maintenanceMinutes.addAndGet(minutes); }
    public void recordEnergy(long kwh) { energyConsumption.addAndGet(kwh); }
    public void recordRequest() { totalRequests.incrementAndGet(); }

    public ElevatorStats getStats() {
        long uptimeMs = System.currentTimeMillis() - startTime;
        double uptimePercentage = uptimeMs > 0
            ? (double)(uptimeMs - maintenanceMinutes.get() * 60 * 1000) / uptimeMs
            : 1.0;
        double avgWait = totalRequests.get() > 0
            ? (double) totalWaitTimeMs.get() / totalRequests.get()
            : 0.0;

        return new ElevatorStats(
            totalTrips.get(), totalFloorsPassed.get(), totalDoorCycles.get(),
            avgWait, emergencyStops.get(), maintenanceMinutes.get() / 60,
            uptimePercentage, energyConsumption.get()
        );
    }
}

// ============================================================
// WEIGHT SENSOR
// ============================================================

class WeightSensor {
    private static final double MAX_WEIGHT_KG = 1000.0;
    private static final double OVERLOAD_THRESHOLD = 0.95; // 95% triggers warning
    private static final double CRITICAL_THRESHOLD = 1.0;  // 100% triggers alarm
    private volatile double currentWeight = 0.0;
    private final List<Runnable> overloadListeners = new CopyOnWriteArrayList<>();

    public void addOverloadListener(Runnable listener) {
        overloadListeners.add(listener);
    }

    public synchronized boolean addPassenger(double weightKg) {
        double newWeight = currentWeight + weightKg;
        if (newWeight > MAX_WEIGHT_KG * CRITICAL_THRESHOLD) {
            overloadListeners.forEach(Runnable::run);
            return false; // Passenger cannot board
        }
        currentWeight = newWeight;
        if (currentWeight > MAX_WEIGHT_KG * OVERLOAD_THRESHOLD) {
            overloadListeners.forEach(Runnable::run);
        }
        return true;
    }

    public synchronized void removePassenger(double weightKg) {
        currentWeight = Math.max(0, currentWeight - weightKg);
    }

    public double getCurrentWeight() { return currentWeight; }
    public double getMaxWeight() { return MAX_WEIGHT_KG; }
    public double getUtilization() { return currentWeight / MAX_WEIGHT_KG; }
    public boolean isOverloaded() { return currentWeight > MAX_WEIGHT_KG * OVERLOAD_THRESHOLD; }
}

// ============================================================
// DOOR OBSTRUCTION DETECTOR
// ============================================================

class DoorObstructionDetector {
    private static final int MAX_OBSTRUCTION_RETRIES = 3;
    private static final Duration OBSTRUCTION_TIMEOUT = Duration.ofSeconds(10);
    private volatile int obstructionCount = 0;
    private volatile boolean permanentlyObstructed = false;
    private final List<Runnable> obstructionListeners = new CopyOnWriteArrayList<>();

    public void addObstructionListener(Runnable listener) {
        obstructionListeners.add(listener);
    }

    public synchronized boolean detectObstruction() {
        if (permanentlyObstructed) return true;

        // Simulate obstruction detection
        boolean obstructed = ThreadLocalRandom.current().nextDouble() < 0.05; // 5% chance
        if (obstructed) {
            obstructionCount++;
            if (obstructionCount >= MAX_OBSTRUCTION_RETRIES) {
                permanentlyObstructed = true;
                obstructionListeners.forEach(Runnable::run);
            }
        }
        return obstructed;
    }

    public void clearObstruction() {
        obstructionCount = 0;
        permanentlyObstructed = false;
    }

    public boolean isPermanentlyObstructed() { return permanentlyObstructed; }
    public int getObstructionCount() { return obstructionCount; }
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
                       && e.getStatus() != ElevatorStatus.OUT_OF_SERVICE
                       && e.getStatus() != ElevatorStatus.EMERGENCY_STOP
                       && e.getStatus() != ElevatorStatus.FIRE_MODE
                       && e.getStatus() != ElevatorStatus.POWER_FAILURE)
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
                       && e.getStatus() != ElevatorStatus.OUT_OF_SERVICE
                       && e.getStatus() != ElevatorStatus.EMERGENCY_STOP
                       && e.getStatus() != ElevatorStatus.FIRE_MODE
                       && e.getStatus() != ElevatorStatus.POWER_FAILURE)
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
                       && e.getStatus() != ElevatorStatus.OUT_OF_SERVICE
                       && e.getStatus() != ElevatorStatus.EMERGENCY_STOP
                       && e.getStatus() != ElevatorStatus.FIRE_MODE
                       && e.getStatus() != ElevatorStatus.POWER_FAILURE)
            .min(Comparator.comparingInt(e ->
                e.getPendingRequests().size() * 5
                + Math.abs(e.getCurrentFloor() - request.floor())))
            .orElseThrow(() -> new IllegalStateException("No available elevators"));
    }
}

class ZoneBasedStrategy implements DispatchingStrategy {
    private final int totalFloors;

    public ZoneBasedStrategy(int totalFloors) {
        this.totalFloors = totalFloors;
    }

    @Override
    public Elevator assignElevator(Request request, List<Elevator> elevators) {
        int numElevators = (int) elevators.stream()
            .filter(e -> e.getStatus() != ElevatorStatus.MAINTENANCE
                       && e.getStatus() != ElevatorStatus.OUT_OF_SERVICE)
            .count();
        if (numElevators == 0) throw new IllegalStateException("No available elevators");

        int zoneSize = totalFloors / Math.max(1, numElevators);
        int requestZone = request.floor() / Math.max(1, zoneSize);

        // Find elevators in the same zone
        return elevators.stream()
            .filter(e -> e.getStatus() != ElevatorStatus.MAINTENANCE
                       && e.getStatus() != ElevatorStatus.OUT_OF_SERVICE)
            .filter(e -> {
                int elevatorZone = e.getCurrentFloor() / Math.max(1, zoneSize);
                return elevatorZone == requestZone;
            })
            .min(Comparator.comparingInt(e ->
                Math.abs(e.getCurrentFloor() - request.floor())))
            .orElseGet(() -> new NearestCarStrategy().assignElevator(request, elevators));
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
    private final WeightSensor weightSensor;
    private final DoorObstructionDetector doorDetector;
    private final StatisticsCollector stats;
    private volatile boolean vipMode = false;
    private EmergencyType activeEmergency;
    private final Deque<Integer> priorityStops = new ConcurrentLinkedDeque<>();
    private long lastMaintenanceDate;
    private static final long MAINTENANCE_INTERVAL_MS = 7 * 24 * 60 * 60 * 1000L; // 7 days

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
        this.weightSensor = new WeightSensor();
        this.doorDetector = new DoorObstructionDetector();
        this.stats = new StatisticsCollector();
        this.lastMaintenanceDate = System.currentTimeMillis();

        // Wire up safety listeners
        this.weightSensor.addOverloadListener(() ->
            notifyOverload(currentLoad, maxCapacity));
        this.doorDetector.addObstructionListener(() ->
            notifyDoorObstructed());
    }

    // --- Public API ---

    public String getId() { return id; }
    public int getCurrentFloor() { return currentFloor; }
    public Direction getDirection() { return direction; }
    public DoorState getDoorState() { return doorState; }
    public ElevatorStatus getStatus() { return status; }
    public int getCurrentLoad() { return currentLoad; }
    public List<Integer> getPendingRequests() { return List.copyOf(stops); }
    public WeightSensor getWeightSensor() { return weightSensor; }
    public StatisticsCollector getStats() { return stats; }
    public boolean isVipMode() { return vipMode; }
    public EmergencyType getActiveEmergency() { return activeEmergency; }
    public boolean isMaintenanceDue() {
        return (System.currentTimeMillis() - lastMaintenanceDate) > MAINTENANCE_INTERVAL_MS;
    }

    public void addObserver(ElevatorObserver observer) {
        observers.add(observer);
    }

    public synchronized void addRequest(Request request) {
        if (!isOperational()) {
            System.out.println("Elevator " + id + " is " + status + ". Request rejected.");
            return;
        }
        if (currentLoad >= maxCapacity) {
            notifyOverload(currentLoad, maxCapacity);
            return;
        }
        stats.recordRequest();
        stops.add(request.floor());
        requestedFloors.add(request.floor());
        notifyRequestProcessed(request);

        if (direction == Direction.IDLE) {
            direction = (request.floor() > currentFloor) ? Direction.UP : Direction.DOWN;
            startMoving();
        }
    }

    public synchronized void addUrgentRequest(UrgentRequest request) {
        if (status == ElevatorStatus.MAINTENANCE || status == ElevatorStatus.OUT_OF_SERVICE) {
            return;
        }

        // Emergency override — clear all normal stops, go to emergency floor
        stops.clear();
        requestedFloors.clear();
        priorityStops.addFirst(request.floor());
        activeEmergency = request.type();
        status = ElevatorStatus.EMERGENCY_STOP;
        direction = (request.floor() > currentFloor) ? Direction.UP : Direction.DOWN;
        notifyEmergency(this, request.type(), "Emergency dispatch to floor " + request.floor());
        startMoving();
    }

    public synchronized void addInternalRequest(int floor) {
        if (!isOperational()) return;
        if (floor < minFloor || floor > maxFloor) {
            System.out.println("Invalid floor: " + floor);
            return;
        }
        if (vipMode) {
            priorityStops.add(floor);
        } else {
            stops.add(floor);
            requestedFloors.add(floor);
        }

        if (direction == Direction.IDLE) {
            direction = (floor > currentFloor) ? Direction.UP : Direction.DOWN;
            startMoving();
        }
    }

    public synchronized void openDoor() {
        if (doorState == DoorState.CLOSED || doorState == DoorState.OBSTRUCTED) {
            doorState = DoorState.OPENING;
            notifyDoorStateChanged();
            sleep(1000);

            // Check for obstruction
            if (doorDetector.detectObstruction()) {
                doorState = DoorState.OBSTRUCTED;
                status = ElevatorStatus.STOPPED;
                notifyDoorStateChanged();
                notifyDoorObstructed();
                return;
            }

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

            // Re-check obstruction during closing
            if (doorDetector.detectObstruction()) {
                doorState = DoorState.OPEN; // Re-open
                status = ElevatorStatus.DOOR_OPEN;
                notifyDoorStateChanged();
                notifyDoorObstructed();
                return;
            }

            doorState = DoorState.CLOSED;
            status = ElevatorStatus.DOOR_CLOSED;
            stats.recordDoorCycle();
            notifyDoorStateChanged();
        }
    }

    public synchronized void setMaintenanceMode(boolean maintenance) {
        if (maintenance) {
            status = ElevatorStatus.MAINTENANCE;
            direction = Direction.IDLE;
            stops.clear();
            priorityStops.clear();
            stats.recordMaintenance(60); // Log 1 hour of maintenance
        } else {
            status = ElevatorStatus.STOPPED;
            lastMaintenanceDate = System.currentTimeMillis();
        }
    }

    public synchronized void activateFireMode() {
        status = ElevatorStatus.FIRE_MODE;
        direction = Direction.IDLE;
        stops.clear();
        priorityStops.clear();
        activeEmergency = EmergencyType.FIRE_ALARM;
        notifyEmergency(this, EmergencyType.FIRE_ALARM, "Fire mode activated — returning to ground floor");

        // In fire mode, elevator goes to ground floor and stays with doors open
        goToFloor(0);
        openDoor();
        status = ElevatorStatus.FIRE_MODE;
    }

    public synchronized void activatePowerFailureMode() {
        status = ElevatorStatus.POWER_FAILURE;
        activeEmergency = EmergencyType.POWER_FAILURE;
        notifyEmergency(this, EmergencyType.POWER_FAILURE, "Power failure — stopping at nearest floor");

        // Stop at nearest floor and open doors
        stopAtCurrentFloor();
        openDoor();
        // Keep doors open with emergency lighting
        status = ElevatorStatus.POWER_FAILURE;
    }

    public synchronized void setVipMode(boolean active) {
        this.vipMode = active;
        notifyVIPModeActivated(active);
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

    private boolean isOperational() {
        return status != ElevatorStatus.MAINTENANCE
            && status != ElevatorStatus.OUT_OF_SERVICE
            && status != ElevatorStatus.FIRE_MODE
            && status != ElevatorStatus.POWER_FAILURE;
    }

    private void startMoving() {
        status = ElevatorStatus.MOVING;
        notifyElevatorStopped(this, currentFloor);
    }

    private void goToFloor(int targetFloor) {
        if (targetFloor < minFloor || targetFloor > maxFloor) return;
        direction = (targetFloor > currentFloor) ? Direction.UP : Direction.DOWN;
        status = ElevatorStatus.MOVING;

        while (currentFloor != targetFloor && running) {
            currentFloor += direction.getValue();
            stats.recordFloorPassed();
            notifyFloorPassed(currentFloor);
            sleep(500); // Time to move one floor
        }

        stopAtCurrentFloor();
    }

    private synchronized void processNextStop() {
        if (!running) return;
        if (!isOperational()) return;

        // Check maintenance due
        if (isMaintenanceDue() && stops.isEmpty() && priorityStops.isEmpty()) {
            notifyMaintenanceRequired("Regular maintenance interval reached");
            return;
        }

        // Check for priority stops first
        Integer priorityStop = priorityStops.peekFirst();
        if (priorityStop != null) {
            if (currentFloor == priorityStop) {
                priorityStops.pollFirst();
                stopAtCurrentFloor();
                return;
            }
            // Move towards priority stop
            direction = (priorityStop > currentFloor) ? Direction.UP : Direction.DOWN;
        }

        if (stops.isEmpty() && priorityStops.isEmpty()) {
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
            stats.recordFloorPassed();
            notifyFloorPassed(currentFloor);

            // Check if we need to stop at this floor
            if (requestedFloors.contains(currentFloor) || currentFloor == nextStop) {
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
        requestedFloors.remove(currentFloor);
        stops.remove(currentFloor);

        status = ElevatorStatus.STOPPED;
        stats.recordTrip();
        notifyElevatorStopped(this, currentFloor);

        openDoor();
        // Simulate passenger exchange
        sleep(2000);

        // Check weight after passenger exchange
        if (weightSensor.isOverloaded()) {
            notifyOverload(currentLoad, maxCapacity);
        }

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

    private void notifyOverload(int load, int capacity) {
        observers.forEach(o -> o.onOverload(this, load, capacity));
    }

    private void notifyEmergency(Elevator e, EmergencyType type, String message) {
        observers.forEach(o -> o.onEmergency(e, type, message));
    }

    private void notifyMaintenanceRequired(String reason) {
        observers.forEach(o -> o.onMaintenanceRequired(this, reason));
    }

    private void notifyDoorObstructed() {
        observers.forEach(o -> o.onDoorObstructed(this));
    }

    private void notifyVIPModeActivated(boolean active) {
        observers.forEach(o -> o.onVIPModeActivated(this, active));
    }

    private void notifyStatisticsUpdated() {
        observers.forEach(o -> o.onStatisticsUpdated(this, stats.getStats()));
    }

    public void notifyEmergency(String message) {
        observers.forEach(o -> o.onEmergency(this, EmergencyType.FIRE_ALARM, message));
    }

    @Override
    public String toString() {
        return String.format("Elevator[%s] Floor=%d Dir=%s Door=%s Status=%s Stops=%d Load=%d/%d",
            id, currentFloor, direction, doorState, status, stops.size(),
            currentLoad, maxCapacity);
    }

    public String detailedReport() {
        return toString() + "\n" + stats.getStats().formattedReport();
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
    private final Map<String, List<String>> emergencyLog;
    private volatile boolean emergencyMode = false;

    public ElevatorController(int numElevators, int minFloor, int maxFloor,
                             int capacity, DispatchingStrategy strategy) {
        this.strategy = strategy;
        this.pendingRequests = new ConcurrentLinkedQueue<>();
        this.elevators = new CopyOnWriteArrayList<>();
        this.scheduler = Executors.newSingleThreadScheduledExecutor();
        this.emergencyLog = new ConcurrentHashMap<>();

        for (int i = 0; i < numElevators; i++) {
            Elevator e = new Elevator("E" + (i + 1), minFloor, maxFloor, capacity);
            e.addObserver(this);
            e.start();
            elevators.add(e);
        }

        // Process pending requests periodically
        scheduler.scheduleAtFixedRate(this::processPendingRequests, 1, 1, TimeUnit.SECONDS);
        // Generate statistics reports periodically
        scheduler.scheduleAtFixedRate(this::generateStatisticsReport, 1, 1, TimeUnit.MINUTES);
    }

    // --- External API ---

    public void requestElevator(int floor, Direction direction) {
        Request request = new Request(floor, direction);
        pendingRequests.add(request);
        System.out.println("📞 Request: Floor=" + floor + " Direction=" + direction);
    }

    public void requestUrgentElevator(int floor, EmergencyType type) {
        UrgentRequest urgent = new UrgentRequest(floor, Direction.IDLE, type);
        System.out.println("🚨 URGENT: " + type + " — dispatching to floor " + floor);

        // Assign to nearest elevator regardless of strategy
        Elevator nearest = elevators.stream()
            .filter(e -> e.getStatus() != ElevatorStatus.MAINTENANCE
                       && e.getStatus() != ElevatorStatus.OUT_OF_SERVICE)
            .min(Comparator.comparingInt(e ->
                Math.abs(e.getCurrentFloor() - floor)))
            .orElse(null);

        if (nearest != null) {
            nearest.addUrgentRequest(urgent);
        }
    }

    public void activateFireAlarm() {
        System.out.println("🔥 FIRE ALARM ACTIVATED — All elevators returning to ground floor");
        emergencyMode = true;
        elevators.forEach(Elevator::activateFireMode);
    }

    public void activatePowerFailure() {
        System.out.println("⚡ POWER FAILURE DETECTED — All elevators stopping at nearest floor");
        emergencyMode = true;
        elevators.forEach(Elevator::activatePowerFailureMode);
    }

    public void clearEmergency() {
        System.out.println("✅ Emergency cleared — Resuming normal operation");
        emergencyMode = false;
        elevators.forEach(e -> e.setMaintenanceMode(false));
    }

    public void setVipMode(String elevatorId, boolean active) {
        elevators.stream()
            .filter(e -> e.getId().equals(elevatorId))
            .findFirst()
            .ifPresent(e -> e.setVipMode(active));
    }

    public void scheduleMaintenance(String elevatorId) {
        elevators.stream()
            .filter(e -> e.getId().equals(elevatorId))
            .findFirst()
            .ifPresent(e -> {
                System.out.println("🔧 Scheduling maintenance for " + elevatorId);
                e.setMaintenanceMode(true);
            });
    }

    public void shutdown() {
        elevators.forEach(Elevator::shutdown);
        scheduler.shutdown();
    }

    public void displayStatus() {
        System.out.println("\n" + "=".repeat(60));
        System.out.println("           ELEVATOR FLEET STATUS");
        System.out.println("=".repeat(60));
        elevators.forEach(e -> System.out.println("  " + e));
        System.out.println("Pending requests: " + pendingRequests.size() + " | " +
            "Emergency mode: " + (emergencyMode ? "🟥 ACTIVE" : "🟢 NORMAL"));
        System.out.println("=".repeat(60));
    }

    public void displayDetailedStatus() {
        System.out.println("\n" + "=".repeat(70));
        System.out.println("           ELEVATOR FLEET — DETAILED REPORT");
        System.out.println("=".repeat(70));
        elevators.forEach(e -> {
            System.out.println("  " + e);
            if (e.isMaintenanceDue()) {
                System.out.println("    ⚠️ MAINTENANCE DUE");
            }
            System.out.println("    Weight: " + String.format("%.0f", e.getWeightSensor().getUtilization() * 100) + "%");

            if (e.getActiveEmergency() != null) {
                System.out.println("    🚨 Emergency: " + e.getActiveEmergency());
            }
        });
        System.out.println("Pending requests: " + pendingRequests.size());
        System.out.println("=".repeat(70));
    }

    // --- Internal ---

    private void processPendingRequests() {
        if (emergencyMode) return; // Don't process normal requests during emergency

        Request request;
        while ((request = pendingRequests.poll()) != null) {
            try {
                Elevator assigned = strategy.assignElevator(request, elevators);
                assigned.addRequest(request);
                System.out.println("  Assigned " + assigned.getId() + " to " + request);
            } catch (IllegalStateException e) {
                System.out.println("  ⏳ No elevator available for " + request + " — queued");
                pendingRequests.add(request); // Re-queue
            }
        }
    }

    private void generateStatisticsReport() {
        System.out.println("\n📊 === STATISTICS REPORT ===");
        elevators.forEach(e -> {
            ElevatorStats stats = e.getStats();
            System.out.printf("  %s: %.1f%% uptime, %d trips, %d emergencies%n",
                e.getId(), stats.uptimePercentage() * 100,
                stats.totalTrips(), stats.emergencyStops());
        });
    }

    // --- Observer callbacks ---

    @Override
    public void onElevatorStopped(Elevator elevator, int floor) {}

    @Override
    public void onDoorStateChanged(Elevator elevator, DoorState state) {
        if (state == DoorState.OBSTRUCTED) {
            System.out.println("⚠️ " + elevator.getId() + ": Door obstructed at floor " + elevator.getCurrentFloor());
        }
    }

    @Override
    public void onFloorPassed(Elevator elevator, int floor) {}

    @Override
    public void onRequestProcessed(Request request) {}

    @Override
    public void onOverload(Elevator elevator, int currentLoad, int capacity) {
        System.out.println("⚠️ WARNING: " + elevator.getId() + " overloaded (" + currentLoad + "/" + capacity + ")");
        // Dispatch another elevator to help
        try {
            Elevator backup = new NearestCarStrategy().assignElevator(
                new Request(elevator.getCurrentFloor(), elevator.getDirection()), elevators);
            if (backup != elevator) {
                System.out.println("  Dispatching " + backup.getId() + " to assist");
            }
        } catch (IllegalStateException e) {
            System.out.println("  No backup elevator available");
        }
    }

    @Override
    public void onEmergency(Elevator elevator, EmergencyType type, String message) {
        System.out.println("🚨 EMERGENCY: " + elevator.getId() + " — " + message);
        emergencyLog.computeIfAbsent(elevator.getId(), k -> new CopyOnWriteArrayList<>())
            .add(LocalDateTime.now() + ": " + type + " — " + message);
    }

    @Override
    public void onMaintenanceRequired(Elevator elevator, String reason) {
        System.out.println("🔧 MAINTENANCE: " + elevator.getId() + " — " + reason);
        elevator.setMaintenanceMode(true);
    }

    @Override
    public void onDoorObstructed(Elevator elevator) {
        System.out.println("⚠️ " + elevator.getId() + ": Persistent door obstruction detected. Maintenance required.");
        elevator.setMaintenanceMode(true);
    }

    @Override
    public void onVIPModeActivated(Elevator elevator, boolean active) {
        System.out.println("👑 " + elevator.getId() + ": VIP mode " + (active ? "ACTIVATED" : "DEACTIVATED"));
    }

    @Override
    public void onStatisticsUpdated(Elevator elevator, ElevatorStats stats) {}
}

// ============================================================
// DEMO
// ============================================================

public class ElevatorSystem {
    public static void main(String[] args) throws InterruptedException {
        System.out.println("╔══════════════════════════════════╗");
        System.out.println("║     ELEVATOR SYSTEM DEMO        ║");
        System.out.println("╚══════════════════════════════════╝\n");

        System.out.println("🏢 Building: 40 floors (3 basements), 6 elevators\n");

        // Create controller with 6 elevators, floors -3 to 40, capacity 15
        DispatchingStrategy strategy = new ScanStrategy();
        ElevatorController controller = new ElevatorController(6, -3, 40, 15, strategy);

        // ---- NORMAL OPERATION ----
        System.out.println("--- NORMAL OPERATION ---");
        controller.requestElevator(5, Direction.UP);
        Thread.sleep(500);
        controller.requestElevator(12, Direction.DOWN);
        Thread.sleep(300);
        controller.requestElevator(3, Direction.UP);
        Thread.sleep(200);
        controller.requestElevator(15, Direction.DOWN);
        controller.requestElevator(0, Direction.UP);
        controller.requestElevator(20, Direction.DOWN);

        Thread.sleep(4000);
        controller.displayStatus();

        // ---- VIP MODE ----
        System.out.println("\n--- VIP MODE ---");
        controller.setVipMode("E2", true);
        controller.requestElevator(10, Direction.UP);
        controller.requestElevator(25, Direction.DOWN);

        Thread.sleep(2000);
        controller.setVipMode("E2", false);

        // ---- EMERGENCY SCENARIOS ----
        System.out.println("\n--- FIRE ALARM DRILL ---");
        controller.activateFireAlarm();
        Thread.sleep(2000);
        controller.displayStatus();

        System.out.println("\n--- CLEARING EMERGENCY ---");
        controller.clearEmergency();
        Thread.sleep(1000);

        // ---- OVERLOAD SCENARIO ----
        System.out.println("\n--- HEAVY TRAFFIC — MULTIPLE REQUESTS ---");
        for (int i = 0; i < 20; i++) {
            int from = ThreadLocalRandom.current().nextInt(0, 30);
            Direction dir = ThreadLocalRandom.current().nextBoolean() ? Direction.UP : Direction.DOWN;
            controller.requestElevator(from, dir);
        }

        Thread.sleep(3000);

        // ---- POWER FAILURE ----
        System.out.println("\n--- POWER FAILURE SCENARIO ---");
        controller.activatePowerFailure();
        Thread.sleep(1500);
        controller.clearEmergency();

        // ---- MAINTENANCE ----
        System.out.println("\n--- SCHEDULED MAINTENANCE ---");
        controller.scheduleMaintenance("E1");
        controller.scheduleMaintenance("E5");

        Thread.sleep(1000);
        controller.displayDetailedStatus();

        // ---- FINAL REPORT ----
        System.out.println("\n📋 FINAL FLEET REPORT:");
        controller.displayStatus();

        // Shutdown
        controller.shutdown();
        System.out.println("\n╔══════════════════════════════════╗");
        System.out.println("║       DEMO COMPLETE             ║");
        System.out.println("╚══════════════════════════════════╝");
    }
}
