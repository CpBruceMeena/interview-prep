# Snakes and Ladders - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** State machines, game theory, randomness, board generation

---

## Question 1: Core Design
**Interviewer:** *"Design a Snakes and Ladders game with configurable board size, multiple players, and customizable dice."*

### 🎯 Expected Answer

**Strategy Pattern for Dice:**
```python
class DiceStrategy(ABC):
    @abstractmethod
    def roll(self) -> int: pass

class StandardDice(DiceStrategy):
    def roll(self): return random.randint(1, 6)

class CrookedDice(DiceStrategy):
    def roll(self): return random.choice([2, 4, 6])  # Always even

class DoubleDice(DiceStrategy):
    def roll(self): return die1.roll() + die2.roll()
```

**Why Strategy for dice?** The dice rolling behavior varies independently from the game rules. You can:
- Use `CrookedDice` for testing (predictable outcomes)
- Swap to `DoubleDice` for a different game mode
- Add `LoadedDice` for a gambling variant — zero changes to game logic

**Observer Pattern for Notifications:**
```python
class GameObserver(ABC):
    @abstractmethod
    def on_turn(self, player, dice_value, old_pos, new_pos, message): pass
    @abstractmethod
    def on_game_over(self, winner): pass
```

This decouples game logic from output. You could have console output, WebSocket notifications, or file logging — all by adding `GameObserver` implementations.

---

## Question 2: Multi-Player Turn Management

**Core challenge:** Turn management with possible extra turns (rolling doubles) and player disconnections.

```python
def play_turn(self) -> bool:
    player = self._players[self._current_index]
    dice_value = self._dice.roll()
    
    new_pos = self._rules.calculate_new_position(player.position, dice_value)
    player.position = new_pos
    
    # Notify observers
    for obs in self._observers:
        obs.on_turn(player, dice_value, old_pos, new_pos, message)
    
    # Check win
    if new_pos >= self._board.size:
        for obs in self._observers:
            obs.on_game_over(player)
        return False  # Game over
    
    # Extra turn on doubles (for DoubleDice)
    if isinstance(self._dice, DoubleDice) and dice_value % 2 == 0:
        print(f"{player.name} gets another turn!")
    else:
        self._current_index = (self._current_index + 1) % len(self._players)
    return True
```

### 💡 Edge Cases in Turn Management

| Issue | Solution |
|-------|----------|
| **Player disconnects** | Skip turn, auto-roll after 30s timeout |
| **Double rolls consecutively** | Limit 3 consecutive doubles, then lose turn |
| **Infinite loop (no progress)** | Move limit (e.g., 1000 total moves = draw) |

---

## Question 3: Gamification Features
**Interviewer:** *"How would you add leaderboards, achievements, and power-ups?"*

### 🎯 Answer

- **Leaderboards**: Store in database keyed on (board_size, dice_type). Score = moves_to_finish (lower is better).
- **Achievements**: Observer that checks conditions:
  - SnakeBitten: "Land on 5 snakes in one game"
  - LuckyStart: "Win without landing on any snake"
  - RollMaster: "Roll 3 sixes in a row"
- **Power-ups**: Strategy pattern wrapping dice rolls:
  - `ForceSnake`: Opponent's next roll sends them down the nearest snake
  - `DoubleJump`: Double the next roll's value

---

## Question 4: Board Generation
**Interviewer:** *"How would you programmatically generate valid boards?"*

### 🎯 Algorithm

```python
def generate_board(size=100, num_snakes=8, num_ladders=9):
    board = [0] * (size + 1)  # cell -> destination
    
    # 1. Place ladders first (bottom->top, distinct cells)
    ladder_bottoms = random.sample(range(2, size-1), num_ladders)
    for bottom in ladder_bottoms:
        top = min(bottom + random.randint(5, 30), size)
        if not any(board[bottom]):  # Ensure no overlap
            board[bottom] = top
    
    # 2. Place snakes (head->tail, distinct from ladders)
    available = [i for i in range(2, size-1) if not board[i]]
    snake_heads = random.sample(available, min(num_snakes, len(available)))
    for head in snake_heads:
        tail = max(2, head - random.randint(5, 30))
        board[head] = tail
    
    return board
```

**Constraints:**
- No cycles (snake landing on ladder, ladder landing on snake)
- Minimum distance between snake head and tail
- Board should be solvable (expected moves < inf)
- Fairness metric: standard deviation of expected moves

---

## Question 5: Serialization & Persistence

```python
class GameSnapshot:
    def to_dict(self):
        return {
            "players": [{"name": p.name, "position": p.position} for p in players],
            "board": self._board._cells,
            "dice_type": type(self._dice).__name__,
            "move_history": self._move_history,
        }
    
    @classmethod
    def from_dict(cls, data) -> GameSnapshot: ...
```

**Storage options:**
- **Local**: JSON file, SQLite
- **Multiplayer**: Serialize to Redis/PostgreSQL, keyed by game_id
- **Replay**: Record all dice rolls → deterministic replay

---

## Question 6: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | DiceStrategy | Interchangeable dice behaviors |
| **Observer** | GameObserver | Decoupled notifications |
| **State** | GameStatus | Lifecycle management |
| **Facade** | SnakeAndLadderGame | Simplified interface |
| **Factory** | Board creation | Different board configurations |
