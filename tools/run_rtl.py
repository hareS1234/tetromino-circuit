#!/usr/bin/env python3
"""Build and run a cocotb test module against a SystemVerilog top with Verilator.

    python tools/run_rtl.py --top counter --test tb_counter --source rtl/learning/counter.sv
    python tools/run_rtl.py --top tetris_core --test tb_core --files-f rtl/files.f --param ARCH=1

Every distinct (top, parameters) pair gets its own build directory under build/.
The test result XML is checked; zero collected tests or any failure exits nonzero.
Extra key=value pairs passed with --env are exported to the simulator process.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_files_f(path: Path):
    sources = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sources.append(line)
    return sources


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", required=True)
    parser.add_argument("--test", required=True, help="cocotb test module under tb/")
    parser.add_argument("--source", action="append", default=[], help="source file (repeatable, dependency order)")
    parser.add_argument("--files-f", default=None, help="file list, one source per line")
    parser.add_argument("--param", action="append", default=[], help="NAME=value top-level parameter")
    parser.add_argument("--env", action="append", default=[], help="NAME=value exported to the test")
    parser.add_argument("--waves", action="store_true")
    parser.add_argument("--build-tag", default="", help="extra build directory suffix")
    parser.add_argument("--testcase", default=None, help="comma-separated subset of test names")
    args = parser.parse_args()

    sources = []
    if args.files_f:
        sources += read_files_f(ROOT / args.files_f)
    sources += args.source
    if not sources:
        parser.error("no sources given")
    resolved = [(ROOT / s).resolve() for s in sources]
    for src in resolved:
        if not src.is_file():
            raise FileNotFoundError(src)

    parameters = {}
    for item in args.param:
        name, value = item.split("=", 1)
        parameters[name] = int(value, 0)
    suffix = "_".join(f"{k}-{v}" for k, v in sorted(parameters.items()))
    build = ROOT / "build" / (args.top + ("_" + suffix if suffix else "") + (("_" + args.build_tag) if args.build_tag else ""))
    build.mkdir(parents=True, exist_ok=True)

    # cocotb 2.0.1's runner exports PYTHONPATH from *this process's sys.path* (not from the
    # environment), so the test/model directories must be inserted into sys.path here.
    for extra in (ROOT / "tests", ROOT / "tb", ROOT):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    os.environ["PYTHONPATH"] = os.pathsep.join(sys.path)
    for item in args.env:
        name, value = item.split("=", 1)
        os.environ[name] = value
    os.environ["TETROMINO_ROOT"] = str(ROOT)
    os.environ["TETROMINO_PARAMS"] = ",".join(f"{k}={v}" for k, v in sorted(parameters.items()))

    from cocotb_tools.runner import get_results, get_runner  # noqa: E402 (needs the venv)

    runner = get_runner("verilator")
    t0 = time.perf_counter()
    runner.build(
        sources=resolved,
        includes=[ROOT / "rtl"],
        hdl_toplevel=args.top,
        parameters=parameters,
        build_dir=build,
        build_args=["--assert", "-Wno-fatal", "--x-assign", "unique", "--x-initial", "unique",
                    "-j", "2", "--timing", "-Wno-WIDTHTRUNC", "-Wno-WIDTHEXPAND"],
        timescale=("1ns", "1ps"),
        waves=args.waves,
    )
    t1 = time.perf_counter()
    results = build / "results.xml"
    if results.exists():
        results.unlink()
    result_path = runner.test(
        hdl_toplevel=args.top,
        test_module=args.test,
        testcase=args.testcase.split(",") if args.testcase else None,
        build_dir=build,
        test_dir=build,
        results_xml=str(results),
        waves=args.waves,
        extra_env={k: v for k, v in os.environ.items() if k.startswith("TETROMINO_")},
    )
    t2 = time.perf_counter()
    if not Path(result_path).is_file():
        raise SystemExit(f"RTL tests: no results XML produced at {result_path}")
    total, failed = get_results(result_path)
    print(f"RTL tests: {total} total, {failed} failed (build {t1 - t0:.1f}s, run {t2 - t1:.1f}s) [{build.name}]")
    if total == 0 or failed:
        raise SystemExit(f"RTL tests: {total} total, {failed} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
