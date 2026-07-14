# Chess Game - Interview Questions & Answers

> **Interviewer Persona:** Principal Software Engineer with 15+ years experience  
> **Target Level:** Senior/Staff Engineer (6+ years)  
> **Evaluation Focus:** Complex state management, polymorphism, recursion, game AI

---

## Question 1: Core Design
**Interviewer:** *"Design a chess game with all standard rules — piece movement, check, checkmate, castling, en passant, and pawn promotion."*

### 🎯 Expected Answer

Let me decompose this. Chess is fundamentally a **state machine** with well-defined transitions enforced by game rules. The core challenge is modeling the polymorphism of 6 different piece types, each with unique movement rules.

**Class Hierarchy (LSP):**
```python
class Piece(ABC):
    @abstractmethod
    def get_possible_moves(self, board: Board) -> List[Tuple[int, int]]:
        pass

class King(Piece): ...
class Queen(Piece): ...
class Rook(Piece): ...
class Bishop(Piece): ...
class Knight(Piece): ...
class Pawn(Piece): ...
```

Each `Piece` subclass knows how it moves. The caller invokes `get_possible_moves()` polymorphically — no `if piece_type == KING` checks anywhere. This is textbook **Open/Closed**: adding a new piece type (e.g., a Fairy Chess piece) requires one new class, zero modifications to existing code.

**Factory Pattern for Piece Creation:**
```python
class PieceFactory:
    _piece_map = {
        PieceType.KING: King,
        PieceType.QUEEN: Queen,
        # ...
    }
    @classmethod
    def create_piece(cls, piece_type, color, position):
        return cls._piece_map[piece_type](color, position)
```

This centralizes piece creation — changing how pieces are initialized (e.g., adding a unique ID for tracking) happens in one place.

### 🔍 Deep Dive: Move Generation vs. Move Validation

A key architectural decision: **separate move generation from move validation**.

```python
# Step 1: Generate candidate moves (piece knows its movement pattern)
candidate_moves = piece.get_possible_moves(board)

# Step 2: Filter to legal moves (board knows rules)
legal_moves = [m for m in candidate_moves if board._is_legal_move(piece, m)]
```

`_is_legal_move` simulates the move on a temporary board state and checks if the king would be in check. This separation means:
- **SRP**: Pieces generate patterns; the board validates legality
- **Testability**: You can unit-test piece movement independently of check detection
- **Performance**: In a chess engine, you'd optimize move generation (bitboards) separately from legality checking

### ⚠️ Recursion Gotcha (Real Bug I Fixed)

The naive implementation of `is_in_check` → `get_possible_moves` → King's castling check → `is_in_check` creates infinite recursion. The fix: **King's attack detection shouldn't invoke full move generation**.

```python
# In is_in_check(): treat King pieces as special cases
if isinstance(piece, King):
    # Direct adjacency check — no recursion risk
    if abs(king_row - r) <= 1 and abs(king_col - c) <= 1:
        return True
else:
    if king.position in piece.get_possible_moves(self):
        return True
```

**Lesson for production:** Be extremely careful about circular dependencies in validation logic. Always separate "can this piece attack X" from "what moves can this piece make considering check."

---

## Question 2: Move Validation Engine
**Interviewer:** *"How do you validate moves efficiently for 6 piece types with different rules?"*

### 🎯 Expected Answer

**Validation Pipeline (Chain of Responsibility pattern):**
```python
class MoveValidator:
    def validate(self, player, start, end) -> bool:
        # 1. Source check
        piece = board.get_piece_at(start)
        if not piece: return False
        if piece.color != player.color: return False
        
        # 2. Move pattern check (polymorphic)
        if end not in piece.get_possible_moves(board): return False
        
        # 3. Legality check (king safety)
        if not board._is_legal_move(piece, end): return False
        
        return True
```

**Pin detection** is particularly interesting. A pinned piece (e.g., bishop pinned to king by enemy rook) shouldn't be able to move off its attack line. In our implementation, this falls out naturally from `_is_legal_move` — any move that exposes the king to check is rejected.

### 💡 Production Performance Considerations

For a competitive chess engine:
1. **Bitboard representation**: Represent the board as 12 × 64-bit integers (one per piece type per color). Move generation becomes bitwise operations — millions of moves/second.
2. **Pre-computed attack tables**: Knighs and kings have lookup tables — O(1) move generation.
3. **Zobrist hashing**: Hash the board state for transposition tables — avoids re-computing positions.
4. **Alpha-beta pruning**: Prune branches that can't improve the evaluation — reduces search tree from O(b^d) to O(b^(d/2)).

---

## Question 3: AI Integration
**Interviewer:** *"How would you design this to support AI opponents of varying difficulty?"*

### 🎯 Expected Answer

