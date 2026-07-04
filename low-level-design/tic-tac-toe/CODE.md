# Tic-Tac-Toe — Implementation

> Python implementation of the Tic-Tac-Toe system following SOLID principles and design patterns.

```python
"""
Tic-Tac-Toe Game - Low Level Design
-------------------------------------
Design Principles: SOLID, Strategy Pattern
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional, Tuple


class PlayerSymbol(Enum):
    X = "X"
    O = "O"

    def opponent(self) -> 'PlayerSymbol':
        return PlayerSymbol.O if self == PlayerSymbol.X else PlayerSymbol.X


# --- Player Hierarchy (OCP / LSP) ---

class Player(ABC):
    """Abstract player - follows Liskov Substitution Principle"""

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
    def get_move(self, board: 'Board') -> Tuple[int, int]:
        """Each player type implements their move strategy"""
        pass


class HumanPlayer(Player):
    def get_move(self, board: 'Board') -> Tuple[int, int]:
        while True:
            try:
                inp = input(f"{self._name} ({self._symbol.value}), enter row,col (0-2): ")
                r, c = map(int, inp.split(","))
                if board.is_valid_move((r, c)):
                    return (r, c)
                print("Cell already taken or invalid!")
            except (ValueError, IndexError):
                print("Invalid input! Use format: row,col (e.g., 1,2)")


class BotPlayer(Player):
    """Simple AI using minimax"""

    def get_move(self, board: 'Board') -> Tuple[int, int]:
        _, move = self._minimax(board, self._symbol, True)
        return move

    def _minimax(self, board: 'Board', symbol: PlayerSymbol,
                 is_maximizing: bool) -> Tuple[int, Optional[Tuple[int, int]]]:
        winner = board.check_winner()
        if winner == self._symbol:
            return (1, None)
        elif winner == self._symbol.opponent():
            return (-1, None)
        elif board.is_full():
            return (0, None)

        if is_maximizing:
            best_score = float('-inf')
            best_move = None
            for move in board.get_available_moves():
                board.place_move(move, self._symbol)
                score, _ = self._minimax(board, self._symbol, False)
                board.undo_move(move)
                if score > best_score:
                    best_score = score
                    best_move = move
            return (best_score, best_move)
        else:
            best_score = float('inf')
            best_move = None
            for move in board.get_available_moves():
                board.place_move(move, self._symbol.opponent())
                score, _ = self._minimax(board, self._symbol, True)
                board.undo_move(move)
                if score < best_score:
                    best_score = score
                    best_move = move
            return (best_score, best_move)


# --- Board (SRP) ---

class Board:
    """Single Responsibility: Manages the 3x3 grid and game state"""

    def __init__(self):
        self._grid: List[List[Optional[PlayerSymbol]]] = [[None] * 3 for _ in range(3)]
        self._move_history: List[Tuple[int, int]] = []

    def is_valid_move(self, pos: Tuple[int, int]) -> bool:
        r, c = pos
        return 0 <= r < 3 and 0 <= c < 3 and self._grid[r][c] is None

    def place_move(self, pos: Tuple[int, int], symbol: PlayerSymbol) -> None:
        if not self.is_valid_move(pos):
            raise ValueError(f"Invalid move: {pos}")
        r, c = pos
        self._grid[r][c] = symbol
        self._move_history.append(pos)

    def undo_move(self, pos: Tuple[int, int]) -> None:
        r, c = pos
        self._grid[r][c] = None

    def get_available_moves(self) -> List[Tuple[int, int]]:
        moves = []
        for r in range(3):
            for c in range(3):
                if self._grid[r][c] is None:
                    moves.append((r, c))
        return moves

    def is_full(self) -> bool:
        return len(self.get_available_moves()) == 0

    def check_winner(self) -> Optional[PlayerSymbol]:
        # Rows & Columns
        for i in range(3):
            if self._grid[i][0] and self._grid[i][0] == self._grid[i][1] == self._grid[i][2]:
                return self._grid[i][0]
            if self._grid[0][i] and self._grid[0][i] == self._grid[1][i] == self._grid[2][i]:
                return self._grid[0][i]
        # Diagonals
        if self._grid[0][0] and self._grid[0][0] == self._grid[1][1] == self._grid[2][2]:
            return self._grid[0][0]
        if self._grid[0][2] and self._grid[0][2] == self._grid[1][1] == self._grid[2][0]:
            return self._grid[0][2]
        return None

    def display(self) -> None:
        print("\n  0   1   2")
        for r in range(3):
            row = [str(self._grid[r][c]) if self._grid[r][c] else " " for c in range(3)]
            print(f"{r} {' | '.join(row)}")
            if r < 2:
                print("  ---------")


# --- Game (Facade / State Pattern) ---

class GameStatus(Enum):
    IN_PROGRESS = "In Progress"
    WIN = "Win"
    DRAW = "Draw"


class TicTacToeGame:
    """Facade for the game"""

    def __init__(self, player1: Player, player2: Player):
        self._board = Board()
        self._player1 = player1
        self._player2 = player2
        self._current_player = player1
        self._status = GameStatus.IN_PROGRESS

    @property
    def status(self) -> GameStatus:
        return self._status

    def play_turn(self) -> None:
        self._board.display()
        move = self._current_player.get_move(self._board)
        self._board.place_move(move, self._current_player.symbol)

        winner = self._board.check_winner()
        if winner:
            self._status = GameStatus.WIN
            self._board.display()
            print(f"\n🎉 {self._current_player.name} wins!")
        elif self._board.is_full():
            self._status = GameStatus.DRAW
            self._board.display()
            print("\n🤝 It's a draw!")
        else:
            self._current_player = (self._player2
                                     if self._current_player == self._player1
                                     else self._player1)

    def play(self) -> None:
        print("=== Tic-Tac-Toe ===")
        while self._status == GameStatus.IN_PROGRESS:
            self.play_turn()

    def reset(self) -> None:
        self._board = Board()
        self._current_player = self._player1
        self._status = GameStatus.IN_PROGRESS


# --- Demo ---

if __name__ == "__main__":
    human = HumanPlayer("Alice", PlayerSymbol.X)
    bot = BotPlayer("Bot", PlayerSymbol.O)
    game = TicTacToeGame(human, bot)
    game.play()
```

---

## ▶️ How to Run

```bash
cd low-level-design/tic-tac-toe
python tic_tac_toe.py
```

## 🧩 Design Patterns

See the [Interview Questions](INTERVIEW_QUESTIONS.md) for a detailed breakdown of design patterns and SOLID principles applied in this implementation.
