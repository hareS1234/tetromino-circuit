"""U04: the A2 specification triple — stage manifest, configuration identity, abstract cycle model —
plus the packed-row-order confirmation against the existing ROM/fixture conventions."""
import json
import random
from pathlib import Path

import pytest

from model import a2_token_model as tm
from model.board import pack_rows, unpack_rows
from model.config import DECLARED, DECLARED_IDS, SUPPORTED, SUPPORTED_IDS, Config, status, validate
from model.pieces import candidate_ids, shape

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((ROOT / "architecture" / "a2_stages.json").read_text())


# ---- packed row order (guide U04 step 2) ---------------------------------------------------------------

def test_packed_row_order_matches_reference_and_rtl_convention():
    rows = [0] * 20
    rows[0] = 0b0000000001      # cell (0,0)
    rows[19] = 0b1000000000     # cell (9,19)
    packed = pack_rows(rows)
    assert packed & 1 == 1 and (packed >> 199) & 1 == 1, "bit 10*y+x: (0,0) is bit 0, (9,19) is bit 199"
    assert unpack_rows(packed) == tuple(rows)
    for y in range(20):
        for x in range(10):
            assert (pack_rows([1 << x if r == y else 0 for r in range(20)]) >> (10 * y + x)) & 1 == 1
    # the RTL row slice convention: row y = board[10*y +: 10]; row 19 = board[199:190] (rtl/line_clear.sv)
    board = pack_rows([y + 1 for y in range(20)])
    assert all(((board >> (10 * y)) & 0x3FF) == y + 1 for y in range(20))


def test_shape_rom_conventions_used_by_the_spec():
    # bottom[dx] is the smallest dy in column dx; colmask marks occupied columns; candidate ids ascend
    s = shape(2, 1)   # T rotation 1: cells (0,0),(0,1),(1,1),(0,2) -> bottom (0,1), width 2, height 3
    assert s.width == 2 and s.height == 3 and s.bottom[:2] == (0, 1)
    for piece in range(7):
        ids = candidate_ids(piece)
        assert list(ids) == sorted(ids) and len(ids) == (17, 9, 34, 17, 17, 34, 34)[piece]
        assert all(0 <= i < 40 for i in ids)


# ---- stage manifest -------------------------------------------------------------------------------------

def test_manifest_has_23_contiguous_single_delay_banks():
    st = MANIFEST["stages"]
    assert MANIFEST["banks"] == 23 == len(st)
    assert [s["index"] for s in st] == list(range(23))
    assert all(s["delay_edges"] == 1 for s in st)
    assert len({s["name"] for s in st}) == 23
    assert sum(s["delay_edges"] for s in st) == MANIFEST["latency"]["transfer_edges"] == 23
    assert MANIFEST["latency"]["visible_edges"] == 22 and MANIFEST["latency"]["candidate_ii"] == 1


def test_manifest_widths_are_consistent():
    for s in MANIFEST["stages"]:
        assert sum(f["bits"] for f in s["out_fields"]) == s["out_bits"], s["name"]
    fields = {f["name"]: f["bits"] for f in MANIFEST["stages"][22]["out_fields"]}
    assert fields == {"score": 32, "legal": 1, "y": 5, "candidate_id": 6, "tag": 16, "last": 1}
    assert {f["name"]: f["bits"] for f in MANIFEST["input_fields"]} == {"rotation": 2, "x": 4, "candidate_id": 6, "tag": 16, "last": 1}
    assert {f["name"]: f["bits"] for f in MANIFEST["context_fields"]} == {"ctx_board_i": 200, "ctx_heights_i": 50, "ctx_piece_i": 3}
    for s in MANIFEST["stages"][2:]:
        names = {f["name"]: f["bits"] for f in s["out_fields"]}
        assert names["legal"] == 1 and names["y"] == 5 and names["candidate_id"] == 6 and names["tag"] == 16 and names["last"] == 1, s["name"]


def test_manifest_groups_tile_the_pipeline():
    g = MANIFEST["stage_groups"]
    spans = sorted(g.values())
    assert spans == [[0, 3], [4, 12], [13, 19], [20, 22]]
    assert MANIFEST["stages"][4]["name"].startswith("P4") and "keep" in MANIFEST["stages"][4]["operation"]
    assert "stride 16" in MANIFEST["stages"][9]["name"] and "match" in MANIFEST["stages"][10]["operation"]


# ---- configuration identity ---------------------------------------------------------------------------------

