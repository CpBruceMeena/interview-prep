"""
Snakes and Ladders Game - Low Level Design
-------------------------------------------
Design Principles: SOLID, Observer Pattern, Strategy Pattern
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Optional, Tuple
import random


class GameStatus(Enum):
    NOT_STARTED = "Not Started"
    IN_PROGRESS = "In Progress"
    FINISHED = "Finished"


class CellType(Enum):
    NORMAL = "Normal"
    SNAKE_HEAD = "Snake Head"
    SNAKE_TAIL = "Snake Tail"
    LADDER_BOTTOM = "Ladder Bottom"
    LADDER_TOP = "Ladder Top"


# --- Movement Strategy (Strategy Pattern - OCP) ---

class DiceStrategy(ABC):
    """Interface Segregation: Specific to dice rolling"""

    @abstractmethod
    def roll(self) -> int:
        pass


class StandardDice(DiceStrategy):
    def __init__(self, sides: int = 6):
        self._sides = sides

    def roll(self) -> int:
        return random.randint(1, self._sides)


class CrookedDice(DiceStrategy):
    """Always rolls even numbers - for testing"""
    def roll(self) -> int:
        return random.choice([2, 4, 6])


class DoubleDice(DiceStrategy):
    """Two dice - allows rolling doublets"""
    def __init__(self):
        self._die1 = StandardDice()
        self._die2 = StandardDice()

    def roll(self) -> int:
        return self._die1.roll() + self._die2.roll()


class MaxDice(DiceStrategy):
    """Always rolls the max value - for testing"""
    def __init__(self, sides: int = 6):
        self._sides = sides

    def roll(self) -> int:
        return self._sides


# --- Cell / Board (SRP) ---

class Cell:
    """Single Responsibility: Represents a single cell on the board"""

    def __init__(self, position: int):
        self._position = position
        self._cell_type = CellType.NORMAL
        self._destination: Optional[int] = None
        self._entity: Optional[str] = None

    @property
    def position(self) -> int:
        return self._position

    @property
    def cell_type(self) -> CellType:
        return self._cell_type

    @property
    def destination(self) -> Optional[int]:
        return self._destination

    def set_snake(self, tail: int) -> None:
        self._cell_type = CellType.SNAKE_HEAD
        self._destination = tail
        self._entity = f"Snake -> {tail}"

    def set_ladder(self, top: int) -> None:
        self._cell_type = CellType.LADDER_BOTTOM
        self._destination = top
        self._entity = f"Ladder -> {top}"

    def __str__(self) -> str:
        if self._cell_type == CellType.NORMAL:
            return f"[{self._position:2d}]"
        return f"[{self._position:2d}|{self._entity}]"


class Board:
    """Single Responsibility: Manages the board layout"""

    def __init__(self, size: int = 100):
        self._size = size
        self._cells: Dict[int, Cell] = {}
        self._snakes: Dict[int, int] = {}  # head -> tail
        self._ladders: Dict[int, int] = {}  # bottom -> top

        for i in range(1, size + 1):
            self._cells[i] = Cell(i)

    @property
    def size(self) -> int:
        return self._size

    def add_snake(self, head: int, tail: int) -> None:
        if head <= tail:
            raise ValueError(f"Snake head ({head}) must be above tail ({tail})")
        if head > self._size or tail < 1:
            raise ValueError(f"Snake positions must be within board (1-{self._size})")
        if self._cells[head].cell_type != CellType.NORMAL:
            raise ValueError(f"Cell {head} already occupied by {self._cells[head].cell_type}")

        self._cells[head].set_snake(tail)
        self._snakes[head] = tail

    def add_ladder(self, bottom: int, top: int) -> None:
        if bottom >= top:
            raise ValueError(f"Ladder bottom ({bottom}) must be below top ({top})")
        if bottom < 1 or top > self._size:
            raise ValueError(f"Ladder positions must be within board (1-{self._size})")
        if self._cells[bottom].cell_type != CellType.NORMAL:
            raise ValueError(f"Cell {bottom} already occupied")

        self._cells[bottom].set_ladder(top)
        self._ladders[bottom] = top

    def get_destination(self, position: int) -> int:
        """Get final position after snakes/ladders"""
        if position > self._size:
            return position - self._size  # Bounce back for overshoot

        cell = self._cells.get(position)
        if cell and cell.destination:
            dest = cell.destination
            return self.get_destination(dest)  # Chain snakes/ladders

        return position

    def display(self, players: Dict[str, int]) -> None:
        print(f"\n=== Board ({self._size} cells) ===")
        # Display snakes
        if self._snakes:
            print("Snakes:", ", ".join(f"{h}->{t}" for h, t in self._snakes.items()))
        if self._ladders:
            print("Ladders:", ", ".join(f"{b}->{t}" for b, t in self._ladders.items()))

        # Show player positions
        for player, pos in players.items():
            print(f"  {player}: Position {pos}")


# --- Player (SRP) ---

class Player:
    def __init__(self, name: str, color: str = "Blue"):
        self._name = name
        self._color = color
        self._position = 0
        self._finished = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def position(self) -> int:
        return self._position

    @position.setter
    def position(self, value: int) -> None:
        self._position = value

    @property
    def finished(self) -> bool:
        return self._finished

    @finished.setter
    def finished(self, value: bool) -> None:
        self._finished = value

    def reset(self) -> None:
        self._position = 0
        self._finished = False


# --- Observer Pattern for Notifications ---

class GameObserver(ABC):
    @abstractmethod
    def on_turn(self, player: Player, dice_value: int,
                old_pos: int, new_pos: int, message: str) -> None:
        pass

    @abstractmethod
    def on_game_over(self, winner: Player) -> None:
        pass


class ConsoleLogger(GameObserver):
    def on_turn(self, player: Player, dice_value: int,
                old_pos: int, new_pos: int, message: str) -> None:
        print(f"  {player.name} rolled {dice_value}: {old_pos} -> {new_pos} {message}")

    def on_game_over(self, winner: Player) -> None:
        print(f"\n🏆 {winner.name} wins the game!")


# --- Game Rules (SRP) ---

class GameRules:
    """Single Responsibility: Defines game rules"""

    def __init__(self, board_size: int, win_at_exact: bool = True):
        self._board_size = board_size
        self._win_at_exact = win_at_exact

    def check_win(self, position: int) -> bool:
        if self._win_at_exact:
            return position == self._board_size
        return position >= self._board_size

    def calculate_new_position(self, current: int, dice_value: int,
                               board: Board) -> Tuple[int, str]:
        new_pos = current + dice_value
        message = ""

        if new_pos > self._board_size and self._win_at_exact:
            # Bounce back or stay
            new_pos = self._board_size - (new_pos - self._board_size)
            if new_pos <= current:
                new_pos = current
                message = "(can't move, need exact roll)"
                return new_pos, message

        final_pos = board.get_destination(new_pos)

        if final_pos > new_pos:
            message = f"🐍 Oops! Snake from {new_pos} to {final_pos}!"
        elif final_pos < new_pos:
            message = f"🪜 Great! Ladder from {new_pos} to {final_pos}!"
        else:
            message = ""

        return final_pos, message


# --- Game (Facade) ---

class SnakeAndLadderGame:
    """Facade for the entire game"""

    def __init__(self, board_size: int = 100, dice: DiceStrategy = None):
        self._board = Board(board_size)
        self._dice = dice or StandardDice()
        self._rules = GameRules(board_size)
        self._players: List[Player] = []
        self._observers: List[GameObserver] = []
        self._current_player_index = 0
        self._status = GameStatus.NOT_STARTED

    @property
    def board(self) -> Board:
        return self._board

    @property
    def status(self) -> GameStatus:
        return self._status

    def add_observer(self, observer: GameObserver) -> None:
        self._observers.append(observer)

    def add_player(self, name: str, color: str = "Blue") -> Player:
        player = Player(name, color)
        self._players.append(player)
        return player

    def setup_default_board(self) -> None:
        # Add snakes
        snakes = [
            (99, 54), (95, 75), (93, 73), (87, 24), (74, 53),
            (64, 36), (62, 19), (56, 53), (49, 11), (47, 26),
            (28, 10), (16, 6),
        ]
        for head, tail in snakes:
            try:
                self._board.add_snake(head, tail)
            except ValueError:
                pass

        # Add ladders
        ladders = [
            (2, 38), (7, 14), (8, 31), (15, 26), (21, 42),
            (28, 84), (35, 44), (39, 60), (44, 65), (51, 67),
            (54, 93), (62, 81), (80, 100),
        ]
        for bottom, top in ladders:
            try:
                self._board.add_ladder(bottom, top)
            except ValueError:
                pass

    def play_turn(self) -> bool:
        """Returns True if game continues, False if game over"""
        player = self._players[self._current_player_index]

        dice_value = self._dice.roll()
        old_pos = player.position
        new_pos, message = self._rules.calculate_new_position(old_pos, dice_value, self._board)

        player.position = new_pos

        # Notify observers
        for obs in self._observers:
            obs.on_turn(player, dice_value, old_pos, new_pos, message)

        # Check win
        if self._rules.check_win(new_pos):
            player.finished = True
            self._status = GameStatus.FINISHED
            for obs in self._observers:
                obs.on_game_over(player)
            return False

        # Check for extra turn (double dice roll)
        if isinstance(self._dice, DoubleDice) and dice_value % 2 == 0:
            print(f"  {player.name} rolled doubles! Extra turn!")
        else:
            self._current_player_index = (self._current_player_index + 1) % len(self._players)

        return True

    def play(self) -> None:
        self._status = GameStatus.IN_PROGRESS
        print("=== Snakes and Ladders ===")
        self._board.display({p.name: p.position for p in self._players})

        print("\n--- Game Start! ---")
        while self._status == GameStatus.IN_PROGRESS:
            if not self.play_turn():
                break

    def reset(self) -> None:
        for player in self._players:
            player.reset()
        self._current_player_index = 0
        self._status = GameStatus.NOT_STARTED


# --- Demo ---

def demo():
    game = SnakeAndLadderGame(100)
    game.add_observer(ConsoleLogger())

    # Add players
    game.add_player("Alice", "Red")
    game.add_player("Bob", "Blue")

    # Setup board
    game.setup_default_board()

    # Use fixed dice for predictable demo
    game._dice = MaxDice()

    # Play a few turns
    print("=== Snakes and Ladders Demo ===")
    print("Using Max Dice for demo purposes\n")

    game._status = GameStatus.IN_PROGRESS
    game.board.display({p.name: p.position for p in game._players})

    for _ in range(5):  # Play 5 turns
        if not game.play_turn():
            break


if __name__ == "__main__":
    demo()
