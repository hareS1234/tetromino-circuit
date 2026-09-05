import json
from pathlib import Path

import pytest

from model.pieces import (BASE_CELLS, PIECE_NAMES, all_candidates, candidate_ids,
                          decode_candidate, is_valid_candidate, rotations, shape)

ROOT = Path(__file__).resolve().parents[2]

EXPECTED_ROTATIONS = [2, 1, 4, 2, 2, 4, 4]
EXPECTED_WIDTHS = {0: [4, 1], 1: [2], 2: [3, 2, 3, 2], 3: [3, 2], 4: [3, 2], 5: [3, 2, 3, 2], 6: [3, 2, 3, 2]}
EXPECTED_CANDIDATES = [17, 9, 34, 17, 17, 34, 34]


def test_rotation_counts():
    assert [len(rotations(p)) for p in range(7)] == EXPECTED_ROTATIONS


def test_widths_in_order():
    for p in range(7):
        assert [shape(p, r).width for r in range(len(rotations(p)))] == EXPECTED_WIDTHS[p]


def test_every_orientation_has_four_distinct_normalised_cells():
    for p in range(7):
        for r, cells in enumerate(rotations(p)):
            assert len(set(cells)) == 4
            assert min(x for x, _ in cells) == 0 and min(y for _, y in cells) == 0
            assert list(cells) == sorted(cells, key=lambda c: (c[1], c[0]))


def test_rotation_zero_matches_base_definition():
    for p in range(7):
        assert rotations(p)[0] == tuple(sorted(BASE_CELLS[p], key=lambda c: (c[1], c[0])))


def test_every_orientation_is_a_rotation_of_the_base():
    """Each generated orientation must be reachable by k clockwise rotations of the base."""
    for p in range(7):
        base = list(BASE_CELLS[p])
        seen = []
        cells = base
        for _ in range(4):
            mx = min(x for x, _ in cells); my = min(y for _, y in cells)
            seen.append(tuple(sorted(((x - mx, y - my) for x, y in cells), key=lambda c: (c[1], c[0]))))
            cells = [(dy, -dx) for dx, dy in cells]
        for r in rotations(p):
            assert r in seen


def test_candidate_counts_and_total():
    counts = [len(candidate_ids(p)) for p in range(7)]
    assert counts == EXPECTED_CANDIDATES
    assert sum(counts) == 162
    assert len(all_candidates()) == 162
    for p in range(7):
        assert sum(11 - shape(p, r).width for r in range(len(rotations(p)))) == counts[p]


def test_candidate_ids_dense_increasing_and_validity():
    for p in range(7):
        ids = candidate_ids(p)
        assert list(ids) == sorted(ids)
        for cid in range(40):
            rotation, x = decode_candidate(cid)
            expect = rotation < len(rotations(p)) and x + shape(p, rotation).width <= 10
            assert is_valid_candidate(p, cid) == expect
            assert (cid in ids) == expect
    assert not is_valid_candidate(0, 40)
    assert not is_valid_candidate(0, -1)


def test_bottom_offsets_and_column_masks():
    for p in range(7):
        for r in range(len(rotations(p))):
            s = shape(p, r)
            for dx in range(4):
                col = [dy for cx, dy in s.cells if cx == dx]
                assert ((s.colmask >> dx) & 1) == (1 if col else 0)
                assert s.bottom[dx] == (min(col) if col else 0)
                assert s.colbits[dx] == sum(1 << dy for dy in col)
            assert bin(s.colmask).count("1") == s.width
            assert 0 in [s.bottom[dx] for dx in range(4) if (s.colmask >> dx) & 1]


def test_j_rotation_3_cells_match_manual():
    assert rotations(5)[3] == ((0, 0), (1, 0), (1, 1), (1, 2))


def test_invalid_piece_rejected():
    with pytest.raises(ValueError):
        rotations(7)
    with pytest.raises(ValueError):
        shape(0, 2)


def test_generated_shapes_json_is_current():
    doc = json.loads((ROOT / "tests" / "fixtures" / "shapes.json").read_text())
    assert doc["total_candidates"] == 162
    for entry in doc["pieces"]:
        p = entry["id"]
        assert entry["name"] == PIECE_NAMES[p]
        assert entry["candidate_ids"] == list(candidate_ids(p))
        for rot in entry["rotations"]:
            s = shape(p, rot["rotation"])
            assert [tuple(c) for c in rot["cells"]] == list(s.cells)
            assert (rot["width"], rot["height"]) == (s.width, s.height)
            assert rot["bottom"] == list(s.bottom) and rot["colmask"] == s.colmask


def test_generated_svh_encodes_every_cell():
    text = (ROOT / "rtl" / "generated" / "shape_case.svh").read_text()
    for p in range(7):
        for r in range(len(rotations(p))):
            s = shape(p, r)
            dx = sum(c[0] << (2 * k) for k, c in enumerate(s.cells))
            dy = sum(c[1] << (2 * k) for k, c in enumerate(s.cells))
            key = f"5'b{p:03b}_{r:02b}:"
            assert key in text
            block = text.split(key, 1)[1].split("end", 1)[0]
            assert f"dx_o = 8'h{dx:02x}" in block and f"dy_o = 8'h{dy:02x}" in block
            assert f"width_o = 3'd{s.width}" in block and f"height_o = 3'd{s.height}" in block
    cand = (ROOT / "rtl" / "generated" / "cand_case.svh").read_text()
    for p in range(7):
        for j, cid in enumerate(candidate_ids(p)):
            assert f"9'b{p:03b}_{j:06b}: cand_id_o = 6'd{cid};" in cand
