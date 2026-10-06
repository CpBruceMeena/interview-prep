import random
import threading
import unittest

from snakes_and_ladders import (
    Board, CrookedDice, Game, GameObserver, GameOverError, GameStatus,
    InvalidBoardError, JumpKind, NotYourTurnError, OvershootPolicy,
    ScriptedDice, StandardDice, default_board,
)


def small_board() -> Board:
    return Board(10, snakes=[(9, 2)], ladders=[(3, 7)])


class BoardTest(unittest.TestCase):
    def test_default_board_is_valid(self):
        b = default_board()
        self.assertEqual(b.size, 100)
        self.assertEqual(len(b.jumps(JumpKind.SNAKE)), 11)
        self.assertEqual(len(b.jumps(JumpKind.LADDER)), 10)

    def test_resolve(self):
        b = small_board()
        self.assertEqual(b.resolve(3), 7)
        self.assertEqual(b.resolve(9), 2)
        self.assertEqual(b.resolve(5), 5)

    def test_rejects_bad_jumps(self):
        bad = [
            dict(snakes=[(3, 5)]),                  # snake going up
            dict(ladders=[(5, 3)]),                 # ladder going down
            dict(ladders=[(5, 11)]),                # off board
            dict(snakes=[(10, 4)]),                 # head on the goal cell
            dict(snakes=[(6, 2)], ladders=[(6, 8)]),  # two jumps on one cell
            dict(snakes=[(8, 4)], ladders=[(4, 8)]),  # cycle 4->8->4
            dict(ladders=[(2, 5), (5, 8)]),         # chain
        ]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(InvalidBoardError):
                Board(10, **kwargs)


class DiceTest(unittest.TestCase):
    def test_doubles_need_matching_faces_not_even_sum(self):
        dice = ScriptedDice([(1, 3), (2, 2), 4])
        r1, r2, r3 = dice.roll(), dice.roll(), dice.roll()
        self.assertEqual(r1.total, 4)
        self.assertFalse(r1.is_doubles)
        self.assertTrue(r2.is_doubles)
        self.assertFalse(r3.is_doubles)  # a single die is never doubles

    def test_seeded_dice_are_reproducible(self):
        a = StandardDice(2, rng=random.Random(1))
        b = StandardDice(2, rng=random.Random(1))
        self.assertEqual([a.roll() for _ in range(20)], [b.roll() for _ in range(20)])

    def test_crooked_dice_only_even(self):
        d = CrookedDice(rng=random.Random(3))
        self.assertTrue(all(d.roll().total in (2, 4, 6) for _ in range(100)))


class GameRulesTest(unittest.TestCase):
    def game(self, rolls, **kw):
        return Game(small_board(), ["A", "B"], dice=ScriptedDice(rolls), **kw)

    def test_ladder_and_snake(self):
        g = self.game([3, 1, 2, 1])
        r = g.play_turn()
        self.assertEqual((r.landed, r.end, r.jump.kind), (3, 7, JumpKind.LADDER))
        g.play_turn()
        r = g.play_turn()
        self.assertEqual((r.landed, r.end, r.jump.kind), (9, 2, JumpKind.SNAKE))

    def test_overshoot_policies(self):
        cases = {OvershootPolicy.STAY: 8, OvershootPolicy.BOUNCE: 6,
                 OvershootPolicy.ALLOW: 10}
        for policy, expected in cases.items():
            with self.subTest(policy=policy):
                g = Game(Board(10), ["A", "B"], dice=ScriptedDice([8, 1, 6]),
                         overshoot=policy)
                g.play_turn(); g.play_turn()
                self.assertEqual(g.play_turn().end, expected)

    def test_bounce_can_land_on_snake(self):
        g = self.game([5, 1, 6], overshoot=OvershootPolicy.BOUNCE)
        g.play_turn(); g.play_turn()
        r = g.play_turn()  # 5 + 6 = 11 -> bounce to 9 -> snake to 2
        self.assertEqual((r.landed, r.end), (9, 2))

    def test_exact_roll_wins_and_game_ends(self):
        g = self.game([4, 1, 6])
        g.play_turn(); g.play_turn()
        r = g.play_turn()
        self.assertTrue(r.won)
        self.assertEqual(g.status, GameStatus.FINISHED)
        self.assertEqual(g.winner, "A")
        with self.assertRaises(GameOverError):
            g.play_turn()

    def test_doubles_extra_turn_and_third_double_forfeits(self):
        g = Game(Board(30), ["A", "B"], dice=ScriptedDice([(1, 1), (2, 2), (3, 3), 1]))
        self.assertTrue(g.play_turn().extra_turn)      # A: 0 -> 2
        self.assertTrue(g.play_turn().extra_turn)      # A: 2 -> 6
        r = g.play_turn()                              # A: third doubles
        self.assertTrue(r.forfeited)
        self.assertEqual(r.end, 6)
        self.assertEqual(g.current_player, "B")
        self.assertEqual(g.play_turn().player, "B")

    def test_winning_on_doubles_gives_no_extra_turn(self):
        g = Game(Board(10), ["A", "B"], dice=ScriptedDice([(5, 5)]))
        r = g.play_turn()
        self.assertTrue(r.won)
        self.assertFalse(r.extra_turn)

    def test_not_your_turn(self):
        g = self.game([1, 1])
        with self.assertRaises(NotYourTurnError):
            g.play_turn("B")
        self.assertEqual(g.play_turn("A").player, "A")
        self.assertEqual(g.play_turn("B").player, "B")

    def test_needs_two_unique_players(self):
        with self.assertRaises(ValueError):
            Game(small_board(), ["A"])
        with self.assertRaises(ValueError):
            Game(small_board(), ["A", "A"])

    def test_observer_sees_every_turn_and_winner(self):
        seen, winners = [], []

        class Rec(GameObserver):
            def on_turn(self, r): seen.append(r.turn_no)
            def on_game_over(self, w): winners.append(w.name)

        g = Game(default_board(), ["A", "B"], dice=StandardDice(rng=random.Random(5)))
        g.add_observer(Rec())
        winner = g.play()
        self.assertEqual(seen, list(range(1, len(g.history()) + 1)))
        self.assertEqual(winners, [winner])


class ConcurrencyTest(unittest.TestCase):
    def test_concurrent_turn_requests_keep_strict_turn_order(self):
        players = [f"P{i}" for i in range(4)]
        # single die: no doubles, so the order must be strictly round-robin
        g = Game(default_board(), players, dice=StandardDice(rng=random.Random(11)),
                 overshoot=OvershootPolicy.BOUNCE)
        rejected = [0]
        count_lock = threading.Lock()

        def client(name: str):
            # Each client hammers "roll for me"; only in-turn requests succeed.
            while True:
                try:
                    g.play_turn(name)
                except NotYourTurnError:
                    with count_lock:
                        rejected[0] += 1
                except GameOverError:
                    return

        threads = [threading.Thread(target=client, args=(p,)) for p in players]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        self.assertFalse(any(t.is_alive() for t in threads))

        hist = g.history()
        self.assertEqual(g.status, GameStatus.FINISHED)
        for i, r in enumerate(hist):
            self.assertEqual(r.turn_no, i + 1)
            self.assertEqual(r.player, players[i % len(players)])
        # every turn starts where that player's previous turn ended
        last = {p: 0 for p in players}
        for r in hist:
            self.assertEqual(r.start, last[r.player])
            last[r.player] = r.end
        self.assertEqual(last, g.positions())
        self.assertEqual(sum(r.won for r in hist), 1)


if __name__ == "__main__":
    unittest.main()
