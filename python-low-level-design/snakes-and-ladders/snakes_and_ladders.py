"""
Snakes and Ladders - Low Level Design
-------------------------------------
Extension points (each is a small ABC or Enum, swapped in through the
constructor, never by editing Game):

    Dice              -> how a roll is produced (count, sides, rigged, scripted)
    OvershootPolicy   -> what happens when a roll goes past the last cell
    GameObserver      -> who hears about turns (console, websocket, achievements)

Board rules enforced at construction time, so the game loop never has to
defend against a bad board:
    * every jump starts and ends on the board, start != end
    * the last cell can't hold a jump start (otherwise nobody could win)
    * a cell holds at most one jump start
    * no chaining: a jump may not end where another jump starts. That rules
      out cycles (snake 50->20 + ladder 20->50) and keeps resolution O(1).

Thread-safety: Game.play_turn() is serialised by one lock per game, so two
concurrent requests (two clients, a retry racing the original) can't both
move. Passing player_name makes the call "act as this player", which rejects
out-of-turn and duplicate requests instead of moving the wrong token.
"""

from __future__ import annotations

import random
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional, Sequence


# --- Errors ---------------------------------------------------------------

class GameError(Exception):
    """Base class for rule violations raised by the game."""


class InvalidBoardError(GameError, ValueError):
    pass


class NotYourTurnError(GameError):
    pass


class GameOverError(GameError):
    pass


# --- Enums ----------------------------------------------------------------

