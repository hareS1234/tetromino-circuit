#!/usr/bin/env python3
"""Play one game with a software policy and write a replay JSONL.

    python tools/play.py --backend python --policy heuristic --seed 2000 --max-pieces 250 --out results/python_demo.jsonl
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.replay import make_decider, metadata, play_game, write_replay  # noqa: E402
from model.streams import load_stream  # noqa: E402

POLICIES = ("heuristic", "random_legal", "lowest_stack")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="python", choices=["python"], help="RTL backends live in tools/play_rtl.py")
    ap.add_argument("--policy", default="heuristic", choices=POLICIES)
    ap.add_argument("--seed", type=int, default=2000)
    ap.add_argument("--max-pieces", type=int, default=250)
    ap.add_argument("--depth", type=int, default=1, choices=[1, 2])
    ap.add_argument("--precision", type=int, default=0, choices=[0, 1, 2, 3, 4])
    ap.add_argument("--engine", default="fast", choices=["fast", "reference"],
                    help="fast = column-bitmask model; reference = literal-descent readable model")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    stream = load_stream(ROOT, args.seed)
    decide = make_decider(args.policy, args.depth, args.precision, args.seed, args.engine)
    t0 = time.perf_counter()
    records, terminal = play_game(decide, stream, args.max_pieces, depth=args.depth)
    elapsed = time.perf_counter() - t0
    meta = metadata(backend=f"python-{args.engine}", policy_name=args.policy, seed=args.seed, stream_doc=stream,
                    max_pieces=args.max_pieces, depth=args.depth, precision=args.precision, root=ROOT,
                    extra={"wall_seconds": round(elapsed, 3)})
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    write_replay(out, meta, records, terminal)
    shown = out.relative_to(ROOT) if out.is_relative_to(ROOT) else out
    print(f"{args.policy} d{args.depth} p{args.precision} seed {args.seed}: {terminal['pieces_locked']} pieces, "
          f"{terminal['lines']} lines, {terminal['reason']} ({elapsed:.2f}s) -> {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
