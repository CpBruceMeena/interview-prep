/**
 * Elevator System - Low Level Design (Java 17+)
 * ----------------------------------------------
 * Run:  java ElevatorSystem.java      (single-file source launcher; main self-checks and
 *                                       throws AssertionError if any behaviour breaks)
 *
 * Scope: a bank of N cars serving floors [minFloor, maxFloor].
 *   - Hall calls (floor + UP/DOWN button) are dispatched to ONE car by a pluggable strategy.
 *   - Car calls (button inside the cab) go straight to that car.
 *   - Each car schedules its own stops with LOOK: keep going in the current direction while
 *     there is work ahead, then reverse; a hall call is only answered when the car is
 *     travelling in the direction the passenger asked for (or is turning around there).
 *   - Cars can be taken out of service; their outstanding hall calls are re-dispatched.
 *
 * Key design decisions:
 *   - Time is discrete. Elevator.step() performs ONE action (move a floor, open doors,
 *     close doors). A ScheduledExecutorService drives step() in real time; tests call
 *     tick() directly, so every scenario is deterministic. No Thread.sleep under a lock.
 *   - Each Elevator guards its state with its own lock. Listener callbacks fire AFTER the
 *     lock is released, so a listener can call back into the controller without creating
 *     a lock-order cycle.
 *   - The controller serialises dispatch with one lock (hall calls arrive at human speed,
 *     so throughput is a non-issue) and keeps a HallCall -> car map so repeated presses of
 *     the same button are idempotent. Lock order is always controller -> elevator.
 */

import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.locks.ReentrantLock;
import java.util.stream.Collectors;

/** Entry point. Must be the first top-level class: `java File.java` runs the first class it finds. */
public class ElevatorSystem {
    public static void main(String[] args) throws Exception {
        ElevatorDemo.run();
    }
}

// ============================================================
// VALUE TYPES
// ============================================================

enum Direction {
    UP(1), DOWN(-1), IDLE(0);

    final int delta;
    Direction(int delta) { this.delta = delta; }

    Direction opposite() {
        return switch (this) {
            case UP -> DOWN;
            case DOWN -> UP;
            case IDLE -> IDLE;
        };
    }
}

/** Per-car state machine: IDLE -> MOVING -> DOORS_OPEN -> (MOVING | IDLE); any -> MAINTENANCE. */
enum ElevatorState { IDLE, MOVING, DOORS_OPEN, MAINTENANCE }

/** A hall button press. Equality is (floor, direction), which is what makes presses idempotent. */
record HallCall(int floor, Direction direction) {
    HallCall {
        if (direction == Direction.IDLE) throw new IllegalArgumentException("hall call needs UP or DOWN");
    }
}

/** Immutable view of a car, taken under its lock, so strategies never see torn state. */
record ElevatorSnapshot(String id, int floor, Direction direction, ElevatorState state,
                        int pendingStops, int lowestStop, int highestStop) {}

/** Observer hook. Callbacks run on the thread that called step(), outside the car's lock. */
interface ElevatorListener {
    default void onStopped(String elevatorId, int floor) {}
    default void onHallCallServed(String elevatorId, HallCall call) {}
}

// ============================================================
// DISPATCH STRATEGIES (Strategy pattern)
// ============================================================

interface DispatchStrategy {
    /** Pick a car for the call from in-service candidates; empty if none is suitable. */
    Optional<ElevatorSnapshot> choose(HallCall call, List<ElevatorSnapshot> candidates);
}

/** Baseline: closest car by distance, ignoring direction. Causes bunching and wrong-way pickups. */
final class NearestCarStrategy implements DispatchStrategy {
    @Override
    public Optional<ElevatorSnapshot> choose(HallCall call, List<ElevatorSnapshot> candidates) {
        return candidates.stream().min(Comparator
                .comparingInt((ElevatorSnapshot s) -> Math.abs(s.floor() - call.floor()))
                .thenComparing(ElevatorSnapshot::id));
    }
}

/**
 * Direction-aware: estimate how many floors each car must travel under LOOK before it can
 * pick this passenger up, and choose the minimum. A car already heading toward the call in
 * the same direction is cheap; a car moving away pays for its whole sweep and the return.
 * (Ignores dwell time at intermediate stops; add a per-stop penalty if that matters.)
 */
final class LookEtaStrategy implements DispatchStrategy {
    @Override
    public Optional<ElevatorSnapshot> choose(HallCall call, List<ElevatorSnapshot> candidates) {
        return candidates.stream().min(Comparator
                .comparingInt((ElevatorSnapshot s) -> eta(s, call))
                .thenComparing(ElevatorSnapshot::id));
    }

