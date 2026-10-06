import threading
import unittest

from chess_game import (
    Board, ChessError, ChessGame, Color, GameOverError, GameStatus,
    InvalidMoveError, King, Pawn, PieceType, Queen, Rook, StaleMoveError,
    square, square_name,
)


def perft(board: Board, color: Color, depth: int) -> int:
    """Count leaf nodes of the legal move tree. Promotions expand to 4 moves."""
    if depth == 0:
        return 1
    total = 0
    for start, end in board.legal_moves(color):
        piece = board.get_piece_at(start)
        promos = [None]
        if isinstance(piece, Pawn) and end[0] in (0, 7):
            promos = [PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP, PieceType.KNIGHT]
        for promo in promos:
            move = board.apply_move(start, end, promo)
            total += perft(board, color.opponent, depth - 1)
            board.undo_move(move)
    return total


def game_from_fen(fen: str) -> ChessGame:
    board, to_move = Board.from_fen(fen)
    return ChessGame(board=board, to_move=to_move)


class PerftTest(unittest.TestCase):
    """Reference counts from the Chess Programming Wiki 'Perft Results' page.
    These catch almost every move-generation bug (castling, en passant, pins, promotion)."""

    def check(self, fen, expected):
        board, color = Board.from_fen(fen)
        snapshot = board.render()
        for depth, count in enumerate(expected, start=1):
            self.assertEqual(perft(board, color, depth), count, f"depth {depth}")
        self.assertEqual(board.render(), snapshot, "make/unmake must restore the board")

    def test_start_position(self):
        self.check("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", [20, 400, 8902])

    def test_kiwipete_castling_and_pins(self):
        self.check("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
                   [48, 2039])

    def test_position3_en_passant_and_discovered_check(self):
        self.check("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", [14, 191, 2812])

    def test_position4_promotions(self):
        self.check("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", [6, 264])


class CoordinateTest(unittest.TestCase):
    def test_round_trip(self):
        self.assertEqual(square("e2"), (6, 4))
        self.assertEqual(square("a8"), (0, 0))
        self.assertEqual(square_name((7, 7)), "h1")
        with self.assertRaises(ValueError):
            square("i9")


class RulesTest(unittest.TestCase):
    def test_scholars_mate(self):
        g = ChessGame()
        for a, b in [("e2", "e4"), ("e7", "e5"), ("f1", "c4"), ("b8", "c6"),
                     ("d1", "h5"), ("g8", "f6"), ("h5", "f7")]:
            g.make_move(a, b)
        self.assertEqual(g.status, GameStatus.CHECKMATE)
        self.assertEqual(g.winner.color, Color.WHITE)
        with self.assertRaises(GameOverError):
            g.make_move("a7", "a6")

    def test_turn_order_and_ownership(self):
        g = ChessGame()
        with self.assertRaises(InvalidMoveError):
            g.make_move("e7", "e5")              # black piece on white's turn
        with self.assertRaises(InvalidMoveError):
            g.make_move("e3", "e4")              # empty square
        with self.assertRaises(InvalidMoveError):
            g.make_move("e2", "e5")              # pawn cannot go three

    def test_pinned_piece_cannot_move(self):
        g = game_from_fen("4r1k1/8/8/8/8/8/4B3/4K3 w - - 0 1")  # bishop pinned on e-file
        with self.assertRaisesRegex(InvalidMoveError, "check"):
            g.make_move("e2", "d3")

    def test_castling_kingside_moves_rook(self):
        g = game_from_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        move = g.make_move("e1", "g1")
        self.assertTrue(move.is_castling)
        self.assertIsInstance(g.board.get_piece_at(square("f1")), Rook)
        self.assertIsNone(g.board.get_piece_at(square("h1")))
        g.undo_last_move()
        self.assertIsInstance(g.board.get_piece_at(square("h1")), Rook)
        self.assertFalse(g.board.get_piece_at(square("e1")).has_moved)

    def test_cannot_castle_through_or_out_of_check(self):
        through = game_from_fen("5r2/8/8/8/8/8/8/4K2R w K - 0 1")    # f1 attacked
        with self.assertRaises(InvalidMoveError):
            through.make_move("e1", "g1")
        out_of = game_from_fen("4r3/8/8/8/8/8/8/4K2R w K - 0 1")     # in check
        with self.assertRaises(InvalidMoveError):
            out_of.make_move("e1", "g1")
        no_right = game_from_fen("8/8/8/8/8/8/8/4K2R w - - 0 1")
        with self.assertRaises(InvalidMoveError):
            no_right.make_move("e1", "g1")

    def test_castling_right_lost_after_rook_moves_and_returns(self):
        g = game_from_fen("4k3/8/8/8/8/8/8/4K2R w K - 0 1")
        g.make_move("h1", "h2"); g.make_move("e8", "d8")
        g.make_move("h2", "h1"); g.make_move("d8", "e8")
        with self.assertRaises(InvalidMoveError):
            g.make_move("e1", "g1")

    def test_en_passant_only_immediately(self):
        g = ChessGame()
        for a, b in [("e2", "e4"), ("a7", "a6"), ("e4", "e5"), ("d7", "d5")]:
            g.make_move(a, b)
        move = g.make_move("e5", "d6")
        self.assertTrue(move.is_en_passant)
        self.assertIsNone(g.board.get_piece_at(square("d5")))
        g.undo_last_move()
        self.assertIsInstance(g.board.get_piece_at(square("d5")), Pawn)

        g2 = ChessGame()
        for a, b in [("e2", "e4"), ("a7", "a6"), ("e4", "e5"), ("d7", "d5"),
                     ("h2", "h3"), ("h7", "h6")]:
            g2.make_move(a, b)
        with self.assertRaises(InvalidMoveError):  # window has passed
            g2.make_move("e5", "d6")

    def test_promotion_default_and_underpromotion(self):
        g = game_from_fen("8/P7/8/8/8/8/k7/4K3 w - - 0 1")
        g.make_move("a7", "a8")
        self.assertIsInstance(g.board.get_piece_at(square("a8")), Queen)
        g.undo_last_move()
        self.assertIsInstance(g.board.get_piece_at(square("a7")), Pawn)
        g.make_move("a7", "a8", promotion=PieceType.KNIGHT)
        self.assertEqual(g.board.get_piece_at(square("a8")).piece_type, PieceType.KNIGHT)
        g.undo_last_move()
        with self.assertRaises(InvalidMoveError):
            g.make_move("a7", "a8", promotion=PieceType.KING)

    def test_stalemate(self):
        g = game_from_fen("7k/8/6Q1/8/8/8/8/K7 w - - 0 1")
        g.make_move("g6", "f7")
        self.assertEqual(g.status, GameStatus.STALEMATE)
        self.assertIsNone(g.winner)

    def test_check_status(self):
        g = game_from_fen("4k3/8/8/8/8/8/8/R3K3 w - - 0 1")
        g.make_move("a1", "a8")
        self.assertEqual(g.status, GameStatus.CHECK)


