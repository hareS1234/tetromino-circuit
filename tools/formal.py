#!/usr/bin/env python3
"""Run an SBY target from formal/ with the pinned suite and record its actual status.

    python tools/formal.py smoke                 # formal/smoke/smoke.sby
    python tools/formal.py compactor             # formal/compactor/compactor.sby
    python tools/formal.py compactor_cover       # formal/compactor/compactor_cover.sby

Status is taken from SBY's summary, never from the return code alone:
  unbounded  - "successful proof by k-induction" (prove mode)
  bounded    - basecase passed to the configured depth but induction did not close (prove mode)
  covered    - every cover statement reached (cover mode)
  fail       - a counterexample exists (its trace path is recorded)
  timeout    - SBY reported TIMEOUT
Results go to results/formal/<target>.json with the summary lines and the log path; the SBY work
directory is build/formal/<target>/ (proof logs and counterexample traces are preserved there).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "smoke": "formal/smoke/smoke.sby",
    "compactor": "formal/compactor/compactor.sby",
    "compactor_cover": "formal/compactor/compactor_cover.sby",
    "reducer": "formal/reducer/reducer.sby",
    "reducer_cover": "formal/reducer/reducer_cover.sby",
    "control": "formal/control/control.sby",
    "control_cover": "formal/control/control_cover.sby",
}


def classify(summary: list[str], rc: int, mode: str) -> tuple[str, str]:
    text = "\n".join(summary)
    if "TIMEOUT" in text:
        return "timeout", "SBY reported a timeout"
    if mode == "cover":
        if rc == 0 and "DONE (PASS" in text:
            return "covered", "all cover statements reached"
        return "fail", "some cover statement was not reached"
    if "successful proof by k-induction" in text:
        return "unbounded", "k-induction closed: holds for all inputs/states"
    base_pass = "returned pass for basecase" in text
    ind_fail = "returned FAIL for induction" in text or "returned fail for induction" in text
    if base_pass and ind_fail:
        return "bounded", "basecase holds to the configured depth; induction did not close"
    if "DONE (PASS" in text and rc == 0:
        return "bounded", "SBY PASS without an explicit k-induction line"
    return "fail", "counterexample or error (see log)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", choices=sorted(TARGETS))
    args = ap.parse_args()
    sby = ROOT / TARGETS[args.target]
    text = sby.read_text()
    mode = re.search(r"^mode\s+(\w+)", text, re.M).group(1)
    depth = re.search(r"^depth\s+(\d+)", text, re.M)
    timeout = re.search(r"^timeout\s+(\d+)", text, re.M)
    workdir = ROOT / "build" / "formal" / args.target
    if workdir.exists():
        shutil.rmtree(workdir)
    t0 = time.perf_counter()
    proc = subprocess.run(["bash", str(ROOT / "scripts" / "env.sh"), "sby", "-f", "-d", str(workdir), str(sby)],
                          cwd=ROOT, capture_output=True, text=True)
    elapsed = time.perf_counter() - t0
    lines = (proc.stdout + proc.stderr).splitlines()
    summary = [l.split("] ", 1)[1] if "] " in l else l for l in lines if "summary:" in l or "DONE" in l]
    status, reason = classify(summary, proc.returncode, mode)
    traces = [l for l in summary if "trace" in l and ".vcd" in l]
    record = {"schema": "formal-result-v1", "target": args.target, "sby": str(sby.relative_to(ROOT)), "mode": mode,
              "depth": int(depth.group(1)) if depth else None, "timeout_s": int(timeout.group(1)) if timeout else None, "engine": re.search(r"^\[engines\]\n(.+)", text, re.M).group(1).strip(),
              "status": status, "reason": reason, "return_code": proc.returncode, "elapsed_s": round(elapsed, 1),
              "summary": summary, "traces": traces, "workdir": str(workdir.relative_to(ROOT)),
              "log": str((workdir / "logfile.txt").relative_to(ROOT)), "recorded_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    out = ROOT / "results" / "formal" / f"{args.target}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=1) + "\n")
    for l in summary:
        print("  ", l)
    ok = status in ("unbounded", "covered") or (status == "bounded" and mode == "bmc")
    print(f"CHECK formal_{args.target} {1 if ok else 0}/1")
    print(f"formal {args.target}: {status} ({reason}; {elapsed:.0f}s) -> {out.relative_to(ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
