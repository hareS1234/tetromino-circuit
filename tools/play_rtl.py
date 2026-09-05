#!/usr/bin/env python3
"""Play a complete game with the RTL core as the decision engine.

    python tools/play_rtl.py --arch 0 --driver native --seed 2000 --max-pieces 250 --out results/rtl_demo.jsonl
    python tools/play_rtl.py --arch 0 --driver cocotb --seed 2000 --max-pieces 50 --out results/rtl_cocotb.jsonl

Every move is checked against the Python reference (same decision, same landing, same
post-clear board) before it is applied.  The simulator process persists for the whole game.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import lookahead, policy  # noqa: E402
from model.config import Config, add_config_arguments, validate  # noqa: E402
from model.native import NativeCore  # noqa: E402
from model.replay import metadata, play_game, read_replay, write_replay  # noqa: E402
from model.streams import load_stream  # noqa: E402
from tools.build_native import build  # noqa: E402


def reference(rows, piece, nxt, cfg: Config):
    if cfg.depth == 2:
        return lookahead.best_move_depth2(rows, piece, nxt, cfg.precision)
    return policy.best_move(rows, piece, cfg.precision)


def play_native(cfg: Config, seed: int, cap: int, out: Path, max_cycles: int):
    stream = load_stream(ROOT, seed)
    exe = build(cfg, ROOT / f"build/native_{cfg.id}")
    mismatches = []
    with NativeCore(exe, max_cycles=max_cycles) as core:
        def decide(rows, piece, nxt):
            rsp = core.request(rows, piece, nxt if nxt is not None else (piece + 3) % 7)
            exp = reference(rows, piece, nxt, cfg)
            if rsp["error"]:
                raise RuntimeError("core reported an error for a valid piece")
            if rsp["no_move"]:
                if exp is not None:
                    raise RuntimeError(f"core reported no move but the reference found {exp}")
                return None
            if exp is None:
                raise RuntimeError("core returned a move where the reference has none")
            got = (rsp["rotation"], rsp["x"], rsp["y"], rsp["score"])
            want = (exp["rotation"], exp["x"], exp["y"], exp["score"])
            if got != want:
                raise RuntimeError(f"decision mismatch: RTL {got} reference {want} on {rows} piece {piece}")
            rec = dict(exp)
            rec["cycles"] = rsp["cycles"]
            rec["interval"] = rsp["interval"]
            return rec
        t0 = time.perf_counter()
        records, terminal = play_game(decide, stream, cap, depth=cfg.depth)
        elapsed = time.perf_counter() - t0
    meta = metadata(backend="rtl-native", policy_name="heuristic", seed=seed, stream_doc=stream, max_pieces=cap,
                    depth=cfg.depth, precision=cfg.precision, arch=cfg.arch, board_repr=cfg.board_repr, lanes=cfg.lanes,
                    root=ROOT, extra={"config_id": cfg.id, "driver": "native", "wall_seconds": round(elapsed, 3),
                                      "checked_against": "python literal-descent reference at every move",
                                      "total_cycles": sum(r["cycles"] for r in records)})
    write_replay(out, meta, records, terminal)
    return records, terminal, elapsed


def play_cocotb(cfg: Config, seed: int, cap: int, out: Path):
    cmd = ["bash", str(ROOT / "scripts/env.sh"), "python", "tools/run_rtl.py", "--top", "tetris_core", "--test", "tb_play",
           "--files-f", "rtl/files.f", "--env", f"TETROMINO_SEED={seed}", "--env", f"TETROMINO_CAP={cap}",
           "--env", f"TETROMINO_REPLAY={out}"]
    for k, v in cfg.params().items():
        cmd += ["--param", f"{k}={v}"]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        print("\n".join((proc.stdout + proc.stderr).splitlines()[-30:]))
        raise SystemExit("cocotb replay failed")
    meta, records, terminal = read_replay(out)
    return records, terminal, time.perf_counter() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    add_config_arguments(ap)
    ap.add_argument("--driver", default="native", choices=["native", "cocotb"])
    ap.add_argument("--seed", type=int, default=2000)
    ap.add_argument("--max-pieces", type=int, default=250)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-cycles", type=int, default=None)
    args = ap.parse_args()
    cfg = validate(Config(args.arch, args.board_repr, args.lanes, args.depth, args.precision))
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    max_cycles = args.max_cycles or (4_000_000 if cfg.depth == 2 else 60_000)
    if args.driver == "native":
        records, terminal, elapsed = play_native(cfg, args.seed, args.max_pieces, out, max_cycles)
    else:
        records, terminal, elapsed = play_cocotb(cfg, args.seed, args.max_pieces, out)
    cyc = [r["cycles"] for r in records]
    print(f"{cfg.id} {args.driver} seed {args.seed}: {terminal['pieces_locked']} pieces, {terminal['lines']} lines, "
          f"{terminal['reason']}; cycles/decision min {min(cyc)} median {sorted(cyc)[len(cyc) // 2]} max {max(cyc)}; "
          f"{elapsed:.1f}s wall -> {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
