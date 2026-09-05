#!/usr/bin/env python3
"""Complete job identities (guide §10.2).

Every cached build or measurement is keyed by a SHA-256 over canonical JSON of *everything that
determines it*: file bytes in the transitive HDL closure (with relative paths and lengths), the
ordered `.f` list, elaboration parameters, tool identities, script versions/options, constraints.
mtimes are never used, and no result is keyed by an RTL hash alone.

    synth_key    = H(hdl closure + ordered .f, top, params, yosys identity, dsp policy, script)
    route_key    = H(synth_key, netlist sha256, nextpnr identity, device, target_mhz, seed,
                     io constraints, options, timeout, route script version)
    analysis_key = H(route_key, parser version)      # re-parse a retained log, never re-route
    native_key   = H(hdl closure of rtl/files_core.f, params, driver, builder, verilator, flags)
    quality_key  = H(protocol content, policy/profile, stream sha256, cap, model closure, runtime)

All functions take an optional `root` (tests use a fake tree) and `tools` (exe -> identity string;
tests inject values, real runs read `--version` once per process).

    python tools/identity.py --synth a1-cache-d1-p0-l1
    python tools/identity.py --native a1-cache-d1-p0-l1
    python tools/identity.py --source
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

INCLUDE_RE = re.compile(r'`include\s+"([^"]+)"')
IDENTITY_VERSION = "identity-v1"
SYNTH_SCRIPT_VERSION = "synth-v2"
ROUTE_SCRIPT_VERSION = "route-v2"
PNR_PARSER_VERSION = "pnr-parser-v2"
NATIVE_FLAGS = ["--cc", "--exe", "--build", "--assert", "-O2", "--x-assign fast", "--x-initial fast",
                "-CFLAGS -O2 -std=c++17"]
DEVICE_ECP5_85F = {"device": "LFE5U-85F", "flag": "--85k", "package": "CABGA381", "speed": "6"}


# ---- canonical serialization -------------------------------------------------------------------

def canonical(obj) -> bytes:
    """Sorted keys, no whitespace, ASCII escapes, no NaN: the same object always gives the same bytes."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def sha256_of(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def file_record(path: Path, root: Path = ROOT) -> dict:
    data = Path(path).read_bytes()
    return {"path": str(Path(path).relative_to(root)), "bytes": len(data), "sha256": sha256_bytes(data)}


def read_files_f(path: Path) -> list[str]:
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


# ---- HDL closure ------------------------------------------------------------------------------------

def hdl_closure(files_f: str = "rtl/files.f", include_dir: str = "rtl", root: Path = ROOT) -> dict:
    """Ordered source list from the .f file plus every transitively `include`d file, each hashed."""
    root = Path(root)
    sources = read_files_f(root / files_f)
    seen, records = set(), []
    stack = [root / s for s in sources]
    while stack:
        p = stack.pop(0)
        rel = str(p.relative_to(root))
        if rel in seen:
            continue
        seen.add(rel)
        records.append(file_record(p, root))
        for inc in INCLUDE_RE.findall(p.read_text(errors="ignore")):
            cand = root / include_dir / inc
            if not cand.is_file():
                cand = p.parent / inc
            if cand.is_file():
                stack.append(cand)
    return {"files_f": files_f, "files_f_sha256": sha256_file(root / files_f), "ordered": list(sources),
            "closure": sorted(records, key=lambda r: r["path"])}


# ---- tool identities ------------------------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def _tool_identity_cached(exe: str, root_str: str) -> str:
    try:
        out = subprocess.run(["bash", str(Path(root_str) / "scripts" / "env.sh"), exe,
                              "--version" if exe != "yosys" else "-V"], capture_output=True, text=True, timeout=60)
        text = (out.stdout or out.stderr).strip()
        return text.splitlines()[0] if text else f"unavailable: {exe} printed nothing"
    except Exception as exc:  # noqa: BLE001
        return f"unavailable: {exc}"


def tool_identity(exe: str, root: Path = ROOT, tools: dict | None = None) -> str:
    if tools and exe in tools:
        return tools[exe]
    return _tool_identity_cached(exe, str(root))


def toolchain_identity(root: Path = ROOT) -> str:
    lock = Path(root) / "toolchains" / "oss_cad_suite.lock.json"
    if lock.is_file():
        doc = json.loads(lock.read_text())
        return f"oss-cad-suite-{doc['release']}"
    old = Path(root) / "toolchain.lock.json"
    if old.is_file():
        doc = json.loads(old.read_text())
        return f"oss-cad-suite-{doc.get('suite_release')}-{doc.get('archive_sha256', '')[:12]}"
    return "none"


def _params(cfg) -> dict:
    """Accept a configuration id, a Config, or an explicit parameter dict."""
    if isinstance(cfg, dict):
        return {k: int(v) for k, v in sorted(cfg.items())}
    if isinstance(cfg, str):
        from model.config import SUPPORTED_IDS
        return SUPPORTED_IDS[cfg].params()
    return cfg.params()


def _with_key(doc: dict, name: str) -> dict:
    doc[name] = sha256_of({k: v for k, v in doc.items() if k != name})
    return doc


# ---- identities ----------------------------------------------------------------------------------------

