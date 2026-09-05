#!/usr/bin/env python3
"""Build the persistent C++ Verilator driver for one configuration, keyed by its complete identity.

    python tools/build_native.py --arch 0 --board-repr 0 --lanes 1 --depth 1 --precision 0

The build lives in build/native/<native_key>/ where native_key (tools/identity.py) covers the
ordered rtl/files_core.f closure including generated headers, the elaboration parameters, the
driver source, this builder, the Verilator identity and the flags.  A build is reused only when
its recorded identity equals the current one; mtimes play no part.  --out (or the legacy
build/native_<id> path used by older callers) becomes a symlink to the identity directory.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.config import Config, add_config_arguments, validate  # noqa: E402
from tools.identity import NATIVE_FLAGS, native_identity  # noqa: E402

WARNING_WAIVERS = ["-Wno-WIDTHTRUNC", "-Wno-WIDTHEXPAND", "-Wno-PINCONNECTEMPTY", "-Wno-UNUSEDSIGNAL",
                   "-Wno-UNUSEDPARAM", "-Wno-DECLFILENAME", "-Wno-CASEINCOMPLETE"]


def identity_dir(key: str) -> Path:
    return ROOT / "build" / "native" / key


def link_alias(alias: Path, target: Path) -> None:
    """Point a convenience path (build/native_<id>) at the identity directory."""
    try:
        if alias.is_symlink() or alias.is_file():
            alias.unlink()
        elif alias.is_dir():
            return  # a real directory from an older layout: leave it alone
        alias.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.path.relpath(target, alias.parent), alias)
    except OSError:
        pass


def build(cfg: Config, out: Path | None = None, files_f: str = "rtl/files_core.f", jobs: int = 2,
          force: bool = False, quiet: bool = False) -> Path:
    ident = native_identity(cfg, files_f)
    key = ident["native_key"]
    bdir = identity_dir(key)
    exe = bdir / "Vtetris_core"
    stamp = bdir / "build.json"
    if out is not None:
        link_alias(Path(out), bdir)
    if exe.is_file() and stamp.is_file() and not force:
        doc = json.loads(stamp.read_text())
        if doc.get("native_key") == key and doc.get("status") == "built":
            return exe
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "identity.json").write_text(json.dumps(ident, indent=1) + "\n")
    sources = [ROOT / s for s in ident["hdl"]["ordered"]]
    cmd = ["bash", str(ROOT / "scripts" / "env.sh"), "verilator", "--cc", "--exe", "--build", "-j", str(jobs), "--assert",
           "-O2", "--x-assign", "fast", "--x-initial", "fast", "--top-module", "tetris_core", f"-I{ROOT / 'rtl'}",
           "-Mdir", str(bdir), *WARNING_WAIVERS, "-CFLAGS", "-O2 -std=c++17"]
    for k, v in cfg.params().items():
        cmd.append(f"-G{k}={v}")
    cmd += [str(s) for s in sources] + [str(ROOT / "sim" / "main.cpp")]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    (bdir / "build.log").write_text(proc.stdout + proc.stderr)
    if proc.returncode != 0 or not exe.is_file():
        stamp.write_text(json.dumps({"native_key": key, "config_id": cfg.id, "status": "failed",
                                     "exit_code": proc.returncode}, indent=1) + "\n")
        print(proc.stdout[-3000:], proc.stderr[-3000:])
        raise SystemExit(f"native build failed for {cfg.id}; see {bdir / 'build.log'}")
    stamp.write_text(json.dumps({"native_key": key, "config": cfg.as_dict(), "config_id": cfg.id, "status": "built",
                                 "flags": NATIVE_FLAGS, "elapsed_s": round(time.perf_counter() - t0, 1)}, indent=1) + "\n")
    if not quiet:
        print(f"built {exe.relative_to(ROOT)} for {cfg.id} ({time.perf_counter() - t0:.0f}s)")
    return exe


def build_harness(top: str, files_f: str, driver: str, params: dict | None = None, jobs: int = 2, force: bool = False,
                  quiet: bool = False, waivers: list | None = None, trace: bool = False, extra_flags: list | None = None) -> Path:
    """Build a native micro-harness (top + driver) keyed by its complete identity, e.g. the compactor.

    extra_flags (e.g. ["--public-flat-rw"] for the trace exporter) are part of the identity and of the build."""
    params = params or {}
    flags = NATIVE_FLAGS + (["--trace"] if trace else []) + list(extra_flags or [])
    ident = native_identity(params, files_f, driver=driver, top=top, flags=flags)
    key = ident["native_key"]
    bdir = identity_dir(key)
    exe = bdir / f"V{top}"
    stamp = bdir / "build.json"
    if exe.is_file() and stamp.is_file() and not force:
        doc = json.loads(stamp.read_text())
        if doc.get("native_key") == key and doc.get("status") == "built":
            return exe
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "identity.json").write_text(json.dumps(ident, indent=1) + "\n")
    sources = [ROOT / s for s in ident["hdl"]["ordered"]]
    cmd = ["bash", str(ROOT / "scripts" / "env.sh"), "verilator", "--cc", "--exe", "--build", "-j", str(jobs), "--assert",
           "-O2", "--x-assign", "fast", "--x-initial", "fast", "--top-module", top, f"-I{ROOT / 'rtl'}",
           "-Mdir", str(bdir), *(WARNING_WAIVERS if waivers is None else waivers), *(["--trace"] if trace else []),
           *list(extra_flags or []), "-CFLAGS", "-O2 -std=c++17"]
    for k, v in params.items():
        cmd.append(f"-G{k}={v}")
    cmd += [str(s) for s in sources] + [str(ROOT / driver)]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    (bdir / "build.log").write_text(proc.stdout + proc.stderr)
    if proc.returncode != 0 or not exe.is_file():
        stamp.write_text(json.dumps({"native_key": key, "top": top, "status": "failed", "exit_code": proc.returncode}, indent=1) + "\n")
        print(proc.stdout[-3000:], proc.stderr[-3000:])
        raise SystemExit(f"native harness build failed for {top}; see {bdir / 'build.log'}")
    stamp.write_text(json.dumps({"native_key": key, "top": top, "params": params, "driver": driver, "files_f": files_f,
                                 "status": "built", "elapsed_s": round(time.perf_counter() - t0, 1)}, indent=1) + "\n")
    if not quiet:
        print(f"built {exe.relative_to(ROOT)} ({top}, {time.perf_counter() - t0:.0f}s)")
    return exe


def main() -> int:
    ap = argparse.ArgumentParser()
    add_config_arguments(ap)
    ap.add_argument("--out", default=None, help="convenience symlink to the identity directory")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--print-key", action="store_true")
    args = ap.parse_args()
    cfg = validate(Config(args.arch, args.board_repr, args.lanes, args.depth, args.precision))
    if args.print_key:
        print(native_identity(cfg)["native_key"])
        return 0
    out = ROOT / (args.out or f"build/native_{cfg.id}")
    exe = build(cfg, out, jobs=args.jobs, force=args.force)
    print(exe.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
