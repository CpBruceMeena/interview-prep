# 🧠 Tic-Tac-Toe LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design, not just *what* the final code looks like.

---

## 📊 Class Diagram

![](tic-tac-toe-class-diagram.drawio)

---

## Phase 0: Requirements Gathering

**Before writing code, ask:**

| Question | Why it matters | Typical answer |
|----------|----------------|----------------|
| Which player types? | Decides the `Player` strategy hierarchy | Human vs human, human vs bot |
| Board size fixed at 3×3? | N×N changes the win check and kills full minimax | "Make it N×N-capable, 3×3 for the bot" |
| Win length = N, or K in a row? | Line sums only work for K = N | K = N |
| How is input delivered? Console, API, UI? | Keep I/O out of the domain so it's testable | API: `make_move(symbol, pos)` |
| Undo? | Board must reverse moves exactly | Nice to have |
| Online / concurrent requests? | Turn enforcement under a lock | Mention it |

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
- **`HumanPlayer`/`BotPlayer`/`ScriptedPlayer`**: Regular — each has its own move strategy
- **`TicTacToeGame`**: Regular — owns turn order, status, winner, and the lock

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Validate move | `Board.is_valid_move()` | Board knows grid state |
| Place move | `Board.place_move()` | Board owns the grid |
| Check win | `Board.place_move()` returns the winner; `Board.check_winner()` reads it | O(1) via row/column/diagonal sums |
| Undo | `Board.undo_move()` | Exact inverse of `place_move` |
| Get move from player | `Player.get_move()` | Each player type decides differently, on a copy of the board |
| Apply a move | `TicTacToeGame.make_move(symbol, pos)` | Enforces turn order and game-over, under a lock |
| Play a turn | `TicTacToeGame.play_turn()` | Asks the current player, then calls `make_move` |

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
        return parse(self._input(...))  # injected input_fn, so tests don't need stdin

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
✅ **OCP:** Add a new player type → new subclass, no changes to `Board` or `TicTacToeGame`
✅ **Testability:** No `input()`/`print()` in the domain; the demo runs without a keyboard
✅ **Encapsulation:** Board grid is private, exposed through methods
✅ **Cohesion:** Each class has a single, clear purpose

---

## Phase 9: How to Run This in a 45–60 min Interview

Tic-tac-toe is small, so the interviewer is grading **code quality and the follow-ups**, not whether you can finish. Budget for two extensions.

| Time | Step | What you do | What you say out loud |
|------|------|-------------|-----------------------|
| 0–5 | **Clarify** | Ask the Phase 0 questions; fix N, K, player types, I/O | *"I'll make the board N×N with N-in-a-row, keep I/O out of the domain, and treat players as strategies."* |
| 5–10 | **Entities & interfaces** | `PlayerSymbol`, `GameStatus`, `Board`, `Player` ABC, `TicTacToeGame` | *"`make_move(symbol, pos)` is the only mutator; everything else reads."* |
| 10–25 | **Core code** | `Board.place_move` with row/column/diagonal sums, `undo_move`, `TicTacToeGame.make_move` with turn checks and exceptions | *"The win check only looks at the lines through the last move: O(1)."* |
| 25–35 | **Bot** | Minimax with memo; faster-win scoring; deterministic tie-break | *"3×3 has 5,478 positions, so memoised minimax is exact and instant."* |
| 35–45 | **Concurrency** | Lock around `make_move`; reject the second request for the same turn | *"Two devices click at once: one lands, the other gets `NotYourTurnError`."* |
| 45–60 | **Extensions & tests** | K-in-a-row, difficulty levels, undo/redo, online play; name the tests (every line wins, invalid/out-of-turn moves, bot never loses, race test) | *"For 'bot never loses' I enumerate every opponent reply, as X and as O."* |

**Watch out for:** `input()` inside the game loop (untestable), recomputing the whole board for every win check without saying why, and a minimax that `undo`es the grid but not the rest of the board state.