    static int eta(ElevatorSnapshot s, HallCall c) {
        return switch (s.direction()) {
            case IDLE -> Math.abs(s.floor() - c.floor());
            case UP -> etaGoingUp(s.floor(), s.lowestStop(), s.highestStop(), c.floor(), c.direction());
            // Mirror the building (floor -> -floor) so DOWN reuses the UP formula.
            case DOWN -> etaGoingUp(-s.floor(), -s.highestStop(), -s.lowestStop(), -c.floor(),
                                    c.direction().opposite());
        };
    }

    private static int etaGoingUp(int at, int lowest, int highest, int callFloor, Direction callDir) {
        if (callDir == Direction.UP && callFloor >= at) return callFloor - at;     // on the way
        int peak = Math.max(highest, at);
        if (callDir == Direction.DOWN) {
            peak = Math.max(peak, callFloor);                                     // reverses there
            return (peak - at) + (peak - callFloor);
        }
        int bottom = Math.min(lowest, callFloor);                                 // UP call behind us
        return (peak - at) + (peak - bottom) + (callFloor - bottom);
    }
}

// ============================================================
// ELEVATOR (per-car state machine + LOOK scheduling)
// ============================================================

final class Elevator {
    private final String id;
    private final int minFloor, maxFloor;
    private final List<ElevatorListener> listeners = new CopyOnWriteArrayList<>();

    private final ReentrantLock lock = new ReentrantLock();
    // ---- guarded by lock ----
    private int floor;
    private Direction direction = Direction.IDLE;
    private ElevatorState state = ElevatorState.IDLE;
    private final TreeSet<Integer> carStops = new TreeSet<>();
    private final TreeSet<Integer> upCalls = new TreeSet<>();
    private final TreeSet<Integer> downCalls = new TreeSet<>();

    Elevator(String id, int minFloor, int maxFloor, int startFloor) {
        if (minFloor >= maxFloor) throw new IllegalArgumentException("need at least two floors");
        if (startFloor < minFloor || startFloor > maxFloor) throw new IllegalArgumentException("bad start floor");
        this.id = id;
        this.minFloor = minFloor;
        this.maxFloor = maxFloor;
        this.floor = startFloor;
    }

    String id() { return id; }
    void addListener(ElevatorListener l) { listeners.add(l); }

    ElevatorSnapshot snapshot() {
        lock.lock();
        try {
            int pending = carStops.size() + upCalls.size() + downCalls.size();
            int lo = floor, hi = floor;
            for (TreeSet<Integer> s : List.of(carStops, upCalls, downCalls)) {
                if (!s.isEmpty()) { lo = Math.min(lo, s.first()); hi = Math.max(hi, s.last()); }
            }
            return new ElevatorSnapshot(id, floor, direction, state, pending, lo, hi);
        } finally {
            lock.unlock();
        }
    }

    /** @return false if the car cannot take the call (out of service); the caller re-dispatches. */
    boolean addHallCall(HallCall call) {
        checkFloor(call.floor());
        lock.lock();
        try {
            if (state == ElevatorState.MAINTENANCE) return false;
            (call.direction() == Direction.UP ? upCalls : downCalls).add(call.floor());
            return true;
        } finally {
            lock.unlock();
        }
    }

    void addCarCall(int target) {
        checkFloor(target);
        lock.lock();
        try {
            if (state == ElevatorState.MAINTENANCE) throw new IllegalStateException(id + " is out of service");
            if (target == floor && state == ElevatorState.DOORS_OPEN) return;   // already there, doors open
            carStops.add(target);
        } finally {
            lock.unlock();
        }
    }

    /** Take the car out of service. Returns hall calls it owed so the controller can reassign them. */
    List<HallCall> enterMaintenance() {
        lock.lock();
        try {
            List<HallCall> orphaned = new ArrayList<>();
            upCalls.forEach(f -> orphaned.add(new HallCall(f, Direction.UP)));
            downCalls.forEach(f -> orphaned.add(new HallCall(f, Direction.DOWN)));
            upCalls.clear();
            downCalls.clear();
            carStops.clear();
            direction = Direction.IDLE;
            state = ElevatorState.MAINTENANCE;
            return orphaned;
        } finally {
            lock.unlock();
        }
    }

