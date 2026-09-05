#!/usr/bin/env python3
"""Validation pilot: play every policy on a split with a common cap; write per-game CSV."""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.replay import git_commit, make_decider, play_game  # noqa: E402
from model.streams import SPLITS, load_stream  # noqa: E402


def run(policies, seeds, cap, depth=1, precision=0):
    rows = []
    for policy_name in policies:
        for seed in seeds:
            stream = load_stream(ROOT, seed)
            decide = make_decider(policy_name, depth, precision, seed, "fast")
            t0 = time.perf_counter()
            records, terminal = play_game(decide, stream, cap, depth=depth)
            rows.append({"commit": git_commit(ROOT), "spec": stream["spec"], "backend": "python-fast",
                         "experiment": "pilot", "policy": policy_name, "depth": depth, "precision": precision,
                         "stream_seed": seed, "stream_sha256": stream["sha256"], "cap": cap,
                         "lines": terminal["lines"], "pieces_locked": terminal["pieces_locked"],
                         "terminal_reason": terminal["reason"], "wall_seconds": round(time.perf_counter() - t0, 3)})
    return rows


def summarise(rows):
    out = []
    for policy_name in sorted({r["policy"] for r in rows}):
        sub = [r for r in rows if r["policy"] == policy_name]
        lines = [r["lines"] for r in sub]
        out.append(f"{policy_name:14s} games {len(sub):3d}  mean {statistics.mean(lines):8.2f}  "
                   f"median {statistics.median(lines):8.1f}  cap_hit {sum(r['terminal_reason'] == 'cap_reached' for r in sub)}/{len(sub)}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="validation", choices=list(SPLITS))
    ap.add_argument("--cap", type=int, default=500)
    ap.add_argument("--policies", default="heuristic,random_legal,lowest_stack")
    ap.add_argument("--out", default="results/pilot_validation.csv")
    args = ap.parse_args()
    rows = run(args.policies.split(","), list(SPLITS[args.split]), args.cap)
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(summarise(rows))
    print("->", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
