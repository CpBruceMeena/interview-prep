# Tic-Tac-Toe - Interview Questions & Answers

> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** AI algorithms, state space, minimax, extensibility

---

## Question 1: Core Design
**Interviewer:** *"Design a Tic-Tac-Toe game supporting Human vs Human, Human vs AI, and AI vs AI modes."*

### 🎯 Expected Answer

**Strategy Pattern for Player Types:**
```python
class Player(ABC):
    @abstractmethod
    def get_move(self, board: Board) -> Tuple[int, int]:
        pass

class HumanPlayer(Player):
    def get_move(self, board) -> Tuple[int, int]:
        # Read from stdin with validation

class BotPlayer(Player):
    def get_move(self, board) -> Tuple[int, int]:
        _, move = self._minimax(board, self._symbol, True)
        return move
```

**Why Strategy over if-else?** With if-else, adding a new AI difficulty means modifying the `get_move` method. With Strategy, you add a class — zero existing code changes (OCP).

**Board encapsulation:**
```python
class Board:
    def is_valid_move(self, pos) -> bool  # Guards
    def place_move(self, pos, symbol)      # Mutators
    def check_winner(self) -> Optional[symbol]  # Queries
    def get_available_moves(self) -> List  # State
```

### 💡 Technical Deep Dive: Win Detection

For 3×3, checking all 8 lines is O(1). But the interviewer will ask: *"How would you generalize to N×N with K-in-a-row?"*

**Efficient K-in-a-row detection O(N²):**
```python
def check_win_nxn(board, N, K):
    for r in range(N):
        for c in range(N):
            if board[r][c] is None: continue
            symbol = board[r][c]
            # Check 4 directions: →, ↓, ↘, ↙
            for dr, dc in [(0,1), (1,0), (1,1), (1,-1)]:
                count = 0
                for i in range(K):
                    nr, nc = r + dr*i, c + dc*i
                    if 0 <= nr < N and 0 <= nc < N and board[nr][nc] == symbol:
                        count += 1
                    else: break
                if count == K: return symbol
    return None
```

---

## Question 2: Minimax AI
**Interviewer:** *"Implement an unbeatable AI. Walk me through the algorithm."*

### 🎯 Expected Answer

**Minimax with Alpha-Beta Pruning:**
```python
def minimax(board, symbol, is_maximizing, alpha=-inf, beta=inf):
    # Terminal states
    winner = board.check_winner()
    if winner == AI_SYMBOL: return 1
    if winner == HUMAN_SYMBOL: return -1
    if board.is_full(): return 0

    if is_maximizing:
        best_score = -inf
        for move in board.get_available_moves():
            board.place_move(move, AI_SYMBOL)
            score = minimax(board, symbol, False, alpha, beta)
            board.undo_move(move)
            best_score = max(best_score, score)
            alpha = max(alpha, score)
            if beta <= alpha: break  # β-cutoff
        return best_score
    # Minimizing player...
```

**Alpha-beta pruning** reduces the search space from O(b^d) to O(b^(d/2)). For Tic-Tac-Toe (b=9, d=9), full minimax is 9! ≈ 362K nodes. With alpha-beta, typically < 10K nodes — real-time AI even for larger boards.

### 🔍 Trade-off Analysis: Optimal vs. Satisfying

| Approach | Pros | Cons | When |
|----------|------|------|------|
| Minimax | Guaranteed optimal | O(b^d) exponential | 3×3 |
| Alpha-Beta | Much faster | Same result | Up to 5×5 |
| Monte Carlo | Handles large spaces | Probabilistic | 6×6+ |
| Heuristic + depth limit | Fast, adjustable | May make suboptimal moves | N×N |

---

## Question 3: Scaling to N×N
**Interviewer:** *"How would you extend this to a 4×4 or N×N board?"*

### 🎯 Key Points

1. **Win condition becomes parameterized**: N-in-a-row instead of 3-in-a-row
2. **Board representation**: Bitboard (int per player) for performance
3. **AI complexity**: Minimax becomes infeasible after 4×4. Switch to:
   - **Heuristic evaluation**: Evaluate board state without full search
   - **Monte Carlo Tree Search (MCTS)**: Simulate random playouts, choose best
   - **Opening book**: Pre-computed best moves for common openings

---

## Question 4: Multi-Player Extensions
**Interviewer:** *"How would you support 3+ players or team play?"*

| Feature | Implementation |
|---------|---------------|
| **3+ players** | More symbols (X, O, Δ, □). Win condition: all 3 in a row must be same symbol. Draw harder to reach. |
| **Team play** | Two symbols per team. Win if team controls a line. |
| **Tournament** | Bracket generation. ELO rating system. Match history. |

---

## Question 5: Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Strategy** | HumanPlayer vs BotPlayer | Interchangeable AI difficulty |
| **State** | GameStatus enum | Track game lifecycle |
| **Command** | Move record | Undo/redo, replay |
| **Observer** | Display refresh | UI updates on state change |
| **Factory** | Player creation | Centralized player config |
| **Memento** | Board snapshots | Save/restore mid-game |

---

## Question 6: Testing Strategy

**Unit tests to write:**
1. Win detection — all 8 lines on 3×3
2. Draw detection — full board, no winner
3. AI correctness — AI as X should never lose on 3×3 (provably optimal)
4. Invalid move rejection — occupied cell, out of bounds
5. Undo/redo — verify state restoration
6. Tournament mode — bracket elimination correctness
