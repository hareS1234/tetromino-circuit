"""Policy equivalence: readable literal-descent policy vs accelerated model, depth 1 and 2,
all precision profiles; baselines; stream determinism."""
import random

from model import fast, lookahead, policy
from model.board import EMPTY_BOARD, H
from model.boards import mixed_boards, trajectory_boards
from model.numeric import PRECISION_IDS, score_bounds, score_profile
from model.streams import STREAM_LENGTH, seven_bag, stream_sha256

BOARDS = mixed_boards(4242, 120)


def _same(a, b):
    if a is None or b is None:
        return a is None and b is None
    keys = ("rotation", "x", "y", "candidate_id", "lines", "A", "Q", "U", "score")
    return all(a[k] == b[k] for k in keys) and tuple(a["next_rows"]) == tuple(b["next_rows"])


def test_depth1_fast_matches_reference_all_profiles():
    checked = 0
    for prec in PRECISION_IDS:
        for rows in BOARDS:
            for piece in range(7):
                ref = policy.best_move(rows, piece, prec)
                got = fast.best_move_fast(rows, piece, prec)
                assert _same(ref, got), (prec, piece, rows)
                checked += 1
    assert checked == len(PRECISION_IDS) * len(BOARDS) * 7


def test_depth2_fast_matches_reference():
    rng = random.Random(3)
    boards = BOARDS[:40] + trajectory_boards(77, 60)[::3]
    checked = 0
    for rows in boards:
        piece = rng.randrange(7)
        nxt = rng.randrange(7)
        ref = lookahead.best_move_depth2(rows, piece, nxt, 0)
        got = fast.best_move_depth2_fast(rows, piece, nxt, 0)
        assert _same(ref, got), (piece, nxt, rows)
        if ref is not None:
            assert ref["surviving"] == got["surviving"] and ref["leaf_count"] == got["leaf_count"]
        checked += 1
    assert checked == len(boards)


def test_depth2_prefers_surviving_root_and_falls_back():
    # A board where only some roots leave room for the next piece.
    rows = [0] * H
    for y in range(16):
        rows[y] = 0b1111111110  # column 0 open, everything else filled to height 16
    rows = tuple(rows)
    rec = lookahead.best_move_depth2(rows, 0, 1, 0)  # I then O
    assert rec is not None
    # Vertical I in the well clears four lines and leaves the board playable; it must survive.
    assert rec["surviving"] is True
    # If the preview cannot be placed anywhere, the fallback picks the best S1 root.
    top = [0] * H
    top[19] = 0b0101010101
    top[18] = 0b0101010101
    top[17] = 0b1111111110
    top = tuple(top)
    rec = lookahead.best_move_depth2(top, 0, 1, 0)  # I vertical fits in column 0 only; O never fits after
    if rec is not None:
        assert rec["surviving"] is False
        assert rec["score"] == rec["score_s1"]


def test_tie_break_lower_candidate_id():
    # Empty board with an S piece: symmetric placements produce equal scores; lower id wins.
    rec = policy.best_move(EMPTY_BOARD, 2)  # T
    assert rec["candidate_id"] == min(r["candidate_id"] for r in policy.evaluate_candidates(EMPTY_BOARD, 2)
                                      if r["score"] == rec["score"])


def test_baselines_are_legal_and_deterministic():
    rng1 = random.Random(policy.random_seed_for_stream(2000))
    rng2 = random.Random(policy.random_seed_for_stream(2000))
    for rows in BOARDS[:30]:
        for piece in range(7):
            a = policy.random_legal(rows, piece, rng1)
            b = policy.random_legal(rows, piece, rng2)
            assert (a is None) == (b is None)
            if a:
                assert a["candidate_id"] == b["candidate_id"]
            ls = policy.lowest_stack(rows, piece)
            if ls:
                recs = policy.evaluate_candidates(rows, piece)
                assert (ls["A"], ls["Q"], ls["U"], ls["candidate_id"]) == min(
                    (r["A"], r["Q"], r["U"], r["candidate_id"]) for r in recs)


def test_score_bounds_fit_signed_16():
    lo, hi = score_bounds(0)
    assert lo == -20640 and hi == 304
    assert -(1 << 15) <= lo and hi < (1 << 15)
    assert score_profile((200, 200, 180), 0, 0) == lo


def test_seven_bag_structure_and_hash():
    pieces = seven_bag(2000)
    assert len(pieces) == STREAM_LENGTH
    for i in range(0, 1995, 7):
        assert sorted(pieces[i:i + 7]) == list(range(7))
    assert seven_bag(2000) == pieces
    assert len(stream_sha256(pieces)) == 64
