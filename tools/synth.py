#!/usr/bin/env python3
"""Yosys synth_ecp5 of a top module for one configuration, keyed by its complete synthesis identity.

    python tools/synth.py --top stream_wrapper --arch 1 --board-repr 1
    python tools/synth.py --top stream_wrapper --arch 1 --board-repr 1 --dsp-policy nodsp

Output goes to build/synth/<synth_key>/ (synth_key from tools/identity.py: ordered rtl/files.f
closure with generated includes, top, parameters, Yosys identity, DSP policy, script version).
A directory whose summary.json carries the same synth_key and whose netlist.json still hashes to
the recorded value is reused; nothing is keyed by mtimes.  --out creates a convenience symlink.
Parameters are applied with `hierarchy -chparam` on the top and must be forwarded explicitly
down the hierarchy by the RTL.
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
from tools.build_native import link_alias  # noqa: E402
from tools.check_synth_log import parse_stat, summarize_ecp5  # noqa: E402
from tools.identity import sha256_file, synth_identity, toolchain_identity  # noqa: E402

TOP_PARAMS = {
    "stream_wrapper": ("ARCH", "BOARD_REPR", "LANES", "DEPTH", "PRECISION"),
    "tetris_core": ("ARCH", "BOARD_REPR", "LANES", "DEPTH", "PRECISION"),
    "candidate_eval": ("ARCH", "BOARD_REPR", "PRECISION"),
}


def synth_dir(key: str) -> Path:
    return ROOT / "build" / "synth" / key


def reusable(sdir: Path, key: str) -> dict | None:
    summary, netlist = sdir / "summary.json", sdir / "netlist.json"
    if not (summary.is_file() and netlist.is_file()):
        return None
    doc = json.loads(summary.read_text())
    if doc.get("synth_key") != key or doc.get("status") != "synthesized":
        return None
    if sha256_file(netlist) != doc.get("netlist_sha256"):
        return None
    return doc


def synthesize(top: str, cfg: Config, out: Path | None = None, files_f: str = "rtl/files.f",
               dsp_policy: str = "default", force: bool = False, quiet: bool = False) -> dict:
    ident = synth_identity(cfg, top, files_f, dsp_policy)
    key = ident["synth_key"]
    sdir = synth_dir(key)
    if out is not None:
        link_alias(Path(out), sdir)
    if not force:
        doc = reusable(sdir, key)
        if doc is not None:
            if not quiet:
                print(f"{top} {cfg.id}: reusing synthesis {key[:12]} ({doc['cells_total']} cells)")
            doc["reused"] = True
            return doc
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "identity.json").write_text(json.dumps(ident, indent=1) + "\n")
    sources = [str(ROOT / s) for s in ident["hdl"]["ordered"]]
    params = cfg.params()
    chparam = " ".join(f"-chparam {k} {params[k]}" for k in TOP_PARAMS[top])
    nodsp = " -nodsp" if dsp_policy == "nodsp" else ""
    script = "\n".join([
        f"read_verilog -sv -I{ROOT / 'rtl'} " + " ".join(sources),
        f"hierarchy -check -top {top} {chparam}",
        f"synth_ecp5{nodsp} -top {top} -json {sdir / 'netlist.json'}",
        "stat",
        "check -assert",
        "",
    ])
    (sdir / "synth.ys").write_text(script)
    log = sdir / "yosys.log"
    for stale in ("summary.json", "netlist.json"):
        (sdir / stale).unlink(missing_ok=True)
    t0 = time.perf_counter()
    proc = subprocess.run(["bash", str(ROOT / "scripts" / "env.sh"), "yosys", "-q", "-l", str(log), "-s", str(sdir / "synth.ys")],
                          capture_output=True, text=True)
    elapsed = time.perf_counter() - t0
    if proc.returncode != 0:
        (sdir / "summary.json").write_text(json.dumps({"synth_key": key, "status": "failed", "exit_code": proc.returncode,
                                                        "log": str(log.relative_to(ROOT))}, indent=1) + "\n")
        print(proc.stdout[-2000:], proc.stderr[-2000:])
        raise SystemExit(f"yosys failed (exit {proc.returncode}); see {log}")
    text = log.read_text()
    stat = parse_stat(text)
    summary = summarize_ecp5(stat["cells"])
    if summary["latches"] or "Latch inferred" in text:
        (sdir / "summary.json").write_text(json.dumps({"synth_key": key, "status": "failed", "reason": "latch inferred"}, indent=1) + "\n")
        raise SystemExit("latch inferred; refusing to accept synthesis")
    doc = {"schema": "synth-record-v2", "status": "synthesized", "synth_key": key, "top": top, "config": cfg.as_dict(),
           "config_id": cfg.id, "params": params, "dsp_policy": dsp_policy, "files_f": files_f,
           "yosys": ident["yosys"], "toolchain_id": toolchain_identity(),
           "cells_total": stat["total"], "cells": stat["cells"], **summary, "elapsed_s": round(elapsed, 1),
           "log": str(log.relative_to(ROOT)), "netlist": str((sdir / "netlist.json").relative_to(ROOT)),
           "netlist_sha256": sha256_file(sdir / "netlist.json"), "reused": False}
    tmp = sdir / "summary.json.part"
    tmp.write_text(json.dumps(doc, indent=1) + "\n")
    tmp.replace(sdir / "summary.json")
    if not quiet:
        print(f"{top} {cfg.id}: {stat['total']} cells, LUT4 {summary['lut4']}, FF {summary['ff']}, CCU2C {summary['ccu2c']}, "
              f"BRAM {summary['bram']}, DSP {summary['dsp']} ({elapsed:.0f}s) -> build/synth/{key[:12]}…")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", default="stream_wrapper", choices=list(TOP_PARAMS))
    add_config_arguments(ap)
    ap.add_argument("--files-f", default="rtl/files.f")
    ap.add_argument("--dsp-policy", default="default", choices=["default", "nodsp"])
    ap.add_argument("--out", default=None, help="convenience symlink to build/synth/<synth_key>")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--print-key", action="store_true")
    args = ap.parse_args()
    cfg = Config(args.arch, args.board_repr, args.lanes, args.depth, args.precision)
    if args.top == "candidate_eval":
        # module-level synthesis only checks arch/precision; lanes/depth are core-level
        if cfg not in SUPPORTED and Config(cfg.arch, cfg.board_repr, 1, 1, cfg.precision) not in SUPPORTED:
            raise SystemExit(f"unsupported configuration {cfg.id}")
    else:
        validate(cfg)
    if args.print_key:
        print(synth_identity(cfg, args.top, args.files_f, args.dsp_policy)["synth_key"])
        return 0
    synthesize(args.top, cfg, ROOT / args.out if args.out else None, args.files_f, args.dsp_policy, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
