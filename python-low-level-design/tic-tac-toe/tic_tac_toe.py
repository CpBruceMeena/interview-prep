"""
Tic-Tac-Toe Game - Low Level Design
-----------------------------------
N x N tic-tac-toe (default 3x3) with pluggable players.

Key decisions:
  - Board keeps a running sum per row, column and both diagonals (+1 for X,
    -1 for O). A line is won when |sum| == n, so the win check after a move is
    O(1) instead of rescanning the grid.
  - Board.undo_move() reverses the last move exactly (grid, counters, winner,
    history). The bot's search and user-facing undo both rely on that.
  - Players are a Strategy: HumanPlayer (reads input), BotPlayer (minimax with
    memoisation, prefers faster wins), ScriptedPlayer (fixed moves, for demos
    and tests). Players get a *copy* of the board, so a buggy or slow strategy
    can't corrupt the real game.
  - TicTacToeGame.make_move(symbol, pos) is the single, lock-protected entry
    point; it checks turn order, so two concurrent requests for the same turn
    can't both land.

Run `python3 tic_tac_toe.py` for a deterministic demo (scripted game + bot vs
bot), or `python3 tic_tac_toe.py --interactive` to play against the bot.
"""

from __future__ import annotations

import argparse
import threading
from abc import ABC, abstractmethod
from enum import Enum
from typing import Callable, Dict, Iterable, List, Optional, Tuple

Position = Tuple[int, int]


# --- Enums ---

class PlayerSymbol(Enum):
    X = "X"
    O = "O"

    def opponent(self) -> "PlayerSymbol":
        return PlayerSymbol.O if self is PlayerSymbol.X else PlayerSymbol.X

    @property
    def sign(self) -> int:
        return 1 if self is PlayerSymbol.X else -1


class GameStatus(Enum):
    IN_PROGRESS = "In Progress"
    WIN = "Win"
    DRAW = "Draw"


# --- Exceptions ---

class GameError(Exception):
    pass


class InvalidMoveError(GameError):
    pass


class NotYourTurnError(GameError):
    pass


class GameOverError(GameError):
    pass


# --- Board ---

class Board:
    """n x n grid with O(1) win detection and exact undo. Not thread-safe on its own."""

    def __init__(self, size: int = 3):
        if size < 3:
            raise ValueError("size must be >= 3")
        self._n = size
        self._grid: List[List[Optional[PlayerSymbol]]] = [[None] * size for _ in range(size)]
        self._rows = [0] * size
        self._cols = [0] * size
        self._diag = 0
        self._anti = 0
        self._history: List[Position] = []
        self._winner: Optional[PlayerSymbol] = None

    @property
    def size(self) -> int:
        return self._n

    @property
    def history(self) -> List[Position]:
        return list(self._history)

    def cell(self, pos: Position) -> Optional[PlayerSymbol]:
        return self._grid[pos[0]][pos[1]]

    def is_valid_move(self, pos: Position) -> bool:
        r, c = pos
        return (self._winner is None and 0 <= r < self._n and 0 <= c < self._n
                and self._grid[r][c] is None)

    def place_move(self, pos: Position, symbol: PlayerSymbol) -> Optional[PlayerSymbol]:
        """Place a mark; returns the winner if this move completed a line."""
        if self._winner is not None:
            raise GameOverError(f"{self._winner.value} has already won")
        if not self.is_valid_move(pos):
            raise InvalidMoveError(f"Invalid move: {pos}")
        r, c = pos
        self._grid[r][c] = symbol
        self._history.append(pos)
        if self._bump(r, c, symbol.sign):
            self._winner = symbol
        return self._winner

    def undo_move(self) -> Position:
        """Reverse the most recent move."""
        if not self._history:
            raise GameError("No moves to undo")
        r, c = self._history.pop()
        symbol = self._grid[r][c]
        self._grid[r][c] = None
        self._bump(r, c, -symbol.sign)
        # Play stops at the first win, so only the last move can have produced one.
        self._winner = None
        return r, c

    def _bump(self, r: int, c: int, delta: int) -> bool:
        n = self._n
        self._rows[r] += delta
        self._cols[c] += delta
        if r == c:
            self._diag += delta
        if r + c == n - 1:
            self._anti += delta
        return (abs(self._rows[r]) == n or abs(self._cols[c]) == n
                or abs(self._diag) == n or abs(self._anti) == n)

    def get_available_moves(self) -> List[Position]:
        return [(r, c) for r in range(self._n) for c in range(self._n)
                if self._grid[r][c] is None]

    def is_full(self) -> bool:
        return len(self._history) == self._n * self._n

    def check_winner(self) -> Optional[PlayerSymbol]:
        return self._winner

    def key(self) -> Tuple[Optional[PlayerSymbol], ...]:
        return tuple(cell for row in self._grid for cell in row)

    def copy(self) -> "Board":
        clone = Board(self._n)
        for pos in self._history:
            clone.place_move(pos, self.cell(pos))
        return clone

    def render(self) -> str:
        header = "  " + "   ".join(str(c) for c in range(self._n))
        sep = "  " + "-" * (4 * self._n - 3)
        lines = [header]
        for r in range(self._n):
            row = [self._grid[r][c].value if self._grid[r][c] else " " for c in range(self._n)]
            lines.append(f"{r} {' | '.join(row)}")
            if r < self._n - 1:
                lines.append(sep)
        return "\n".join(lines)


