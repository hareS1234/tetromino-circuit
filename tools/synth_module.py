#!/usr/bin/env python3
"""Micro-synthesis of one module (Yosys synth_ecp5) with inspection checks (U06+).

    python tools/synth_module.py --top line_clear_pipe --files-f rtl/files_compactor_pipe.f \
        --expect-no-latch --expect-no-dsp --expect-ff-min 500 --expect-lut-min 1000

Writes build/synth_module/<top>/{synth.ys,yosys.log,summary.json} and prints CHECK lines.  With
--noflatten the per-module statistics are kept so live submodule logic is visible (e.g. that the
selection network survives optimization).  Not keyed by identity: this is an inspection step, the
measured release synthesis goes through tools/synth.py.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.check_synth_log import parse_stat, summarize_ecp5  # noqa: E402
from tools.identity import read_files_f  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", required=True)
    ap.add_argument("--files-f", required=True)
    ap.add_argument("--param", action="append", default=[])
    ap.add_argument("--noflatten", action="store_true")
    ap.add_argument("--expect-no-latch", action="store_true")
    ap.add_argument("--expect-no-dsp", action="store_true")
    ap.add_argument("--expect-ff-min", type=int, default=None)
    ap.add_argument("--expect-ff-max", type=int, default=None)
    ap.add_argument("--expect-lut-min", type=int, default=None)
    ap.add_argument("--expect-module-live", action="append", default=[], help="with --noflatten: module name that must keep cells")
    args = ap.parse_args()
    out = ROOT / "build" / "synth_module" / args.top
    out.mkdir(parents=True, exist_ok=True)
    sources = [str(ROOT / s) for s in read_files_f(ROOT / args.files_f)]
    chparam = " ".join(f"-chparam {p.split('=')[0]} {p.split('=')[1]}" for p in args.param)
    script = "\n".join([
        f"read_verilog -sv -I{ROOT / 'rtl'} " + " ".join(sources),
        f"hierarchy -check -top {args.top} {chparam}",
        f"synth_ecp5 -top {args.top}{' -noflatten' if args.noflatten else ''}",
        "stat",
        "check -assert",
        "",
    ])
    (out / "synth.ys").write_text(script)
    log = out / "yosys.log"
    proc = subprocess.run(["bash", str(ROOT / "scripts" / "env.sh"), "yosys", "-q", "-l", str(log), "-s", str(out / "synth.ys")],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout[-2000:], proc.stderr[-2000:])
        raise SystemExit(f"yosys failed (exit {proc.returncode}); see {log}")
    text = log.read_text()
    stat = parse_stat(text)
    summary = summarize_ecp5(stat["cells"])
    latch = bool(summary["latches"]) or "Latch inferred" in text
    problems = []
    checks = []

    def chk(name, cond):
        checks.append((name, cond))
        if not cond:
            problems.append(name)

    if args.expect_no_latch:
        chk("no_latch", not latch)
    if args.expect_no_dsp:
        chk("no_dsp", summary["dsp"] == 0)
    if args.expect_ff_min is not None:
        chk(f"ff_min_{args.expect_ff_min}", summary["ff"] >= args.expect_ff_min)
    if args.expect_ff_max is not None:
        chk(f"ff_max_{args.expect_ff_max}", summary["ff"] <= args.expect_ff_max)
    if args.expect_lut_min is not None:
        chk(f"lut_min_{args.expect_lut_min}", summary["lut4"] >= args.expect_lut_min)
    per_module = {}
    if args.noflatten:
        # per-module tables precede the "including submodules" table
        import re
        for m in re.finditer(r"=== (\S+) ===\n(.*?)(?=\n===|\Z)", text[text.rfind("Printing statistics"):], re.S):
            cells = re.findall(r"^\s+(\d+)\s+(\$?[\w$]+)\s*$", m.group(2), re.M)
            per_module[m.group(1)] = sum(int(n) for n, name in cells if not name.startswith("$"))
        for name in args.expect_module_live:
            chk(f"module_live_{name}", per_module.get(name, 0) > 0)
    doc = {"top": args.top, "files_f": args.files_f, "params": args.param, "noflatten": args.noflatten, "cells_total": stat["total"],
           "cells": stat["cells"], **summary, "latch": latch, "per_module_cells": per_module, "checks": checks, "log": str(log.relative_to(ROOT))}
    (out / "summary.json").write_text(json.dumps(doc, indent=1) + "\n")
    print(f"{args.top}: {stat['total']} cells, LUT4 {summary['lut4']}, FF {summary['ff']}, CCU2C {summary['ccu2c']}, BRAM {summary['bram']}, "
          f"DSP {summary['dsp']}, latch {latch}")
    if per_module:
        print("  per module:", ", ".join(f"{k}={v}" for k, v in sorted(per_module.items())))
    print(f"CHECK synth_{args.top} {sum(1 for _, c in checks if c)}/{len(checks)}")
    if problems:
        print("  failed:", problems)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
