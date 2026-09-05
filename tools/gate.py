#!/usr/bin/env python3
"""Run a job's gate commands and record results/evidence/E##/summary.json.

    python tools/gate.py E01 -- make gen -- make test-geometry

Each "--"-separated group is one command (run through scripts/env.sh from the
repository root).  All commands run even if an earlier one fails; the job status
is 'passed' only when every exit code is zero.  Test counts are read from any
pytest/cocotb summary lines found in the captured output.  A gate with zero commands
is rejected (status 'failed'): an empty command list is not evidence.  This is the
v1 recorder kept for the E-jobs; upgrade jobs use tools/ugate.py.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EVIDENCE = Path(os.environ.get("TETROMINO_EVIDENCE_DIR", ROOT / "results" / "evidence"))

from model.replay import git_commit  # noqa: E402


def source_hash() -> str:
    h = hashlib.sha256()
    for pat in ("model/*.py", "rtl/*.sv", "rtl/generated/*.svh", "tb/*.py", "tools/*.py", "sim/*.cpp", "tests/**/*.py"):
        for p in sorted(ROOT.glob(pat)):
            h.update(str(p.relative_to(ROOT)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def toolchain_id() -> str:
    lock = ROOT / "toolchain.lock.json"
    if not lock.is_file():
        return "none"
    doc = json.loads(lock.read_text())
    return f"oss-cad-suite-{doc.get('suite_release')}-{doc.get('archive_sha256', '')[:12]}"


def split_commands(argv):
    groups, cur = [], []
    for a in argv:
        if a == "--":
            if cur:
                groups.append(cur)
            cur = []
        else:
            cur.append(a)
    if cur:
        groups.append(cur)
    return groups


def run_command(job_dir: Path, index: int, cmd):
    log = job_dir / f"cmd{index:02d}.log"
    t0 = time.perf_counter()
    with open(log, "w") as fh:
        proc = subprocess.Popen(["bash", "scripts/env.sh"] + cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        out_lines = []
        for line in proc.stdout:
            fh.write(line)
            out_lines.append(line)
            sys.stdout.write(line)
        proc.wait()
    text = "".join(out_lines)
    tests = {}
    m = re.findall(r"(\d+) passed", text)
    if m:
        tests["pytest_passed"] = sum(int(x) for x in m)
    m = re.findall(r"(\d+) failed", text)
    if m:
        tests["pytest_failed"] = sum(int(x) for x in m)
    m = re.findall(r"RTL tests: (\d+) total, (\d+) failed", text)
    if m:
        tests["rtl_total"] = sum(int(a) for a, _ in m)
        tests["rtl_failed"] = sum(int(b) for _, b in m)
    return {"argv": cmd, "exit_code": proc.returncode, "elapsed_s": round(time.perf_counter() - t0, 2),
            "log": str(log.relative_to(ROOT)) if log.is_relative_to(ROOT) else str(log), "tests": tests}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    job = sys.argv[1]
    note = None
    argv = sys.argv[2:]
    if argv and argv[0].startswith("--note="):
        note = argv[0][len("--note="):]
        argv = argv[1:]
    groups = split_commands(argv)
    job_dir = EVIDENCE / job
    job_dir.mkdir(parents=True, exist_ok=True)
    if not groups:
        summary = {"job": job, "status": "failed", "spec": "drop-v1.1", "commit": git_commit(ROOT), "source_hash": source_hash(),
                   "toolchain_id": toolchain_id(), "recorded_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "note": "rejected: a gate with zero commands is not evidence", "commands": [], "elapsed_s": 0.0}
        (job_dir / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
        print(f"[gate] {job}: FAILED — zero commands supplied")
        return 1
    results = [run_command(job_dir, i, cmd) for i, cmd in enumerate(groups)]
    status = "passed" if results and all(r["exit_code"] == 0 for r in results) else "failed"
    summary = {
        "job": job, "status": status, "spec": "drop-v1.1", "commit": git_commit(ROOT), "source_hash": source_hash(),
        "toolchain_id": toolchain_id(), "recorded_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": note, "commands": results,
        "elapsed_s": round(sum(r["elapsed_s"] for r in results), 2),
    }
    (job_dir / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(f"[gate] {job}: {status} ({summary['elapsed_s']}s) -> {job_dir}/summary.json")
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
