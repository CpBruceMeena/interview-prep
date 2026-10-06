# Chess Game — Implementation

> Python implementation of two-player chess with the full rule set: castling (with the "not out of, through or into check" rules), en passant, promotion, check / checkmate / stalemate, draws (insufficient material, 50/75-move rule, threefold/fivefold repetition), undo, and a thread-safe game facade.
> Move generation is verified against published **perft** counts in `test_chess_game.py`.

---

## 🧭 Walkthrough

### Class map

| Class | Responsibility |
|-------|----------------|
| `Color`, `PieceType`, `GameStatus` | Vocabulary. `Color.opponent` and `GameStatus.is_over` remove `if`-chains elsewhere. |
| `Piece` (ABC) | `get_possible_moves(board)`: pseudo-legal destinations. `attacks(board)`: squares it attacks. |
| `SlidingPiece` → `Queen`, `Rook`, `Bishop` | One slide loop driven by a `DIRECTIONS` tuple; the three subclasses only declare directions. |
| `Knight`, `King`, `Pawn` | Their own patterns. `King` adds castling; `Pawn` adds double push, diagonal capture, en passant. |
| `PieceFactory` | `PieceType` → class. Used by setup, FEN loading and promotion. |
| `Move` (dataclass) | Everything needed to undo: captured piece *and square* (they differ for en passant), rook hop for castling, promoted piece, previous en-passant target, previous `has_moved`. |
| `Board` | Grid + en-passant target. `apply_move` / `undo_move` (exact inverses), `is_square_attacked`, `is_in_check`, `is_legal_move`, `legal_moves`, `is_checkmate`, `is_stalemate`, `has_insufficient_material`, `position_key`, `from_fen`. |
| `Player` (frozen dataclass) | Name + colour. |
| `MoveValidator` | Turns a request into a `Piece` or an `InvalidMoveError` with a precise reason (empty square, wrong colour, bad pattern, leaves king in check). |
| `ChessGame` | Facade: turn order, status transitions, draw rules, `undo_last_move`, `resign`, `claim_draw`. Owns the lock and the `expected_ply` check. |

### Key design decisions

1. **Pseudo-legal generation, legality by make/unmake.** A piece only knows its pattern. `Board.is_legal_move` applies the move, asks "is my king attacked?", and undoes it. Pins, discovered checks and "king walks into check" all fall out of that one test; no pin-detection code exists.
2. **`attacks()` is separate from `get_possible_moves()`.** Two pieces differ: pawns move straight but attack diagonally (even onto empty squares), and castling is a king *move* but not an *attack*. Check detection uses only `attacks()`, so `King.get_possible_moves` can safely ask `is_square_attacked` for the castling squares without recursing into castling again.
3. **Undo is exact.** `undo_move` restores `has_moved` from the record rather than setting it to `False` (an older version did that, which silently restored castling rights after any undo). The same make/unmake pair powers legality checks, `ChessGame.undo_last_move`, and perft.
4. **Castling rights are derived from `has_moved`.** A rook that moves away and back has still moved, so the right is gone; the test `test_castling_right_lost_after_rook_moves_and_returns` pins that down.
5. **Draws follow FIDE.** Insufficient material, the 75-move rule and fivefold repetition end the game automatically; the 50-move rule and threefold repetition are *claims* (`can_claim_draw` / `claim_draw`). `position_key` includes side to move, castling rights and the en-passant square only when a capture there is actually possible, which is what FIDE means by "same position".
6. **Concurrency at the facade.** In an online game two requests can arrive for the same turn (double click, client retry, reconnect replay). `make_move` runs under a lock and accepts `expected_ply`: a submission built against an old position raises `StaleMoveError` instead of being applied to the new one. This is optimistic concurrency, the same idea as a `version` column.
7. **Exceptions, no printing in domain code.** `InvalidMoveError`, `GameOverError`, `StaleMoveError` (all `ChessError`). The demo prints.

### Performance note

This is an interview-grade array board: legality costs a full attack scan per candidate move. Perft(3) from the start position (8,902 leaves) runs in roughly 0.1 s. Engines use bitboards and incremental attack maps (see INTERVIEW_QUESTIONS Q5) and are several orders of magnitude faster. That is the right trade-off for a game server validating one move at a time, and the wrong one for an engine searching millions of positions.

