# 🧠 Snakes & Ladders LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

---

## 📊 Class Diagram

![Class Diagram](snakes-and-ladders-class-diagram.drawio)

---

## Phase 0: Requirements Gathering

Board size? Number of players? Dice strategy (standard, double, crooked)? Snake/ladder positions? Win condition (exact roll)?

## Phase 1: Identify the Nouns

> *"Players roll dice to move across a board. Landing on a snake head slides you down; landing on a ladder bottom climbs you up."*

| Noun | Decision | Why |
|------|----------|-----|
| Board | Regular Class | Manages 100 cells with snakes/ladders |
| Cell | Regular Class | Has position, type, destination |
| Player | Regular Class | Has position, name |
| DiceStrategy | ABC | Multiple dice types (standard, crooked, double) |
| GameRules | Regular Class | SRP: win condition, position calculation |
| GameObserver | ABC | Observer pattern for notifications |
| GameStatus | Enum | Fixed states |
| CellType | Enum | NORMAL, SNAKE, LADDER |

## Phase 2: Enums First

```python
class CellType(Enum):
    NORMAL, SNAKE_HEAD, SNAKE_TAIL, LADDER_BOTTOM, LADDER_TOP

class GameStatus(Enum):
    NOT_STARTED, IN_PROGRESS, FINISHED
```

## Phase 3: dataclass vs `__init__`

- **`Cell`**: Regular `__init__` — has state and setters (`set_snake()`, `set_ladder()`)
- **`Board`**: Regular `__init__` — complex state management (dictionary of cells)
- **`Player`**: Regular — has position state that gets modified
- **Dice strategies**: Regular — each has a `roll()` method

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Roll dice | `DiceStrategy.roll()` | Strategy encapsulates rolling logic |
| Add snake/ladder | `Board.add_snake()/add_ladder()` | Board owns cell layout |
| Calculate final position | `Board.get_destination()` | Board resolves snake/ladder chains |
| Check win condition | `GameRules.check_win()` | SRP: rules are separate from board |
| Calculate new position | `GameRules.calculate_new_position()` | Rules + Board = result |
| Play a turn | `Game.play_turn()` | Orchestrates dice → rules → board |

## Phase 5: Composition

```
Game HAS-A Board, HAS-A DiceStrategy, HAS-A GameRules
Game OBSERVES → GameObserver (ConsoleLogger)
Board HAS-A many Cell objects
```

## Phase 6: Strategy Pattern for Dice

```python
class DiceStrategy(ABC):
    @abstractmethod
    def roll(self) -> int: pass

class StandardDice(DiceStrategy):  # 1-6
class CrookedDice(DiceStrategy):   # Always even
class DoubleDice(DiceStrategy):    # Two dice
```

The game doesn't care *how* dice work — it just calls `dice.roll()`.

## Phase 7: Observer Pattern

`GameObserver` is notified on each turn and game over. This cleanly separates *game logic* from *output/display*.

## Phase 8: Quick Checklist

✅ **SRP:** Board owns layout, Rules owns win logic, Observer owns output
✅ **Strategy:** Dice strategies are swappable
✅ **Observer:** Display concerns don't pollute game logic
✅ **Encapsulation:** Player position is private, modified through turns