    void exitMaintenance() {
        lock.lock();
        try {
            if (state == ElevatorState.MAINTENANCE) state = ElevatorState.IDLE;
        } finally {
            lock.unlock();
        }
    }

    /** Advance the state machine by one action. Events are published after the lock is released. */
    void step() {
        List<Runnable> events = new ArrayList<>();
        lock.lock();
        try {
            switch (state) {
                case MAINTENANCE -> { }
                case DOORS_OPEN -> {                         // close doors, decide what is next
                    if (hasAnyStop()) {
                        state = ElevatorState.MOVING;
                    } else {
                        state = ElevatorState.IDLE;
                        direction = Direction.IDLE;
                    }
                }
                case IDLE, MOVING -> {
                    if (serveCurrentFloor(events)) {
                        state = ElevatorState.DOORS_OPEN;
                    } else {
                        direction = chooseDirection();
                        if (direction == Direction.IDLE) {
                            state = ElevatorState.IDLE;
                        } else {
                            floor += direction.delta;        // never leaves [min,max]: stops are validated
                            state = ElevatorState.MOVING;
                        }
                    }
                }
            }
        } finally {
            lock.unlock();
        }
        events.forEach(Runnable::run);
    }

    // ---- LOOK internals (caller holds lock) ----

    /** Opens doors here if a car stop or a hall call we can accept in our direction is at this floor. */
    private boolean serveCurrentFloor(List<Runnable> events) {
        boolean carStop = carStops.remove(floor);
        Direction preferred = direction != Direction.IDLE ? direction
                : upCalls.contains(floor) ? Direction.UP : Direction.DOWN;
        Direction served = null;
        if (removeHallCall(preferred)) {
            served = preferred;
        } else if (!hasStopAhead(preferred) && removeHallCall(preferred.opposite())) {
            served = preferred.opposite();                   // end of sweep: turn around here
        }
        if (!carStop && served == null) return false;

        if (served != null) {
            direction = served;                              // lantern shows the direction we'll go
            HallCall call = new HallCall(floor, served);
            listeners.forEach(l -> events.add(() -> l.onHallCallServed(id, call)));
        }
        int at = floor;
        listeners.forEach(l -> events.add(() -> l.onStopped(id, at)));
        return true;
    }

    private boolean removeHallCall(Direction d) {
        return (d == Direction.UP ? upCalls : downCalls).remove(floor);
    }

    private Direction chooseDirection() {
        boolean above = hasStopAhead(Direction.UP), below = hasStopAhead(Direction.DOWN);
        return switch (direction) {
            case UP -> above ? Direction.UP : below ? Direction.DOWN : Direction.IDLE;
            case DOWN -> below ? Direction.DOWN : above ? Direction.UP : Direction.IDLE;
            case IDLE -> {
                if (!above && !below) yield Direction.IDLE;
                if (!below) yield Direction.UP;
                if (!above) yield Direction.DOWN;
                yield nearest(Direction.UP) - floor <= floor - nearest(Direction.DOWN) ? Direction.UP : Direction.DOWN;
            }
        };
    }

    private boolean hasStopAhead(Direction d) {
        if (d == Direction.IDLE) return false;
        for (TreeSet<Integer> s : List.of(carStops, upCalls, downCalls)) {
            if ((d == Direction.UP ? s.higher(floor) : s.lower(floor)) != null) return true;
        }
        return false;
    }

    private int nearest(Direction d) {
        int best = d == Direction.UP ? Integer.MAX_VALUE : Integer.MIN_VALUE;
        for (TreeSet<Integer> s : List.of(carStops, upCalls, downCalls)) {
            Integer f = d == Direction.UP ? s.higher(floor) : s.lower(floor);
            if (f != null) best = d == Direction.UP ? Math.min(best, f) : Math.max(best, f);
        }
        return best;
    }

    private boolean hasAnyStop() {
        return !carStops.isEmpty() || !upCalls.isEmpty() || !downCalls.isEmpty();
    }

    private void checkFloor(int f) {
        if (f < minFloor || f > maxFloor) throw new IllegalArgumentException("floor " + f + " out of range");
    }

    @Override
    public String toString() {
        ElevatorSnapshot s = snapshot();
        return "%s[floor=%d dir=%s state=%s pending=%d]".formatted(id, s.floor(), s.direction(), s.state(), s.pendingStops());
    }
}

// ============================================================
// CONTROLLER (Facade: dispatch, maintenance, real-time driver)
// ============================================================