# --- Players (Strategy) ---

class Player(ABC):
    def __init__(self, name: str, symbol: PlayerSymbol):
        self._name = name
        self._symbol = symbol

    @property
    def name(self) -> str:
        return self._name

    @property
    def symbol(self) -> PlayerSymbol:
        return self._symbol

    @abstractmethod
    def get_move(self, board: Board) -> Position:
        """Choose a move. `board` is a private copy; mutating it is harmless."""


class HumanPlayer(Player):
    """Reads 'row,col' from an injectable input function (stdin by default)."""

    def __init__(self, name: str, symbol: PlayerSymbol,
                 input_fn: Callable[[str], str] = input,
                 output_fn: Callable[[str], None] = print):
        super().__init__(name, symbol)
        self._input = input_fn
        self._output = output_fn

    def get_move(self, board: Board) -> Position:
        while True:
            raw = self._input(f"{self._name} ({self._symbol.value}), enter row,col: ")
            try:
                r, c = (int(x) for x in raw.split(","))
            except ValueError:
                self._output("Invalid input! Use format: row,col (e.g. 1,2)")
                continue
            if board.is_valid_move((r, c)):
                return r, c
            self._output("Cell already taken or off the board!")


class ScriptedPlayer(Player):
    """Plays a fixed list of moves. Deterministic demos and tests."""

    def __init__(self, name: str, symbol: PlayerSymbol, moves: Iterable[Position]):
        super().__init__(name, symbol)
        self._moves = list(moves)

    def get_move(self, board: Board) -> Position:
        while self._moves:
            move = self._moves.pop(0)
            if board.is_valid_move(move):
                return move
        raise GameError(f"{self._name} ran out of scripted moves")


class BotPlayer(Player):
    """Minimax with memoisation. Exact (unbeatable) on 3x3, where there are only
    5,478 reachable positions. For bigger boards pass max_depth to cap the search;
    unresolved positions then score 0 (a deliberately weak heuristic).

    Scores are from the bot's point of view: a win is worth 1 + empty cells left,
    so the bot prefers faster wins and slower losses. Ties go to the first move in
    row-major order, which keeps play deterministic."""

    def __init__(self, name: str, symbol: PlayerSymbol, max_depth: Optional[int] = None):
        super().__init__(name, symbol)
        self._max_depth = max_depth
        self._memo: Dict[tuple, int] = {}

    def get_move(self, board: Board) -> Position:
        best_score, best_move = None, None
        for move in board.get_available_moves():
            board.place_move(move, self._symbol)
            score = self._score(board, self._symbol.opponent(), 1)
            board.undo_move()
            if best_score is None or score > best_score:
                best_score, best_move = score, move
        if best_move is None:
            raise GameError("No moves available")
        return best_move

    def _score(self, board: Board, to_move: PlayerSymbol, depth: int) -> int:
        winner = board.check_winner()
        empty = board.size * board.size - len(board.history)
        if winner is not None:
            return (1 + empty) if winner is self._symbol else -(1 + empty)
        if empty == 0:
            return 0
        if self._max_depth is not None and depth >= self._max_depth:
            return 0
        key = (board.key(), to_move, None if self._max_depth is None else self._max_depth - depth)
        if key in self._memo:
            return self._memo[key]
        scores = []
        for move in board.get_available_moves():
            board.place_move(move, to_move)
            scores.append(self._score(board, to_move.opponent(), depth + 1))
            board.undo_move()
        result = max(scores) if to_move is self._symbol else min(scores)
        self._memo[key] = result
        return result


