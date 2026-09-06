"""Drive the committed corpus through the core and compare every decision."""
import json
import os

import cocotb

from common import ROOT, param, reset
from core_driver import idle_inputs, request
from model import policy
from model.pieces import candidate_ids

DEPTH = param("DEPTH", 1)
PREC = param("PRECISION", 0)
COUNT = int(os.environ.get("TETROMINO_COUNT", "50"))
RESULTS = os.environ.get("TETROMINO_RESULTS")
TIMEOUT = 25000 if param("ARCH", 0) == 0 else 5000


def load_corpus():
    path = ROOT / "benchmarks" / "states" / "corpus_d1.jsonl"
    recs = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if COUNT > len(recs):
        raise AssertionError(f"corpus has {len(recs)} cases; {COUNT} requested")
    # take a stratified prefix: every category is represented in small subsets
    by_cat = {}
    for r in recs:
        by_cat.setdefault(r["category"], []).append(r)
    out = []
    while len(out) < COUNT:
        for cat in sorted(by_cat):
            if by_cat[cat] and len(out) < COUNT:
                out.append(by_cat[cat].pop(0))
    return out


@cocotb.test()
async def corpus_requests(dut):
    idle_inputs(dut)
    await reset(dut)
    results = []
    for rec in load_corpus():
        rows = tuple(rec["rows"])
        piece = rec["piece"]
        # expected decision computed independently (literal-descent reference) before driving the DUT
        exp = policy.best_move(rows, piece, PREC)
        fields, edges, _ = await request(dut, rows, piece, next_piece=(piece + 1) % 7, timeout=TIMEOUT)
        assert fields["error"] == 0, rec["id"]
        if exp is None:
            assert fields["no_move"] == 1 and fields["rotation"] == 0 and fields["x"] == 0 and fields["y"] == 0 \
                and fields["score"] == 0, f"case {rec['id']} ({rec['category']}): expected no_move, got {fields}"
        else:
            assert fields["no_move"] == 0, f"case {rec['id']}: unexpected no_move"
            got = (fields["rotation"], fields["x"], fields["y"], fields["score"])
            want = (exp["rotation"], exp["x"], exp["y"], exp["score"])
            assert got == want, f"case {rec['id']} ({rec['category']}): got {got} want {want}"
            if PREC == 0 and not rec["expected"]["no_move"]:
                assert want == (rec["expected"]["rotation"], rec["expected"]["x"], rec["expected"]["y"], rec["expected"]["score"]), \
                    "committed corpus expectation is stale; regenerate with tools/make_corpus.py"
        assert fields["cycles"] == edges, f"case {rec['id']}: cycles_o {fields['cycles']} != measured {edges}"
        results.append({"state_id": rec["id"], "category": rec["category"], "core_cycles": edges,
                        "root_candidates": len(candidate_ids(piece)), "no_move": fields["no_move"],
                        "rotation": fields["rotation"], "x": fields["x"], "y": fields["y"], "score": fields["score"]})
    if RESULTS:
        with open(RESULTS, "w") as fh:
            json.dump(results, fh)
    cyc = [r["core_cycles"] for r in results]
    dut._log.info(f"{len(results)} requests: cycles min {min(cyc)} median {sorted(cyc)[len(cyc) // 2]} max {max(cyc)}")
