#!/usr/bin/env python3
"""Resumable orchestrator of the documented release pipeline (no second implementation path:
every step is an existing Make target or tool).  Steps whose outputs exist for the current
source identity are skipped; a failed step stops the run and is reported."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "results" / "reproduce_state.json"

STEPS = [
    ("doctor", ["make", "doctor"]),
    ("gen", ["make", "gen"]),
    ("streams-check", ["python", "tools/make_streams.py", "--check"]),
    ("smoke", ["make", "smoke"]),
    ("test-python", ["make", "test-python"]),
    ("test-rtl", ["make", "test-rtl"]),
    ("demo-python", ["make", "tournament-python"]),
    ("pilot-python", ["make", "pilot-python"]),
    ("replays-a0", ["make", "replay-suite", "ARCH=0", "CAP=250"]),
    ("demo-rtl", ["make", "demo-rtl"]),
    ("wrapper", ["make", "test-wrapper"]),
    ("fast", ["make", "test-fast"]),
    ("cache", ["make", "test-cache"]),
    ("precision", ["python", "tools/test_precision.py", "--skip-candidate"]),
    ("lookahead-ref", ["make", "test-lookahead-reference"]),
    ("lookahead-rtl", ["make", "test-lookahead-rtl"]),
    ("lanes", ["make", "test-lanes"]),
    ("bench-config", ["make", "check-benchmark-config"]),
    # The v1 study (precision/depth suites, 45-route matrix) is frozen: it is validated, not re-run.
    ("check-v1-results", ["make", "check-v1-results"]),
    ("tournament", ["make", "tournament"]),
    ("plots", ["make", "plots"]),
    ("report", ["python", "tools/write_report.py"]),
    ("check-report", ["make", "check-report"]),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-step", default=None)
    ap.add_argument("--only", default=None, help="comma-separated step names")
    ap.add_argument("--fresh", action="store_true", help="ignore recorded progress")
    args = ap.parse_args()
    state = {} if args.fresh or not STATE.is_file() else json.loads(STATE.read_text())
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    only = set(args.only.split(",")) if args.only else None
    started = args.from_step is None
    for name, cmd in STEPS:
        if name == args.from_step:
            started = True
        if not started or (only and name not in only):
            continue
        rec = state.get(name)
        if rec and rec.get("status") == "passed" and rec.get("commit") == commit and not args.fresh:
            print(f"[skip] {name} (passed at this commit)")
            continue
        print(f"[run ] {name}: {' '.join(cmd)}")
        t0 = time.perf_counter()
        proc = subprocess.run(["bash", str(ROOT / "scripts/env.sh")] + cmd, cwd=ROOT)
        state[name] = {"status": "passed" if proc.returncode == 0 else "failed", "exit": proc.returncode,
                       "elapsed_s": round(time.perf_counter() - t0, 1), "commit": commit}
        STATE.write_text(json.dumps(state, indent=1) + "\n")
        if proc.returncode != 0:
            print(f"[fail] {name} exited {proc.returncode}; fix and rerun `make reproduce` (resumes here)")
            return 1
        print(f"[ok  ] {name} ({state[name]['elapsed_s']}s)")
    print("reproduce: all steps passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