### Where to extend

| Interviewer asks for | Change |
|----------------------|--------|
| Chess clocks | A `Clock` per colour on `ChessGame`; `make_move` charges elapsed time under the same lock and adds increment; a timeout is a new terminal status. |
| AI opponent | `ChessAI.choose_move(board, color)` strategy that uses `board.legal_moves` + `apply_move`/`undo_move` for search. |
| PGN / SAN export | `Move` already carries capture, castling, promotion flags; SAN needs disambiguation using `legal_moves`. |
| Fairy piece (e.g. Archbishop) | New `Piece` subclass + `PieceType` + factory entry. Board, validator and game are untouched. |
| Persistence | `Board.from_fen` loads a position; store the move list (append-only) and rebuild by replay. |

---

## 📦 Source

<!-- source: chess_game.py -->
```python
"""
Chess Game System - Low Level Design
------------------------------------
Two-player chess with the full rule set an interviewer will poke at:
castling (not out of, through, or into check), en passant, promotion,
check / checkmate / stalemate, and draws (insufficient material, 50/75-move
rule, threefold/fivefold repetition). Moves can be undone.

Key decisions:
  - Each Piece generates *pseudo-legal* destinations (get_possible_moves) and,
    separately, the squares it *attacks* (attacks). Check detection only uses
    attacks(), so castling can ask "is this square attacked?" without recursion.
  - Board.apply_move / undo_move are exact inverses. A move records everything
    needed to reverse it (captured piece and square, rook hop, previous
    en-passant target, previous has_moved flags), so legality is checked by
    make -> test king safety -> unmake, with no board copies.
  - ChessGame is the facade. It serialises moves with a lock and accepts an
    optional expected_ply so a stale or duplicated client submission is
    rejected instead of being applied to the wrong position.

Coordinates: (row, col) with row 0 = rank 8 and col 0 = file a, so "e2" is (6, 4).
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union

Square = Tuple[int, int]
SquareLike = Union[Square, str]


# --- Enums ---

class Color(Enum):
    WHITE = "White"
    BLACK = "Black"

    @property
    def opponent(self) -> "Color":
        return Color.BLACK if self is Color.WHITE else Color.WHITE


class PieceType(Enum):
    KING = "King"
    QUEEN = "Queen"
    ROOK = "Rook"
    BISHOP = "Bishop"
    KNIGHT = "Knight"
    PAWN = "Pawn"


PROMOTION_CHOICES = (PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT)


class GameStatus(Enum):
    ACTIVE = "Active"
    CHECK = "Check"
    CHECKMATE = "Checkmate"
    STALEMATE = "Stalemate"
    DRAW = "Draw"            # insufficient material, 75-move, fivefold, or a claimed draw
    RESIGNED = "Resigned"

    @property
    def is_over(self) -> bool:
        return self not in (GameStatus.ACTIVE, GameStatus.CHECK)


# --- Exceptions ---

class ChessError(Exception):
    pass


class InvalidMoveError(ChessError):
    pass


class GameOverError(ChessError):
    pass


class StaleMoveError(ChessError):
    """The client's expected_ply does not match the game: retry or duplicate."""


# --- Coordinates ---

def square(name: str) -> Square:
    """'e4' -> (4, 4)."""
    if len(name) != 2 or name[0] not in "abcdefgh" or name[1] not in "12345678":
        raise ValueError(f"Bad square {name!r}")
    return 8 - int(name[1]), ord(name[0]) - ord("a")


def square_name(pos: Square) -> str:
    return f"{'abcdefgh'[pos[1]]}{8 - pos[0]}"


def _on_board(r: int, c: int) -> bool:
    return 0 <= r < 8 and 0 <= c < 8


# --- Move (Command-style record: enough to undo) ---

@dataclass
class Move:
    start_pos: Square
    end_pos: Square
    piece: "Piece"
    captured_piece: Optional["Piece"] = None
    captured_pos: Optional[Square] = None          # differs from end_pos for en passant
    promotion: Optional[PieceType] = None
    promoted_piece: Optional["Piece"] = None
    is_castling: bool = False
    is_en_passant: bool = False
    rook_from: Optional[Square] = None
    rook_to: Optional[Square] = None
    prev_en_passant_target: Optional[Square] = None
    prev_has_moved: bool = False

    def __str__(self) -> str:
        s = f"{square_name(self.start_pos)}{square_name(self.end_pos)}"
        if self.promotion:
            s += "=" + _SYMBOL[self.promotion]
        return s


# --- Piece Hierarchy (LSP / OCP) ---

_SYMBOL = {PieceType.KING: "K", PieceType.QUEEN: "Q", PieceType.ROOK: "R",
           PieceType.BISHOP: "B", PieceType.KNIGHT: "N", PieceType.PAWN: "P"}


class Piece(ABC):
    """A piece knows its movement pattern; legality (king safety) is the Board's job."""

    def __init__(self, color: Color, position: Square):
        self._color = color
        self._position = position
        self._has_moved = False

    @property
    def color(self) -> Color:
        return self._color

    @property
    def position(self) -> Square:
        return self._position

    @position.setter
    def position(self, pos: Square) -> None:
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
        ...

    @abstractmethod
    def get_possible_moves(self, board: "Board") -> List[Square]:
        """Pseudo-legal destinations: obey the movement pattern, ignore own-king safety."""

    def attacks(self, board: "Board") -> List[Square]:
        """Squares this piece attacks. Same as its moves for every piece except
        pawns (attack diagonally, move straight) and kings (castling is not an attack)."""
        return self.get_possible_moves(board)

    @property
    def symbol(self) -> str:
        s = _SYMBOL[self.piece_type]
        return s if self._color is Color.WHITE else s.lower()

    def __str__(self) -> str:
        return f"{self._color.value[0]}{_SYMBOL[self.piece_type]}"

    def __repr__(self) -> str:
        return f"{self._color.value} {self.piece_type.value}@{square_name(self._position)}"


class SlidingPiece(Piece):
    """Queen, rook and bishop: slide along directions until blocked."""

    DIRECTIONS: Tuple[Square, ...] = ()

    def get_possible_moves(self, board: "Board") -> List[Square]:
        moves = []
        for dr, dc in self.DIRECTIONS:
            r, c = self._position[0] + dr, self._position[1] + dc
            while _on_board(r, c):
                target = board.get_piece_at((r, c))
                if target is None:
                    moves.append((r, c))
                else:
                    if target.color is not self._color:
                        moves.append((r, c))
                    break
                r, c = r + dr, c + dc
        return moves


_ORTHOGONAL = ((1, 0), (-1, 0), (0, 1), (0, -1))
_DIAGONAL = ((1, 1), (1, -1), (-1, 1), (-1, -1))


class Queen(SlidingPiece):
    DIRECTIONS = _ORTHOGONAL + _DIAGONAL

    @property
    def piece_type(self) -> PieceType:
        return PieceType.QUEEN


class Rook(SlidingPiece):
    DIRECTIONS = _ORTHOGONAL

    @property
    def piece_type(self) -> PieceType:
        return PieceType.ROOK


class Bishop(SlidingPiece):
    DIRECTIONS = _DIAGONAL

    @property
    def piece_type(self) -> PieceType:
        return PieceType.BISHOP


class Knight(Piece):
    JUMPS = ((2, 1), (2, -1), (-2, 1), (-2, -1), (1, 2), (1, -2), (-1, 2), (-1, -2))

    @property
    def piece_type(self) -> PieceType:
        return PieceType.KNIGHT

    def get_possible_moves(self, board: "Board") -> List[Square]:
        moves = []
        for dr, dc in self.JUMPS:
            r, c = self._position[0] + dr, self._position[1] + dc
            if _on_board(r, c):
                target = board.get_piece_at((r, c))
                if target is None or target.color is not self._color:
                    moves.append((r, c))
        return moves


class King(Piece):
    @property
    def piece_type(self) -> PieceType:
        return PieceType.KING

    def attacks(self, board: "Board") -> List[Square]:
        out = []
        for dr, dc in _ORTHOGONAL + _DIAGONAL:
            r, c = self._position[0] + dr, self._position[1] + dc
            if _on_board(r, c):
                target = board.get_piece_at((r, c))
                if target is None or target.color is not self._color:
                    out.append((r, c))
        return out

    def get_possible_moves(self, board: "Board") -> List[Square]:
        moves = self.attacks(board)
        if not self._has_moved and not board.is_in_check(self._color):
            r, c = self._position
            if self._can_castle(board, rook_col=7, empty=(5, 6), safe=(5, 6)):
                moves.append((r, c + 2))
            if self._can_castle(board, rook_col=0, empty=(1, 2, 3), safe=(3, 2)):
                moves.append((r, c - 2))
        return moves

    def _can_castle(self, board: "Board", rook_col: int,
                    empty: Tuple[int, ...], safe: Tuple[int, ...]) -> bool:
        r = self._position[0]
        rook = board.get_piece_at((r, rook_col))
        if not isinstance(rook, Rook) or rook.color is not self._color or rook.has_moved:
            return False
        if any(board.get_piece_at((r, c)) for c in empty):
            return False
        # The king may not pass through or land on an attacked square.
        enemy = self._color.opponent
        return not any(board.is_square_attacked((r, c), enemy) for c in safe)


class Pawn(Piece):
    @property
    def piece_type(self) -> PieceType:
        return PieceType.PAWN

    @property
    def direction(self) -> int:
        return -1 if self._color is Color.WHITE else 1

    def attacks(self, board: "Board") -> List[Square]:
        r, c = self._position
        nr = r + self.direction
        return [(nr, nc) for nc in (c - 1, c + 1) if _on_board(nr, nc)]

    def get_possible_moves(self, board: "Board") -> List[Square]:
        moves = []
        r, c = self._position
        nr = r + self.direction
        start_row = 6 if self._color is Color.WHITE else 1

        if _on_board(nr, c) and board.get_piece_at((nr, c)) is None:
            moves.append((nr, c))
            two = nr + self.direction
            if r == start_row and board.get_piece_at((two, c)) is None:
                moves.append((two, c))

        for target_sq in self.attacks(board):
            target = board.get_piece_at(target_sq)
            if target is not None and target.color is not self._color:
                moves.append(target_sq)
            elif target_sq == board.en_passant_target:
                victim = board.get_piece_at((r, target_sq[1]))
                if isinstance(victim, Pawn) and victim.color is not self._color:
                    moves.append(target_sq)
        return moves


# --- Piece Factory ---

class PieceFactory:
    _piece_map = {
        PieceType.KING: King,
        PieceType.QUEEN: Queen,
        PieceType.ROOK: Rook,
        PieceType.BISHOP: Bishop,
        PieceType.KNIGHT: Knight,
        PieceType.PAWN: Pawn,
    }

    @classmethod
    def create_piece(cls, piece_type: PieceType, color: Color, position: Square) -> Piece:
        piece_class = cls._piece_map.get(piece_type)
        if piece_class is None:
            raise ValueError(f"Unknown piece type: {piece_type}")
        return piece_class(color, position)


# --- Board ---

_BACK_RANK = (PieceType.ROOK, PieceType.KNIGHT, PieceType.BISHOP, PieceType.QUEEN,
              PieceType.KING, PieceType.BISHOP, PieceType.KNIGHT, PieceType.ROOK)


class Board:
    """8x8 grid plus the one piece of board state that isn't on a square: the en-passant target."""

    def __init__(self, setup: bool = True):
        self._grid: List[List[Optional[Piece]]] = [[None] * 8 for _ in range(8)]
        self._en_passant_target: Optional[Square] = None
        if setup:
            self._setup_pieces()

    def _setup_pieces(self) -> None:
        for color, back, pawns in ((Color.WHITE, 7, 6), (Color.BLACK, 0, 1)):
            for c, piece_type in enumerate(_BACK_RANK):
                self.place(piece_type, color, (back, c))
                self.place(PieceType.PAWN, color, (pawns, c))

    @classmethod
    def from_fen(cls, fen: str) -> Tuple["Board", Color]:
        """Load the placement, side to move, castling rights and en-passant fields of a FEN."""
        fields = fen.split()
        placement, side = fields[0], fields[1]
        rights = fields[2] if len(fields) > 2 else "-"
        ep = fields[3] if len(fields) > 3 else "-"
        board = cls(setup=False)
        by_symbol = {v: k for k, v in _SYMBOL.items()}
        for r, rank in enumerate(placement.split("/")):
            c = 0
            for ch in rank:
                if ch.isdigit():
                    c += int(ch)
                    continue
                color = Color.WHITE if ch.isupper() else Color.BLACK
                # Everything counts as moved unless a castling right says otherwise.
                board.place(by_symbol[ch.upper()], color, (r, c), has_moved=True)
                c += 1
        for color, row, k_side, q_side in ((Color.WHITE, 7, "K", "Q"), (Color.BLACK, 0, "k", "q")):
            for flag, rook_col in ((k_side, 7), (q_side, 0)):
                if flag in rights:
                    for pos in ((row, 4), (row, rook_col)):
                        piece = board.get_piece_at(pos)
                        if piece is not None:
                            piece.has_moved = False
        for p in board.pieces(Color.WHITE) + board.pieces(Color.BLACK):
            if isinstance(p, Pawn) and p.position[0] == (6 if p.color is Color.WHITE else 1):
                p.has_moved = False
        board._en_passant_target = None if ep == "-" else square(ep)
        return board, Color.WHITE if side == "w" else Color.BLACK

    def place(self, piece_type: PieceType, color: Color, pos: Square,
              has_moved: bool = False) -> Piece:
        """Put a piece on a square (setup and tests)."""
        piece = PieceFactory.create_piece(piece_type, color, pos)
        piece.has_moved = has_moved
        self._grid[pos[0]][pos[1]] = piece
        return piece

    def get_piece_at(self, pos: Square) -> Optional[Piece]:
        r, c = pos
        return self._grid[r][c] if _on_board(r, c) else None

    @property
    def en_passant_target(self) -> Optional[Square]:
        return self._en_passant_target

    def pieces(self, color: Optional[Color] = None) -> List[Piece]:
        return [p for row in self._grid for p in row
                if p is not None and (color is None or p.color is color)]

    def find_king(self, color: Color) -> Optional[Piece]:
        for p in self.pieces(color):
            if p.piece_type is PieceType.KING:
                return p
        return None

    # ---- attack / check ----

    def is_square_attacked(self, pos: Square, by_color: Color) -> bool:
        return any(pos in p.attacks(self) for p in self.pieces(by_color))

    def is_in_check(self, color: Color) -> bool:
        king = self.find_king(color)
        return king is not None and self.is_square_attacked(king.position, color.opponent)

    # ---- make / unmake ----

    def apply_move(self, start: Square, end: Square,
                   promotion: Optional[PieceType] = None) -> Move:
        """Execute a pseudo-legal move and return a record that undo_move() can reverse.
        Does not check legality; callers go through MoveValidator / legal_moves."""
        piece = self.get_piece_at(start)
        if piece is None:
            raise InvalidMoveError(f"No piece at {square_name(start)}")
        move = Move(start, end, piece,
                    prev_en_passant_target=self._en_passant_target,
                    prev_has_moved=piece.has_moved)

        if isinstance(piece, Pawn) and end == self._en_passant_target and start[1] != end[1] \
                and self.get_piece_at(end) is None:
            move.is_en_passant = True
            move.captured_pos = (start[0], end[1])
        elif self.get_piece_at(end) is not None:
            move.captured_pos = end
        if move.captured_pos is not None:
            move.captured_piece = self.get_piece_at(move.captured_pos)
            self._set(move.captured_pos, None)

        self._set(start, None)
        self._set(end, piece)
        piece.position = end
        piece.has_moved = True

        if isinstance(piece, King) and abs(end[1] - start[1]) == 2:
            move.is_castling = True
            rook_col_from, rook_col_to = (7, 5) if end[1] > start[1] else (0, 3)
            move.rook_from, move.rook_to = (start[0], rook_col_from), (start[0], rook_col_to)
            rook = self.get_piece_at(move.rook_from)
            self._set(move.rook_from, None)
            self._set(move.rook_to, rook)
            rook.position = move.rook_to
            rook.has_moved = True        # it was unmoved, or castling would be illegal

        last_row = 0 if piece.color is Color.WHITE else 7
        if isinstance(piece, Pawn) and end[0] == last_row:
            promotion = promotion or PieceType.QUEEN
            if promotion not in PROMOTION_CHOICES:
                raise InvalidMoveError(f"Cannot promote to {promotion.value}")
            move.promotion = promotion
            move.promoted_piece = PieceFactory.create_piece(promotion, piece.color, end)
            move.promoted_piece.has_moved = True
            self._set(end, move.promoted_piece)

        if isinstance(piece, Pawn) and abs(end[0] - start[0]) == 2:
            self._en_passant_target = ((start[0] + end[0]) // 2, start[1])
        else:
            self._en_passant_target = None
        return move

    def undo_move(self, move: Move) -> None:
        piece = move.piece
        self._set(move.end_pos, None)
        self._set(move.start_pos, piece)
        piece.position = move.start_pos
        piece.has_moved = move.prev_has_moved
        if move.captured_piece is not None:
            self._set(move.captured_pos, move.captured_piece)
            move.captured_piece.position = move.captured_pos
        if move.is_castling:
            rook = self.get_piece_at(move.rook_to)
            self._set(move.rook_to, None)
            self._set(move.rook_from, rook)
            rook.position = move.rook_from
            rook.has_moved = False
        self._en_passant_target = move.prev_en_passant_target

    def _set(self, pos: Square, piece: Optional[Piece]) -> None:
        self._grid[pos[0]][pos[1]] = piece

    # ---- legality ----

    def is_legal_move(self, piece: Piece, end: Square) -> bool:
        """Pseudo-legal for this piece AND does not leave its own king in check."""
        if end not in piece.get_possible_moves(self):
            return False
        move = self.apply_move(piece.position, end)
        try:
            return not self.is_in_check(piece.color)
        finally:
            self.undo_move(move)

    def legal_moves(self, color: Color) -> List[Tuple[Square, Square]]:
        out = []
        for p in self.pieces(color):
            start = p.position
            for end in p.get_possible_moves(self):
                move = self.apply_move(start, end)
                if not self.is_in_check(color):
                    out.append((start, end))
                self.undo_move(move)
        return out

    def has_legal_moves(self, color: Color) -> bool:
        for p in self.pieces(color):
            start = p.position
            for end in p.get_possible_moves(self):
                move = self.apply_move(start, end)
                safe = not self.is_in_check(color)
                self.undo_move(move)
                if safe:
                    return True
        return False

    def is_checkmate(self, color: Color) -> bool:
        return self.is_in_check(color) and not self.has_legal_moves(color)

    def is_stalemate(self, color: Color) -> bool:
        return not self.is_in_check(color) and not self.has_legal_moves(color)

    def has_insufficient_material(self) -> bool:
        """K vs K, K+minor vs K, or K+B vs K+B with same-coloured bishops."""
        others = [p for p in self.pieces() if p.piece_type is not PieceType.KING]
        if not others:
            return True
        if len(others) == 1 and others[0].piece_type in (PieceType.BISHOP, PieceType.KNIGHT):
            return True
        if all(p.piece_type is PieceType.BISHOP for p in others):
            return len({sum(p.position) % 2 for p in others}) == 1
        return False

    def position_key(self, side_to_move: Color) -> Tuple:
        """Identity of a position for repetition: placement, side to move, castling
        rights, and the en-passant square only if a capture there is possible."""
        placement = tuple(p.symbol if p else "." for row in self._grid for p in row)
        rights = []
        for color, r in ((Color.WHITE, 7), (Color.BLACK, 0)):
            king = self.get_piece_at((r, 4))
            if isinstance(king, King) and king.color is color and not king.has_moved:
                for rc in (7, 0):
                    rook = self.get_piece_at((r, rc))
                    if isinstance(rook, Rook) and rook.color is color and not rook.has_moved:
                        rights.append((color.value, rc))
        ep = None
        if self._en_passant_target is not None:
            if any(isinstance(p, Pawn) and self._en_passant_target in p.get_possible_moves(self)
                   for p in self.pieces(side_to_move)):
                ep = self._en_passant_target
        return placement, side_to_move.value, tuple(rights), ep

    def render(self) -> str:
        lines = ["  a b c d e f g h"]
        for r in range(8):
            cells = " ".join(p.symbol if p else "." for p in self._grid[r])
            lines.append(f"{8 - r} {cells} {8 - r}")
        lines.append("  a b c d e f g h")
        return "\n".join(lines)


# --- Player ---

@dataclass(frozen=True)
class Player:
    name: str
    color: Color


# --- Move Validator ---

class MoveValidator:
    """Turns a (player, start, end) request into either OK or a precise reason."""

    def __init__(self, board: Board):
        self._board = board

    def validate(self, player: Player, start: Square, end: Square) -> Piece:
        piece = self._board.get_piece_at(start)
        if piece is None:
            raise InvalidMoveError(f"No piece at {square_name(start)}")
        if piece.color is not player.color:
            raise InvalidMoveError(f"{square_name(start)} is not {player.name}'s piece")
        if end not in piece.get_possible_moves(self._board):
            raise InvalidMoveError(
                f"{piece.piece_type.value} cannot move {square_name(start)}->{square_name(end)}")
        if not self._board.is_legal_move(piece, end):
            raise InvalidMoveError("Move leaves own king in check")
        return piece


# --- Game (Facade) ---

@dataclass
class _Snapshot:
    move: Move
    status: GameStatus
    halfmove_clock: int
    position_key: Tuple


class ChessGame:
    """Facade: turn order, status transitions, draws, undo. Thread-safe."""

    def __init__(self, white_name: str = "White", black_name: str = "Black",
                 board: Optional[Board] = None, to_move: Color = Color.WHITE):
        self._board = board if board is not None else Board()
        self._validator = MoveValidator(self._board)
        self._players = {Color.WHITE: Player(white_name, Color.WHITE),
                         Color.BLACK: Player(black_name, Color.BLACK)}
        self._to_move = to_move
        self._status = GameStatus.ACTIVE
        self._winner: Optional[Player] = None
        self._history: List[_Snapshot] = []
        self._halfmove_clock = 0                       # plies since last capture or pawn move
        self._positions: Counter = Counter()
        self._lock = threading.Lock()
        self._positions[self._board.position_key(self._to_move)] += 1
        self._refresh_status()

    # ---- read-only views ----

    @property
    def board(self) -> Board:
        return self._board

    @property
    def current_player(self) -> Player:
        return self._players[self._to_move]

    @property
    def status(self) -> GameStatus:
        return self._status

    @property
    def winner(self) -> Optional[Player]:
        return self._winner

    @property
    def ply(self) -> int:
        """Number of half-moves played. Clients echo it back as expected_ply."""
        return len(self._history)

    @property
    def moves(self) -> List[Move]:
        return [s.move for s in self._history]

    def player(self, color: Color) -> Player:
        return self._players[color]

    # ---- commands ----

    def make_move(self, start: SquareLike, end: SquareLike,
                  promotion: Optional[PieceType] = None,
                  expected_ply: Optional[int] = None) -> Move:
        start, end = _sq(start), _sq(end)
        with self._lock:
            if self._status.is_over:
                raise GameOverError(f"Game is over: {self._status.value}")
            if expected_ply is not None and expected_ply != self.ply:
                raise StaleMoveError(f"expected ply {expected_ply}, game is at {self.ply}")
            if promotion is not None and promotion not in PROMOTION_CHOICES:
                raise InvalidMoveError(f"Cannot promote to {promotion.value}")
            piece = self._validator.validate(self.current_player, start, end)

            snapshot_status, snapshot_clock = self._status, self._halfmove_clock
            move = self._board.apply_move(start, end, promotion)

            resets = isinstance(piece, Pawn) or move.captured_piece is not None
            self._halfmove_clock = 0 if resets else self._halfmove_clock + 1
            self._to_move = self._to_move.opponent
            new_key = self._board.position_key(self._to_move)
            self._positions[new_key] += 1
            self._history.append(_Snapshot(move, snapshot_status, snapshot_clock, new_key))
            self._refresh_status()
            return move

    def undo_last_move(self) -> Move:
        with self._lock:
            if not self._history:
                raise ChessError("Nothing to undo")
            snap = self._history.pop()
            self._positions[snap.position_key] -= 1
            if self._positions[snap.position_key] == 0:
                del self._positions[snap.position_key]
            self._board.undo_move(snap.move)
            self._to_move = self._to_move.opponent
            self._halfmove_clock = snap.halfmove_clock
            self._status, self._winner = snap.status, None
            return snap.move

    def resign(self, color: Color) -> None:
        with self._lock:
            if self._status.is_over:
                raise GameOverError(f"Game is over: {self._status.value}")
            self._status = GameStatus.RESIGNED
            self._winner = self._players[color.opponent]

    def can_claim_draw(self) -> bool:
        """FIDE: the player to move may claim at threefold repetition or 50 moves (100 plies)."""
        current = self._board.position_key(self._to_move)
        return self._positions[current] >= 3 or self._halfmove_clock >= 100

    def claim_draw(self) -> None:
        with self._lock:
            if self._status.is_over:
                raise GameOverError(f"Game is over: {self._status.value}")
            if not self.can_claim_draw():
                raise ChessError("No draw claim available")
            self._status = GameStatus.DRAW

    # ---- internals ----

    def _refresh_status(self) -> None:
        side = self._to_move
        if self._board.is_checkmate(side):
            self._status = GameStatus.CHECKMATE
            self._winner = self._players[side.opponent]
        elif self._board.is_stalemate(side):
            self._status = GameStatus.STALEMATE
        elif (self._board.has_insufficient_material()
              or self._halfmove_clock >= 150                      # 75-move rule: automatic
              or self._positions[self._board.position_key(side)] >= 5):  # fivefold: automatic
            self._status = GameStatus.DRAW
        elif self._board.is_in_check(side):
            self._status = GameStatus.CHECK
        else:
            self._status = GameStatus.ACTIVE

    def render(self) -> str:
        head = (f"--- {self._status.value} | ply {self.ply} | "
                f"to move: {self.current_player.name} ({self._to_move.value}) ---")
        return head + "\n" + self._board.render()


def _sq(s: SquareLike) -> Square:
    if isinstance(s, str):
        return square(s)
    if not _on_board(*s):
        raise InvalidMoveError(f"Off-board square {s}")
    return s


# --- Demo ---

def play_scripted(game: ChessGame, moves: List[str]) -> None:
    for m in moves:
        promo = {"q": PieceType.QUEEN, "n": PieceType.KNIGHT}.get(m[4:5])
        move = game.make_move(m[:2], m[2:4], promotion=promo)
        print(f"{game.ply:>3}. {move}  -> {game.status.value}")


def main() -> None:
    print("=== Game 1: Scholar's mate ===")
    game = ChessGame("Alice", "Bob")
    play_scripted(game, ["e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7"])
    print(game.render())
    print(f"Winner: {game.winner.name if game.winner else None}")
    try:
        game.make_move("a7", "a6")
    except GameOverError as e:
        print(f"Rejected: {e}")

    print("\n=== Game 2: castling, en passant, illegal moves, undo ===")
    game = ChessGame("Carol", "Dan")
    play_scripted(game, ["e2e4", "a7a6", "e4e5", "d7d5", "e5d6",      # e5xd6 en passant
                         "a6a5", "g1f3", "a5a4", "f1e2", "a4a3", "e1g1"])  # O-O
    print(game.render())
    for bad in (("c2", "c3"), ("e8", "e6"), ("d8", "d5")):
        try:
            game.make_move(*bad)
        except InvalidMoveError as e:
            print(f"Rejected {bad[0]}{bad[1]}: {e}")
    try:
        game.make_move("b7", "b6", expected_ply=5)
    except StaleMoveError as e:
        print(f"Rejected stale submission: {e}")
    undone = game.undo_last_move()
    print(f"Undid {undone}; white king back on e1: {game.board.get_piece_at(square('e1'))!r}")


if __name__ == "__main__":
    main()
```
<!-- /source -->

---

## ▶️ How to Run

```bash
cd python-low-level-design/chess-game
python3 chess_game.py                    # scripted demo: scholar's mate, castling, en passant, undo
python3 -m unittest test_chess_game -v   # rules, perft, draws, concurrency
```

## 🧩 Design Patterns

| Pattern | Where | Why |
|---------|-------|-----|
| **Polymorphism / Template** | `Piece`, `SlidingPiece` | No `if piece_type == ...`; sliders share one loop |
| **Factory** | `PieceFactory` | One place that maps types to classes (setup, FEN, promotion) |
| **Command (lightweight)** | `Move` | Self-contained record that `undo_move` reverses |
| **Facade** | `ChessGame` | One entry point that also owns synchronisation |

See [Interview Questions](INTERVIEW_QUESTIONS.md) for the follow-ups and trade-offs.
