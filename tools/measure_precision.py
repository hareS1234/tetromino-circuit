#!/usr/bin/env python3
"""Validation pilot for the numerical profiles (Python fast model, A1-equivalent policy):
lines per game on validation streams, disagreement with exact on the corpus, and one explained
divergence replay (first move on seed 2000 where a profile differs from exact) rendered as a
two-panel tournament with the candidate scores at the divergence."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import policy  # noqa: E402
from model.numeric import PROFILES  # noqa: E402
from model.replay import git_commit, make_decider, metadata, play_game, write_replay  # noqa: E402
from model.streams import SPLITS, load_stream  # noqa: E402


def games(precision: int, seeds, cap: int):
    rows = []
    for seed in seeds:
        stream = load_stream(ROOT, seed)
        records, terminal = play_game(make_decider("heuristic", 1, precision, seed, "fast"), stream, cap)
        rows.append({"commit": git_commit(ROOT), "spec": stream["spec"], "backend": "python-fast", "experiment": "precision_pilot",
                     "policy": "heuristic", "depth": 1, "precision": precision, "stream_seed": seed,
                     "stream_sha256": stream["sha256"], "cap": cap, "lines": terminal["lines"],
                     "pieces_locked": terminal["pieces_locked"], "terminal_reason": terminal["reason"]})
    return rows


def divergence(seed: int, precision: int, cap: int):
    """Replays of P0 and the profile on the same stream and the first move where they differ."""
    stream = load_stream(ROOT, seed)
    out = {}
    for p in (0, precision):
        records, terminal = play_game(make_decider("heuristic", 1, p, seed, "fast"), stream, cap)
        path = ROOT / "results" / f"divergence_seed{seed}_p{p}.jsonl"
        write_replay(path, metadata(backend="python-fast", policy_name="heuristic", seed=seed, stream_doc=stream,
                                    max_pieces=cap, precision=p, root=ROOT), records, terminal)
        out[p] = (path, records)
    a, b = out[0][1], out[precision][1]
    for i, (ra, rb) in enumerate(zip(a, b)):
        if (ra["rotation"], ra["x"]) != (rb["rotation"], rb["x"]):
            rows = tuple(ra["rows_before"])
            piece = ra["piece_id"]
            cands0 = policy.evaluate_candidates(rows, piece, 0)
            candsp = policy.evaluate_candidates(rows, piece, precision)
            explain = {
                "seed": seed, "move_index": i, "piece": piece, "rows_before": list(rows),
                "exact_choice": {k: ra[k] for k in ("rotation", "x", "y", "lines", "score")},
                "profile_choice": {k: rb[k] for k in ("rotation", "x", "y", "lines", "score")},
                "candidates_exact": [{k: c[k] for k in ("candidate_id", "rotation", "x", "y", "lines", "A", "Q", "U", "score")} for c in cands0],
                "candidates_profile": [{k: c[k] for k in ("candidate_id", "rotation", "x", "y", "lines", "A", "Q_used", "U_used", "score")} for c in candsp],
                "replays": {"exact": str(out[0][0].relative_to(ROOT)), "profile": str(out[precision][0].relative_to(ROOT))},
            }
            return explain
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="validation", choices=list(SPLITS))
    ap.add_argument("--cap", type=int, default=500)
    ap.add_argument("--divergence-profile", type=int, default=1)
    args = ap.parse_args()
    seeds = list(SPLITS[args.split])
    rows = []
    for p in sorted(PROFILES):
        rows += games(p, seeds, args.cap)
        lines = [r["lines"] for r in rows if r["precision"] == p]
        caps = sum(r["terminal_reason"] == "cap_reached" for r in rows if r["precision"] == p)
        print(f"P{p} {PROFILES[p].name:14s} mean {statistics.mean(lines):7.2f} median {statistics.median(lines):6.1f} "
              f"min {min(lines):4d} cap_hit {caps}/{len(lines)}")
    out = ROOT / "results" / f"precision_{args.split}_cap{args.cap}.csv"
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("->", out.relative_to(ROOT))
    for p in (args.divergence_profile,):
        exp = divergence(seeds[0], p, args.cap)
        if exp is None:
            print(f"P{p}: no divergence from exact on seed {seeds[0]} within {args.cap} pieces")
            continue
        path = ROOT / "results" / f"precision_divergence_p{p}.json"
        path.write_text(json.dumps(exp, indent=1) + "\n")
        print(f"P{p} diverges from exact at move {exp['move_index']} (piece {exp['piece']}): exact {exp['exact_choice']} vs profile {exp['profile_choice']} -> {path.relative_to(ROOT)}")
        gif = ROOT / "assets" / f"divergence_p0_vs_p{p}.gif"
        subprocess.run(["bash", str(ROOT / "scripts/env.sh"), "python", "tools/render_tournament.py", "--replays",
                        exp["replays"]["exact"], exp["replays"]["profile"], "--sync", "pieces", "--out",
                        str(gif.relative_to(ROOT)), "--max-frames", "150"], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
