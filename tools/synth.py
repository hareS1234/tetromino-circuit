#!/usr/bin/env python3
"""Yosys synth_ecp5 of a top module for one configuration.

    python tools/synth.py --top stream_wrapper --arch 1 --board-repr 1 --out build/synth_a1-cache-d1-p0-l1

Reads rtl/files.f, writes the expanded .ys script and log, and saves summary.json with the
cell counts.  Parameters are applied with `hierarchy -chparam` on the top and must be
forwarded explicitly down the hierarchy by the RTL.
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

from model.config import Config, SUPPORTED, add_config_arguments, validate  # noqa: E402
from tools.check_synth_log import parse_stat, summarize_ecp5  # noqa: E402
from tools.run_rtl import read_files_f  # noqa: E402

TOP_PARAMS = {
    "stream_wrapper": ("ARCH", "BOARD_REPR", "LANES", "DEPTH", "PRECISION"),
    "tetris_core": ("ARCH", "BOARD_REPR", "LANES", "DEPTH", "PRECISION"),
    "candidate_eval": ("ARCH", "BOARD_REPR", "PRECISION"),
}


def synthesize(top: str, cfg: Config, out: Path, files_f: str = "rtl/files.f") -> dict:
    out.mkdir(parents=True, exist_ok=True)
    sources = [str(ROOT / s) for s in read_files_f(ROOT / files_f)]
    params = cfg.params()
    chparam = " ".join(f"-chparam {k} {params[k]}" for k in TOP_PARAMS[top])
    script = "\n".join([
        f"read_verilog -sv -I{ROOT / 'rtl'} " + " ".join(sources),
        f"hierarchy -check -top {top} {chparam}",
        f"synth_ecp5 -top {top} -json {out / 'netlist.json'}",
        "stat",
        "check -assert",
        "",
    ])
    (out / "synth.ys").write_text(script)
    log = out / "yosys.log"
    t0 = time.perf_counter()
    proc = subprocess.run(["bash", str(ROOT / "scripts" / "env.sh"), "yosys", "-q", "-l", str(log), "-s", str(out / "synth.ys")],
                          capture_output=True, text=True)
    elapsed = time.perf_counter() - t0
    if proc.returncode != 0:
        print(proc.stdout[-2000:], proc.stderr[-2000:])
        raise SystemExit(f"yosys failed (exit {proc.returncode}); see {log}")
    text = log.read_text()
    stat = parse_stat(text)
    summary = summarize_ecp5(stat["cells"])
    if summary["latches"] or "Latch inferred" in text:
        raise SystemExit("latch inferred; refusing to accept synthesis")
    doc = {"top": top, "config": cfg.as_dict(), "config_id": cfg.id, "cells_total": stat["total"], "cells": stat["cells"],
           **summary, "elapsed_s": round(elapsed, 1), "log": str(log.relative_to(ROOT)), "netlist": str((out / "netlist.json").relative_to(ROOT))}
    (out / "summary.json").write_text(json.dumps(doc, indent=1) + "\n")
    print(f"{top} {cfg.id}: {stat['total']} cells, LUT4 {summary['lut4']}, FF {summary['ff']}, CCU2C {summary['ccu2c']}, "
          f"BRAM {summary['bram']}, DSP {summary['dsp']} ({elapsed:.0f}s)")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", default="stream_wrapper", choices=list(TOP_PARAMS))
    add_config_arguments(ap)
    ap.add_argument("--files-f", default="rtl/files.f")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    cfg = Config(args.arch, args.board_repr, args.lanes, args.depth, args.precision)
    if args.top == "candidate_eval":
        # module-level synthesis only checks arch/precision; lanes/depth are core-level
        if cfg not in SUPPORTED and Config(cfg.arch, cfg.board_repr, 1, 1, cfg.precision) not in SUPPORTED:
            raise SystemExit(f"unsupported configuration {cfg.id}")
    else:
        validate(cfg)
    synthesize(args.top, cfg, ROOT / args.out, args.files_f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