**Strategy Pattern for AI:**
```python
class ChessAI(ABC):
    @abstractmethod
    def choose_move(self, board: Board, color: Color) -> Move:
        pass

class RandomAI(ChessAI):
    """Easy: picks random legal move"""

class MinimaxAI(ChessAI):
    """Medium: minimax with depth limit"""

class AlphaBetaAI(ChessAI):
    """Hard: minimax + alpha-beta pruning + opening book"""
```

**Minimax with Alpha-Beta:**
```python
def minimax(board, depth, alpha, beta, maximizing):
    if depth == 0 or game_over:
        return evaluate(board)
    
    if maximizing:
        max_eval = -inf
        for move in generate_moves(board):
            board.make_move(move)
            eval = minimax(board, depth-1, alpha, beta, False)
            board.undo_move(move)
            max_eval = max(max_eval, eval)
            alpha = max(alpha, eval)
            if beta <= alpha:
                break  # Beta cut-off
        return max_eval
```

**Piece-square tables** for evaluation:
```python
# Give bonus for central control
PIECE_SQUARE_TABLES = {
    PAWN: [
        [0, 0, 0, 0, 0, 0, 0, 0],
        [50, 50, 50, 50, 50, 50, 50, 50],
        [10, 10, 20, 30, 30, 20, 10, 10],
        [5, 5, 10, 25, 25, 10, 5, 5],
        [0, 0, 0, 20, 20, 0, 0, 0],
        [5, -5, -10, 0, 0, -10, -5, 5],
        [5, 10, 10, -20, -20, 10, 10, 5],
        [0, 0, 0, 0, 0, 0, 0, 0]
    ]
}
```

---

## Question 4: Game State & Undo
**Interviewer:** *"How would you handle saving/loading, undo/redo, and PGN export?"*

### 🎯 Expected Answer

**Command Pattern** for move history:
```python
class Move:
    def __init__(self, start, end, piece, captured, 
                 promotion=None, is_castling=False):
        self.start = start
        self.end = end
        self.piece = piece
        self.captured = captured
        self.promotion = promotion
        self.is_castling = is_castling

class MoveHistory:
    def __init__(self):
        self._moves: List[Move] = []
        self._current = -1
    
    def record(self, move: Move): ...
    def undo(self) -> Move: ...  # Pop and reverse
    def redo(self) -> Move: ...  # Re-apply
```

**Memento Pattern** for game state snapshots:
```python
class GameSnapshot:
    def __init__(self, board_state, turn, castling_rights, 
                 en_passant_target, half_move_clock):
        ...

class ChessGame:
    def save_state(self) -> GameSnapshot:
        return deepcopy(self._state)
    
    def restore_state(self, snapshot: GameSnapshot):
        self._state = deepcopy(snapshot)
```

**PGN Export:**
```python
def to_pgn(moves: List[Move], white: str, black: str) -> str:
    pgn = f"[White \"{white}\"]\n[Black \"{black}\"]\n\n"
    for i, move in enumerate(moves):
        if i % 2 == 0:
            pgn += f"{i//2 + 1}. {move_to_algebraic(move)}"
        else:
            pgn += f" {move_to_algebraic(move)}\n"
    return pgn
```

---

## Question 5: Performance Optimization
**Interviewer:** *"How would you make move generation competitive with Stockfish-level engines?"*

### 🎯 Answer

The jump from OOP chess to competitive engine is massive. Key optimizations:

1. **Bitboards**: Replace 2D array with `uint64` per piece type. `king_attacks = KING_ATTACK_TABLE[king_square]` — O(1) lookup.
2. **Magic bitboards** for sliding pieces (bishop, rook, queen): Pre-computed attack sets via magic hash functions.
3. **Null-move pruning**: If the opponent can't improve position even with two moves in a row, skip their turn.
4. **Transposition table**: Zobrist-hashed dictionary of (board_hash, depth, score) — avoids re-searching positions.
5. **Iterative deepening**: Search depth 1, 2, 3... until time runs out — you always have a best move ready.

---

## Question 6: Special Rules

| Rule | Implementation |
|------|---------------|
| **Castling** | Check king/rook hasn't moved, no pieces between, king not in check, doesn't pass through check |
| **En passant** | Track last double-pawn-push square; allow diagonal capture on that square for one turn |
| **Pawn promotion** | On reaching rank 0/7, prompt selection or default to Queen |
| **Threefold repetition** | Hash every board state; if same hash seen 3 times, claim draw |
| **50-move rule** | Track half-move clock since last capture/pawn push; reset on each |

---

## Question 7: Design Patterns Inventory

| Pattern | Where | Why |
|---------|-------|-----|
| **Factory** | PieceFactory | Centralizes piece creation |
| **Strategy** | ChessAI | Interchangeable AI difficulty |
| **Command** | Move | Undo/redo, replay |
| **Memento** | GameSnapshot | Save/restore game state |
| **State** | GameStatus | ACTIVE, CHECK, CHECKMATE, DRAW |
| **Observer** | UI update | React to board changes |
| **Facade** | ChessGame | Unified interface |
