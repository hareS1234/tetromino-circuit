#!/usr/bin/env python3
"""Make sure every planned hardware job has one coherent, identity-matched outcome."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.config import SUPPORTED_IDS  # noqa: E402
from tools import pnr  # noqa: E402
from tools.identity import native_identity  # noqa: E402
from tools.measure_matrix import RAW_DECISIONS, SUMMARY_DIR, corpus_hash, expand_jobs, job_label, job_timeout, load_manifest, plan  # noqa: E402

OUTCOMES = ("routed_timing_met", "routed_timing_failed", "route_timeout")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="benchmarks/hardware_v2.json")
    args = ap.parse_args()
    m = load_manifest(ROOT / args.manifest)
    items = plan(m, None, None)              # synthesis identities are reused (never re-run when cached)
    problems = []
    statuses = {}
    per_config = {}
    for it in items:
        rec = pnr.existing_record(it["route_key"])
        label = it["label"]
        if rec is None:
            problems.append(f"{label}: no record under route {it['route_key'][:12]}")
            statuses[label] = "missing"
            continue
        st = rec.get("status")
        statuses[label] = st
        if st not in OUTCOMES:
            problems.append(f"{label}: status {st} is not an outcome (attempt {rec['attempt']['number']}: {rec.get('status_reason')})")
        if rec.get("synth_key") != it["synth_key"]:
            problems.append(f"{label}: record synthesis {rec.get('synth_key', '')[:12]} != planned {it['synth_key'][:12]}")
        if rec.get("route_timeout_s") != job_timeout(m, it["configuration"]) or rec.get("dsp_policy") != m["dsp_policy"]:
            problems.append(f"{label}: budget/DSP policy differ from the manifest")
        if rec.get("analysis", {}).get("parser_version") != pnr.PNR_PARSER_VERSION:
            problems.append(f"{label}: parsed with {rec.get('analysis', {}).get('parser_version')}, not {pnr.PNR_PARSER_VERSION}")
        t = rec.get("timing", {})
        if st == "routed_timing_met" and not (t.get("met") is True and t.get("reported_fmax_mhz")):
            problems.append(f"{label}: routed_timing_met without a reported fmax")
        if st == "routed_timing_failed" and not (t.get("met") is False and t.get("reported_fmax_mhz")):
            problems.append(f"{label}: routed_timing_failed without a reported fmax")
        if st == "route_timeout" and not rec.get("process", {}).get("timed_out"):
            problems.append(f"{label}: route_timeout without the timed_out flag")
        if not rec.get("area", {}).get("lut4"):
            problems.append(f"{label}: no area in the record")
        cfgc = per_config.setdefault(it["configuration"], {"jobs": 0, **{k: 0 for k in OUTCOMES}, "other": 0})
        cfgc["jobs"] += 1
        cfgc[st if st in OUTCOMES else "other"] += 1
    n = len(items)
    ok_jobs = sum(1 for s in statuses.values() if s in OUTCOMES)
    print(f"CHECK hardware_v2_jobs {ok_jobs}/{n}")
    counts = {k: sum(1 for s in statuses.values() if s == k) for k in OUTCOMES}
    counts["incomplete"] = n - ok_jobs
    print(f"  outcomes: {counts}")
    for cid, c in sorted(per_config.items()):
        print(f"  {cid:22s} jobs {c['jobs']:2d}: met {c['routed_timing_met']:2d}  failed {c['routed_timing_failed']:2d}  timeout {c['route_timeout']:2d}  other {c['other']}")
    # decisions
    dec = m.get("decisions")
    dec_ok = dec_n = 0
    if dec:
        for cid in dec["configurations"]:
            dec_n += 1
            cfg = SUPPORTED_IDS[cid]
            meta_path = RAW_DECISIONS / cid / f"{corpus_hash(cfg.depth, int(dec['count']))}.json"
            if not meta_path.is_file():
                problems.append(f"decisions {cid}: no record")
                continue
            meta = json.loads(meta_path.read_text())
            if meta.get("status") != "matched" or meta.get("count") != int(dec["count"]):
                problems.append(f"decisions {cid}: status {meta.get('status')} count {meta.get('count')}")
                continue
            if meta.get("native_key") != native_identity(cfg)["native_key"]:
                problems.append(f"decisions {cid}: record from another native identity (source changed since the run)")
                continue
            if not (ROOT / meta["csv"]).is_file():
                problems.append(f"decisions {cid}: CSV missing")
                continue
            dec_ok += 1
        print(f"CHECK hardware_v2_decisions {dec_ok}/{dec_n}")
    # derived CSV
    csv_path = SUMMARY_DIR / f"routes_{m.get('name', 'matrix')}.csv"
    if csv_path.is_file():
        with open(csv_path) as fh:
            rows = list(csv.DictReader(fh))
        current = {r["route_key"] for r in rows if r.get("current") in ("1", "True", "true")}
        planned = {it["route_key"] for it in items}
        missing = planned - current
        print(f"CHECK hardware_v2_csv_current {len(planned) - len(missing)}/{len(planned)}")
        if missing:
            problems.append(f"derived CSV lacks {len(missing)} current job rows (re-run the matrix to re-derive)")
    else:
        problems.append(f"derived CSV missing: {csv_path.relative_to(ROOT)}")
    for p in problems:
        print("  -", p)
    if problems:
        print(f"check-hardware-v2: INCOMPLETE ({len(problems)} problem(s)); timeouts and timing failures are outcomes, missing or "
              "erroring jobs are not")
        return 1
    print(f"check-hardware-v2: OK. All {n} declared route jobs and {dec_ok} decision corpora are accounted for")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
