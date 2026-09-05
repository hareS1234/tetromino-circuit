#!/usr/bin/env python3
"""Check the executable environment.  --profile python (software jobs) or full (hardware gate)."""
from __future__ import annotations

import argparse
import importlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE_BIN = ROOT / ".tools" / "oss-cad-suite" / "bin"
MIN_VERILATOR = (5, 36)


def run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return out.returncode, (out.stdout + out.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def check_python(problems, facts):
    v = sys.version_info
    facts["python"] = f"{v.major}.{v.minor}.{v.micro} ({sys.executable})"
    if (v.major, v.minor) not in ((3, 11), (3, 12)):
        problems.append(f"python 3.11/3.12 required, running {v.major}.{v.minor}")
    if not sys.executable.startswith(str(ROOT / ".venv")):
        problems.append("not running inside .venv (use scripts/env.sh)")
    for mod in ("pytest", "numpy", "matplotlib", "PIL", "cocotb", "cocotb_tools", "model"):
        try:
            m = importlib.import_module(mod)
            facts[mod] = getattr(m, "__version__", "ok")
        except ImportError as exc:
            problems.append(f"missing python module {mod}: {exc}")
    if facts.get("cocotb") not in (None, "2.0.1"):
        problems.append(f"cocotb 2.0.1 required, found {facts.get('cocotb')}")
    lock = ROOT / "requirements.lock"
    if not lock.is_file():
        problems.append("requirements.lock missing")
    elif re.search(r"file://|/home/|/Users/", lock.read_text()):
        problems.append("requirements.lock contains local absolute paths")
    for tool in ("c++", "make", "git"):
        if shutil.which(tool) is None:
            problems.append(f"{tool} not on PATH")
        else:
            facts[tool] = run([tool, "--version"])[1].splitlines()[0]


def check_hardware(problems, facts):
    for exe in ("verilator", "yosys", "nextpnr-ecp5"):
        path = shutil.which(exe)
        if path is None or not path.startswith(str(SUITE_BIN)):
            problems.append(f"{exe} must come from {SUITE_BIN} (found {path})")
            continue
        code, out = run([exe, "--version" if exe != "yosys" else "-V"])
        facts[exe] = out.splitlines()[0] if out else "?"
        if code != 0:
            problems.append(f"{exe} --version failed: {out[:200]}")
    m = re.search(r"Verilator (\d+)\.(\d+)", facts.get("verilator", ""))
    if m and (int(m.group(1)), int(m.group(2))) < MIN_VERILATOR:
        problems.append(f"verilator >= {MIN_VERILATOR[0]}.{MIN_VERILATOR[1]:03d} required for cocotb 2.0.1")
    code, out = run(["nextpnr-ecp5", "--help"])
    if "--85k" not in out or "--package" not in out:
        problems.append("nextpnr-ecp5 lacks expected ECP5 options")
    lock = ROOT / "toolchain.lock.json"
    if lock.is_file():
        doc = json.loads(lock.read_text())
        facts["suite_release"] = doc.get("suite_release")
        facts["archive_sha256"] = doc.get("archive_sha256")
        recorded = (SUITE_BIN.parent / ".bootstrap-sha256")
        if recorded.is_file() and recorded.read_text().strip() != doc.get("archive_sha256"):
            problems.append("installed suite hash differs from toolchain.lock.json")
    else:
        problems.append("toolchain.lock.json missing (run scripts/bootstrap.sh)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="full", choices=["python", "full"])
    ap.add_argument("--json", default=None, help="write facts/problems to this file")
    args = ap.parse_args()
    problems, facts = [], {}
    check_python(problems, facts)
    if args.profile == "full":
        check_hardware(problems, facts)
    for k, v in facts.items():
        print(f"  {k:16s} {v}")
    if args.json:
        Path(args.json).write_text(json.dumps({"profile": args.profile, "facts": facts, "problems": problems}, indent=1))
    if problems:
        print("doctor: FAIL")
        for p in problems:
            print("  -", p)
        return 1
    print(f"doctor: OK ({args.profile} profile)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
