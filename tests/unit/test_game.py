import json
from pathlib import Path

import pytest

from model.board import FULL_ROW, H, W, occupied_count
from model.features import features, score
from model.game import drop_y, fits, legal_actions, lock_and_clear, physical_landing
from model.pieces import candidate_ids, decode_candidate, shape
from model.policy import best_move

ROOT = Path(__file__).resolve().parents[2]
FIX = json.loads((ROOT / "tests" / "fixtures" / "hand_fixtures.json").read_text())


def rows_of(spec):
    rows = [0] * H
    for k, v in spec.items():
        rows[int(k)] = v
    return tuple(rows)


@pytest.mark.parametrize("fx", FIX["placements"], ids=[f["name"] for f in FIX["placements"]])
def test_hand_fixture(fx):
    rows = rows_of(fx["rows"])
    exp = fx["expected"]
    y = drop_y(rows, fx["piece"], fx["rotation"], fx["x"])
    if not exp["legal"]:
        assert y is None
        assert physical_landing(rows, fx["piece"], fx["rotation"], fx["x"]) == exp["physical_y"]
        return
    assert y == exp["y"]
    after, lines = lock_and_clear(rows, fx["piece"], fx["rotation"], fx["x"], y)
    assert lines == exp["lines"]
    assert after == rows_of(exp["rows_after"])
    a, q, u = features(after)
    assert (a, q, u) == (exp["A"], exp["Q"], exp["U"])
    assert score((a, q, u), lines) == exp["score"]


def test_retired_rule_would_have_accepted_the_j_regression():
    """Documents why entry from above matters: the old inside-board spawn accepted y=16."""
    fx = next(f for f in FIX["placements"] if f["name"] == "spawn_under_overhang_J")
    rows = rows_of(fx["rows"])
    shp = shape(fx["piece"], fx["rotation"])
    y = H - shp.height
    assert fits(rows, shp.cells, fx["x"], y)  # the retired spawn position "fits"
    while y > 0 and fits(rows, shp.cells, fx["x"], y - 1):
        y -= 1
    assert y == fx["expected"]["retired_rule_y"]
    assert drop_y(rows, fx["piece"], fx["rotation"], fx["x"]) is None


@pytest.mark.parametrize("fx", FIX["feature_only"], ids=[f["name"] for f in FIX["feature_only"]])
def test_feature_only(fx):
    a, q, u = features(rows_of(fx["rows"]))
    assert (a, q, u) == (fx["expected"]["A"], fx["expected"]["Q"], fx["expected"]["U"])


def test_hole_counted_once_per_empty_cell_below_top():
    rows = [0] * H
    rows[1] = 1  # (0,1)
    rows[5] = 1  # (0,5): holes at y=0,2,3,4 -> 4 holes in column 0
    a, q, u = features(tuple(rows))
    assert (a, q, u) == (6, 4, 6)


@pytest.mark.parametrize("fx", FIX["empty_board_best"], ids=lambda f: f"piece{f['piece']}")
def test_empty_board_best(fx):
    rec = best_move(tuple([0] * H), fx["piece"])
    assert (rec["rotation"], rec["x"], rec["y"], rec["score"]) == (fx["rotation"], fx["x"], fx["y"], fx["score"])


@pytest.mark.parametrize("fx", FIX["no_move"], ids=[f["name"] for f in FIX["no_move"]])
def test_no_move(fx):
    assert best_move(rows_of(fx["rows"]), fx["piece"]) is None
    assert legal_actions(rows_of(fx["rows"]), fx["piece"]) == []


def test_fits_boundaries():
    cells = shape(1, 0).cells
    empty = tuple([0] * H)
    assert fits(empty, cells, 0, 0)
    assert fits(empty, cells, 8, 18)
    assert fits(empty, cells, 0, 20)      # entirely above the board is empty space
    assert fits(empty, cells, 0, 19)      # partially above
    assert not fits(empty, cells, 9, 0)   # right wall
    assert not fits(empty, cells, -1, 0)  # left wall
    assert not fits(empty, cells, 0, -1)  # floor


def test_lock_and_clear_does_not_mutate_and_validates():
    rows = tuple([1008] + [0] * 19)
    copy = tuple(rows)
    after, lines = lock_and_clear(rows, 0, 0, 0, 0)
    assert rows == copy and lines == 1
    with pytest.raises(ValueError):
        lock_and_clear(rows, 0, 0, 4, 0)  # overlaps occupied cells
    with pytest.raises(ValueError):
        lock_and_clear(rows, 1, 0, 0, 19)  # protrudes above the board


def test_legal_actions_order_and_invariants():
    rows = tuple([0] * 17 + [5, 0, 0])
    for piece in range(7):
        acts = legal_actions(rows, piece)
        ids = [10 * r + x for r, x, _ in acts]
        assert ids == sorted(ids)
        for r, x, y in acts:
            shp = shape(piece, r)
            assert fits(rows, shp.cells, x, y)
            assert y == 0 or not fits(rows, shp.cells, x, y - 1)
            assert y + shp.height <= H
            after, lines = lock_and_clear(rows, piece, r, x, y)
            assert occupied_count(after) == occupied_count(rows) + 4 - 10 * lines
            assert all(row != FULL_ROW for row in after)