def synth_identity(cfg, top: str = "stream_wrapper", files_f: str = "rtl/files.f", dsp_policy: str = "default",
                   script_version: str = SYNTH_SCRIPT_VERSION, root: Path = ROOT, tools: dict | None = None) -> dict:
    if dsp_policy not in ("default", "nodsp"):
        raise ValueError(f"unknown dsp policy {dsp_policy}")
    doc = {
        "identity_version": IDENTITY_VERSION, "kind": "synth", "top": top, "params": _params(cfg),
        "hdl": hdl_closure(files_f, root=root), "yosys": tool_identity("yosys", root, tools), "dsp_policy": dsp_policy,
        "script": {"version": script_version,
                   "commands": ["read_verilog -sv", "hierarchy -check -top -chparam",
                                f"synth_ecp5{' -nodsp' if dsp_policy == 'nodsp' else ''} -json", "stat", "check -assert"]},
    }
    return _with_key(doc, "synth_key")


def route_identity(synth_key: str, netlist_sha256: str, freq_mhz: float, seed: int, device: dict = DEVICE_ECP5_85F,
                   timeout_s: int = 600, options: list | None = None, script_version: str = ROUTE_SCRIPT_VERSION,
                   root: Path = ROOT, tools: dict | None = None) -> dict:
    doc = {
        "identity_version": IDENTITY_VERSION, "kind": "route", "synth_key": synth_key, "netlist_sha256": netlist_sha256,
        "nextpnr": tool_identity("nextpnr-ecp5", root, tools), "device": dict(device), "target_mhz": float(freq_mhz),
        "seed": int(seed), "io_constraints": "auto-allocated (--lpf-allow-unconstrained)",
        "options": list(options or ["--lpf-allow-unconstrained"]), "route_timeout_s": int(timeout_s),
        "script_version": script_version,
    }
    return _with_key(doc, "route_key")


def analysis_identity(route_key: str, parser_version: str = PNR_PARSER_VERSION) -> dict:
    """Parsing a retained log is cheap; a parser change re-analyses raw outputs instead of re-routing."""
    return _with_key({"identity_version": IDENTITY_VERSION, "kind": "analysis", "route_key": route_key,
                      "parser_version": parser_version}, "analysis_key")


def native_identity(cfg, files_f: str = "rtl/files_core.f", root: Path = ROOT, tools: dict | None = None,
                    flags: list | None = None) -> dict:
    root = Path(root)
    doc = {
        "identity_version": IDENTITY_VERSION, "kind": "native", "params": _params(cfg), "hdl": hdl_closure(files_f, root=root),
        "driver": file_record(root / "sim" / "main.cpp", root),
        "builder": sha256_file(root / "tools" / "build_native.py") if (root / "tools" / "build_native.py").is_file() else None,
        "verilator": tool_identity("verilator", root, tools), "flags": list(flags or NATIVE_FLAGS),
    }
    return _with_key(doc, "native_key")


def quality_identity(protocol: dict, policy: dict, stream_sha256: str, cap: int, protocol_path: str,
                     model_closure: str | None = None, runtime: dict | None = None) -> dict:
    doc = {
        "identity_version": IDENTITY_VERSION, "kind": "quality", "protocol_path": protocol_path,
        "protocol_sha256": sha256_of(protocol), "policy": dict(policy), "stream_sha256": stream_sha256, "cap": int(cap),
        "model_closure": model_closure if model_closure is not None else model_closure_sha256(),
        "runtime": runtime if runtime is not None else {"python": ".".join(map(str, sys.version_info[:3]))},
    }
    return _with_key(doc, "quality_key")


# ---- closures used by evidence records ------------------------------------------------------------------

def model_closure_sha256(root: Path = ROOT) -> str:
    root = Path(root)
    recs = [file_record(p, root) for p in sorted((root / "model").glob("*.py"))]
    return sha256_of(recs)


SOURCE_PATTERNS = ("model/*.py", "rtl/*.sv", "rtl/*.f", "rtl/generated/*.svh", "tb/*.py", "tools/*.py", "sim/*.cpp",
                   "tests/**/*.py", "tests/fixtures/*.json", "benchmarks/*.json", "Makefile", "scripts/*.sh")


def source_closure_sha256(root: Path = ROOT) -> str:
    """Hash of everything that can change a measurement: model, rtl, generated, tb, tools, sim, tests, manifests."""
    root = Path(root)
    recs = []
    for pat in SOURCE_PATTERNS:
        for p in sorted(root.glob(pat)):
            if p.is_file():
                recs.append(file_record(p, root))
    return sha256_of(recs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synth", metavar="CONFIG_ID")
    ap.add_argument("--native", metavar="CONFIG_ID")
    ap.add_argument("--dsp-policy", default="default", choices=["default", "nodsp"])
    ap.add_argument("--source", action="store_true")
    ap.add_argument("--full", action="store_true", help="print the whole identity document")
    args = ap.parse_args()
    if args.source:
        print(source_closure_sha256())
    if args.synth:
        doc = synth_identity(args.synth, dsp_policy=args.dsp_policy)
        print(json.dumps(doc if args.full else {"synth_key": doc["synth_key"]}, indent=1))
    if args.native:
        doc = native_identity(args.native)
        print(json.dumps(doc if args.full else {"native_key": doc["native_key"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
