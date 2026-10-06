import threading
import unittest

from tic_tac_toe import (
    Board, BotPlayer, GameError, GameOverError, GameStatus, HumanPlayer,
    InvalidMoveError, NotYourTurnError, PlayerSymbol, ScriptedPlayer,
    TicTacToeGame, main,
)

X, O = PlayerSymbol.X, PlayerSymbol.O


def lines(n):
    rows = [[(r, c) for c in range(n)] for r in range(n)]
    cols = [[(r, c) for r in range(n)] for c in range(n)]
    diags = [[(i, i) for i in range(n)], [(i, n - 1 - i) for i in range(n)]]
    return rows + cols + diags


class BoardTest(unittest.TestCase):
    def test_every_line_wins_for_both_symbols(self):
        for n in (3, 4, 5):
            for line in lines(n):
                for sym in (X, O):
                    b = Board(n)
                    results = [b.place_move(p, sym) for p in line]
                    self.assertEqual(results[-1], sym, f"n={n} {line}")
                    self.assertTrue(all(r is None for r in results[:-1]))

    def test_mixed_line_is_not_a_win(self):
        b = Board()
        b.place_move((0, 0), X)
        b.place_move((0, 1), O)
        self.assertIsNone(b.place_move((0, 2), X))

    def test_invalid_moves(self):
        b = Board()
        b.place_move((1, 1), X)
        for bad in [(1, 1), (3, 0), (-1, 0), (0, 3)]:
            with self.assertRaises(InvalidMoveError):
                b.place_move(bad, O)

    def test_no_moves_after_win(self):
        b = Board()
        for p in [(0, 0), (0, 1), (0, 2)]:
            b.place_move(p, X)
        with self.assertRaises(GameOverError):
            b.place_move((2, 2), O)

    def test_undo_restores_everything(self):
        b = Board()
        for p in [(0, 0), (0, 1)]:
            b.place_move(p, X)
        self.assertEqual(b.place_move((0, 2), X), X)
        self.assertEqual(b.undo_move(), (0, 2))
        self.assertIsNone(b.check_winner())
        self.assertEqual(b.history, [(0, 0), (0, 1)])
        self.assertIsNone(b.place_move((0, 2), O))   # counters really were reversed
        with self.assertRaises(GameError):
            Board().undo_move()

    def test_full_board(self):
        b = Board()
        for p, s in zip([(0, 0), (0, 1), (0, 2), (1, 1), (1, 0), (1, 2), (2, 1), (2, 0), (2, 2)],
                        [X, O, X, O, O, X, X, X, O]):
            b.place_move(p, s)
        self.assertTrue(b.is_full())
        self.assertIsNone(b.check_winner())

    def test_copy_is_independent(self):
        b = Board()
        b.place_move((0, 0), X)
        c = b.copy()
        c.place_move((1, 1), O)
        self.assertIsNone(b.cell((1, 1)))
        self.assertEqual(c.history, [(0, 0), (1, 1)])


