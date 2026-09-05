#!/usr/bin/env python3
"""v1 release validator (manual Appendix D): checks recorded evidence and artifacts; creates nothing.

Exact expected-job membership of the frozen v1 experiment (quality, routes, decisions, evidence)
comes from tools/check_v1_results.py; no minimum row counts are used.  The v2 upgrade release
(U-jobs, v2 manifests) is validated by check_release_v2 (U20).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.check_v1_results import run_checks as v1_checks  # noqa: E402


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def main() -> int:
    problems, notes = [], []
    # frozen v1 experiment: exact expected-job membership, single identities, recomputed summary, evidence
    v1_problems, v1_checks_done = v1_checks()
    problems += v1_problems
    for name, ok, total in v1_checks_done:
        notes.append(f"CHECK {name} {ok}/{total}")
    # deterministic generation and streams
    if run([sys.executable, "tools/gen_shapes.py", "--check"]).returncode != 0:
        problems.append("generated geometry is stale")
    if run([sys.executable, "tools/make_streams.py", "--check"]).returncode != 0:
        problems.append("committed streams differ from the generator")
    # locks and toolchain
    for rel in ("requirements.lock", "toolchain.lock.json", "toolchains/oss_cad_suite.lock.json", "docs/toolchain.md",
                "benchmarks/config.json", ".github/workflows/ci.yml"):
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
    # RTL replays: the three named baseline games (exact membership)
    for seed in (2000, 2001, 2002):
        rp = ROOT / "results" / "replays" / f"a0-bitmap-d1-p0-l1_seed{seed}_cap250.jsonl"
        if not rp.is_file() or rp.stat().st_size == 0:
            problems.append(f"missing or empty RTL baseline replay {rp.name}")
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
