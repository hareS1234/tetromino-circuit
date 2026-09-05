#!/usr/bin/env python3
"""Complete job identities (guide §10.2).  Every cached build or measurement is keyed by a
SHA-256 over canonical JSON of *everything that determines it*: file bytes in the transitive
HDL closure (with paths, lengths and explicit separators), ordered file lists, parameters,
tool identities, scripts/options and constraints.  mtimes are never used.

    python tools/identity.py --synth a1-cache-d1-p0-l1
    python tools/identity.py --route a1-cache-d1-p0-l1 --freq 50 --seed 1
    python tools/identity.py --source
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

INCLUDE_RE = re.compile(r'`include\s+"([^"]+)"')
IDENTITY_VERSION = "identity-v1"


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha256_of(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def file_record(path: Path) -> dict:
    data = path.read_bytes()
    return {"path": str(path.relative_to(ROOT)), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def read_files_f(path: Path):
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def hdl_closure(files_f: str = "rtl/files.f", include_dir: str = "rtl"):
    """Ordered source list plus every transitively `include`d file, each with its hash."""
    sources = read_files_f(ROOT / files_f)
    seen, records = set(), []
    stack = [ROOT / s for s in sources]
    ordered = [str((ROOT / s).relative_to(ROOT)) for s in sources]
    while stack:
        p = stack.pop(0)
        rel = str(p.relative_to(ROOT))
        if rel in seen:
            continue
        seen.add(rel)
        records.append(file_record(p))
        for inc in INCLUDE_RE.findall(p.read_text(errors="ignore")):
            cand = (ROOT / include_dir / inc)
            if not cand.is_file():
                cand = p.parent / inc
            if cand.is_file():
                stack.append(cand)
    return {"files_f": files_f, "ordered": ordered, "closure": sorted(records, key=lambda r: r["path"])}


def tool_identity(exe: str) -> str:
    import subprocess
    try:
        out = subprocess.run(["bash", str(ROOT / "scripts/env.sh"), exe, "--version" if exe != "yosys" else "-V"],
                             capture_output=True, text=True, timeout=60)
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except Exception as exc:  # noqa: BLE001
        return f"unavailable: {exc}"


def toolchain_identity() -> str:
    lock = ROOT / "toolchains" / "oss_cad_suite.lock.json"
    if lock.is_file():
        doc = json.loads(lock.read_text())
        return f"oss-cad-suite-{doc['release']}"
    old = ROOT / "toolchain.lock.json"
    if old.is_file():
        doc = json.loads(old.read_text())
        return f"oss-cad-suite-{doc.get('suite_release')}-{doc.get('archive_sha256', '')[:12]}"
    return "none"


def synth_identity(cfg_id: str, top: str = "stream_wrapper", files_f: str = "rtl/files.f", dsp_policy: str = "default",
                   script_version: str = "synth-v2") -> dict:
    from model.config import SUPPORTED_IDS
    cfg = SUPPORTED_IDS[cfg_id]
    doc = {
        "identity_version": IDENTITY_VERSION, "kind": "synth", "top": top, "params": cfg.params(),
        "hdl": hdl_closure(files_f), "yosys": tool_identity("yosys"), "dsp_policy": dsp_policy,
        "script": {"version": script_version, "commands": ["read_verilog -sv", "hierarchy -check -top -chparam", f"synth_ecp5{' -nodsp' if dsp_policy == 'nodsp' else ''} -json", "stat", "check -assert"]},
        "script_source": file_record(ROOT / "tools" / "synth.py")["sha256"],
    }
    doc["synth_key"] = sha256_of({k: v for k, v in doc.items() if k != "synth_key"})
    return doc


def route_identity(synth_key: str, netlist_sha256: str, freq_mhz: float, seed: int, device: dict, timeout_s: int,
                   options: list | None = None, parser_version: str = "pnr-parser-v2") -> dict:
    doc = {
        "identity_version": IDENTITY_VERSION, "kind": "route", "synth_key": synth_key, "netlist_sha256": netlist_sha256,
        "nextpnr": tool_identity("nextpnr-ecp5"), "device": device, "target_mhz": float(freq_mhz), "seed": int(seed),
        "io_constraints": "auto-allocated (--lpf-allow-unconstrained)", "options": options or ["--lpf-allow-unconstrained"],
        "route_timeout_s": int(timeout_s), "parser_version": parser_version,
        "script_source": file_record(ROOT / "tools" / "pnr.py")["sha256"],
    }
    doc["route_key"] = sha256_of({k: v for k, v in doc.items() if k != "route_key"})
    return doc


def native_identity(cfg_id: str, files_f: str = "rtl/files_core.f") -> dict:
    from model.config import SUPPORTED_IDS
    cfg = SUPPORTED_IDS[cfg_id]
    doc = {
        "identity_version": IDENTITY_VERSION, "kind": "native", "params": cfg.params(), "hdl": hdl_closure(files_f),
        "driver": file_record(ROOT / "sim" / "main.cpp"), "builder": file_record(ROOT / "tools" / "build_native.py")["sha256"],
        "verilator": tool_identity("verilator"),
        "flags": ["--cc", "--exe", "--build", "--assert", "-O2", "--x-assign fast", "--x-initial fast", "-CFLAGS -O2 -std=c++17"],
    }
    doc["native_key"] = sha256_of({k: v for k, v in doc.items() if k != "native_key"})
    return doc


def quality_identity(protocol: dict, policy: dict, stream_sha256: str, cap: int, protocol_path: str) -> dict:
    doc = {
        "identity_version": IDENTITY_VERSION, "kind": "quality", "protocol_path": protocol_path,
        "protocol_sha256": sha256_of(protocol), "policy": policy, "stream_sha256": stream_sha256, "cap": int(cap),
        "model_closure": model_closure_sha256(),
        "runtime": {"python": ".".join(map(str, sys.version_info[:3]))},
    }
    doc["quality_key"] = sha256_of({k: v for k, v in doc.items() if k != "quality_key"})
    return doc


def model_closure_sha256() -> str:
    recs = [file_record(p) for p in sorted((ROOT / "model").glob("*.py"))]
    recs += [file_record(ROOT / "tools" / "bench.py")] if (ROOT / "tools" / "bench.py").is_file() else []
    return sha256_of(recs)


def source_closure_sha256() -> str:
    """Hash of everything that can change a measurement: model, rtl, generated, tb, tools, sim, tests."""
    recs = []
    for pat in ("model/*.py", "rtl/*.sv", "rtl/*.f", "rtl/generated/*.svh", "tb/*.py", "tools/*.py", "sim/*.cpp",
                "tests/**/*.py", "tests/fixtures/*.json", "benchmarks/*.json", "Makefile", "scripts/*.sh"):
        for p in sorted(ROOT.glob(pat)):
            recs.append(file_record(p))
    return sha256_of(recs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synth", metavar="CONFIG_ID")
    ap.add_argument("--route", metavar="CONFIG_ID")
    ap.add_argument("--native", metavar="CONFIG_ID")
    ap.add_argument("--freq", type=float, default=50.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--source", action="store_true")
    args = ap.parse_args()
    if args.source:
        print(source_closure_sha256())
    if args.synth:
        print(json.dumps({"synth_key": synth_identity(args.synth)["synth_key"]}))
    if args.native:
        print(json.dumps({"native_key": native_identity(args.native)["native_key"]}))
    if args.route:
        s = synth_identity(args.route)
        print(json.dumps({"route_key_inputs": "netlist hash required; see tools/pnr.py", "synth_key": s["synth_key"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
