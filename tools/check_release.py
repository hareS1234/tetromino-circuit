#!/usr/bin/env python3
"""Release validator (Appendix D): checks recorded evidence and artifacts; creates nothing."""
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def main() -> int:
    problems, notes = [], []
    # E00-E19 evidence
    for i in range(20):
        p = ROOT / "results" / "evidence" / f"E{i:02d}" / "summary.json"
        if not p.is_file():
            if i == 19:
                notes.append("E19 evidence not yet recorded (this validator is part of the E19 gate)")
            else:
                problems.append(f"E{i:02d}: no evidence summary")
            continue
        s = json.loads(p.read_text())
        if s.get("status") != "passed":
            problems.append(f"E{i:02d}: status {s.get('status')}")
    # deterministic generation and streams
    if run([sys.executable, "tools/gen_shapes.py", "--check"]).returncode != 0:
        problems.append("generated geometry is stale")
    if run([sys.executable, "tools/make_streams.py", "--check"]).returncode != 0:
        problems.append("committed streams differ from the generator")
    # locks and toolchain
    for rel in ("requirements.lock", "toolchain.lock.json", "docs/toolchain.md", "benchmarks/config.json", ".github/workflows/ci.yml"):
        if not (ROOT / rel).is_file():
            problems.append(f"missing {rel}")
    lock = (ROOT / "requirements.lock").read_text() if (ROOT / "requirements.lock").is_file() else ""
    if re.search(r"/home/|/Users/|file://", lock):
        problems.append("requirements.lock contains local paths")
    # absolute laptop paths must not leak into scripts
    leaks = []
    for pat in ("tools/*.py", "scripts/*.sh", "tb/*.py", "model/*.py", "Makefile"):
        for p in ROOT.glob(pat):
            if p.name in ("check_release.py", "fresh_clone_check.sh"):
                continue  # these two files contain the search pattern itself
            if re.search(r"/home/[a-z]+/|/Users/[a-z]+/", p.read_text()):
                leaks.append(str(p.relative_to(ROOT)))
    if leaks:
        problems.append(f"absolute paths leaked into {leaks}")
    # verification counts
    dec = ROOT / "results" / "decisions" / "a0-bitmap-d1-p0-l1_native_1000.csv"
    if not dec.is_file() or sum(1 for _ in open(dec)) < 1001:
        problems.append("fewer than 1,000 exact-baseline differential decisions recorded")
    replays = list((ROOT / "results" / "replays").glob("a0-bitmap-d1-p0-l1_seed200*_cap250.jsonl"))
    if len(replays) < 3:
        problems.append("fewer than three RTL baseline game replays")
    impl = ROOT / "results" / "implementation.csv"
    if impl.is_file():
        rows = list(csv.DictReader(open(impl)))
        cfgs = {(r["arch"], r["board_repr"], r["lanes"], r["depth"], r["precision"]) for r in rows}
        notes.append(f"{len(rows)} routing attempts across {len(cfgs)} configurations; {sum(r['timing_met'] == 'True' for r in rows)} met timing")
        if len(rows) < 45:
            problems.append(f"implementation matrix has {len(rows)} attempts, expected 45")
    else:
        problems.append("missing results/implementation.csv")
    q = ROOT / "results" / "quality.csv"
    if q.is_file():
        rows = [r for r in csv.DictReader(open(q)) if r["experiment"] in ("precision", "depth")]
        notes.append(f"{len(rows)} held-out games recorded")
        if len(rows) < 640:
            problems.append(f"quality.csv has {len(rows)} held-out games, expected 640")
    else:
        problems.append("missing results/quality.csv")
    # README statements
    readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").is_file() else ""
    for needle in ("drop-only", "excluded", "RTL simulation", "Limitations", "References"):
        if needle.lower() not in readme.lower():
            problems.append(f"README lacks '{needle}'")
    if re.search(r"physical board (?:measurement|result)s? (?:were|was) (?:taken|obtained)", readme, re.I):
        problems.append("README claims physical board measurements")
    # report validator
    r = run([sys.executable, "tools/check_report.py"])
    if r.returncode != 0:
        problems.append("check-report failed: " + r.stdout.strip().splitlines()[-1])
    # tags
    tags = run(["git", "tag"]).stdout.split()
    for t in ("v0.1-python", "v0.2-rtl", "v0.3-implemented"):
        if t not in tags:
            problems.append(f"missing tag {t}")
    for n in notes:
        print("  ", n)
    if problems:
        print("check-release: FAIL")
        for p in problems:
            print("  -", p)
        return 1
    print("check-release: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
