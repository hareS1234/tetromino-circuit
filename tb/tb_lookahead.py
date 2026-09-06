"""Depth-two search against the exhaustive reference; at depth one, the preview must be inert."""
import json
import os

import cocotb

from common import ROOT, cycle, pack, param, reset
from core_driver import idle_inputs, request
from model import lookahead, policy
from model.pieces import candidate_ids

DEPTH = param("DEPTH", 1)
COUNT = int(os.environ.get("TETROMINO_COUNT", "250"))
RESULTS = os.environ.get("TETROMINO_RESULTS")
# derived bound (A1/cache): root candidate <= 41 cycles + 3 controller, B1 cache 1, leaf <= 41 + 3;
# 34 roots x (44 + 1 + 34 x 44) + 34 finish = ~52,700; guard with margin
TIMEOUT = 120_000 if DEPTH == 2 else 5000


def corpus():
    path = ROOT / "benchmarks" / "states" / "corpus_d2.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()][:COUNT]


@cocotb.test()
async def depth_two_corpus(dut):
    if DEPTH != 2:
        return
    idle_inputs(dut)
    await reset(dut)
    results = []
    worst = 0
    for rec in corpus():
        rows, piece, nxt = tuple(rec["rows"]), rec["piece"], rec["next_piece"]
        exp = lookahead.best_move_depth2(rows, piece, nxt)
        fields, edges, _ = await request(dut, rows, piece, next_piece=nxt, timeout=TIMEOUT)
        assert fields["error"] == 0
        if exp is None:
            assert fields["no_move"] == 1 and fields["score"] == 0 and fields["rotation"] == 0 and fields["x"] == 0 and fields["y"] == 0, rec["id"]
        else:
            got = (fields["no_move"], fields["rotation"], fields["x"], fields["y"], fields["score"])
            want = (0, exp["rotation"], exp["x"], exp["y"], exp["score"])
            assert got == want, f"case {rec['id']} ({rec['category']}): got {got} want {want}"
        assert fields["cycles"] == edges
        worst = max(worst, edges)
        results.append({"state_id": rec["id"], "category": rec["category"], "core_cycles": edges,
                        "root_candidates": len(candidate_ids(piece)), "leaf_candidates": len(candidate_ids(nxt)),
                        "no_move": fields["no_move"], "rotation": fields["rotation"], "x": fields["x"], "y": fields["y"],
                        "score": fields["score"]})
    if RESULTS:
        with open(RESULTS, "w") as fh:
            json.dump(results, fh)
    dut._log.info(f"depth-two: {len(results)} cases, worst {worst} cycles (guard {TIMEOUT})")


@cocotb.test()
async def preview_seven_is_error_at_depth_two(dut):
    if DEPTH != 2:
        return
    idle_inputs(dut)
    await reset(dut)
    empty = tuple([0] * 20)
    fields, edges, _ = await request(dut, empty, 1, next_piece=7, timeout=TIMEOUT)
    assert fields == {"error": 1, "no_move": 0, "rotation": 0, "x": 0, "y": 0, "score": 0, "cycles": edges}
    fields, edges, _ = await request(dut, empty, 7, next_piece=1, timeout=TIMEOUT)
    assert fields["error"] == 1
    exp = lookahead.best_move_depth2(empty, 1, 2)
    fields, edges, _ = await request(dut, empty, 1, next_piece=2, timeout=TIMEOUT)
    assert (fields["rotation"], fields["x"], fields["y"], fields["score"]) == (exp["rotation"], exp["x"], exp["y"], exp["score"])


@cocotb.test()
async def reset_during_inner_search(dut):
    if DEPTH != 2:
        return
    idle_inputs(dut)
    await reset(dut)
    rows = tuple([0] * 16 + [0b1111111110, 0, 0, 0])
    exp = lookahead.best_move_depth2(rows, 0, 2)
    _, latency, _ = await request(dut, rows, 0, next_piece=2, timeout=TIMEOUT)
    for after in (latency // 3, latency // 2, latency - 2):
        dut.board_i.value = pack(rows); dut.piece_i.value = 0; dut.next_piece_i.value = 2; dut.req_valid.value = 1
        await cycle(dut)
        dut.req_valid.value = 0
        await cycle(dut, after)
        dut.rst.value = 1
        await cycle(dut)
        dut.rst.value = 0
        assert int(dut.rsp_valid.value) == 0
        fields, edges, _ = await request(dut, rows, 0, next_piece=2, timeout=TIMEOUT)
        assert (fields["rotation"], fields["x"], fields["y"], fields["score"]) == (exp["rotation"], exp["x"], exp["y"], exp["score"])
        assert edges == latency


@cocotb.test()
async def preview_independence_at_depth_one(dut):
    if DEPTH != 1:
        return
    idle_inputs(dut)
    await reset(dut)
    for rec in corpus()[:30]:
        rows, piece = tuple(rec["rows"]), rec["piece"]
        exp = policy.best_move(rows, piece)
        base = None
        for nxt in range(8):
            fields, edges, _ = await request(dut, rows, piece, next_piece=nxt, timeout=TIMEOUT)
            key = (fields["error"], fields["no_move"], fields["rotation"], fields["x"], fields["y"], fields["score"], fields["cycles"])
            base = key if base is None else base
            assert key == base, f"case {rec['id']}: preview {nxt} changed a depth-one result"
        assert base[0] == 0
        if exp is not None:
            assert base[2:6] == (exp["rotation"], exp["x"], exp["y"], exp["score"])
