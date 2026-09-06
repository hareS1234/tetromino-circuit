#!/usr/bin/env python3
"""Regenerate the report blocks and inspect its files and GIFs, without creating results."""
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CSV = {
    "results/quality.csv": ["commit", "spec", "backend", "experiment", "policy", "depth", "precision", "stream_seed", "stream_sha256", "cap", "lines", "pieces_locked", "terminal_reason"],
    "results/implementation.csv": ["commit", "toolchain_id", "arch", "board_repr", "lanes", "depth", "precision", "target", "package", "speed_grade", "route_seed", "target_mhz", "timing_met", "reported_fmax_mhz", "lut4", "ff", "bram", "dsp", "log_path"],
}
GIFS = ["assets/rtl_demo.gif", "assets/tournament_rtl.gif", "assets/python_demo.gif", "assets/tournament_python.gif"]
PLOTS = ["area_vs_cycles.png", "precision_area_lines.png", "depth_quality_cost.png", "board_access.png", "fmax_seeds.png", "divergence_p1.png", "stage_cycles.png"]


def main() -> int:
    problems = []
    proc = subprocess.run([sys.executable, str(ROOT / "tools" / "write_report.py"), "--check"], capture_output=True, text=True)
    if proc.returncode != 0:
        problems.append("results blocks are stale: " + proc.stdout.strip().replace("\n", "; "))
    for rel, cols in REQUIRED_CSV.items():
        p = ROOT / rel
        if not p.is_file():
            problems.append(f"missing {rel}")
            continue
        rows = list(csv.DictReader(open(p)))
        missing = [c for c in cols if c not in (rows[0] if rows else {})]
        if not rows or missing:
            problems.append(f"{rel}: {'empty' if not rows else 'missing columns ' + ','.join(missing)}")
    dec = list((ROOT / "results" / "decisions").glob("*_native_*.csv"))
    if len(dec) < 9:
        problems.append(f"expected decision CSVs for nine configurations, found {len(dec)}")
    insp = ROOT / "results" / "inspection"
    for rel in GIFS:
        p = ROOT / rel
        if not p.is_file():
            problems.append(f"missing {rel}")
            continue
        if p.stat().st_size > 10 * 1024 * 1024:
            problems.append(f"{rel} exceeds 10 MB")
        im = Image.open(p)
        n = getattr(im, "n_frames", 1)
        if n < 3:
            problems.append(f"{rel} has {n} frames")
            continue
        for tag, idx in (("first", 0), ("middle", n // 2), ("last", n - 1)):
            im.seek(idx)
            still = insp / f"{p.stem}_{tag}.png"
            if not still.is_file():
                problems.append(f"missing inspection still {still.relative_to(ROOT)}")
                continue
            actual = im.convert("RGB")
            with Image.open(still) as saved:
                expected = saved.convert("RGB")
            if actual.size != expected.size or ImageChops.difference(actual, expected).getbbox() is not None:
                problems.append(f"{still.relative_to(ROOT)} does not match the {tag} frame of {rel}")
    for name in PLOTS:
        p = ROOT / "assets" / "plots" / name
        if not p.is_file() or p.stat().st_size < 1000:
            problems.append(f"missing or empty plot {name}")
    readme = (ROOT / "README.md").read_text()
    for needle in ("drop-only", "drop-v1.1", "RTL simulation", "not measured on a board"):
        if needle not in readme:
            problems.append(f"README lacks the phrase '{needle}'")
    forbidden = re.findall(r"(globally optimal|(?<!not )measured on (?:the|a) board|GPU speedup|CPU speedup)", readme, re.I)
    if forbidden:
        problems.append(f"README contains forbidden claims: {forbidden}")
    for rel in ("results/tournament_report.json", "results/implementation_manifest.json", "results/quality_summary.json"):
        if not (ROOT / rel).is_file():
            problems.append(f"missing {rel}")
    if problems:
        print("check-report: FAIL")
        for p in problems:
            print("  -", p)
        return 1
    print(f"check-report: OK (results blocks current; {len(dec)} decision files; inspection stills match their GIF frames)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
