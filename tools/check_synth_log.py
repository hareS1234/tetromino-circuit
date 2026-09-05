#!/usr/bin/env python3
"""Validate a Yosys log: nonempty cell count, no latches, and print the ECP5 resource summary."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def parse_stat(text: str) -> dict:
    """Return {'total': n, 'cells': {type: count}} from the last statistics table of a Yosys log.

    Handles both the classic "Number of cells:" format and the Yosys 0.4x+ format
    ("      13 cells" followed by indented "       4   CCU2C" lines).  When a
    hierarchy is present the table for the top module including submodules is used.
    """
    cells = {}
    total = None
    idx = text.rfind("Printing statistics")
    section = text[idx:] if idx >= 0 else text
    # prefer the 'Count including submodules' table when it exists
    inc = section.rfind("Count including submodules")
    if inc >= 0:
        section = section[inc:]
    lines = section.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"\s*(\d+)\s+cells\s*$", line) or re.match(r"\s*Number of cells:\s+(\d+)", line)
        if m:
            total = int(m.group(1))
            cells = {}
            for sub in lines[i + 1:]:
                mm = re.match(r"\s+(\d+)\s+(\$?[\w$]+)\s*$", sub) or re.match(r"\s+(\$?[\w$]+)\s+(\d+)\s*$", sub)
                if mm:
                    a, b = mm.groups()
                    if a.isdigit():
                        cells[b] = cells.get(b, 0) + int(a)
                    else:
                        cells[a] = cells.get(a, 0) + int(b)
                elif sub.strip() == "" and cells:
                    break
                elif sub.strip() == "":
                    continue
                else:
                    break
            break
    if total is None:
        total = 0
    return {"total": total, "cells": cells}


def summarize_ecp5(cells: dict) -> dict:
    lut4 = sum(v for k, v in cells.items() if k in ("LUT4",))
    ff = sum(v for k, v in cells.items() if k.startswith("TRELLIS_FF") or k in ("TRELLIS_FF",))
    carry = sum(v for k, v in cells.items() if k in ("CCU2C",))
    bram = sum(v for k, v in cells.items() if k.startswith("DP16KD") or k.startswith("PDPW16KD"))
    dsp = sum(v for k, v in cells.items() if k.startswith("MULT18X18D") or k.startswith("ALU54"))
    dist = sum(v for k, v in cells.items() if k.startswith("TRELLIS_DPR16X4") or k.startswith("TRELLIS_SLICE"))
    latches = sum(v for k, v in cells.items() if "DLATCH" in k or k == "$dlatch" or k == "$_DLATCH_P_")
    return {"lut4": lut4, "ff": ff, "ccu2c": carry, "bram": bram, "dsp": dsp, "dpr16x4": dist, "latches": latches,
            "lut_equiv": lut4 + 2 * carry}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--min-cells", type=int, default=1)
    args = ap.parse_args()
    text = Path(args.log).read_text()
    stat = parse_stat(text)
    summary = summarize_ecp5(stat["cells"])
    print(f"cells total {stat['total']}  LUT4 {summary['lut4']}  FF {summary['ff']}  CCU2C {summary['ccu2c']}  "
          f"BRAM {summary['bram']}  DSP {summary['dsp']}  latches {summary['latches']}")
    if "Latch inferred" in text or summary["latches"]:
        print("ERROR: latch inferred")
        return 1
    if stat["total"] < args.min_cells:
        print(f"ERROR: only {stat['total']} cells (expected >= {args.min_cells}); design may have been optimized away")
        return 1
    if re.search(r"^ERROR", text, re.M):
        print("ERROR in yosys log")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
