# 🧠 Chess Game LLD — Thought Process Guide

> **Goal:** Learn *how* to think when designing a Low-Level Design.

---

## 📊 Class Diagram

![Class Diagram](chess-game-class-diagram.drawio)

---

## Phase 0: Requirements Gathering

What pieces? What moves? (Castling, en passant, promotion.) Check/checkmate logic? Move validation? Game state management?

## Phase 1: Identify the Nouns

> *"Two players play chess on an 8×8 board. Each piece type moves differently. The game ends in checkmate, stalemate, or draw."*

| Noun | Decision | Why |
|------|----------|-----|
| Piece | ABC | 6 piece types with different move rules |
| King/Queen/Rook/Bishop/Knight/Pawn | Regular | Each implements `get_possible_moves()` |
| Board | Regular | Manages 8×8 grid, piece positions |
| Move | Regular | Data class for a single move |
| Player | Regular | Identity class (name + color) |
| MoveValidator | Regular | Validates moves against chess rules |
| ChessGame | Facade | Orchestrates the game |
| Color | Enum | WHITE, BLACK |
| PieceType | Enum | KING, QUEEN, ROOK, BISHOP, KNIGHT, PAWN |
| GameStatus | Enum | ACTIVE, CHECK, CHECKMATE, STALEMATE, DRAW, RESIGNED |

## Phase 2: Enums First

```python
class Color(Enum):     WHITE, BLACK
class PieceType(Enum): KING, QUEEN, ROOK, BISHOP, KNIGHT, PAWN
class GameStatus(Enum): ACTIVE, CHECK, CHECKMATE, STALEMATE, DRAW, RESIGNED
```

## Phase 3: dataclass vs `__init__`

- **`Piece`**: ABC — abstract, subclasses implement move logic
- **`King`/`Queen`/`Rook`/`Bishop`/`Knight`/`Pawn`**: Regular — each has its own `get_possible_moves()`
- **`Board`**: Regular — complex 2D grid management
- **`Move`**: Regular — groups all move-related data
- **`Player`**: Regular — simple identity class
- **`MoveValidator`**: Regular — validation logic
- **`ChessGame`**: Regular — orchestrates everything

## Phase 4: Assigning Responsibilities

| Action | Owner | Why |
|--------|-------|-----|
| Get possible moves | Each Piece subclass | Each piece knows its movement rules |
| Place/get piece | `Board.get_piece_at()` / `Board._place_piece()` | Board owns the grid |
| Execute move | `Board.move_piece()` | Board updates grid + piece position |
| Check if in check | `Board.is_in_check()` | Board evaluates king safety |
| Check checkmate | `Board.is_checkmate()` | Board evaluates all legal moves |
| Validate move | `MoveValidator.validate()` | Checks piece color, move legality, check |
| Make a move | `ChessGame.make_move()` | Validates → executes → updates status |
| Undo a move | `Board.undo_move()` | Needed for legal move validation |

## Phase 5: Piece Hierarchy (LSP in Action)

```python
class Piece(ABC):
    @abstractmethod
    def get_possible_moves(self, board) -> List[Tuple[int, int]]: pass

class Rook(Piece):    # Moves horizontally/vertically
class Bishop(Piece):  # Moves diagonally
class Queen(Piece):   # Moves like Rook + Bishop
class Knight(Piece):  # L-shaped jumps
class King(Piece):    # One square any direction + castling
class Pawn(Piece):    # Forward, capture diagonally, en passant
```

The Board doesn't care *what kind* of piece it is — it just calls `piece.get_possible_moves(board)`. This is Textbook LSP.

## Phase 6: Factory Pattern for Pieces

```python
class PieceFactory:
    _piece_map = {
        PieceType.KING: King, PieceType.QUEEN: Queen,
        PieceType.ROOK: Rook, PieceType.BISHOP: Bishop,
        PieceType.KNIGHT: Knight, PieceType.PAWN: Pawn,
    }
    @classmethod
    def create_piece(cls, piece_type, color, position):
        return cls._piece_map[piece_type](color, position)
```

## Phase 7: Move Validation (Legal vs Possible)

Critical distinction:
- **Possible moves:** What the piece can do ignoring check
- **Legal moves:** Possible moves that don't leave the king in check

`Board._is_legal_move()` simulates the move, checks if king is safe, then undoes it.

## Phase 8: Quick Checklist

✅ **LSP:** Every Piece subclass is substitutable for Piece
✅ **SRP:** Board owns grid, Piece owns moves, ChessGame owns flow
✅ **Factory:** Creating pieces is centralized
✅ **OCP:** New piece type → new subclass, no Board/Game changes
✅ **Encapsulation:** Board grid is private, accessed through methods