# --- Game (Facade) ---

class TicTacToeGame:
    """Turn order, status and winner. make_move() is the only mutator and is thread-safe."""

    def __init__(self, player1: Player, player2: Player, size: int = 3):
        if player1.symbol is player2.symbol:
            raise ValueError("Players need different symbols")
        self._players = (player1, player2)
        self._size = size
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self._board = Board(self._size)
        self._turn = 0                      # index into self._players
        self._status = GameStatus.IN_PROGRESS
        self._winner: Optional[Player] = None

    @property
    def status(self) -> GameStatus:
        return self._status

    @property
    def winner(self) -> Optional[Player]:
        return self._winner

    @property
    def current_player(self) -> Player:
        return self._players[self._turn]

    @property
    def board(self) -> Board:
        """A copy: callers can inspect it but cannot change the game."""
        with self._lock:
            return self._board.copy()

    def make_move(self, symbol: PlayerSymbol, pos: Position) -> GameStatus:
        with self._lock:
            if self._status is not GameStatus.IN_PROGRESS:
                raise GameOverError(f"Game is over: {self._status.value}")
            player = self._players[self._turn]
            if symbol is not player.symbol:
                raise NotYourTurnError(f"It is {player.symbol.value}'s turn")
            if self._board.place_move(pos, symbol) is not None:
                self._status, self._winner = GameStatus.WIN, player
            elif self._board.is_full():
                self._status = GameStatus.DRAW
            else:
                self._turn = 1 - self._turn
            return self._status

    def undo(self) -> Position:
        """Take back the last move (any status)."""
        with self._lock:
            pos = self._board.undo_move()
            if self._status is GameStatus.IN_PROGRESS:
                self._turn = 1 - self._turn
            self._status, self._winner = GameStatus.IN_PROGRESS, None
            return pos

    def play_turn(self) -> GameStatus:
        player = self.current_player
        move = player.get_move(self.board)          # the player sees a copy
        return self.make_move(player.symbol, move)

    def play(self, on_move: Optional[Callable[["TicTacToeGame"], None]] = None) -> GameStatus:
        while self._status is GameStatus.IN_PROGRESS:
            self.play_turn()
            if on_move:
                on_move(self)
        return self._status


# --- Demo ---

def _describe(game: TicTacToeGame) -> str:
    if game.status is GameStatus.WIN:
        return f"{game.winner.name} ({game.winner.symbol.value}) wins"
    return game.status.value


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Tic-tac-toe demo")
    parser.add_argument("--interactive", action="store_true",
                        help="play as X against the bot (reads stdin)")
    args = parser.parse_args(argv)

    if args.interactive:
        game = TicTacToeGame(HumanPlayer("You", PlayerSymbol.X), BotPlayer("Bot", PlayerSymbol.O))
        print(game.board.render())
        game.play(on_move=lambda g: print("\n" + g.board.render()))
        print(_describe(game))
        return

    print("=== Scripted X vs bot O: the bot blocks, then wins ===")
    game = TicTacToeGame(ScriptedPlayer("Alice", PlayerSymbol.X, [(0, 0), (0, 1), (2, 2), (1, 0)]),
                         BotPlayer("Bot", PlayerSymbol.O))
    game.play()
    print(game.board.render())
    print(f"Moves: {game.board.history} -> {_describe(game)}")

    try:
        game.make_move(PlayerSymbol.X, (2, 0))
    except GameOverError as e:
        print(f"Rejected: {e}")

    print("\n=== Bot vs bot (perfect play is a draw) ===")
    game = TicTacToeGame(BotPlayer("Bot X", PlayerSymbol.X), BotPlayer("Bot O", PlayerSymbol.O))
    game.play()
    print(game.board.render())
    print(f"Moves: {game.board.history} -> {_describe(game)}")

    print("\n=== 4x4, two humans via the API ===")
    game = TicTacToeGame(ScriptedPlayer("P1", PlayerSymbol.X, []),
                         ScriptedPlayer("P2", PlayerSymbol.O, []), size=4)
    for i in range(4):
        game.make_move(PlayerSymbol.X, (i, i))
        if game.status is GameStatus.IN_PROGRESS:
            game.make_move(PlayerSymbol.O, (i, 3 - i) if i != 3 - i else (0, 1))
    try:
        game.make_move(PlayerSymbol.O, (3, 3))
    except GameOverError as e:
        print(f"Rejected: {e}")
    print(game.board.render())
    print(_describe(game))


if __name__ == "__main__":
    main()