final class ElevatorController implements AutoCloseable {
    private final Map<String, Elevator> elevators;          // insertion-ordered, immutable after construction
    private final int minFloor, maxFloor;
    private final DispatchStrategy strategy;

    private final ReentrantLock dispatchLock = new ReentrantLock();
    private final Map<HallCall, String> assignments = new HashMap<>();   // guarded by dispatchLock
    private ScheduledExecutorService ticker;                             // guarded by this

    ElevatorController(int cars, int minFloor, int maxFloor, DispatchStrategy strategy) {
        this.minFloor = minFloor;
        this.maxFloor = maxFloor;
        this.strategy = Objects.requireNonNull(strategy);
        Map<String, Elevator> m = new LinkedHashMap<>();
        for (int i = 1; i <= cars; i++) {
            Elevator e = new Elevator("E" + i, minFloor, maxFloor, minFloor);
            e.addListener(new ElevatorListener() {
                @Override public void onHallCallServed(String elevatorId, HallCall call) { release(call, elevatorId); }
            });
            m.put(e.id(), e);
        }
        this.elevators = Collections.unmodifiableMap(m);
    }

    void addListener(ElevatorListener l) { elevators.values().forEach(e -> e.addListener(l)); }

    /** Press a hall button. Thread-safe and idempotent: re-pressing returns the car already assigned. */
    String requestElevator(int floor, Direction direction) {
        if (floor < minFloor || floor > maxFloor) throw new IllegalArgumentException("floor " + floor + " out of range");
        if ((floor == maxFloor && direction == Direction.UP) || (floor == minFloor && direction == Direction.DOWN)) {
            throw new IllegalArgumentException("no " + direction + " button on floor " + floor);
        }
        HallCall call = new HallCall(floor, direction);
        dispatchLock.lock();
        try {
            return dispatchLocked(call);
        } finally {
            dispatchLock.unlock();
        }
    }

    /** Press a button inside a car. */
    void selectFloor(String elevatorId, int floor) { car(elevatorId).addCarCall(floor); }

    void setMaintenance(String elevatorId, boolean on) {
        Elevator e = car(elevatorId);
        if (!on) { e.exitMaintenance(); return; }
        dispatchLock.lock();
        try {
            for (HallCall orphan : e.enterMaintenance()) {
                assignments.remove(orphan, elevatorId);
                try {
                    dispatchLocked(orphan);
                } catch (IllegalStateException noCar) {
                    // Whole bank is down: the call is dropped and the hall lamp goes dark (passenger re-presses).
                }
            }
        } finally {
            dispatchLock.unlock();
        }
    }

    /** One simulation step for every car. Called by the ticker, or directly by tests. */
    void tick() { elevators.values().forEach(Elevator::step); }

    synchronized void start(Duration period) {
        if (ticker != null) return;
        ticker = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "elevator-ticker");
            t.setDaemon(true);
            return t;
        });
        // Wrap so one unexpected exception doesn't silently cancel the periodic task.
        ticker.scheduleAtFixedRate(() -> {
            try { tick(); } catch (RuntimeException ex) { ex.printStackTrace(); }
        }, 0, period.toNanos(), TimeUnit.NANOSECONDS);
    }

    @Override
    public synchronized void close() {
        if (ticker != null) { ticker.shutdownNow(); ticker = null; }
    }

    boolean isQuiescent() {
        dispatchLock.lock();
        try {
            if (!assignments.isEmpty()) return false;
        } finally {
            dispatchLock.unlock();
        }
        return elevators.values().stream().map(Elevator::snapshot)
                .allMatch(s -> s.pendingStops() == 0 && s.state() != ElevatorState.DOORS_OPEN
                        && s.state() != ElevatorState.MOVING);
    }

    ElevatorSnapshot status(String elevatorId) { return car(elevatorId).snapshot(); }

    int outstandingHallCalls() {
        dispatchLock.lock();
        try { return assignments.size(); } finally { dispatchLock.unlock(); }
    }

    // ---- internals ----

    private String dispatchLocked(HallCall call) {
        String existing = assignments.get(call);
        if (existing != null) return existing;
        Set<String> rejected = new HashSet<>();
        while (true) {
            List<ElevatorSnapshot> candidates = elevators.values().stream()
                    .map(Elevator::snapshot)
                    .filter(s -> s.state() != ElevatorState.MAINTENANCE && !rejected.contains(s.id()))
                    .collect(Collectors.toList());
            ElevatorSnapshot pick = strategy.choose(call, candidates)
                    .orElseThrow(() -> new IllegalStateException("no elevator in service"));
            // Snapshot may be stale by now; addHallCall re-checks under the car's lock.
            if (car(pick.id()).addHallCall(call)) {
                assignments.put(call, pick.id());
                return pick.id();
            }
            rejected.add(pick.id());
        }
    }

    /** Called from Elevator.step() after the car released its lock: lock order stays controller -> car. */
    private void release(HallCall call, String elevatorId) {
        dispatchLock.lock();
        try {
            assignments.remove(call, elevatorId);
        } finally {
            dispatchLock.unlock();
        }
    }

    private Elevator car(String id) {
        Elevator e = elevators.get(id);
        if (e == null) throw new IllegalArgumentException("unknown elevator " + id);
        return e;
    }
}

