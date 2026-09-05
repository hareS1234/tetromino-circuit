#!/usr/bin/env python3
"""nextpnr-ecp5 place and route of a synthesized netlist (ECP5 85k, CABGA381, speed 6).

    python tools/pnr.py --arch 1 --board-repr 1 --seed 1 --json build/synth_a1-cache-d1-p0-l1/netlist.json --out build/pnr_...

I/O is auto-allocated (--lpf-allow-unconstrained): this is an implementation experiment, not a
board pinout.  The run is NOT given --timing-allow-fail, so a timing failure is a failing run;
the log and report (when produced) are kept and the row is recorded with timing_met=False.
Results are appended to results/implementation.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.config import Config, add_config_arguments, validate  # noqa: E402
from model.replay import git_commit  # noqa: E402

DEVICE = {"device": "LFE5U-85F", "flag": "--85k", "package": "CABGA381", "speed": "6"}
CSV_FIELDS = ["commit", "toolchain_id", "arch", "board_repr", "lanes", "depth", "precision", "target", "package",
              "speed_grade", "route_seed", "target_mhz", "timing_met", "reported_fmax_mhz", "lut4", "ff", "bram", "dsp",
              "ccu2c", "slices", "log_path", "status", "elapsed_s"]


def toolchain_id() -> str:
    lock = ROOT / "toolchain.lock.json"
    if not lock.is_file():
        return "none"
    doc = json.loads(lock.read_text())
    return f"oss-cad-suite-{doc.get('suite_release')}-{doc.get('archive_sha256', '')[:12]}"


def parse_log(text: str):
    """Return (fmax_mhz, constraint_mhz, met) from the final 'Max frequency for clock' line."""
    lines = re.findall(r"Max frequency for clock\s+'([^']+)':\s+([\d.]+) MHz \((PASS|FAIL) at ([\d.]+) MHz\)", text)
    if not lines:
        return None, None, None
    name, fmax, status, constraint = lines[-1]
    return float(fmax), float(constraint), status == "PASS"


def parse_utilization(text: str) -> dict:
    util = {}
    for m in re.finditer(r"^\s*Info:\s+(\S+):\s+(\d+)/\s*(\d+)", text, re.M):
        util[m.group(1)] = int(m.group(2))
    return util


def route(cfg: Config, seed: int, netlist: Path, out: Path, freq: float = 50.0) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    log = out / "nextpnr.log"
    report = out / "timing.json"
    cmd = ["bash", str(ROOT / "scripts" / "env.sh"), "nextpnr-ecp5", DEVICE["flag"], "--package", DEVICE["package"],
           "--speed", DEVICE["speed"], "--json", str(netlist), "--freq", str(freq), "--seed", str(seed),
           "--lpf-allow-unconstrained", "--textcfg", str(out / "routed.config"), "--report", str(report),
           "--log", str(log)]
    (out / "command.txt").write_text(" ".join(cmd[2:]) + "\n")
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.perf_counter() - t0
    text = log.read_text() if log.is_file() else proc.stdout + proc.stderr
    fmax, constraint, met = parse_log(text)
    util = parse_utilization(text)
    status = "routed" if proc.returncode == 0 else ("timing_failed" if met is False else f"error_{proc.returncode}")
    synth_summary = json.loads((netlist.parent / "summary.json").read_text()) if (netlist.parent / "summary.json").is_file() else {}
    row = {
        "commit": git_commit(ROOT), "toolchain_id": toolchain_id(), "arch": cfg.arch, "board_repr": cfg.board_repr,
        "lanes": cfg.lanes, "depth": cfg.depth, "precision": cfg.precision, "target": DEVICE["device"],
        "package": DEVICE["package"], "speed_grade": DEVICE["speed"], "route_seed": seed, "target_mhz": freq,
        "timing_met": met if met is not None else False, "reported_fmax_mhz": fmax if fmax is not None else "",
        "lut4": synth_summary.get("lut4", ""), "ff": synth_summary.get("ff", ""), "bram": synth_summary.get("bram", ""),
        "dsp": synth_summary.get("dsp", ""), "ccu2c": synth_summary.get("ccu2c", ""),
        "slices": util.get("TRELLIS_SLICE", util.get("TRELLIS_COMB", "")),
        "log_path": str(log.relative_to(ROOT)), "status": status, "elapsed_s": round(elapsed, 1),
    }
    (out / "summary.json").write_text(json.dumps(row, indent=1) + "\n")
    append_row(row)
    print(f"{cfg.id} seed {seed}: {status}, fmax {fmax} MHz vs {constraint} MHz, timing_met={met}, "
          f"slices {row['slices']} ({elapsed:.0f}s)")
    return row


def append_row(row: dict, path: Path = ROOT / "results" / "implementation.csv") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.is_file()
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in CSV_FIELDS})


def main() -> int:
    ap = argparse.ArgumentParser()
    add_config_arguments(ap)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--freq", type=float, default=50.0)
    ap.add_argument("--json", required=True, help="synthesized netlist")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    cfg = validate(Config(args.arch, args.board_repr, args.lanes, args.depth, args.precision))
    row = route(cfg, args.seed, ROOT / args.json, ROOT / args.out, args.freq)
    return 0 if row["status"] == "routed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