def test_a2_identity_and_neighbours_are_unsupported():
    """Since U10 the exact A2 configuration is verified; every neighbouring A2 combination stays unsupported."""
    a2 = Config(2, 1, 1, 1, 0)
    assert a2.id == "a2-cache-d1-p0-l1" and status(a2) == "verified" and validate(a2) is a2
    # nine v1 identities + A2 (U10) + the four-lane A1 (U13)
    assert a2.id in SUPPORTED_IDS and DECLARED == () and len(SUPPORTED) == 11
    from model.config import V1_SUPPORTED_IDS
    assert len(V1_SUPPORTED_IDS) == 9 and a2.id not in V1_SUPPORTED_IDS
    l4 = Config(1, 1, 4, 1, 0)
    assert l4.id == "a1-cache-d1-p0-l4" and status(l4) == "verified" and l4.id not in V1_SUPPORTED_IDS
    for bad in (Config(1, 0, 4, 1, 0), Config(1, 1, 4, 2, 0), Config(1, 1, 4, 1, 1), Config(0, 0, 4, 1, 0)):
        assert status(bad) == "unsupported"
    for bad in (Config(2, 0, 1, 1, 0), Config(2, 1, 2, 1, 0), Config(2, 1, 4, 1, 0), Config(2, 1, 1, 2, 0), Config(2, 1, 1, 1, 1),
                Config(2, 1, 1, 1, 4)):
        assert status(bad) == "unsupported"
        with pytest.raises(ValueError, match="not supported: A2"):
            validate(bad)
    for c in SUPPORTED:
        assert validate(c) is c and status(c) == "verified"
    with pytest.raises(ValueError, match="unknown ARCH"):
        validate(Config(3, 0, 1, 1, 0))


def test_tools_refuse_unsupported_a2_neighbours():
    """No stub returns a canned move for an unsupported A2 combination."""
    import subprocess
    for argv in (["tools/build_native.py", "--arch", "2", "--board-repr", "0", "--print-key"],
                 ["tools/synth.py", "--arch", "2", "--board-repr", "1", "--lanes", "2", "--print-key"],
                 ["tools/test_core.py", "--arch", "2", "--board-repr", "1", "--depth", "2", "--count", "1"]):
        r = subprocess.run(["bash", str(ROOT / "scripts" / "env.sh"), "python", *argv], cwd=ROOT, capture_output=True, text=True)
        assert r.returncode != 0 and "not supported" in r.stderr, argv


# ---- abstract cycle contract ----------------------------------------------------------------------------------

def test_token_model_latencies_and_ii():
    s = tm.stream(4096)
    assert set(s["visible_latency"].values()) == {22} and set(s["transfer_latency"].values()) == {23}
    assert set(s["accept_spacings"]) == {1} and s["order_preserved"]


def test_token_model_bubbles_and_stalls_preserve_count_and_order():
    rng = random.Random(3)
    stall = {e for e in range(20000) if rng.random() < 0.4}
    bubble = {e for e in range(20000) if rng.random() < 0.3}
    s = tm.stream(1000, ready=lambda e: e not in stall, bubbles=lambda e: e in bubble)
    assert s["order_preserved"] and len(s["transfer_latency"]) == 1000
    assert min(s["transfer_latency"].values()) >= 23 and min(s["accept_spacings"]) >= 1
    p = tm.Pipe()
    for i in range(10):
        p.step(True, i, False)          # fill while the output is blocked
    assert p.occupancy == 10
    p.step(True, 99, True, rst=True)    # reset clears everything with priority over advance
    assert p.occupancy == 0 and not p.m_valid


def test_stall_freezes_the_whole_pipeline():
    p = tm.Pipe()
    for i in range(23):
        p.step(True, i, True)
    assert p.m_valid and p.m_payload == 0 and p.occupancy == 23
    before = list(p.payload)
    res = p.step(True, 100, False)      # output blocked: nothing moves, input not accepted
    assert res["accepted"] is None and res["transferred"] is None and p.payload == before
    res = p.step(True, 100, True)       # consume and accept on the same edge
    assert res["transferred"] == 0 and res["accepted"] == 100 and p.occupancy == 23


@pytest.mark.parametrize("n,expected", [(9, 38), (17, 46), (34, 63)])
def test_decision_latency_formula_matches_simulation(n, expected):
    d = tm.decision_latency(n)
    sim = tm.simulate_search(n)
    assert d["decision_cycles"] == expected == tm.formula(n) == sim["rsp_valid_edge"]
    assert d["first_issue"] == 4 and d["last_issue"] == n + 3 and d["last_visible"] == n + 25 and d["reducer_done"] == n + 26
    assert sim["issued"] == sim["retired"] == n
    assert tm.request_interval(n) == expected + 2, "II of one candidate per cycle is not one decision per cycle"


def test_manifest_and_model_agree_on_bank_count():
    assert tm.BANKS == MANIFEST["banks"]
    assert "N + 29" in MANIFEST["latency"]["decision_formula"] and "D(N) + 2" in MANIFEST["latency"]["request_interval_formula"]
