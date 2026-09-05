#!/usr/bin/env python3
"""Differential core tests on the committed corpus for one configuration.

    python tools/test_core.py --arch 0 --count 50 --driver cocotb|native|both

cocotb: runs tb/tb_core.py inside the simulator.  native: drives the persistent C++ harness.
both: runs both and requires every response field and cycle count to agree.  Depth-two
configurations use the depth-two corpus and the depth-two reference.  Per-decision rows are
written to build/decisions/<config>_<driver>_<count>.csv (manual Section 7 columns) unless --out
names a path; the frozen v1 corpora live in results/decisions/ and are not rewritten.
"""
from __future__ import annotations

import argparse
import csv
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
from model.pieces import candidate_ids  # noqa: E402
from model.replay import git_commit  # noqa: E402
from tools.build_native import build  # noqa: E402

DECISION_FIELDS = ["commit", "arch", "board_repr", "lanes", "depth", "precision", "state_id", "category",
                   "root_candidates", "leaf_candidates", "rotation", "x", "y", "score", "no_move", "core_cycles",
                   "request_interval_cycles", "driver"]


def load_corpus(depth: int, count: int):
    path = ROOT / "benchmarks" / "states" / ("corpus_d2.jsonl" if depth == 2 else "corpus_d1.jsonl")
    recs = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if count > len(recs):
        raise SystemExit(f"corpus has {len(recs)} distinct cases; {count} requested")
    by_cat = {}
    for r in recs:
        by_cat.setdefault(r["category"], []).append(r)
    out = []
    while len(out) < count:
        for cat in sorted(by_cat):
            if by_cat[cat] and len(out) < count:
                out.append(by_cat[cat].pop(0))
    return out


def expected(rec, cfg: Config):
    rows = tuple(rec["rows"])
    if cfg.depth == 2:
        e = lookahead.best_move_depth2(rows, rec["piece"], rec["next_piece"], cfg.precision)
    else:
        e = policy.best_move(rows, rec["piece"], cfg.precision)
    if e is None:
        return {"error": 0, "no_move": 1, "rotation": 0, "x": 0, "y": 0, "score": 0}
    return {"error": 0, "no_move": 0, "rotation": e["rotation"], "x": e["x"], "y": e["y"], "score": e["score"]}


def run_native(cfg: Config, corpus, max_cycles: int):
    exe = build(cfg, ROOT / f"build/native_{cfg.id}")
    out = []
    t0 = time.perf_counter()
    with NativeCore(exe, max_cycles=max_cycles) as core:
        for rec in corpus:
            nxt = rec.get("next_piece", (rec["piece"] + 3) % 7)
            out.append(core.request(tuple(rec["rows"]), rec["piece"], nxt))
    elapsed = time.perf_counter() - t0
    total_cycles = sum(r["cycles"] for r in out)
    print(f"native: {len(out)} requests, {total_cycles} cycles in {elapsed:.2f}s "
          f"({total_cycles / max(elapsed, 1e-9) / 1e6:.2f} Mcycles/s host rate)")
    return out


def run_cocotb(cfg: Config, count: int):
    results = ROOT / "build" / f"core_results_{cfg.id}.json"
    if results.exists():
        results.unlink()
    cmd = ["bash", str(ROOT / "scripts/env.sh"), "python", "tools/run_rtl.py", "--top", "tetris_core", "--test",
           "tb_core" if cfg.depth == 1 else "tb_lookahead", "--files-f", "rtl/files.f",
           "--env", f"TETROMINO_COUNT={count}", "--env", f"TETROMINO_RESULTS={results}"]
    for k, v in cfg.params().items():
        cmd += ["--param", f"{k}={v}"]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-25:])
    if proc.returncode != 0:
        print(tail)
        raise SystemExit("cocotb core test failed")
    print("\n".join(line for line in tail.splitlines() if "RTL tests" in line or "requests:" in line))
    print(f"cocotb: {time.perf_counter() - t0:.1f}s wall")
    return json.loads(results.read_text())


def write_rows(cfg: Config, driver: str, corpus, responses, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    commit = git_commit(ROOT)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=DECISION_FIELDS)
        w.writeheader()
        for rec, rsp in zip(corpus, responses):
            w.writerow({"commit": commit, "arch": cfg.arch, "board_repr": cfg.board_repr, "lanes": cfg.lanes,
                        "depth": cfg.depth, "precision": cfg.precision, "state_id": rec["id"], "category": rec["category"],
                        "root_candidates": len(candidate_ids(rec["piece"])),
                        "leaf_candidates": len(candidate_ids(rec["next_piece"])) if cfg.depth == 2 else 0,
                        "rotation": rsp["rotation"], "x": rsp["x"], "y": rsp["y"], "score": rsp["score"],
                        "no_move": rsp["no_move"], "core_cycles": rsp.get("cycles", rsp.get("core_cycles")),
                        "request_interval_cycles": rsp.get("interval", ""), "driver": driver})


def main() -> int:
    ap = argparse.ArgumentParser()
    add_config_arguments(ap)
    ap.add_argument("--count", type=int, default=50)
    ap.add_argument("--driver", default="native", choices=["native", "cocotb", "both"])
    ap.add_argument("--max-cycles", type=int, default=None)
    ap.add_argument("--out", default=None, help="native decision CSV path (default build/decisions/<config>_native_<count>.csv)")
    args = ap.parse_args()
    cfg = validate(Config(args.arch, args.board_repr, args.lanes, args.depth, args.precision))
    max_cycles = args.max_cycles or (4_000_000 if cfg.depth == 2 else (60_000 if cfg.arch == 0 else 10_000))
    corpus = load_corpus(cfg.depth, args.count)

    native = cocotb_rsp = None
    if args.driver in ("native", "both"):
        native = run_native(cfg, corpus, max_cycles)
        mism = 0
        for rec, rsp in zip(corpus, native):
            exp = expected(rec, cfg)
            got = {k: rsp[k] for k in exp}
            if got != exp:
                mism += 1
                if mism <= 5:
                    print(f"MISMATCH case {rec['id']} ({rec['category']}): got {got} expected {exp}")
        if mism:
            raise SystemExit(f"native: {mism} of {len(corpus)} decisions disagree with the reference")
        cyc = sorted(r["cycles"] for r in native)
        print(f"native: all {len(corpus)} decisions match; cycles min {cyc[0]} median {cyc[len(cyc) // 2]} max {cyc[-1]}")
        write_rows(cfg, "native", corpus, native, ROOT / args.out if args.out else ROOT / "build" / "decisions" / f"{cfg.id}_native_{args.count}.csv")
    if args.driver in ("cocotb", "both"):
        cocotb_rsp = run_cocotb(cfg, args.count)
        write_rows(cfg, "cocotb", corpus, cocotb_rsp, ROOT / "build" / "decisions" / f"{cfg.id}_cocotb_{args.count}.csv")
    if args.driver == "both":
        diff = 0
        for rec, a, b in zip(corpus, native, cocotb_rsp):
            for k in ("rotation", "x", "y", "score", "no_move"):
                if a[k] != b[k]:
                    diff += 1
            if a["cycles"] != b["core_cycles"]:
                diff += 1
                print(f"cycle mismatch case {rec['id']}: native {a['cycles']} cocotb {b['core_cycles']}")
        if diff:
            raise SystemExit(f"drivers disagree on {diff} fields")
        print(f"drivers agree on all response fields and cycle counts for {len(corpus)} requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
