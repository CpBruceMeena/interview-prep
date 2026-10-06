# Snakes and Ladders - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** Modelling, turn state machine, randomness/testability, concurrency, extensibility

---

## Question 1: Core Design
**Interviewer:** *"Design a Snakes and Ladders game with configurable board size, multiple players, and customizable dice."*

### 🎯 Expected Answer

**One `Jump` type, validated once.** A snake and a ladder are both `start -> end`; direction tells you which. `Board` stores `dict[start, Jump]` and rejects bad layouts in its constructor (off-board, jump on the goal cell, two jumps on one cell, chains). After that, `resolve(cell)` is one lookup.

**Strategy for dice, returning the faces:**
```python
@dataclass(frozen=True)
class Roll:
    faces: tuple[int, ...]
    @property
    def total(self): return sum(self.faces)
    @property
    def is_doubles(self): return len(self.faces) > 1 and len(set(self.faces)) == 1

class Dice(ABC):
    @abstractmethod
    def roll(self) -> Roll: ...

class StandardDice(Dice):          # count dice, `sides` faces, injectable rng
class CrookedDice(Dice):           # only even faces
class ScriptedDice(Dice):          # fixed sequence, for tests and replay
```

Returning `int` from `roll()` is the common trap: you lose the faces and then can't tell doubles (`3+3`) from an even sum (`1+5`).

**Observer for output.** `GameObserver.on_turn(TurnResult)` / `on_game_over(winner)`. Console, websocket push and achievements are all observers; `Game` never prints.

---

## Question 2: Turn Management with Doubles
**Interviewer:** *"Two dice. Doubles give another turn, but three doubles in a row forfeits the turn."*

```python
roll = self._dice.roll()
self._doubles_streak = self._doubles_streak + 1 if roll.is_doubles else 0
forfeited = self._doubles_streak >= self._max_doubles
...
extra = self._extra_turn_on_doubles and roll.is_doubles and not forfeited and not won
if not extra:
    self._doubles_streak = 0
    self._current = (self._current + 1) % len(self._players)
```

Points interviewers look for: the streak is per-turn-holder and resets when the turn passes; winning on doubles ends the game rather than granting a turn; the forfeit check happens *before* moving.

---

## Question 3: "Now make it online — two clients can press roll at once"

**Answer:** One lock per game. Inside it: check status, check it's this caller's turn, roll, move, advance the turn, append history. Outside callers get `NotYourTurnError` / `GameOverError`.

The bug to avoid is check-then-act across the lock boundary:

```python
if game.current_player == me:   # check (unlocked)
    game.play_turn()            # act — another request may have moved in between
```

`play_turn(player_name)` does the check *inside* the critical section. A duplicate request (client retry, double-click) arrives after the turn has passed and is rejected, so it can't double-move. Lock granularity is per game because games share no state. In a multi-node service the same idea becomes optimistic concurrency on a version/turn number (see the HLD).

**Why not lock-free?** The critical section is microseconds and contention is at most a handful of players; a mutex is the simplest correct answer.

---

## Question 4: Overshoot Rules
**Interviewer:** *"What if a player at 97 rolls a 5?"*

Three common rules, selected via `OvershootPolicy`:

| Policy | 97 + 5 | Note |
|--------|--------|------|
| `STAY` | 97 | Needs an exact roll; the turn is still used |
| `BOUNCE` | 98 (100, back 2) | The bounced cell can hold a snake — still resolve the jump |
| `ALLOW` | 100, wins | Simplest |

---

## Question 5: Board Validation and Generation
**Interviewer:** *"How would you programmatically generate valid boards?"*

**Invariants first** (the same ones `Board` enforces): endpoints on the board, no jump starting on the last cell, one jump start per cell, no jump ending on another's start (no chains → no cycles).

**Generation:** sample distinct start cells from `2..size-1`, pick an end per jump, reject and resample on any invariant violation. Then score the board:

- **Expected game length** — exact, not simulated: the game is a Markov chain over cells `0..size`, so expected turns-to-finish solves a linear system (or value iteration). Monte Carlo (10K games) is fine as a quick approximation.
- **Variance / fairness** — length spread, and first-player advantage (simulate N games, compare win rate by seat).
- Reject boards outside the target range; difficulty = target length.

---

## Question 6: Testing Strategy
**Interviewer:** *"How do you test a game built on randomness?"*

- **Inject the randomness.** `ScriptedDice([3, (2, 2), 1])` turns every rule into a deterministic unit test (ladder, snake, bounce-onto-snake, third doubles, exact win).
- **Seeded RNG** (`StandardDice(rng=random.Random(7))`) for whole-game regression tests and bug reproduction.
- **Table tests for validation** — each invalid board must raise `InvalidBoardError`.
- **Invariant tests under concurrency** — N threads hammer `play_turn(name)`; assert history is strictly round-robin, each turn starts where that player's last turn ended, and exactly one turn is a win.
- **Statistical tests only at the edges** — e.g. `CrookedDice` never returns odd. Don't assert distributions in unit tests; they flake.

---

## Question 7: Persistence and Replay

`TurnResult` is the event. Persist it append-only (`moves` table / event stream). Replay = feed the stored faces into `ScriptedDice` and re-run; positions must match. Store the board layout and rule config with the game, because the same rolls on a different layout give a different game.

---

## Question 8: Extensions Interviewers Push On

| Ask | Where it lands |
|-----|----------------|
| Play until all finish, rank players | `Game`: `finish_order`, skip finished players, end when one remains |
| Power-ups / special cells | Generalise `Jump` into a `CellEffect` ABC (`apply(player, game)`) |
| Undo last move | Pop `history`; positions are recoverable from `start` of the popped result |
| AI / bot player | A `PlayerController` that decides when to roll; for this game there's no decision, so it's just a timer calling `play_turn` |
| Disconnect timeout | Scheduler calls `play_turn(current)` on their behalf; the lock makes it race-safe with a late real request |

---

## ❌ Common Mistakes

- `roll()` returning `int`, then detecting doubles with `dice_value % 2 == 0` or `isinstance(dice, DoubleDice)`.
- Recursively following jumps without guarding against cycles (snake 50→20 + ladder 20→50 = infinite recursion).
- Silently skipping invalid snakes/ladders (`except ValueError: pass`) instead of failing the build.
- Allowing a snake head on the final cell — the game becomes unwinnable.
- Overshoot that wraps (`pos - size`) instead of staying or bouncing.
- Demo or tests depending on real randomness, or mutating private fields (`game._dice = ...`) to make them deterministic.
- "Thread-safe" claims with the turn check outside the lock.
- One `Cell` object per square with a type enum and nullable fields; most of it is never used.

---

## 🎚️ Senior vs Staff Signal

- **Senior:** clean entities, dice as a strategy, correct turn/doubles/overshoot logic, board validation, deterministic tests via injected dice, a lock that covers check-and-move.
- **Staff:** states the invariants that make the loop simple (no chains → O(1), no cycles) and why; makes `TurnResult` the single event that drives logs, persistence and replay; sizes abstractions honestly (Enum vs ABC); moves the lock story to the service (versioned writes, idempotent roll requests, server-authoritative RNG); knows board fairness is a Markov-chain question, not just "simulate it".
