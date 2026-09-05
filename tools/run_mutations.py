#!/usr/bin/env python3
"""Deliberate mutation checks (guide §8.4, U11).

    python tools/run_mutations.py [--set tests/mutations/a2_mutations.json] [--only name,...]

For each mutation: the edits are applied to the production file (each `old` must occur exactly
once), the named test runs through scripts/env.sh, the file is restored (always, also on errors),
and the outcome is classified:
  killed      the test exited nonzero AND its output matches the kill signature (a behavioural failure)
  tool_error  the test exited nonzero without the signature (compile/elaboration/runner error: not a kill)
  survived    the test passed with the mutation in place
The record results/evidence/U11/mutations.json keeps, per mutation, the first matching output line.
A clean-tree check runs the working tree's git status before and after.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL_ERROR = re.compile(r"%Error|syntax error|ERROR:|Traceback|error:|not applicable")


def git_dirty_paths() -> set[str]:
    out = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True)
    return {l[3:] for l in out.stdout.splitlines() if l.strip()}


def run_one(m: dict, timeout: int) -> dict:
    path = ROOT / m["file"]
    original = path.read_text()
    text = original
    for old, new in m["edits"]:
        if text.count(old) != 1:
            return {"name": m["name"], "status": "not_applicable", "detail": f"pattern occurs {text.count(old)} times: {old[:60]!r}"}
        text = text.replace(old, new)
    t0 = time.perf_counter()
    try:
        path.write_text(text)
        proc = subprocess.run(["bash", str(ROOT / "scripts" / "env.sh"), *m["test"]], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        output = proc.stdout + proc.stderr
        code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        output += "\n[mutation runner] test timed out"
        code = -9
    finally:
        path.write_text(original)
    kill = re.compile(m["kill"])
    hit = next((l.strip() for l in output.splitlines() if kill.search(l)), None)
    if code == 0:
        status = "survived"
    elif hit is not None:
        status = "killed"
    elif code == -9:
        status = "killed" if "timeout" in m["kill"] else "tool_error"
        hit = "[test timed out]"
    else:
        status = "tool_error"
        hit = next((l.strip() for l in output.splitlines() if TOOL_ERROR.search(l)), None)
    return {"name": m["name"], "family": m["family"], "file": m["file"], "status": status, "exit_code": code,
            "killed_by": hit, "test": " ".join(m["test"]), "elapsed_s": round(time.perf_counter() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="tests/mutations/a2_mutations.json")
    ap.add_argument("--only", default=None)
    ap.add_argument("--timeout", type=int, default=1200)
    ap.add_argument("--out", default="results/evidence/U11/mutations.json")
    args = ap.parse_args()
    doc = json.loads((ROOT / args.set).read_text())
    only = set(args.only.split(",")) if args.only else None
    before = git_dirty_paths()
    results = []
    for m in doc["mutations"]:
        if only and m["name"] not in only:
            continue
        r = run_one(m, args.timeout)
        results.append(r)
        print(f"  {r['name']:36s} {r['status']:12s} {r.get('elapsed_s', 0):6.1f}s  {r.get('killed_by') or r.get('detail') or ''}"[:200], flush=True)
    after = git_dirty_paths()
    restored = before == after
    killed = sum(1 for r in results if r["status"] == "killed")
    record = {"schema": "mutation-results-v1", "set": args.set, "recorded_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "results": results, "killed": killed, "total": len(results), "tree_restored": restored}
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=1) + "\n")
    print(f"CHECK mutations_killed {killed}/{len(results)}")
    if not restored:
        print(f"ERROR: working tree changed: {sorted(after - before)}")
        return 1
    return 0 if killed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
