#!/usr/bin/env python3
"""Check either the Python environment or the full platform-locked CAD toolchain."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import platform as pf
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_V2 = Path(os.environ.get("TETROMINO_LOCK", ROOT / "toolchains" / "oss_cad_suite.lock.json"))
TOOLS_DIR = Path(os.environ.get("TETROMINO_TOOLS_DIR", ROOT / ".tools"))
HOST_DIR = Path(os.environ.get("TETROMINO_HOST_DIR", ROOT / "results" / "host"))
SUITE_DIR = TOOLS_DIR / "oss-cad-suite"
SUITE_BIN = SUITE_DIR / "bin"
LOCK_V1 = ROOT / "toolchain.lock.json"


def run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return out.returncode, (out.stdout + out.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def load_lock():
    if not LOCK_V2.is_file():
        return None
    return json.loads(LOCK_V2.read_text())


def detect_platform() -> str:
    return os.environ.get("TETROMINO_PLATFORM") or f"{pf.system()}-{pf.machine()}"


def parse_version(text: str):
    m = re.search(r"(\d+)\.(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def check_python(problems, facts, lock):
    v = sys.version_info
    facts["python"] = f"{v.major}.{v.minor}.{v.micro} ({sys.executable})"
    supported = (lock or {}).get("python", {}).get("supported", ["3.11", "3.12"])
    if f"{v.major}.{v.minor}" not in supported:
        problems.append(f"python {'/'.join(supported)} required by the lock, running {v.major}.{v.minor}")
    venv = ROOT / os.environ.get("TETROMINO_VENV", ".venv")
    if not sys.executable.startswith(str(venv)):
        problems.append(f"not running inside {venv.name} (use scripts/env.sh)")
    for mod in ("pytest", "numpy", "matplotlib", "PIL", "cocotb", "cocotb_tools", "model"):
        try:
            m = importlib.import_module(mod)
            facts[mod] = getattr(m, "__version__", "ok")
        except ImportError as exc:
            problems.append(f"missing python module {mod}: {exc}")
    if facts.get("cocotb") not in (None, "2.0.1"):
        problems.append(f"cocotb 2.0.1 required, found {facts.get('cocotb')}")
    req = ROOT / "requirements.lock"
    if not req.is_file():
        problems.append("requirements.lock missing")
    elif re.search(r"file://|/home/|/Users/", req.read_text()):
        problems.append("requirements.lock contains local absolute paths")
    for tool in ("c++", "make", "git"):
        if shutil.which(tool) is None:
            problems.append(f"{tool} not on PATH")
        else:
            facts[tool] = run([tool, "--version"])[1].splitlines()[0]


def check_hardware(problems, facts, lock):
    for exe in ("verilator", "yosys", "nextpnr-ecp5"):
        path = shutil.which(exe)
        if path is None or not path.startswith(str(SUITE_BIN)):
            problems.append(f"{exe} must come from {SUITE_BIN} (found {path})")
            continue
        code, out = run([exe, "--version" if exe != "yosys" else "-V"])
        facts[exe] = out.splitlines()[0] if out else "?"
        if code != 0:
            problems.append(f"{exe} --version failed: {out[:200]}")
    minimum = parse_version((lock or {}).get("verilator_minimum", "5.036")) or (5, 36)
    m = re.search(r"Verilator (\d+)\.(\d+)", facts.get("verilator", ""))
    if m and (int(m.group(1)), int(m.group(2))) < minimum:
        problems.append(f"verilator >= {minimum[0]}.{minimum[1]:03d} required for cocotb 2.0.1")
    code, out = run(["nextpnr-ecp5", "--help"])
    if "--85k" not in out or "--package" not in out:
        problems.append("nextpnr-ecp5 lacks expected ECP5 options")

    if lock is None:
        problems.append(f"{LOCK_V2.relative_to(ROOT) if LOCK_V2.is_relative_to(ROOT) else LOCK_V2} missing")
        return
    plat = detect_platform()
    family = lock.get("platform_map", {}).get(plat)
    facts["platform"] = f"{plat} -> {family or 'unsupported'}"
    facts["suite_release"] = lock.get("release")
    if family is None:
        problems.append(f"platform {plat} is not in the lock's platform_map")
        return
    entry = lock["assets"][family]
    expected = entry.get("sha256")
    facts["lock_entry"] = f"{entry.get('asset')} ({entry.get('status')})"
    if not expected:
        problems.append(f"no recorded archive hash for {family}; run 'bash scripts/bootstrap.sh --enroll' on this platform")
    recorded = SUITE_DIR / ".bootstrap-sha256"
    asset_marker = SUITE_DIR / ".bootstrap-asset"
    if not recorded.is_file() or not asset_marker.is_file():
        problems.append("installed suite lacks bootstrap markers (.bootstrap-sha256/.bootstrap-asset); run scripts/bootstrap.sh")
    else:
        observed = recorded.read_text().strip()
        facts["installed_sha256"] = observed
        if expected and observed != expected:
            problems.append(f"installed suite hash {observed[:16]}… differs from the {family} lock entry {expected[:16]}…")
        if asset_marker.read_text().strip() != entry.get("asset"):
            problems.append(f"installed asset {asset_marker.read_text().strip()} is not the locked {entry.get('asset')}")
    obs = HOST_DIR / f"{plat}.json"
    if not obs.is_file():
        problems.append(f"host observation {obs.relative_to(ROOT) if obs.is_relative_to(ROOT) else obs} missing; run scripts/bootstrap.sh on this host")
    else:
        doc = json.loads(obs.read_text())
        facts["host_observation"] = f"{doc.get('recorded_utc')} ({doc.get('schema')})"
        if doc.get("schema") != "host-observation-v1":
            problems.append("host observation has an unexpected schema")
        if doc.get("asset_family") != family:
            problems.append("host observation was written for a different asset family")
    if LOCK_V1.is_file():
        v1 = json.loads(LOCK_V1.read_text())
        facts["v1_lock"] = f"historical: {v1.get('asset')} {str(v1.get('archive_sha256'))[:16]}… (not enforced)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="full", choices=["python", "full"])
    ap.add_argument("--json", default=None, help="write facts/problems to this file")
    args = ap.parse_args()
    problems, facts = [], {}
    lock = load_lock()
    check_python(problems, facts, lock)
    if args.profile == "full":
        check_hardware(problems, facts, lock)
    for k, v in facts.items():
        print(f"  {k:18s} {v}")
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