class GameStatus(Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


class JumpKind(Enum):
    SNAKE = "snake"
    LADDER = "ladder"


class OvershootPolicy(Enum):
    STAY = "stay"        # roll past the end -> don't move (classic "exact roll")
    BOUNCE = "bounce"    # 98 + 5 -> 100, then back 3 -> 97
    ALLOW = "allow"      # any roll that reaches or passes the end wins


# --- Dice (Strategy) ------------------------------------------------------

@dataclass(frozen=True)
class Roll:
    faces: tuple[int, ...]

    @property
    def total(self) -> int:
        return sum(self.faces)

    @property
    def is_doubles(self) -> bool:
        return len(self.faces) > 1 and len(set(self.faces)) == 1


class Dice(ABC):
    @abstractmethod
    def roll(self) -> Roll: ...


class StandardDice(Dice):
    """`count` fair dice with `sides` faces. Pass a seeded Random for replays."""

    def __init__(self, count: int = 1, sides: int = 6,
                 rng: Optional[random.Random] = None):
        if count < 1 or sides < 2:
            raise ValueError("need at least one die with at least two sides")
        self._count = count
        self._sides = sides
        self._rng = rng or random.Random()

    def roll(self) -> Roll:
        return Roll(tuple(self._rng.randint(1, self._sides) for _ in range(self._count)))


class CrookedDice(Dice):
    """A single die that only shows even faces (a classic 'add a variant' ask)."""

    def __init__(self, rng: Optional[random.Random] = None):
        self._rng = rng or random.Random()

    def roll(self) -> Roll:
        return Roll((self._rng.choice((2, 4, 6)),))


class ScriptedDice(Dice):
    """Replays a fixed sequence of rolls. For tests, demos and replays."""

    def __init__(self, rolls: Iterable[int | Sequence[int]]):
        self._rolls = [tuple(r) if isinstance(r, Sequence) else (r,) for r in rolls]
        self._next = 0

    def roll(self) -> Roll:
        if self._next >= len(self._rolls):
            raise RuntimeError("ScriptedDice ran out of rolls")
        faces = self._rolls[self._next]
        self._next += 1
        return Roll(faces)


# --- Board ----------------------------------------------------------------

@dataclass(frozen=True)
class Jump:
    start: int
    end: int

    @property
    def kind(self) -> JumpKind:
        return JumpKind.SNAKE if self.end < self.start else JumpKind.LADDER


class Board:
    """Cells 1..size. Players start off-board at 0. Immutable after build."""

    def __init__(self, size: int = 100,
                 snakes: Iterable[tuple[int, int]] = (),
                 ladders: Iterable[tuple[int, int]] = ()):
        if size < 2:
            raise InvalidBoardError("board needs at least 2 cells")
        self._size = size
        self._jumps: dict[int, Jump] = {}   # start cell -> jump
        for head, tail in snakes:
            if head <= tail:
                raise InvalidBoardError(f"snake {head}->{tail} must go down")
            self._add(Jump(head, tail))
        for bottom, top in ladders:
            if bottom >= top:
                raise InvalidBoardError(f"ladder {bottom}->{top} must go up")
            self._add(Jump(bottom, top))
        ends = {j.end for j in self._jumps.values()}
        chained = sorted(ends & self._jumps.keys())
        if chained:
            raise InvalidBoardError(f"jumps may not end on another jump's start: {chained}")

    def _add(self, jump: Jump) -> None:
        for cell in (jump.start, jump.end):
            if not 1 <= cell <= self._size:
                raise InvalidBoardError(f"{jump} is off the board (1..{self._size})")
        if jump.start == self._size:
            raise InvalidBoardError(f"cell {self._size} is the goal; no jump may start there")
        if jump.start in self._jumps:
            raise InvalidBoardError(f"cell {jump.start} already has {self._jumps[jump.start]}")
        self._jumps[jump.start] = jump

    @property
    def size(self) -> int:
        return self._size

    def jump_at(self, cell: int) -> Optional[Jump]:
        return self._jumps.get(cell)

    def resolve(self, cell: int) -> int:
        """Final cell after taking the (at most one) jump starting at `cell`."""
        jump = self._jumps.get(cell)
        return jump.end if jump else cell

    def jumps(self, kind: JumpKind) -> list[Jump]:
        return sorted((j for j in self._jumps.values() if j.kind is kind),
                      key=lambda j: j.start)


def default_board() -> Board:
    """A valid 10x10 layout (no chains, nothing on 100)."""
    return Board(
        100,
        snakes=[(99, 54), (95, 75), (92, 73), (87, 24), (74, 53), (64, 36),
                (62, 19), (56, 33), (49, 11), (47, 26), (16, 6)],
        ladders=[(2, 38), (7, 14), (8, 31), (15, 26), (21, 42), (28, 84),
                 (37, 44), (51, 67), (71, 91), (78, 98)],
    )


# --- Players, turns, observers --------------------------------------------

@dataclass
class Player:
    name: str
    position: int = 0


@dataclass(frozen=True)
class TurnResult:
    turn_no: int
    player: str
    roll: Roll
    start: int
    landed: int                 # cell reached by the dice, before any jump
    end: int                    # final cell after the jump
    jump: Optional[Jump]
    forfeited: bool             # too many consecutive doubles: no move
    extra_turn: bool
    won: bool


class GameObserver:
    """Override what you need. Called under the game lock, in turn order,
    so keep handlers fast (enqueue, don't do I/O)."""

    def on_turn(self, result: TurnResult) -> None:
        pass

    def on_game_over(self, winner: Player) -> None:
        pass


class ConsoleLogger(GameObserver):
    def on_turn(self, r: TurnResult) -> None:
        faces = "+".join(map(str, r.roll.faces))
        if r.forfeited:
            note = "third doubles in a row, turn forfeited"
        elif r.jump and r.jump.kind is JumpKind.SNAKE:
            note = f"snake {r.jump.start}->{r.jump.end}"
        elif r.jump:
            note = f"ladder {r.jump.start}->{r.jump.end}"
        elif r.landed == r.start:
            note = "overshoot, stays"
        elif r.landed != r.start + r.roll.total:
            note = "overshoot, bounced back"
        else:
            note = ""
        extra = " (extra turn)" if r.extra_turn else ""
        print(f"  #{r.turn_no:<3} {r.player:<6} rolled {faces:<5} "
              f"{r.start:>3} -> {r.end:<3} {note}{extra}")

    def on_game_over(self, winner: Player) -> None:
        print(f"  {winner.name} wins!")


# --- Game -----------------------------------------------------------------

class Game:
    def __init__(self, board: Board, player_names: Sequence[str],
                 dice: Optional[Dice] = None,
                 overshoot: OvershootPolicy = OvershootPolicy.STAY,
                 extra_turn_on_doubles: bool = True,
                 max_consecutive_doubles: int = 3):
        if len(player_names) < 2:
            raise ValueError("need at least two players")
        if len(set(player_names)) != len(player_names):
            raise ValueError("player names must be unique")
        self._board = board
        self._players = [Player(n) for n in player_names]
        self._dice = dice or StandardDice()
        self._overshoot = overshoot
        self._extra_turn_on_doubles = extra_turn_on_doubles
        self._max_doubles = max_consecutive_doubles
        self._observers: list[GameObserver] = []

        self._lock = threading.Lock()
        self._status = GameStatus.NOT_STARTED
        self._current = 0
        self._doubles_streak = 0
        self._winner: Optional[Player] = None
        self._history: list[TurnResult] = []

    # -- queries (snapshots, safe to call from any thread) --
    @property
    def status(self) -> GameStatus:
        return self._status

    @property
    def winner(self) -> Optional[str]:
        return self._winner.name if self._winner else None

    @property
    def current_player(self) -> str:
        return self._players[self._current].name

    def positions(self) -> dict[str, int]:
        with self._lock:
            return {p.name: p.position for p in self._players}

    def history(self) -> list[TurnResult]:
        with self._lock:
            return list(self._history)

    def add_observer(self, observer: GameObserver) -> None:
        self._observers.append(observer)

    # -- commands --
    def play_turn(self, player_name: Optional[str] = None) -> TurnResult:
        """Roll and move for the current player.

        player_name, if given, must be the current player; otherwise
        NotYourTurnError. That check and the move are one critical section,
        so a duplicate/late request can never move a token out of turn.
        """
        with self._lock:
            if self._status is GameStatus.FINISHED:
                raise GameOverError(f"game already won by {self._winner.name}")
            player = self._players[self._current]
            if player_name is not None and player_name != player.name:
                raise NotYourTurnError(f"it is {player.name}'s turn, not {player_name}'s")
            self._status = GameStatus.IN_PROGRESS

            roll = self._dice.roll()
            start = player.position
            self._doubles_streak = self._doubles_streak + 1 if roll.is_doubles else 0
            forfeited = self._doubles_streak >= self._max_doubles

            if forfeited:
                landed = end = start
                jump = None
            else:
                landed = self._advance(start, roll.total)
                jump = self._board.jump_at(landed) if landed != start else None
                end = self._board.resolve(landed) if jump else landed
            player.position = end
            won = end == self._board.size

            extra = (self._extra_turn_on_doubles and roll.is_doubles
                     and not forfeited and not won)
            if not extra:
                self._doubles_streak = 0
                self._current = (self._current + 1) % len(self._players)

            result = TurnResult(len(self._history) + 1, player.name, roll, start,
                                landed, end, jump, forfeited, extra, won)
            self._history.append(result)
            for obs in self._observers:
                obs.on_turn(result)
            if won:
                self._status = GameStatus.FINISHED
                self._winner = player
                for obs in self._observers:
                    obs.on_game_over(player)
            return result

    def play(self, max_turns: int = 10_000) -> str:
        """Play to completion; returns the winner's name.
        max_turns guards against a board/dice combo that never finishes."""
        for _ in range(max_turns):
            if self.play_turn().won:
                return self._winner.name
        raise RuntimeError(f"no winner after {max_turns} turns")

    def _advance(self, start: int, steps: int) -> int:
        size = self._board.size
        target = start + steps
        if target <= size:
            return target
        if self._overshoot is OvershootPolicy.STAY:
            return start
        if self._overshoot is OvershootPolicy.BOUNCE:
            return size - (target - size)
        return size  # ALLOW


# --- Demo -----------------------------------------------------------------

def demo() -> None:
    print("=== Scripted rules walkthrough (10-cell board) ===")
    small = Board(10, snakes=[(9, 2)], ladders=[(3, 7)])
    game = Game(small, ["Alice", "Bob"],
                dice=ScriptedDice([3, (2, 2), 1, 4, 2, 5, 1, 2]))
    game.add_observer(ConsoleLogger())
    # Alice 0->3 ladder->7; Bob doubles 0->4 extra turn, then 4->5;
    # Alice 7+4 overshoots, stays; Bob 5->7; Alice 7+5 overshoots;
    # Bob 7->8; Alice 7->9 snake->2.
    for _ in range(8):
        game.play_turn()
    print("  positions:", game.positions())

    print("\n=== Seeded full game (default 100-cell board, two dice) ===")
    game = Game(default_board(), ["Alice", "Bob", "Carol"],
                dice=StandardDice(count=2, rng=random.Random(7)),
                overshoot=OvershootPolicy.BOUNCE)
    game.add_observer(ConsoleLogger())
    winner = game.play()
    print(f"  winner={winner} after {len(game.history())} turns")


if __name__ == "__main__":
    demo()
