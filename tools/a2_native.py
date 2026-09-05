#!/usr/bin/env python3
"""Generate oracle vectors, build the native candidate-pipeline harness, run a phase (U09).

    python tools/a2_native.py --phase all|stream|traffic|metadata|reset [--contexts 60] [--seed 2024]
    python tools/a2_native.py --phase all --trace results/traces/a2_stall_reset.vcd
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.a2_vectors import write_vectors  # noqa: E402
from tools.build_native import build_harness  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="all", choices=["all", "stream", "traffic", "metadata", "reset"])
    ap.add_argument("--contexts", type=int, default=60)
    ap.add_argument("--seed", type=int, default=2024)
    ap.add_argument("--stream", type=int, default=4096)
    ap.add_argument("--stalls", type=int, default=30)
    ap.add_argument("--bubbles", type=int, default=20)
    ap.add_argument("--trace", default=None, help="write a bounded VCD of the stall/reset scenario (builds with --trace)")
    ap.add_argument("--jobs", type=int, default=2)
    args = ap.parse_args()
    vec = ROOT / "build" / "a2_vectors" / f"ctx{args.contexts}_seed{args.seed}.txt"
    info = write_vectors(vec, args.contexts, args.seed, 6)
    print(f"vectors: {info} -> {vec.relative_to(ROOT)}")
    exe = build_harness("candidate_pipe", "rtl/files_candidate_pipe.f", "sim/candidate_pipe_main.cpp", jobs=args.jobs,
                        waivers=["-Wall"], trace=bool(args.trace))
    plus = [f"+vectors={vec}", f"+phase={args.phase}", f"+stream={args.stream}", f"+seed={args.seed}", f"+stalls={args.stalls}", f"+bubbles={args.bubbles}"]
    if args.trace:
        Path(ROOT / args.trace).parent.mkdir(parents=True, exist_ok=True)
        plus.append(f"+trace={ROOT / args.trace}")
    t0 = time.perf_counter()
    proc = subprocess.run([str(exe), *plus], cwd=ROOT, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    print(f"({time.perf_counter() - t0:.1f}s wall, {exe.relative_to(ROOT)})")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
