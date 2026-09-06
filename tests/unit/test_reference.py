"""Grid, literal bitmap, and fast closed-form placement must agree."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))

import pytest  # noqa: E402

from model import fast  # noqa: E402
from model.board import EMPTY_BOARD, H, W, occupied_count  # noqa: E402
from model.boards import mixed_boards  # noqa: E402
from model.features import column_heights, features  # noqa: E402
from model.game import drop_y, fits, lock_and_clear, physical_landing  # noqa: E402
from model.numeric import profile  # noqa: E402
from model.pieces import all_candidates, shape  # noqa: E402
from reference_grid import (cells_from_rows, ref_features, ref_landing, ref_lock_and_clear,  # noqa: E402
                            rows_from_cells)

BOARDS = mixed_boards(20260905, 250)
CANDS = all_candidates()


def fast_landing(rows, piece, rotation, x):
    cols = fast.rows_to_cols(rows)
    placed = fast._place(cols, fast.heights_of(cols), shape(piece, rotation), x)
    if placed is None:
        return None
    return placed


def retired_rule_y(rows, piece, rotation, x):
    shp = shape(piece, rotation)
    if x + shp.width > W:
        return None
    y = H - shp.height
    if not fits(rows, shp.cells, x, y):
        return None
    while y > 0 and fits(rows, shp.cells, x, y - 1):
        y -= 1
    return y


def test_corpus_is_the_declared_size_and_normalized():
    assert len(BOARDS) == 250 and len(CANDS) == 162
    for rows in BOARDS:
        assert len(rows) == H and all(0 <= r < 1023 for r in rows)


def test_three_way_differential_40500_cases():
    cases = 0
    retired_disagreements = 0
    high_overhang_cases = 0
    for rows in BOARDS:
        occupied = cells_from_rows(rows)
        cols = fast.rows_to_cols(rows)
        heights = fast.heights_of(cols)
        assert heights == column_heights(rows)
        for piece, rotation, x in CANDS:
            cases += 1
            shp = shape(piece, rotation)
            ref_y, ref_legal = ref_landing(occupied, shp.cells, shp.width, x)
            phys = physical_landing(rows, piece, rotation, x)
            y = drop_y(rows, piece, rotation, x)
            assert phys == ref_y
            assert (y is not None) == ref_legal
            placed = fast._place(cols, heights, shp, x)
            if ref_legal:
                assert y == ref_y
                assert placed is not None and placed[0] == y
                after, lines = lock_and_clear(rows, piece, rotation, x, y)
                ref_after, ref_lines = ref_lock_and_clear(occupied, shp.cells, x, y)
                assert lines == ref_lines and after == rows_from_cells(ref_after)
                assert placed[2] == lines and fast.cols_to_rows(placed[1]) == after
                assert occupied_count(after) == occupied_count(rows) + 4 - 10 * lines
                assert features(after) == ref_features(ref_after)
                a, qu, uu, q, u = fast.features_cols(placed[1], profile(0))
                assert (a, q, u) == features(after)
            else:
                assert placed is None
                if ref_y is not None and ref_y < H:
                    high_overhang_cases += 1
            if retired_rule_y(rows, piece, rotation, x) != y:
                retired_disagreements += 1
    assert cases == 40500
    assert high_overhang_cases > 0, "corpus must contain entry-path obstructions"
    assert retired_disagreements > 0, "corpus must distinguish drop-v1.1 from the retired rule"


def test_profiles_features_used():
    rows = BOARDS[3]
    a, q, u = features(rows)
    cols = fast.rows_to_cols(rows)
    for p in range(5):
        prof = profile(p)
        fa, fq_used, fu_used, fq, fu = fast.features_cols(cols, prof)
        assert (fa, fq, fu) == (a, q, u)
        assert fq_used == (q if prof.q_cap is None else min(q, prof.q_cap))
        assert fu_used == (u if prof.use_u else 0)


def test_columns_round_trip():
    for rows in BOARDS[:50]:
        assert fast.cols_to_rows(fast.rows_to_cols(rows)) == rows
    assert fast.rows_to_cols(EMPTY_BOARD) == tuple([0] * W)
