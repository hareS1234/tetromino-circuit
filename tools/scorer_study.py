#!/usr/bin/env python3
"""Scorer-mapping study for the numerical profiles (U14, guide §9.3 last paragraph).

    python tools/scorer_study.py                       # P0-P7 scorer microbenchmarks + A1/cache cores P0, P5-P7
    python tools/scorer_study.py --cores 0,1,2,3,4,5,6,7

Two separately reported measurements, never mixed:
  * registered scorer microbenchmarks: `score` alone (rtl/files_score.f) per PRECISION, Yosys synth_ecp5
    -nodsp, all 33 output bits (valid_o, score_o[31:0]) are top-level ports and therefore observed; the
    P0 constant-multiply form (USE_MULT=1, DSP policy default) is included as the DSP reference;
  * complete A1/cache/depth-one/one-lane cores (stream_wrapper, identity-keyed synth records via
    tools/synth.py, -nodsp) per profile, LUT4/FF/CCU2C/DSP and the delta against P0.
Scorer-only savings must not be read as full-core savings; the core numbers are the full-core numbers.
Writes results/v2/precision/scorer_study.json (schema scorer-study-v1).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.config import Config, validate  # noqa: E402
from model.numeric import PRECISION_IDS, profile_metadata  # noqa: E402
from tools.check_synth_log import parse_stat, summarize_ecp5  # noqa: E402
from tools.identity import read_files_f, source_closure_sha256, toolchain_identity  # noqa: E402
from tools.synth import synthesize  # noqa: E402

OUT = ROOT / "results" / "v2" / "precision" / "scorer_study.json"


def micro_synth(precision: int, use_mult: int, nodsp: bool) -> dict:
    tag = f"score_p{precision}" + ("_mult" if use_mult else "") + ("" if nodsp else "_dsp")
    out = ROOT / "build" / "synth_module" / tag
    out.mkdir(parents=True, exist_ok=True)
    sources = [str(ROOT / s) for s in read_files_f(ROOT / "rtl" / "files_score.f")]
    script = "\n".join([
        f"read_verilog -sv -I{ROOT / 'rtl'} " + " ".join(sources),
        f"hierarchy -check -top score -chparam PRECISION {precision} -chparam USE_MULT {use_mult}",
        f"synth_ecp5{' -nodsp' if nodsp else ''} -top score",
        "stat",
        "check -assert",
        "",
    ])
    (out / "synth.ys").write_text(script)
    log = out / "yosys.log"
    proc = subprocess.run(["bash", str(ROOT / "scripts" / "env.sh"), "yosys", "-q", "-l", str(log), "-s", str(out / "synth.ys")],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout[-2000:], proc.stderr[-2000:])
        raise SystemExit(f"yosys failed for {tag}; see {log}")
    text = log.read_text()
    stat = parse_stat(text)
    summary = summarize_ecp5(stat["cells"])
    if summary["latches"] or "Latch inferred" in text:
        raise SystemExit(f"latch inferred in {tag}")
    doc = {"tag": tag, "precision": precision, "use_mult": use_mult, "dsp_policy": "nodsp" if nodsp else "default",
           "cells_total": stat["total"], "cells": stat["cells"], "lut4": summary["lut4"], "ff": summary["ff"], "ccu2c": summary["ccu2c"],
           "dsp": summary["dsp"], "lut_equiv": summary["lut_equiv"],
           "observed_outputs": "valid_o and score_o[31:0] are the module's ports: all 33 registered bits are observed; "
                               "sign-extension copies may be merged by opt_merge (identical D input), which the FF count shows",
           "log": str(log.relative_to(ROOT))}
    (out / "summary.json").write_text(json.dumps(doc, indent=1) + "\n")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cores", default="0,5,6,7", help="profiles whose complete A1/cache core is synthesized (-nodsp)")
    ap.add_argument("--scorers", default=",".join(str(p) for p in PRECISION_IDS))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    scorers = []
    for p in (int(x) for x in args.scorers.split(",")):
        d = micro_synth(p, 0, True)
        scorers.append(d)
        print(f"scorer P{p}: LUT4 {d['lut4']} FF {d['ff']} CCU2C {d['ccu2c']} DSP {d['dsp']} ({d['cells_total']} cells)")
    ref = micro_synth(0, 1, False)
    print(f"scorer P0 constant multiplies (DSP allowed): LUT4 {ref['lut4']} FF {ref['ff']} CCU2C {ref['ccu2c']} DSP {ref['dsp']}")
    cores = {}
    for p in (int(x) for x in args.cores.split(",")):
        cfg = validate(Config(1, 1, 1, 1, p))
        doc = synthesize("stream_wrapper", cfg, files_f="rtl/files.f", dsp_policy="nodsp", force=args.force, quiet=False)
        cores[f"p{p}"] = {"configuration_id": cfg.id, "synth_key": doc["synth_key"], "reused": doc.get("reused", False),
                          "cells_total": doc["cells_total"], "lut4": doc["lut4"], "ff": doc["ff"], "ccu2c": doc["ccu2c"], "dsp": doc["dsp"],
                          "bram": doc["bram"], "netlist_sha256": doc["netlist_sha256"], "dsp_policy": "nodsp", "top": "stream_wrapper"}
    base = cores.get("p0")
    if base:
        for k, c in cores.items():
            c["delta_vs_p0"] = {m: c[m] - base[m] for m in ("lut4", "ff", "ccu2c", "dsp", "cells_total")}
    out = {"schema": "scorer-study-v1", "recorded_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "toolchain_id": toolchain_identity(), "source_sha256": source_closure_sha256(),
           "profiles": {f"p{p}": profile_metadata(p) for p in PRECISION_IDS},
           "scorer_microbenchmarks": {"method": "yosys synth_ecp5 -nodsp of module `score` (rtl/files_score.f) alone; registered output",
                                      "rows": scorers, "p0_constant_multiply_reference": ref},
           "cores": {"method": "tools/synth.py stream_wrapper ARCH=1 BOARD_REPR=1 LANES=1 DEPTH=1 -nodsp (identity-keyed, build/synth/<key>)",
                     "rows": cores},
           "caveat": "scorer-only mapping and total player area are reported separately; a scorer saving is not a core saving"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(f"CHECK scorer_study {len(scorers) + len(cores)}/{len(scorers) + len(cores)}")
    print(f"-> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
