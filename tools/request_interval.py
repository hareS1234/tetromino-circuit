#!/usr/bin/env python3
"""Measure the public request interval with two real acceptance edges (U10 step 6, guide §10.4).

    python tools/request_interval.py --arch 2 --board-repr 1 [--count 200]

For each pair of corpus states the second request is offered while the first is in flight and the
first response is consumed on the edge it appears; interval_measured is the number of rising edges
between the two acceptance edges.  It is compared with the inferred single-request interval
(cycles + 2 for this core) and, for A2, with the specification R(N) = D(N) + 2 = N + 31.  Decision
latency (cycles) is reported separately; candidate II = 1 is not a decision rate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import a2_token_model as tm  # noqa: E402
from model.config import Config, add_config_arguments, validate  # noqa: E402
from model.native import NativeCore  # noqa: E402
from model.pieces import candidate_ids  # noqa: E402
from tools.build_native import build  # noqa: E402
from tools.test_core import expected, load_corpus  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    add_config_arguments(ap)
    ap.add_argument("--count", type=int, default=200, help="number of request pairs")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    cfg = validate(Config(args.arch, args.board_repr, args.lanes, args.depth, args.precision))
    exe = build(cfg, ROOT / f"build/native_{cfg.id}", quiet=True)
    corpus = load_corpus(cfg.depth, 2 * args.count)
    rows_out = []
    bad = 0
    with NativeCore(exe, max_cycles=4_000_000) as core:
        for i in range(args.count):
            a, b = corpus[2 * i], corpus[2 * i + 1]
            single = core.request(tuple(a["rows"]), a["piece"], a.get("next_piece", 0))   # the existing inferred interval
            r1, r2 = core.request_pair(tuple(a["rows"]), a["piece"], a.get("next_piece", 0), tuple(b["rows"]), b["piece"], b.get("next_piece", 0))
            r1["interval"] = single["interval"]
            if single["cycles"] != r1["cycles"]:
                bad += 1
            for rec, rsp in ((a, r1), (b, r2)):
                exp = expected(rec, cfg)
                got = {k: rsp[k] for k in exp}
                if got != exp:
                    bad += 1
            n = len(candidate_ids(a["piece"]))
            rows_out.append({"state": a["id"], "piece": a["piece"], "N": n, "cycles": r1["cycles"], "interval_inferred": r1["interval"],
                             "interval_measured": r1["interval_measured"], "second_cycles": r2["cycles"],
                             "formula_R": tm.request_interval(n) if cfg.arch == 2 else None, "formula_D": tm.formula(n) if cfg.arch == 2 else None})
    agree = sum(1 for r in rows_out if r["interval_measured"] == r["interval_inferred"])
    formula_ok = sum(1 for r in rows_out if cfg.arch != 2 or (r["interval_measured"] == r["formula_R"] and r["cycles"] == r["formula_D"]))
    by_n = {}
    for r in rows_out:
        by_n.setdefault(r["N"], set()).add((r["cycles"], r["interval_measured"]))
    print(f"request interval ({cfg.id}): {len(rows_out)} pairs, decisions correct {2 * len(rows_out) - bad}/{2 * len(rows_out)}")
    for n in sorted(by_n):
        print(f"  N={n:2d}: (decision cycles, measured interval) = {sorted(by_n[n])}")
    print(f"CHECK request_interval_matches_inferred {agree}/{len(rows_out)}")
    if cfg.arch == 2:
        print(f"CHECK a2_latency_equation {formula_ok}/{len(rows_out)}  (D(N)=N+29 and R(N)=N+31)")
    doc = {"configuration_id": cfg.id, "pairs": rows_out, "agree_with_inferred": agree, "decisions_wrong": bad,
           "note": "interval_measured = edges between two real acceptance edges with the second request offered during the first and immediate consumption"}
    out = ROOT / (args.out or f"results/v2/raw/intervals/{cfg.id}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1) + "\n")
    return 0 if (bad == 0 and agree == len(rows_out) and formula_ok == len(rows_out)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
