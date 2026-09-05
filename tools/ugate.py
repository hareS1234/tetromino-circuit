#!/usr/bin/env python3
"""Record upgrade-job evidence (schema upgrade-evidence-v1) by running real commands.

    python tools/ugate.py U05 --config a2-cache-d1-p0-l1 \
        --check "prefix unit tests" --artifact results/x.json --limitation "bounded proof" \
        -- make test-prefix -- make formal-compactor

Every "--"-separated group is one command run through scripts/env.sh from the repository
root.  A job with zero commands is rejected.  The record stores each command's argv, exit code,
elapsed time and log path, the test counts parsed from its output (pytest/cocotb/native lines),
the named checks with their counts, and the source-closure hash from tools/identity.py.
Status is 'passed' only if every command exited 0 and at least one check recorded a nonzero
count; otherwise 'failed'.  --blocked "reason" records a blocked job without running anything.
"""
from __future__ import annotations

import datetime as dt
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

from tools.identity import source_closure_sha256, toolchain_identity  # noqa: E402


def git_state() -> dict:
    """HEAD plus dirtiness of *tracked* files; untracked paths (new evidence) are listed, not counted as dirty."""
    def git(*args):
        out = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
        return out.stdout if out.returncode == 0 else None
    head = (git("rev-parse", "HEAD") or "unknown").strip()
    tracked = [l for l in (git("status", "--porcelain", "--untracked-files=no") or "").splitlines() if l.strip()]
    untracked = [l for l in (git("ls-files", "--others", "--exclude-standard") or "").splitlines() if l.strip()]
    return {"commit": head + ("-dirty" if tracked else ""),
            "modified_tracked": [l[3:] for l in tracked], "untracked": untracked}


def parse_counts(text: str) -> dict:
    counts = {}
    m = re.findall(r"(\d+) passed", text)
    if m:
        counts["pytest_passed"] = sum(int(x) for x in m)
    m = re.findall(r"(\d+) failed", text)
    if m:
        counts["pytest_failed"] = sum(int(x) for x in m)
    m = re.findall(r"RTL tests: (\d+) total, (\d+) failed", text)
    if m:
        counts["rtl_total"] = sum(int(a) for a, _ in m)
        counts["rtl_failed"] = sum(int(b) for _, b in m)
    m = re.findall(r"native: all (\d+) decisions match", text)
    if m:
        counts["native_decisions"] = sum(int(x) for x in m)
    m = re.findall(r"CHECK (\S+) (\d+)/(\d+)", text)
    for name, ok, total in m:
        counts[f"check_{name}"] = f"{ok}/{total}"
    return counts


def count_ok(value) -> bool:
    """A count is evidence only when it is nonzero: 'N' > 0, or 'ok/total' with ok == total > 0."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value > 0
    if isinstance(value, str) and "/" in value:
        ok, total = value.split("/", 1)
        return ok.isdigit() and total.isdigit() and int(ok) == int(total) > 0
    return False


def run_command(job_dir: Path, index: int, argv):
    log = job_dir / f"cmd{index:02d}.log"
    t0 = time.perf_counter()
    lines = []
    with open(log, "w") as fh:
        proc = subprocess.Popen(["bash", "scripts/env.sh"] + argv, cwd=ROOT, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            fh.write(line)
            lines.append(line)
            sys.stdout.write(line)
        proc.wait()
    return {"argv": argv, "exit_code": proc.returncode, "elapsed_s": round(time.perf_counter() - t0, 2),
            "log": str(log.relative_to(ROOT)) if log.is_relative_to(ROOT) else str(log), "counts": parse_counts("".join(lines))}


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    job = argv[0]
    opts = {"config": None, "checks": [], "artifacts": [], "limitations": [], "blocked": None, "note": None}
    i = 1
    while i < len(argv) and argv[i] != "--":
        a = argv[i]
        if a == "--config":
            opts["config"] = argv[i + 1]; i += 2
        elif a == "--check":
            opts["checks"].append(argv[i + 1]); i += 2
        elif a == "--artifact":
            opts["artifacts"].append(argv[i + 1]); i += 2
        elif a == "--limitation":
            opts["limitations"].append(argv[i + 1]); i += 2
        elif a == "--blocked":
            opts["blocked"] = argv[i + 1]; i += 2
        elif a == "--note":
            opts["note"] = argv[i + 1]; i += 2
        else:
            raise SystemExit(f"unknown option {a}")
    groups, cur = [], []
    for a in argv[i:]:
        if a == "--":
            if cur:
                groups.append(cur)
            cur = []
        else:
            cur.append(a)
    if cur:
        groups.append(cur)

    job_dir = EVIDENCE / job
    job_dir.mkdir(parents=True, exist_ok=True)
    git = git_state()
    record = {
        "schema": "upgrade-evidence-v1", "job": job, "status": "running",
        "git_commit": git["commit"], "git_modified_tracked": git["modified_tracked"], "git_untracked": git["untracked"],
        "source_sha256": source_closure_sha256(),
        "configuration_id": opts["config"], "toolchain_id": toolchain_identity(),
        "recorded_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commands": [], "checks": [], "artifacts": [], "limitations": list(opts["limitations"]), "note": opts["note"],
    }
    if opts["blocked"]:
        record["status"] = "blocked"
        record["limitations"].append(opts["blocked"])
        (job_dir / "summary.json").write_text(json.dumps(record, indent=1) + "\n")
        print(f"[ugate] {job}: blocked — {opts['blocked']}")
        return 0
    if not groups:
        record["status"] = "failed"
        record["limitations"].append("no commands were supplied; a gate with zero commands is not evidence")
        (job_dir / "summary.json").write_text(json.dumps(record, indent=1) + "\n")
        print(f"[ugate] {job}: FAILED — zero commands")
        return 1
    results = [run_command(job_dir, k, g) for k, g in enumerate(groups)]
    record["commands"] = results
    for name in opts["checks"]:
        # a check names a command-derived count; format "label=count_key" or free text with counts inline
        if "=" in name:
            label, key = name.split("=", 1)
            vals = [r["counts"].get(key) for r in results if key in r["counts"]]
            record["checks"].append({"name": label, "count_key": key, "values": vals, "ok": bool(vals) and all(count_ok(v) for v in vals)})
        else:
            record["checks"].append({"name": name, "ok": all(r["exit_code"] == 0 for r in results)})
    any_count = any(any(isinstance(v, int) and v > 0 for v in r["counts"].values()) or
                    any(isinstance(v, str) for v in r["counts"].values()) for r in results)
    for a in opts["artifacts"]:
        p = ROOT / a
        record["artifacts"].append({"path": a, "exists": p.exists(), "bytes": p.stat().st_size if p.exists() else None})
    ok = all(r["exit_code"] == 0 for r in results) and all(c["ok"] for c in record["checks"]) and all(a["exists"] for a in record["artifacts"])
    if ok and not any_count and not record["checks"]:
        record["limitations"].append("no test counts were parsed from the command output")
    record["status"] = "passed" if ok else "failed"
    (job_dir / "summary.json").write_text(json.dumps(record, indent=1) + "\n")
    print(f"[ugate] {job}: {record['status']} ({sum(r['elapsed_s'] for r in results):.1f}s) -> {job_dir}/summary.json")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
