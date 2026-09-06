#!/usr/bin/env python3
"""Run the native compactor exhaustively, randomly, or as a stalled stream."""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.build_native import build_harness  # noqa: E402

# the new modules are built with no warning waivers at all: any warning is a build failure
STRICT = ["-Wall"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="exhaustive", choices=["exhaustive", "random", "stream"])
    ap.add_argument("--count", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--stalls", type=int, default=None, help="stream mode: percent of stalled output cycles")
    ap.add_argument("--bubbles", type=int, default=None, help="stream mode: percent of input bubbles")
    ap.add_argument("--jobs", type=int, default=2)
    args = ap.parse_args()
    if args.mode == "stream":
        exe = build_harness("line_clear_pipe_harness", "rtl/files_compactor_pipe.f", "sim/compactor_pipe_main.cpp", jobs=args.jobs, waivers=STRICT)
        plus = [f"+count={args.count}", f"+seed={args.seed}"]
        if args.stalls is not None:
            plus.append(f"+stalls={args.stalls}")
        if args.bubbles is not None:
            plus.append(f"+bubbles={args.bubbles}")
    else:
        exe = build_harness("line_clear_parallel", "rtl/files_compactor.f", "sim/compactor_main.cpp", jobs=args.jobs, waivers=STRICT)
        plus = [f"+mode={args.mode}", f"+count={args.count}", f"+seed={args.seed}"]
    t0 = time.perf_counter()
    proc = subprocess.run([str(exe), *plus], cwd=ROOT, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    print(f"({time.perf_counter() - t0:.1f}s wall, {exe.relative_to(ROOT)})")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