class DrawTest(unittest.TestCase):
    def test_insufficient_material(self):
        g = game_from_fen("4k3/8/8/8/8/8/3q4/4K3 w - - 0 1")
        g.make_move("e1", "d2")                  # king takes the last queen
        self.assertEqual(g.status, GameStatus.DRAW)

    def test_threefold_claim_and_fivefold_automatic(self):
        g = ChessGame()
        shuffle = [("g1", "f3"), ("g8", "f6"), ("f3", "g1"), ("f6", "g8")]
        self.assertFalse(g.can_claim_draw())
        for a, b in shuffle * 2:
            g.make_move(a, b)
        self.assertTrue(g.can_claim_draw())       # start position seen 3 times
        self.assertEqual(g.status, GameStatus.ACTIVE)
        for a, b in shuffle * 2:
            g.make_move(a, b)
        self.assertEqual(g.status, GameStatus.DRAW)   # fifth occurrence

    def test_claim_draw_rejected_without_grounds(self):
        with self.assertRaises(ChessError):
            ChessGame().claim_draw()


class GameFlowTest(unittest.TestCase):
    def test_resign(self):
        g = ChessGame("A", "B")
        g.resign(Color.WHITE)
        self.assertEqual(g.status, GameStatus.RESIGNED)
        self.assertEqual(g.winner.name, "B")
        with self.assertRaises(GameOverError):
            g.resign(Color.BLACK)

    def test_undo_restores_checkmate_to_playable(self):
        g = ChessGame()
        for a, b in [("f2", "f3"), ("e7", "e5"), ("g2", "g4"), ("d8", "h4")]:
            g.make_move(a, b)
        self.assertEqual(g.status, GameStatus.CHECKMATE)
        g.undo_last_move()
        self.assertEqual(g.status, GameStatus.ACTIVE)
        self.assertIsNone(g.winner)
        self.assertEqual(g.current_player.color, Color.BLACK)
        with self.assertRaises(ChessError):
            ChessGame().undo_last_move()

    def test_stale_expected_ply_rejected(self):
        g = ChessGame()
        g.make_move("e2", "e4", expected_ply=0)
        with self.assertRaises(StaleMoveError):
            g.make_move("e7", "e5", expected_ply=0)   # duplicate of an old submission
        g.make_move("e7", "e5", expected_ply=1)


class ConcurrencyTest(unittest.TestCase):
    def test_duplicate_submissions_apply_once(self):
        """Many threads submit the same move for the same ply: exactly one wins."""
        g = ChessGame()
        n = 16
        barrier = threading.Barrier(n)
        ok, stale = [], []

        def submit():
            barrier.wait()
            try:
                g.make_move("e2", "e4", expected_ply=0)
                ok.append(1)
            except (StaleMoveError, InvalidMoveError):
                stale.append(1)

        threads = [threading.Thread(target=submit) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(ok), 1)
        self.assertEqual(len(stale), n - 1)
        self.assertEqual(g.ply, 1)
        self.assertIsInstance(g.board.get_piece_at(square("e4")), Pawn)
        self.assertIsInstance(g.board.find_king(Color.WHITE), King)


if __name__ == "__main__":
    unittest.main()
