"""LANES=2: identical decisions to the reference (hence to one lane), equal-score winners split
across lanes, the winning lane finishing last, and per-lane candidate/active-cycle counters."""
import json
import os

import cocotb

from common import ROOT, param, reset
from core_driver import idle_inputs, request
from model import policy
from model.pieces import candidate_ids

LANES = param("LANES", 1)
assert LANES == 2, "tb_lanes requires LANES=2"
COUNT = int(os.environ.get("TETROMINO_COUNT", "300"))
TIMEOUT = 5000


def corpus():
    path = ROOT / "benchmarks" / "states" / "corpus_d1.jsonl"
    recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    ties = [r for r in recs if r["category"] == "equal_scores"]
    last = [r for r in recs if r["category"] == "last_candidate_winner"]
    rest = [r for r in recs if r["category"] not in ("equal_scores", "last_candidate_winner")]
    return (ties + last + rest)[:COUNT]


def lane(dut, k):
    return getattr(dut.g_d1, f"g_lane[{k}]").u_lane


@cocotb.test()
async def two_lanes_match_reference_with_lane_stats(dut):
    idle_inputs(dut)
    await reset(dut)
    cross_lane_ties = 0
    winner_last = 0
    stats = []
    for rec in corpus():
        rows, piece = tuple(rec["rows"]), rec["piece"]
        exp = policy.best_move(rows, piece)
        fields, edges, _ = await request(dut, rows, piece, timeout=TIMEOUT)
        assert fields["error"] == 0
        if exp is None:
            assert fields["no_move"] == 1
            continue
        assert (fields["no_move"], fields["rotation"], fields["x"], fields["y"], fields["score"]) == \
            (0, exp["rotation"], exp["x"], exp["y"], exp["score"]), f"case {rec['id']}"
        ids = list(candidate_ids(piece))
        per_lane = []
        for k in range(2):
            L = lane(dut, k)
            per_lane.append({"evaluated": int(L.evaluated_o.value), "legal": int(L.legal_o.value),
                             "active": int(L.active_cycles_o.value), "best_valid": int(L.best_valid_o.value),
                             "best_id": int(L.best_id_o.value), "best_score": int(L.best_score_o.value)})
        owned = [len(ids[k::2]) for k in range(2)]
        assert [p["evaluated"] for p in per_lane] == owned, f"case {rec['id']}: lane counts {per_lane} vs {owned}"
        # equal-score winners in different lanes exercise the global tie-break
        recs = policy.evaluate_candidates(rows, piece)
        best = max(r["score"] for r in recs)
        tied = sorted(r["candidate_id"] for r in recs if r["score"] == best)
        lanes_of_tied = {ids.index(c) % 2 for c in tied}
        if len(tied) >= 2 and len(lanes_of_tied) == 2:
            cross_lane_ties += 1
        winner_lane = ids.index(exp["candidate_id"]) % 2
        if per_lane[winner_lane]["active"] >= per_lane[1 - winner_lane]["active"]:
            winner_last += 1
        stats.append({"state_id": rec["id"], "cycles": edges, "lane0": per_lane[0], "lane1": per_lane[1]})
    assert cross_lane_ties > 0, "no equal-score case with tied candidates in different lanes"
    assert winner_last > 0, "no case where the winning lane finished last"
    out = ROOT / "results" / "lanes2_stats.json"
    out.write_text(json.dumps({"cases": len(stats), "cross_lane_ties": cross_lane_ties, "winner_lane_finished_last": winner_last,
                               "stats": stats}, indent=1) + "\n")
    dut._log.info(f"{len(stats)} cases; cross-lane ties {cross_lane_ties}; winner lane finished last in {winner_last}")
