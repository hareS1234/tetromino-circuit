"""A0/A1 candidate evaluator against the oracle, including intermediate values."""
import cocotb

from common import ROOT, cycle, load_fixtures, pack, pack_heights, param, reset, rows_of, run_transaction, signed32, unpack
from model.boards import mixed_boards
from model.features import column_heights, features
from model.game import drop_y, lock_and_clear, merged_board, physical_landing
from model.numeric import features_used, score_profile
from model.pieces import all_candidates, rotation_count

PREC = param("PRECISION", 0)
ARCH = param("ARCH", 0)
CACHE = param("BOARD_REPR", 0)
GUARD = 512


async def evaluate(dut, rows, piece, rot, x):
    def set_inputs():
        dut.board_i.value = pack(rows)
        dut.heights_i.value = pack_heights(column_heights(rows)) if CACHE else 0
        dut.piece_i.value = piece
        dut.rot_i.value = rot
        dut.x_i.value = x
    n = await run_transaction(dut, set_inputs, GUARD, "candidate_eval")
    return {
        "legal": int(dut.legal_o.value), "y": int(dut.y_o.value), "score": signed32(int(dut.score_o.value)),
        "lines": int(dut.lines_o.value), "board": unpack(int(dut.board_o.value)),
        "A": int(dut.a_o.value), "Q": int(dut.q_o.value), "U": int(dut.u_o.value),
        "merged": unpack(int(dut.merged_o.value)), "phys": int(dut.phys_y_o.value),
        "cycles": int(dut.cycles_o.value), "n": n,
    }


def check(rows, piece, rot, x, got):
    valid_rot = rot < rotation_count(piece)
    y = drop_y(rows, piece, rot, x) if valid_rot else None
    if y is None:
        assert got["legal"] == 0, f"illegal candidate reported legal: piece {piece} rot {rot} x {x}"
        assert got["y"] == 0 and got["score"] == 0 and got["lines"] == 0 and got["board"] == tuple([0] * 20)
        phys = physical_landing(rows, piece, rot, x) if valid_rot else None
        if phys is not None:
            assert got["phys"] == phys
        return
    assert got["legal"] == 1, f"legal candidate reported illegal: piece {piece} rot {rot} x {x} rows {rows}"
    assert got["y"] == y, f"y {got['y']} != {y}"
    merged = merged_board(rows, piece, rot, x, y)
    if ARCH == 0:
        assert got["merged"] == merged, "merged board mismatch"
    after, lines = lock_and_clear(rows, piece, rot, x, y)
    assert got["board"] == after, "cleared board mismatch"
    assert got["lines"] == lines
    a, q, u = features_used(features(after), PREC)
    assert (got["A"], got["Q"], got["U"]) == (a, q, u), f"features {(got['A'], got['Q'], got['U'])} != {(a, q, u)}"
    assert got["score"] == score_profile(features(after), lines, PREC), f"score {got['score']}"


@cocotb.test()
async def hand_fixtures(dut):
    await reset(dut)
    fx = load_fixtures()
    for f in fx["placements"]:
        rows = rows_of(f["rows"])
        got = await evaluate(dut, rows, f["piece"], f["rotation"], f["x"])
        check(rows, f["piece"], f["rotation"], f["x"], got)
        e = f["expected"]
        if e["legal"] and PREC == 0:
            assert got["score"] == e["score"] and got["lines"] == e["lines"], f["name"]


@cocotb.test()
async def invalid_geometry(dut):
    await reset(dut)
    rows = tuple([0] * 20)
    for piece in range(7):
        for rot in range(4):
            for x in range(10):
                got = await evaluate(dut, rows, piece, rot, x)
                check(rows, piece, rot, x, got)


@cocotb.test()
async def mixed_boards_all_candidates(dut):
    await reset(dut)
    worst = 0
    count = 0
    for rows in mixed_boards(2024, 100):
        for piece, rot, x in all_candidates():
            got = await evaluate(dut, rows, piece, rot, x)
            check(rows, piece, rot, x, got)
            worst = max(worst, got["n"])
            assert got["cycles"] == got["n"], f"cycles_o {got['cycles']} != observed {got['n']}"
            count += 1
    assert count == 16200
    dut._log.info(f"ARCH={ARCH} worst-case candidate latency {worst} cycles (guard {GUARD})")
    assert worst < GUARD


@cocotb.test()
async def scratch_state_is_reset_between_candidates(dut):
    """Candidate two must start from the immutable original board, not candidate one's scratch."""
    await reset(dut)
    rows = tuple([1008] + [0] * 19)
    a = await evaluate(dut, rows, 0, 0, 0)   # clears a line
    b = await evaluate(dut, rows, 1, 0, 8)   # O at the right, no clear
    check(rows, 0, 0, 0, a)
    check(rows, 1, 0, 8, b)
    await cycle(dut, 3)
    assert int(dut.done_o.value) == 0 and int(dut.busy_o.value) == 0


@cocotb.test()
async def stage_cycle_profile(dut):
    """Trace the evaluator FSM for representative candidates and record cycles per stage."""
    await reset(dut)
    import json as _json
    from pathlib import Path as _Path
    names = ["IDLE", "DECODE", "PROFILE", "DROP_START", "DROP_WAIT", "MERGE_START", "MERGE_WAIT", "CLEAR_START",
             "CLEAR_WAIT", "FEAT_START", "FEAT_WAIT", "SCORE_START", "SCORE_WAIT", "FINISH"]
    profiles = {}
    cases = {"legal_no_clear": (tuple([0] * 20), 1, 0, 0), "legal_line_clear": (tuple([1008] + [0] * 19), 0, 0, 0),
             "illegal_blocked": (tuple([0] * 19 + [3]), 1, 0, 0), "tall_stack": (tuple([1023 & ~1] * 18 + [0, 0]), 0, 1, 0)}
    for name, (rows, piece, rot, x) in cases.items():
        dut.board_i.value = pack(rows)
        dut.heights_i.value = pack_heights(column_heights(rows)) if CACHE else 0
        dut.piece_i.value = piece; dut.rot_i.value = rot; dut.x_i.value = x
        dut.start_i.value = 1
        await cycle(dut)
        dut.start_i.value = 0
        counts = {}
        n = 0
        while True:
            st = names[int(dut.state.value)]
            counts[st] = counts.get(st, 0) + 1
            await cycle(dut)
            n += 1
            if int(dut.done_o.value):
                break
            assert n < GUARD
        counts["total"] = n
        profiles[name] = counts
    # v1 profiles keep their historical location; the v2 profiles (P5-P7, U14) record under results/v2/
    out_dir = _Path(ROOT) / "results" / ("v2/stage_cycles" if PREC >= 5 else "")
    out = out_dir / f"stage_cycles_a{ARCH}_repr{CACHE}_p{PREC}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_json.dumps({"arch": ARCH, "board_repr": CACHE, "precision": PREC, "profiles": profiles}, indent=1) + "\n")
    dut._log.info(f"stage profile: {profiles}")
