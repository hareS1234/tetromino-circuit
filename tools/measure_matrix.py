#!/usr/bin/env python3
"""Frozen hardware matrix: synthesize each required configuration once, route it with seeds 1-5
at the common target, and run the decision corpus through its native driver.  Resumable: a
route whose summary.json exists for the current source hash is skipped.  Rows accumulate in
results/implementation.csv; a manifest records source/toolchain identity and attempt counts."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.config import SUPPORTED_IDS  # noqa: E402
from model.replay import git_commit  # noqa: E402
from tools.pnr import route, toolchain_id  # noqa: E402
from tools.synth import synthesize  # noqa: E402

MANIFEST = ROOT / "results" / "implementation_manifest.json"


def rtl_hash() -> str:
    h = hashlib.sha256()
    for p in sorted(list((ROOT / "rtl").glob("*.sv")) + list((ROOT / "rtl" / "generated").glob("*.svh"))):
        if p.name == "fast_tb.sv":
            continue
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default=None, help="comma-separated subset of configuration ids")
    ap.add_argument("--seeds", default=None, help="comma-separated subset of route seeds")
    ap.add_argument("--skip-decisions", action="store_true")
    args = ap.parse_args()
    cfg = json.loads((ROOT / "benchmarks" / "config.json").read_text())
    hw = cfg["hardware_matrix"]
    ids = args.configs.split(",") if args.configs else hw["configurations"]
    seeds = [int(s) for s in args.seeds.split(",")] if args.seeds else hw["route_seeds"]
    src = rtl_hash()
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.is_file() else {"attempts": {}, "decisions": {}}
    manifest.update({"rtl_hash": src, "commit": git_commit(ROOT), "toolchain_id": toolchain_id(),
                     "device": hw["device"], "package": hw["package"], "speed_grade": hw["speed_grade"],
                     "target_mhz": hw["target_mhz"], "route_seeds": seeds})
    t0 = time.perf_counter()
    for cid in ids:
        c = SUPPORTED_IDS[cid]
        synth_dir = ROOT / f"build/synth_{cid}"
        summary = synth_dir / "summary.json"
        if not (summary.is_file() and json.loads(summary.read_text()).get("rtl_hash") == src):
            doc = synthesize("stream_wrapper", c, synth_dir)
            doc["rtl_hash"] = src
            summary.write_text(json.dumps(doc, indent=1) + "\n")
        for seed in seeds:
            out = ROOT / f"build/pnr_{cid}_s{seed}"
            done = out / "summary.json"
            if done.is_file() and json.loads(done.read_text()).get("rtl_hash") == src:
                print(f"{cid} seed {seed}: already routed for rtl {src}")
                continue
            row = route(c, seed, synth_dir / "netlist.json", out, hw["target_mhz"])
            row["rtl_hash"] = src
            done.write_text(json.dumps(row, indent=1) + "\n")
            manifest["attempts"][f"{cid}:s{seed}"] = {"status": row["status"], "timing_met": row["timing_met"],
                                                        "fmax": row["reported_fmax_mhz"], "rtl_hash": src}
            MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n")
        if not args.skip_decisions:
            count = 250 if c.depth == 2 else 1000
            cmd = ["bash", str(ROOT / "scripts/env.sh"), "python", "tools/test_core.py", "--arch", str(c.arch), "--board-repr",
                   str(c.board_repr), "--lanes", str(c.lanes), "--depth", str(c.depth), "--precision", str(c.precision),
                   "--count", str(count), "--driver", "native"]
            proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            if proc.returncode != 0:
                print(proc.stdout[-2000:], proc.stderr[-2000:])
                raise SystemExit(f"decision corpus failed for {cid}")
            line = [l for l in proc.stdout.splitlines() if l.startswith("native: all")][-1]
            print(f"{cid}: {line}")
            manifest["decisions"][cid] = {"count": count, "rtl_hash": src, "result": line,
                                          "csv": f"results/decisions/{cid}_native_{count}.csv"}
            MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n")
    attempts = [v for k, v in manifest["attempts"].items() if k.split(":")[0] in ids]
    manifest["summary"] = {"routing_attempts": len(attempts), "timing_met": sum(1 for a in attempts if a["timing_met"]),
                           "elapsed_s": round(time.perf_counter() - t0, 1)}
    MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"matrix: {manifest['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
