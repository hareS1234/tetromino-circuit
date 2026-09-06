"""Lane ownership and global reduction when two or four A1 evaluators run together."""
import json
import os

import cocotb

from common import ROOT, param, reset
from core_driver import idle_inputs, request
from model import policy
from model.pieces import candidate_ids

LANES = param("LANES", 1)
assert LANES in (2, 4), "tb_lanes requires LANES=2 or LANES=4"
COUNT = int(os.environ.get("TETROMINO_COUNT", "300"))
TIMEOUT = 5000
EXPECTED_OWNERSHIP = {4: {9: [3, 2, 2, 2], 17: [5, 4, 4, 4], 34: [9, 9, 8, 8]}, 2: {9: [5, 4], 17: [9, 8], 34: [17, 17]}}


def corpus():
    path = ROOT / "benchmarks" / "states" / "corpus_d1.jsonl"
    recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    first = ("equal_scores", "last_candidate_winner", "no_move", "blocked_spawn")
    picked = [r for cat in first for r in recs if r["category"] == cat]
    rest = [r for r in recs if r["category"] not in first]
    return (picked + rest)[:COUNT]


def lane(dut, k):
    return getattr(dut.g_d1, f"g_lane[{k}]").u_lane


@cocotb.test()
async def lanes_match_reference_with_ownership_and_lane_stats(dut):
    idle_inputs(dut)
    await reset(dut)
    cross_lane_ties = winner_last_or_tied = winner_strictly_last = invalid_local_best = unequal_finish = 0
    stats = []
    for rec in corpus():
        rows, piece = tuple(rec["rows"]), rec["piece"]
        exp = policy.best_move(rows, piece)
        fields, edges, _ = await request(dut, rows, piece, timeout=TIMEOUT)
        assert fields["error"] == 0
        ids = list(candidate_ids(piece))
        owned_sets = [ids[k::LANES] for k in range(LANES)]
        assert sorted(sum(owned_sets, [])) == ids and len(set(sum(owned_sets, []))) == len(ids), "ownership must partition the dense list"
        assert [len(s) for s in owned_sets] == EXPECTED_OWNERSHIP[LANES][len(ids)], f"ownership counts for N={len(ids)}"
        per_lane = []
        for k in range(LANES):
            L = lane(dut, k)
            per_lane.append({"evaluated": int(L.evaluated_o.value), "legal": int(L.legal_o.value),
                             "active": int(L.active_cycles_o.value), "best_valid": int(L.best_valid_o.value),
                             "best_id": int(L.best_id_o.value), "best_score": int(L.best_score_o.value)})
        assert [p["evaluated"] for p in per_lane] == [len(s) for s in owned_sets], f"case {rec['id']}: lane counts {per_lane}"
        invalid_local_best += sum(1 for p in per_lane if p["best_valid"] == 0)
        if len({p["active"] for p in per_lane}) > 1:
            unequal_finish += 1
        if exp is None:
            assert fields["no_move"] == 1 and all(p["best_valid"] == 0 for p in per_lane)
            continue
        assert (fields["no_move"], fields["rotation"], fields["x"], fields["y"], fields["score"]) == \
            (0, exp["rotation"], exp["x"], exp["y"], exp["score"]), f"case {rec['id']}"
        recs = policy.evaluate_candidates(rows, piece)
        best = max(r["score"] for r in recs)
        tied = sorted(r["candidate_id"] for r in recs if r["score"] == best)
        lanes_of_tied = {ids.index(c) % LANES for c in tied}
        if len(tied) >= 2 and len(lanes_of_tied) >= 2:
            cross_lane_ties += 1
        winner_lane = ids.index(exp["candidate_id"]) % LANES
        others = [p["active"] for k, p in enumerate(per_lane) if k != winner_lane]
        if per_lane[winner_lane]["active"] >= max(others):
            winner_last_or_tied += 1
        if per_lane[winner_lane]["active"] > max(others):
            winner_strictly_last += 1
        stats.append({"state_id": rec["id"], "cycles": edges, "winner_lane": winner_lane, "lanes": per_lane})
    assert cross_lane_ties > 0, "no equal-score case with tied candidates in different lanes"
    assert winner_strictly_last > 0, "no strict witness of the winning lane finishing last"
    assert invalid_local_best > 0, "no lane ever had an invalid local best (no legal candidate in its set)"
    assert unequal_finish > 0, "lanes always finished together"
    out = ROOT / "results" / "v2" / "lanes" / f"lanes{LANES}_stats.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"lanes": LANES, "cases": len(stats), "cross_lane_ties": cross_lane_ties,
                               "winner_lane_finished_last_or_tied": winner_last_or_tied, "winner_lane_finished_strictly_last": winner_strictly_last,
                               "invalid_local_bests": invalid_local_best, "unequal_finish_cases": unequal_finish,
                               "ownership": EXPECTED_OWNERSHIP[LANES], "stats": stats}, indent=1) + "\n")
    dut._log.info(f"LANES={LANES}: {len(stats)} cases; cross-lane ties {cross_lane_ties}; winner strictly last {winner_strictly_last} "
                  f"(last-or-tied {winner_last_or_tied}); invalid local bests {invalid_local_best}; unequal finishes {unequal_finish}")
