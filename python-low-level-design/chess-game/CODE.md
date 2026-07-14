# Chess Game — Implementation

> Python implementation of the Chess Game system following SOLID principles and design patterns.

```python
"""
Chess Game System - Low Level Design
------------------------------------
Design Principles: SOLID, Strategy Pattern, Factory Pattern, State Pattern
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional, Tuple, Set


class Color(Enum):
    WHITE = "White"
    BLACK = "Black"


class PieceType(Enum):
    KING = "King"
    QUEEN = "Queen"
    ROOK = "Rook"
    BISHOP = "Bishop"
    KNIGHT = "Knight"
    PAWN = "Pawn"


class GameStatus(Enum):
    ACTIVE = "Active"
    CHECK = "Check"
    CHECKMATE = "Checkmate"
    STALEMATE = "Stalemate"
    DRAW = "Draw"
    RESIGNED = "Resigned"


class Move:
    """Represents a chess move with all relevant information"""

    def __init__(self, start_pos: Tuple[int, int], end_pos: Tuple[int, int],
                 piece: 'Piece', captured_piece: Optional['Piece'] = None,
                 promotion: Optional[PieceType] = None,
                 is_castling: bool = False, is_en_passant: bool = False):
        self.start_pos = start_pos
        self.end_pos = end_pos
        self.piece = piece
        self.captured_piece = captured_piece
        self.promotion = promotion
        self.is_castling = is_castling
        self.is_en_passant = is_en_passant


# --- Piece Hierarchy (LSP / OCP) ---

class Piece(ABC):
    """Abstract base for all chess pieces - follows LSP"""

    def __init__(self, color: Color, position: Tuple[int, int]):
        self._color = color
        self._position = position
        self._has_moved = False

    @property
    def color(self) -> Color:
        return self._color

    @property
    def position(self) -> Tuple[int, int]:
        return self._position

    @position.setter
    def position(self, pos: Tuple[int, int]) -> None:
        self._position = pos

    @property
    def has_moved(self) -> bool:
        return self._has_moved

    @has_moved.setter
    def has_moved(self, value: bool) -> None:
        self._has_moved = value

    @property
    @abstractmethod
    def piece_type(self) -> PieceType:
        pass

    @abstractmethod
    def get_possible_moves(self, board: 'Board') -> List[Tuple[int, int]]:
        """Each piece knows how it moves - Strategy pattern variant"""
        pass

    def __str__(self) -> str:
        return f"{self._color.value[0]}{self.piece_type.value[0]}"


# --- Concrete Piece Implementations ---

class King(Piece):
    @property
    def piece_type(self) -> PieceType:
        return PieceType.KING

    def get_possible_moves(self, board: 'Board') -> List[Tuple[int, int]]:
        moves = []
        directions = [(1, 0), (-1, 0), (0, 1), (0, -1),
                      (1, 1), (1, -1), (-1, 1), (-1, -1)]
        for dr, dc in directions:
            r, c = self._position[0] + dr, self._position[1] + dc
            if 0 <= r < 8 and 0 <= c < 8:
                target = board.get_piece_at((r, c))
                if target is None or target.color != self._color:
                    moves.append((r, c))
        # Castling - check squares between king and rook are empty
        # (check validation happens in MoveValidator)
        if not self._has_moved:
            if self._can_castle_kingside(board):
                moves.append((self._position[0], self._position[1] + 2))
            if self._can_castle_queenside(board):
                moves.append((self._position[0], self._position[1] - 2))
        return moves

    def _can_castle_kingside(self, board: 'Board') -> bool:
        r, c = self._position
        rook = board.get_piece_at((r, 7))
        if not isinstance(rook, Rook) or rook.has_moved:
            return False
        if board.get_piece_at((r, 5)) or board.get_piece_at((r, 6)):
            return False
        return True

    def _can_castle_queenside(self, board: 'Board') -> bool:
        r, c = self._position
        rook = board.get_piece_at((r, 0))
        if not isinstance(rook, Rook) or rook.has_moved:
            return False
        if board.get_piece_at((r, 1)) or board.get_piece_at((r, 2)) or board.get_piece_at((r, 3)):
            return False
        return True


class Queen(Piece):
    @property
    def piece_type(self) -> PieceType:
        return PieceType.QUEEN

    def get_possible_moves(self, board: 'Board') -> List[Tuple[int, int]]:
        moves = []
        directions = [(1, 0), (-1, 0), (0, 1), (0, -1),
                      (1, 1), (1, -1), (-1, 1), (-1, -1)]
        for dr, dc in directions:
            r, c = self._position[0] + dr, self._position[1] + dc
            while 0 <= r < 8 and 0 <= c < 8:
                target = board.get_piece_at((r, c))
                if target is None:
                    moves.append((r, c))
                elif target.color != self._color:
                    moves.append((r, c))
                    break
                else:
                    break
                r += dr
                c += dc
        return moves


class Rook(Piece):
    @property
    def piece_type(self) -> PieceType:
        return PieceType.ROOK

    def get_possible_moves(self, board: 'Board') -> List[Tuple[int, int]]:
        moves = []
        directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        for dr, dc in directions:
            r, c = self._position[0] + dr, self._position[1] + dc
            while 0 <= r < 8 and 0 <= c < 8:
                target = board.get_piece_at((r, c))
                if target is None:
                    moves.append((r, c))
                elif target.color != self._color:
                    moves.append((r, c))
                    break
                else:
                    break
                r += dr
                c += dc
        return moves


class Bishop(Piece):
    @property
    def piece_type(self) -> PieceType:
        return PieceType.BISHOP

    def get_possible_moves(self, board: 'Board') -> List[Tuple[int, int]]:
        moves = []
        directions = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
        for dr, dc in directions:
            r, c = self._position[0] + dr, self._position[1] + dc
            while 0 <= r < 8 and 0 <= c < 8:
                target = board.get_piece_at((r, c))
                if target is None:
                    moves.append((r, c))
                elif target.color != self._color:
                    moves.append((r, c))
                    break
                else:
                    break
                r += dr
                c += dc
        return moves


class Knight(Piece):
    @property
    def piece_type(self) -> PieceType:
        return PieceType.KNIGHT

    def get_possible_moves(self, board: 'Board') -> List[Tuple[int, int]]:
        moves = []
        jumps = [(2, 1), (2, -1), (-2, 1), (-2, -1),
                 (1, 2), (1, -2), (-1, 2), (-1, -2)]
        for dr, dc in jumps:
            r, c = self._position[0] + dr, self._position[1] + dc
            if 0 <= r < 8 and 0 <= c < 8:
                target = board.get_piece_at((r, c))
                if target is None or target.color != self._color:
                    moves.append((r, c))
        return moves


class Pawn(Piece):
    @property
    def piece_type(self) -> PieceType:
        return PieceType.PAWN

    def get_possible_moves(self, board: 'Board') -> List[Tuple[int, int]]:
        moves = []
        direction = -1 if self._color == Color.WHITE else 1
        start_row = 6 if self._color == Color.WHITE else 1
        r, c = self._position

        # Forward one
        nr = r + direction
        if 0 <= nr < 8 and board.get_piece_at((nr, c)) is None:
            moves.append((nr, c))
            # Forward two from start
            if r == start_row and board.get_piece_at((nr + direction, c)) is None:
                moves.append((nr + direction, c))

        # Captures
        for dc in [-1, 1]:
            nc = c + dc
            if 0 <= nc < 8 and 0 <= nr < 8:
                target = board.get_piece_at((nr, nc))
                if target and target.color != self._color:
                    moves.append((nr, nc))
                # En passant
                if board.en_passant_target == (nr, nc):
                    moves.append((nr, nc))

        return moves


# --- Piece Factory (Factory Pattern) ---

class PieceFactory:
    """Creates pieces - Open for extension"""

    _piece_map = {
        PieceType.KING: King,
        PieceType.QUEEN: Queen,
        PieceType.ROOK: Rook,
        PieceType.BISHOP: Bishop,
        PieceType.KNIGHT: Knight,
        PieceType.PAWN: Pawn,
    }

    @classmethod
    def create_piece(cls, piece_type: PieceType, color: Color,
                     position: Tuple[int, int]) -> Piece:
        piece_class = cls._piece_map.get(piece_type)
        if not piece_class:
            raise ValueError(f"Unknown piece type: {piece_type}")
        return piece_class(color, position)


# --- Board (SRP) ---

class Board:
    """Single Responsibility: Manages the 8x8 board state"""

    def __init__(self):
        self._grid: List[List[Optional[Piece]]] = [[None] * 8 for _ in range(8)]
        self._en_passant_target: Optional[Tuple[int, int]] = None
        self._setup_pieces()

    def _setup_pieces(self) -> None:
        """Initialize standard chess starting position"""
        # White pieces
        self._place_piece(PieceFactory.create_piece(PieceType.ROOK, Color.WHITE, (7, 0)))
        self._place_piece(PieceFactory.create_piece(PieceType.KNIGHT, Color.WHITE, (7, 1)))
        self._place_piece(PieceFactory.create_piece(PieceType.BISHOP, Color.WHITE, (7, 2)))
        self._place_piece(PieceFactory.create_piece(PieceType.QUEEN, Color.WHITE, (7, 3)))
        self._place_piece(PieceFactory.create_piece(PieceType.KING, Color.WHITE, (7, 4)))
        self._place_piece(PieceFactory.create_piece(PieceType.BISHOP, Color.WHITE, (7, 5)))
        self._place_piece(PieceFactory.create_piece(PieceType.KNIGHT, Color.WHITE, (7, 6)))
        self._place_piece(PieceFactory.create_piece(PieceType.ROOK, Color.WHITE, (7, 7)))
        for c in range(8):
            self._place_piece(PieceFactory.create_piece(PieceType.PAWN, Color.WHITE, (6, c)))

        # Black pieces
        self._place_piece(PieceFactory.create_piece(PieceType.ROOK, Color.BLACK, (0, 0)))
        self._place_piece(PieceFactory.create_piece(PieceType.KNIGHT, Color.BLACK, (0, 1)))
        self._place_piece(PieceFactory.create_piece(PieceType.BISHOP, Color.BLACK, (0, 2)))
        self._place_piece(PieceFactory.create_piece(PieceType.QUEEN, Color.BLACK, (0, 3)))
        self._place_piece(PieceFactory.create_piece(PieceType.KING, Color.BLACK, (0, 4)))
        self._place_piece(PieceFactory.create_piece(PieceType.BISHOP, Color.BLACK, (0, 5)))
        self._place_piece(PieceFactory.create_piece(PieceType.KNIGHT, Color.BLACK, (0, 6)))
        self._place_piece(PieceFactory.create_piece(PieceType.ROOK, Color.BLACK, (0, 7)))
        for c in range(8):
            self._place_piece(PieceFactory.create_piece(PieceType.PAWN, Color.BLACK, (1, c)))

    def _place_piece(self, piece: Piece) -> None:
        r, c = piece.position
        self._grid[r][c] = piece

    def get_piece_at(self, pos: Tuple[int, int]) -> Optional[Piece]:
        r, c = pos
        if 0 <= r < 8 and 0 <= c < 8:
            return self._grid[r][c]
        return None

    def move_piece(self, start: Tuple[int, int], end: Tuple[int, int]) -> Move:
        piece = self.get_piece_at(start)
        captured = self.get_piece_at(end)
        self._grid[end[0]][end[1]] = piece
        self._grid[start[0]][start[1]] = None
        piece.position = end
        piece.has_moved = True
        return Move(start, end, piece, captured_piece=captured)

    def undo_move(self, move: Move) -> None:
        self._grid[move.start_pos[0]][move.start_pos[1]] = move.piece
        self._grid[move.end_pos[0]][move.end_pos[1]] = move.captured_piece
        move.piece.position = move.start_pos
        move.piece.has_moved = False

    @property
    def en_passant_target(self) -> Optional[Tuple[int, int]]:
        return self._en_passant_target

    @en_passant_target.setter
    def en_passant_target(self, value: Optional[Tuple[int, int]]) -> None:
        self._en_passant_target = value

    def find_king(self, color: Color) -> Optional[Piece]:
        for r in range(8):
            for c in range(8):
                piece = self._grid[r][c]
                if piece and piece.piece_type == PieceType.KING and piece.color == color:
                    return piece
        return None

    def is_in_check(self, color: Color) -> bool:
        king = self.find_king(color)
        if not king:
            return False
        opponent = Color.BLACK if color == Color.WHITE else Color.WHITE
        for r in range(8):
            for c in range(8):
                piece = self._grid[r][c]
                if piece and piece.color == opponent:
                    # For kings, check adjacency directly to avoid recursion
                    if isinstance(piece, King):
                        if abs(king.position[0] - r) <= 1 and abs(king.position[1] - c) <= 1:
                            return True
                    elif king.position in piece.get_possible_moves(self):
                        return True
        return False

    def is_checkmate(self, color: Color) -> bool:
        if not self.is_in_check(color):
            return False
        return not self._has_legal_moves(color)

    def is_stalemate(self, color: Color) -> bool:
        if self.is_in_check(color):
            return False
        return not self._has_legal_moves(color)

    def _has_legal_moves(self, color: Color) -> bool:
        for r in range(8):
            for c in range(8):
                piece = self._grid[r][c]
                if piece and piece.color == color:
                    for move_to in piece.get_possible_moves(self):
                        if self._is_legal_move(piece, move_to):
                            return True
        return False

    def _is_legal_move(self, piece: Piece, end: Tuple[int, int]) -> bool:
        start = piece.position
        captured = self.get_piece_at(end)
        self._grid[end[0]][end[1]] = piece
        self._grid[start[0]][start[1]] = None
        piece.position = end

        in_check = self.is_in_check(piece.color)

        piece.position = start
        self._grid[start[0]][start[1]] = piece
        self._grid[end[0]][end[1]] = captured

        return not in_check

    def display(self) -> None:
        print("  a b c d e f g h")
        for r in range(8):
            print(8 - r, end=" ")
            for c in range(8):
                piece = self._grid[r][c]
                if piece:
                    print(piece, end=" ")
                else:
                    print(".", end=" ")
            print(8 - r)
        print("  a b c d e f g h")


# --- Player (SRP) ---

class Player:
    def __init__(self, name: str, color: Color):
        self._name = name
        self._color = color

    @property
    def name(self) -> str:
        return self._name

    @property
    def color(self) -> Color:
        return self._color


# --- Move Validator (SRP) ---

class MoveValidator:
    """Single Responsibility: Validates moves according to chess rules"""

    def __init__(self, board: Board):
        self._board = board

    def validate(self, player: Player, start: Tuple[int, int],
                 end: Tuple[int, int]) -> bool:
        piece = self._board.get_piece_at(start)
        if not piece:
            print("No piece at source")
            return False
        if piece.color != player.color:
            print(f"Not your piece ({piece.color} != {player.color})")
            return False
        if end not in piece.get_possible_moves(self._board):
            print(f"Invalid move for {piece.piece_type.value}")
            return False
        if not self._board._is_legal_move(piece, end):
            print("Move leaves king in check")
            return False
        return True


# --- Game (Facade / State Pattern) ---

class ChessGame:
    """Facade for the entire chess game - manages game flow"""

    def __init__(self, player1_name: str = "Player 1",
                 player2_name: str = "Player 2"):
        self._board = Board()
        self._validator = MoveValidator(self._board)
        self._player1 = Player(player1_name, Color.WHITE)
        self._player2 = Player(player2_name, Color.BLACK)
        self._current_player = self._player1
        self._status = GameStatus.ACTIVE
        self._move_history: List[Move] = []
        self._half_move_clock = 0

    @property
    def board(self) -> Board:
        return self._board

    @property
    def current_player(self) -> Player:
        return self._current_player

    @property
    def status(self) -> GameStatus:
        return self._status

    def make_move(self, start: Tuple[int, int], end: Tuple[int, int]) -> bool:
        if self._status not in (GameStatus.ACTIVE, GameStatus.CHECK):
            print(f"Game is over: {self._status.value}")
            return False

        if not self._validator.validate(self._current_player, start, end):
            return False

        move = self._board.move_piece(start, end)
        self._move_history.append(move)
        self._update_game_status()
        self._switch_player()
        return True

    def _update_game_status(self) -> None:
        opponent = self._player2 if self._current_player == self._player1 else self._player1
        if self._board.is_checkmate(opponent.color):
            self._status = GameStatus.CHECKMATE
            print(f"Checkmate! {self._current_player.name} wins!")
        elif self._board.is_stalemate(opponent.color):
            self._status = GameStatus.STALEMATE
            print("Stalemate! It's a draw!")
        elif self._board.is_in_check(opponent.color):
            self._status = GameStatus.CHECK
            print(f"Check! {opponent.name} is in check")
        else:
            self._status = GameStatus.ACTIVE

    def _switch_player(self) -> None:
        self._current_player = (self._player2
                                if self._current_player == self._player1
                                else self._player1)

    def resign(self, player: Player) -> None:
        self._status = GameStatus.RESIGNED
        winner = self._player2 if player == self._player1 else self._player1
        print(f"{player.name} resigns. {winner.name} wins!")

    def display(self) -> None:
        print(f"\n--- Chess Game ({self._status.value}) ---")
        print(f"Current turn: {self._current_player.name} ({self._current_player.color.value})")
        self._board.display()


# --- Demo ---

def play_sample_game():
    game = ChessGame("Alice", "Bob")
    game.display()

    # Sample moves
    moves = [
        ((6, 4), (4, 4)),  # e4
        ((1, 3), (3, 3)),  # d5
        ((7, 3), (3, 7)),  # Qh5 (Scholar's Mate attempt)
        ((0, 1), (2, 2)),  # Nc6
        ((3, 7), (1, 5)),  # Qxf7#
    ]

    for start, end in moves:
        print(f"\nMove: {start} -> {end}")
        game.make_move(start, end)
        game.display()

    print(f"\nFinal status: {game.status.value}")


if __name__ == "__main__":
    play_sample_game()
```

---

## ▶️ How to Run

```bash
cd low-level-design/chess-game
python chess_game.py
```

## 🧩 Design Patterns

See the [Interview Questions](INTERVIEW_QUESTIONS.md) for a detailed breakdown of design patterns and SOLID principles applied in this implementation.