// ============================================================
// DEMO + SELF-CHECKS
// ============================================================

final class ElevatorDemo {

    /** Records the order of stops per car so tests can assert LOOK ordering. */
    static final class StopRecorder implements ElevatorListener {
        final Map<String, List<Integer>> stops = new ConcurrentHashMap<>();
        final Map<HallCall, AtomicInteger> served = new ConcurrentHashMap<>();
        @Override public void onStopped(String id, int floor) {
            stops.computeIfAbsent(id, k -> Collections.synchronizedList(new ArrayList<>())).add(floor);
        }
        @Override public void onHallCallServed(String id, HallCall call) {
            served.computeIfAbsent(call, k -> new AtomicInteger()).incrementAndGet();
        }
        List<Integer> of(String id) { return stops.getOrDefault(id, List.of()); }
    }

    static void check(boolean ok, String what) {
        if (!ok) throw new AssertionError("FAILED: " + what);
        System.out.println("  ok  " + what);
    }

    static void runUntilQuiet(ElevatorController c, int maxTicks) {
        for (int i = 0; i < maxTicks; i++) {
            c.tick();
            if (c.isQuiescent()) return;
        }
        throw new AssertionError("system did not settle within " + maxTicks + " ticks");
    }

    static void run() throws Exception {
        System.out.println("== 1. LOOK ordering of car calls ==");
        try (ElevatorController c = new ElevatorController(1, 0, 10, new LookEtaStrategy())) {
            StopRecorder rec = new StopRecorder();
            c.addListener(rec);
            c.selectFloor("E1", 5);
            c.selectFloor("E1", 2);
            c.tick(); c.tick();                     // car now moving up from 0
            c.selectFloor("E1", 8);
            c.selectFloor("E1", 1);                 // behind the car: served after the up sweep
            runUntilQuiet(c, 100);
            check(rec.of("E1").equals(List.of(2, 5, 8, 1)), "car visits 2,5,8 on the way up then 1: " + rec.of("E1"));
        }

        System.out.println("== 2. Hall calls respect direction ==");
        try (ElevatorController c = new ElevatorController(1, 0, 10, new LookEtaStrategy())) {
            StopRecorder rec = new StopRecorder();
            c.addListener(rec);
            c.selectFloor("E1", 9);
            c.tick();                               // leaves floor 0 going up
            c.requestElevator(4, Direction.DOWN);   // wrong direction: skip on the way up
            c.requestElevator(6, Direction.UP);     // same direction: pick up on the way
            c.requestElevator(10, Direction.DOWN);  // top of sweep: turn around there
            runUntilQuiet(c, 100);
            check(rec.of("E1").equals(List.of(6, 9, 10, 4)), "stops 6(up),9,10(turn),4(down): " + rec.of("E1"));
            check(c.outstandingHallCalls() == 0, "all hall-call assignments released");
        }

        System.out.println("== 3. Dispatch: ETA beats nearest-car ==");
        {
            ElevatorSnapshot upAt9 = new ElevatorSnapshot("E1", 9, Direction.UP, ElevatorState.MOVING, 1, 9, 20);
            ElevatorSnapshot idleAt0 = new ElevatorSnapshot("E2", 0, Direction.IDLE, ElevatorState.IDLE, 0, 0, 0);
            HallCall down8 = new HallCall(8, Direction.DOWN);
            HallCall up12 = new HallCall(12, Direction.UP);
            List<ElevatorSnapshot> cars = List.of(upAt9, idleAt0);
            check(new NearestCarStrategy().choose(down8, cars).orElseThrow().id().equals("E1"),
                  "nearest-car picks E1 for DOWN@8 although E1 must go to 20 first");
            check(LookEtaStrategy.eta(upAt9, down8) == 23 && LookEtaStrategy.eta(idleAt0, down8) == 8,
                  "ETA: E1 = (20-9)+(20-8) = 23 floors, E2 = 8 floors");
            check(new LookEtaStrategy().choose(down8, cars).orElseThrow().id().equals("E2"),
                  "LOOK-ETA picks the idle E2 for DOWN@8");
            check(new LookEtaStrategy().choose(up12, cars).orElseThrow().id().equals("E1"),
                  "LOOK-ETA picks E1 for UP@12 (on its way)");
        }

        System.out.println("== 4. Idempotent presses, validation ==");
        try (ElevatorController c = new ElevatorController(3, 0, 10, new LookEtaStrategy())) {
            String first = c.requestElevator(7, Direction.UP);
            check(c.requestElevator(7, Direction.UP).equals(first) && c.outstandingHallCalls() == 1,
                  "pressing UP@7 twice yields one assignment");
            check(throwsIAE(() -> c.requestElevator(11, Direction.DOWN)), "floor out of range rejected");
            check(throwsIAE(() -> c.requestElevator(10, Direction.UP)), "no UP button on the top floor");
        }

        System.out.println("== 5. Maintenance re-dispatches orphaned hall calls ==");
        try (ElevatorController c = new ElevatorController(2, 0, 10, new LookEtaStrategy())) {
            StopRecorder rec = new StopRecorder();
            c.addListener(rec);
            String owner = c.requestElevator(5, Direction.UP);
            String other = owner.equals("E1") ? "E2" : "E1";
            c.setMaintenance(owner, true);
            check(c.status(owner).state() == ElevatorState.MAINTENANCE, owner + " is in maintenance");
            check(throwsISE(() -> c.selectFloor(owner, 3)), "car calls rejected while in maintenance");
            runUntilQuiet(c, 100);
            check(rec.of(other).contains(5) && rec.of(owner).isEmpty(), "UP@5 served by " + other + " instead");
            c.setMaintenance("E1", true);
            c.setMaintenance("E2", true);
            check(throwsISE(() -> c.requestElevator(3, Direction.UP)), "whole bank down -> request fails loudly");
            c.setMaintenance("E1", false);
            check(c.requestElevator(3, Direction.UP).equals("E1"), "E1 back in service takes calls");
        }

        System.out.println("== 6. Concurrency: 8 threads pressing buttons while the ticker runs ==");
        try (ElevatorController c = new ElevatorController(4, 0, 30, new LookEtaStrategy())) {
            StopRecorder rec = new StopRecorder();
            c.addListener(rec);
            c.start(Duration.ofMillis(1));
            Set<HallCall> pressed = ConcurrentHashMap.newKeySet();
            ExecutorService pool = Executors.newFixedThreadPool(8);
            CountDownLatch go = new CountDownLatch(1);
            List<Future<?>> futures = new ArrayList<>();
            for (int t = 0; t < 8; t++) {
                final long seed = t;
                futures.add(pool.submit(() -> {
                    Random rnd = new Random(seed);
                    go.await();
                    for (int i = 0; i < 200; i++) {
                        int floor = 1 + rnd.nextInt(29);                       // 1..29 has both buttons
                        Direction d = rnd.nextBoolean() ? Direction.UP : Direction.DOWN;
                        c.requestElevator(floor, d);
                        pressed.add(new HallCall(floor, d));
                        if (i % 50 == 0) c.selectFloor("E" + (1 + rnd.nextInt(4)), rnd.nextInt(31));
                    }
                    return null;
                }));
            }
            go.countDown();
            for (Future<?> f : futures) f.get(10, TimeUnit.SECONDS);   // rethrows any worker exception
            pool.shutdown();
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10);
            while (!c.isQuiescent()) {
                if (System.nanoTime() > deadline) throw new AssertionError("did not drain: " + c.outstandingHallCalls());
                Thread.sleep(5);
            }
            check(rec.served.keySet().containsAll(pressed), "every distinct hall call pressed (" + pressed.size() + ") was served");
            check(c.outstandingHallCalls() == 0, "assignment map drained (no leaked or deadlocked calls)");
        }

        System.out.println("\nAll elevator checks passed.");
    }

    private static boolean throwsIAE(Runnable r) {
        try { r.run(); return false; } catch (IllegalArgumentException e) { return true; }
    }

    private static boolean throwsISE(Runnable r) {
        try { r.run(); return false; } catch (IllegalStateException e) { return true; }
    }
}
