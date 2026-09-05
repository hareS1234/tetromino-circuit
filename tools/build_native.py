#!/usr/bin/env python3
"""Build the persistent C++ Verilator driver for one configuration.

    python tools/build_native.py --arch 0 --board-repr 0 --lanes 1 --depth 1 --precision 0 --out build/native_a0-bitmap-d1-p0-l1
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.config import Config, add_config_arguments, validate  # noqa: E402
from tools.run_rtl import read_files_f  # noqa: E402


def build(cfg: Config, out: Path, files_f: str = "rtl/files_core.f", jobs: int = 2, force: bool = False) -> Path:
    exe = out / "Vtetris_core"
    stamp = out / "build.json"
    sources = [ROOT / s for s in read_files_f(ROOT / files_f)]
    newest = max([p.stat().st_mtime for p in sources] + [(ROOT / "sim" / "main.cpp").stat().st_mtime]
                 + [p.stat().st_mtime for p in (ROOT / "rtl" / "generated").glob("*.svh")])
    if exe.is_file() and stamp.is_file() and not force:
        doc = json.loads(stamp.read_text())
        if doc.get("config") == cfg.as_dict() and doc.get("source_mtime", 0) >= newest:
            return exe
    out.mkdir(parents=True, exist_ok=True)
    cmd = ["bash", str(ROOT / "scripts" / "env.sh"), "verilator", "--cc", "--exe", "--build", "-j", str(jobs), "--assert",
           "-O2", "--x-assign", "fast", "--x-initial", "fast", "--top-module", "tetris_core", f"-I{ROOT / 'rtl'}",
           "-Mdir", str(out), "-Wno-WIDTHTRUNC", "-Wno-WIDTHEXPAND", "-Wno-PINCONNECTEMPTY", "-Wno-UNUSEDSIGNAL",
           "-Wno-UNUSEDPARAM", "-Wno-DECLFILENAME", "-Wno-CASEINCOMPLETE",
           "-CFLAGS", "-O2 -std=c++17"]
    for k, v in cfg.params().items():
        cmd.append(f"-G{k}={v}")
    cmd += [str(s) for s in sources] + [str(ROOT / "sim" / "main.cpp")]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    (out / "build.log").write_text(proc.stdout + proc.stderr)
    if proc.returncode != 0 or not exe.is_file():
        print(proc.stdout[-3000:], proc.stderr[-3000:])
        raise SystemExit(f"native build failed for {cfg.id}; see {out / 'build.log'}")
    stamp.write_text(json.dumps({"config": cfg.as_dict(), "config_id": cfg.id, "source_mtime": newest,
                                 "elapsed_s": round(time.perf_counter() - t0, 1)}, indent=1))
    print(f"built {exe.relative_to(ROOT)} ({time.perf_counter() - t0:.0f}s)")
    return exe


def main() -> int:
    ap = argparse.ArgumentParser()
    add_config_arguments(ap)
    ap.add_argument("--out", default=None)
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    cfg = validate(Config(args.arch, args.board_repr, args.lanes, args.depth, args.precision))
    out = ROOT / (args.out or f"build/native_{cfg.id}")
    build(cfg, out, jobs=args.jobs, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