class GameTest(unittest.TestCase):
    def scripted(self, xs, os, size=3):
        return TicTacToeGame(ScriptedPlayer("A", X, xs), ScriptedPlayer("B", O, os), size)

    def test_win_and_draw(self):
        g = self.scripted([(0, 0), (0, 1), (0, 2)], [(1, 0), (1, 1)])
        self.assertEqual(g.play(), GameStatus.WIN)
        self.assertEqual(g.winner.name, "A")
        g = self.scripted([(0, 0), (0, 2), (1, 2), (2, 0), (2, 1)],
                          [(0, 1), (1, 1), (1, 0), (2, 2)])
        self.assertEqual(g.play(), GameStatus.DRAW)
        self.assertIsNone(g.winner)

    def test_turn_order_enforced(self):
        g = self.scripted([], [])
        with self.assertRaises(NotYourTurnError):
            g.make_move(O, (0, 0))
        g.make_move(X, (0, 0))
        with self.assertRaises(NotYourTurnError):
            g.make_move(X, (1, 1))
        with self.assertRaises(InvalidMoveError):
            g.make_move(O, (0, 0))
        self.assertIs(g.current_player.symbol, O)   # failed move didn't advance the turn

    def test_moves_after_game_over_rejected(self):
        g = self.scripted([(0, 0), (1, 1), (2, 2)], [(0, 1), (0, 2)])
        g.play()
        with self.assertRaises(GameOverError):
            g.make_move(O, (2, 0))

    def test_undo_reopens_finished_game(self):
        g = self.scripted([(0, 0), (1, 1), (2, 2)], [(0, 1), (0, 2)])
        g.play()
        g.undo()
        self.assertEqual(g.status, GameStatus.IN_PROGRESS)
        self.assertIs(g.current_player.symbol, X)
        g.make_move(X, (2, 2))
        self.assertEqual(g.status, GameStatus.WIN)

    def test_board_property_is_a_copy(self):
        g = self.scripted([], [])
        g.board.place_move((0, 0), X)
        self.assertIsNone(g.board.cell((0, 0)))

    def test_same_symbol_rejected(self):
        with self.assertRaises(ValueError):
            TicTacToeGame(ScriptedPlayer("A", X, []), ScriptedPlayer("B", X, []))

    def test_human_player_retries_bad_input(self):
        answers = iter(["oops", "5,5", "1,1"])
        out = []
        h = HumanPlayer("H", X, input_fn=lambda _: next(answers), output_fn=out.append)
        self.assertEqual(h.get_move(Board()), (1, 1))
        self.assertEqual(len(out), 2)

    def test_demo_runs_without_stdin(self):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            main([])
        self.assertIn("Draw", buf.getvalue())


class BotTest(unittest.TestCase):
    def test_takes_immediate_win_over_block(self):
        b = Board()
        for p, s in [((0, 0), O), ((1, 0), X), ((0, 1), O), ((1, 1), X)]:
            b.place_move(p, s)
        self.assertEqual(BotPlayer("bot", O).get_move(b), (0, 2))

    def test_blocks(self):
        b = Board()
        for p, s in [((0, 0), X), ((1, 1), O), ((0, 1), X)]:
            b.place_move(p, s)
        self.assertEqual(BotPlayer("bot", O).get_move(b), (0, 2))

    def test_bot_vs_bot_draws(self):
        g = TicTacToeGame(BotPlayer("x", X), BotPlayer("o", O))
        self.assertEqual(g.play(), GameStatus.DRAW)

    def test_bot_never_loses_against_any_opponent(self):
        """Exhaustively try every opponent move at every turn, bot as X and as O."""
        for bot_symbol in (X, O):
            bot = BotPlayer("bot", bot_symbol)
            losses = []

            def explore(board, to_move):
                if board.check_winner() is not None or board.is_full():
                    if board.check_winner() is bot_symbol.opponent():
                        losses.append(board.history)
                    return
                if to_move is bot_symbol:
                    board.place_move(bot.get_move(board), to_move)
                    explore(board, to_move.opponent())
                    board.undo_move()
                else:
                    for move in board.get_available_moves():
                        board.place_move(move, to_move)
                        explore(board, to_move.opponent())
                        board.undo_move()

            explore(Board(), X)
            self.assertEqual(losses, [], f"bot as {bot_symbol.value}")

    def test_depth_limited_bot_on_4x4_still_takes_win(self):
        b = Board(4)
        for p, s in [((0, 0), X), ((3, 0), O), ((0, 1), X), ((3, 1), O), ((0, 2), X), ((2, 2), O)]:
            b.place_move(p, s)
        self.assertEqual(BotPlayer("bot", X, max_depth=2).get_move(b), (0, 3))


class ConcurrencyTest(unittest.TestCase):
    def test_racing_moves_for_same_turn_apply_once(self):
        for _ in range(20):
            g = TicTacToeGame(ScriptedPlayer("A", X, []), ScriptedPlayer("B", O, []))
            barrier = threading.Barrier(9)
            ok, rejected = [], []

            def submit(pos):
                barrier.wait()
                try:
                    g.make_move(X, pos)
                    ok.append(pos)
                except NotYourTurnError:
                    rejected.append(pos)

            threads = [threading.Thread(target=submit, args=((r, c),))
                       for r in range(3) for c in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(len(ok), 1)
            self.assertEqual(len(rejected), 8)
            self.assertEqual(g.board.history, ok)
            self.assertIs(g.current_player.symbol, O)


if __name__ == "__main__":
    unittest.main()
