# 🧠 Tic-Tac-Toe LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design, not just *what* the final code looks like.

## Phase 0: Requirements Gathering

**Before writing code, ask:** What kind of players? (Human vs Bot, Human vs Human). Board size? Win condition? Is AI needed?

## Phase 1: Identify the Nouns

> *"Two players take turns placing X and O on a 3x3 grid. The first to get 3 in a row wins."*

| Noun | Decision | Why |
|------|----------|-----|
| Player | Abstract Class | Multiple player types (Human, Bot) |
| Board | Regular Class | Manages grid state |
| Game | Facade | Orchestrates the flow |
| PlayerSymbol | Enum | Fixed: X, O |
| GameStatus | Enum | Fixed: IN_PROGRESS, WIN, DRAW |

## Phase 2: Enums First

```python
class PlayerSymbol(Enum):
    X = "X"
    O = "O"
```

## Phase 3: dataclass vs `__init__`

- **`Board`**: Regular `__init__` — has behavior (`place_move`, `check_winner`, `display`)
- **`Player`**: ABC — abstract, subclasses implement `get_move()`
- **`HumanPlayer`/`BotPlayer`**: Regular — each has its own move strategy

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Validate move | `Board.is_valid_move()` | Board knows grid state |
| Place move | `Board.place_move()` | Board owns the grid |
| Check win | `Board.check_winner()` | Board can evaluate its state |
| Get move from player | `Player.get_move()` | Each player type decides differently |
| Play a turn | `Game.play_turn()` | Game orchestrates player → board flow |

**Key insight:** The `BotPlayer` implements minimax *within itself* — the Board doesn't need to know about AI logic. This is good SRP.

## Phase 5: Composition vs Inheritance

```
Player(ABC) ─── BotPlayer IS-A Player
           └── HumanPlayer IS-A Player
Game HAS-A Board, HAS-A Player1, HAS-A Player2
```

## Phase 6: Polymorphism

Instead of `if player_type == "human"` branching, use abstract `get_move()`:

```python
class Player(ABC):
    @abstractmethod
    def get_move(self, board) -> Tuple[int, int]: pass

class HumanPlayer(Player):
    def get_move(self, board) -> Tuple[int, int]:
        return user_input()  # Read from console

class BotPlayer(Player):
    def get_move(self, board) -> Tuple[int, int]:
        return minimax(board)  # AI logic
```

No if-else needed anywhere in the game flow.

## Phase 7: Design Patterns

- **Strategy (implicit):** Different player types = different move strategies
- **Facade:** `Game` class hides the complexity of board + players

## Phase 8: Quick Checklist

✅ **SRP:** Board manages grid, Player manages move decisions, Game orchestrates
✅ **OCP:** Add a new player type → new subclass, zero existing changes
✅ **Encapsulation:** Board grid is private, exposed through methods
✅ **Cohesion:** Each class has a single, clear purpose
