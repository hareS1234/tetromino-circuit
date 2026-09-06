#!/usr/bin/env python3
"""Check P1–P4 against their own arithmetic; disagreement with P0 is an outcome, not a failure."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import policy  # noqa: E402

PROFILES = (1, 2, 3, 4)


def run(cmd):
    proc = subprocess.run(["bash", str(ROOT / "scripts/env.sh")] + cmd, cwd=ROOT, capture_output=True, text=True)
    tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-3:])
    if proc.returncode != 0:
        print(proc.stdout[-3000:], proc.stderr[-2000:])
        raise SystemExit(f"failed: {' '.join(cmd)}")
    return tail


def disagreement(prec: int, count: int = 1000):
    path = ROOT / "benchmarks" / "states" / "corpus_d1.jsonl"
    recs = [json.loads(line) for line in path.read_text().splitlines() if line.strip()][:count]
    differ = 0
    legal = 0
    for r in recs:
        rows, piece = tuple(r["rows"]), r["piece"]
        a = policy.best_move(rows, piece, 0)
        b = policy.best_move(rows, piece, prec)
        assert (a is None) == (b is None), "a profile changed legality"
        if a is None:
            continue
        legal += 1
        if (a["rotation"], a["x"]) != (b["rotation"], b["x"]):
            differ += 1
    return differ, legal


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", default="1,2,3,4")
    ap.add_argument("--skip-candidate", action="store_true", help="skip the 16,200-case evaluator test (fast iteration)")
    args = ap.parse_args()
    summary = {}
    for p in [int(x) for x in args.profiles.split(",")]:
        print(f"== PRECISION {p} ==")
        print(run(["make", "test-score", f"PRECISION={p}"]).splitlines()[-1])
        print(run(["python", "tools/run_rtl.py", "--top", "fast_tb", "--test", "tb_fast", "--files-f", "rtl/files_fast.f",
                   "--param", f"PRECISION={p}"]).splitlines()[-1])
        if not args.skip_candidate:
            print(run(["make", "test-candidate", "ARCH=1", "BOARD_REPR=1", f"PRECISION={p}"]).splitlines()[-1])
        print(run(["python", "tools/test_core.py", "--arch", "1", "--board-repr", "1", "--precision", str(p),
                   "--count", "250", "--driver", "native"]).splitlines()[-1])
        d, n = disagreement(p)
        summary[p] = {"disagree_with_p0": d, "legal_states": n, "rate": round(d / n, 4)}
        print(f"profile {p}: chooses a different move from P0 on {d}/{n} corpus states ({100 * d / n:.1f}%)")
    out = ROOT / "results" / "precision_disagreement.json"
    out.write_text(json.dumps(summary, indent=1) + "\n")
    print("->", out.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
