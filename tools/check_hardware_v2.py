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
from tools.identity import native_identity, route_identity, synth_identity, tool_identity, toolchain_identity  # noqa: E402
from tools.measure_matrix import (RAW_DECISIONS, SUMMARY_DIR, corpus_hash, expand_jobs, job_label, job_timeout,  # noqa: E402
                                  load_manifest, load_raw_records)

OUTCOMES = ("routed_timing_met", "routed_timing_failed", "route_timeout")
HEX64 = set("0123456789abcdef")


def resolve_route_records(m: dict, records: list[dict] | None = None, *, root: Path = ROOT,
                          tools: dict | None = None) -> tuple[list[dict], list[str]]:
    """Match matrix jobs to records without rebuilding a path-stamped Yosys netlist."""
    jobs = expand_jobs(m)
    records = load_raw_records() if records is None else records
    by_label = {}
    for rec in records:
        try:
            label = job_label({"configuration": rec["configuration_id"], "target_mhz": rec["target_mhz"], "seed": rec["seed"]})
        except (KeyError, TypeError, ValueError):
            continue
        by_label.setdefault(label, []).append(rec)

    synth_docs = {}
    for cid in {j["configuration"] for j in jobs}:
        synth_docs[cid] = synth_identity(SUPPORTED_IDS[cid], top=m["top"], dsp_policy=m["dsp_policy"], root=root, tools=tools)
    nextpnr = tool_identity("nextpnr-ecp5", root, tools)
    tcid = toolchain_identity(root)
    options = ["--lpf-allow-unconstrained"]
    io_constraints = "auto-allocated (--lpf-allow-unconstrained)"
    found, problems = [], []

    for job in jobs:
        label = job_label(job)
        cfg = SUPPORTED_IDS[job["configuration"]]
        synth_doc = synth_docs[job["configuration"]]
        timeout = job_timeout(m, job["configuration"])
        matches = {}
        for rec in by_label.get(label, []):
            netlist_sha = rec.get("netlist_sha256")
            fixed_fields_match = (
                rec.get("schema") == "route-record-v2"
                and rec.get("synth_key") == synth_doc["synth_key"]
                and rec.get("yosys") == synth_doc["yosys"]
                and rec.get("nextpnr") == nextpnr
                and rec.get("toolchain_id") == tcid
                and rec.get("top") == m["top"]
                and rec.get("params") == cfg.params()
                and rec.get("device") == pnr.DEVICE
                and rec.get("dsp_policy") == m["dsp_policy"]
                and rec.get("route_timeout_s") == timeout
                and rec.get("options") == options
                and rec.get("io_constraints") == io_constraints
                and rec.get("script_version") == pnr.ROUTE_SCRIPT_VERSION
                and isinstance(netlist_sha, str) and len(netlist_sha) == 64 and set(netlist_sha) <= HEX64
            )
            if not fixed_fields_match:
                continue
            ident = route_identity(synth_doc["synth_key"], netlist_sha, job["target_mhz"], job["seed"], pnr.DEVICE,
                                   timeout, options, pnr.ROUTE_SCRIPT_VERSION, root, tools)
            if rec.get("route_key") == ident["route_key"]:
                matches.setdefault(rec["route_key"], []).append(rec)
        if not matches:
            problems.append(f"{label}: no record matches the current HDL and locked Linux tools "
                            f"(synthesis {synth_doc['synth_key'][:12]}; {len(by_label.get(label, []))} record(s) for this job)")
            found.append({**job, "label": label, "synth_key": synth_doc["synth_key"], "route_key": None, "record": None})
            continue
        if len(matches) != 1:
            problems.append(f"{label}: {len(matches)} path-distinct netlist records match one synthesis identity")
            found.append({**job, "label": label, "synth_key": synth_doc["synth_key"], "route_key": None, "record": None})
            continue
        key, attempts = next(iter(matches.items()))
        rec = max(attempts, key=lambda d: int(d.get("attempt", {}).get("number", 0)))
        found.append({**job, "label": label, "synth_key": synth_doc["synth_key"], "route_key": key, "record": rec})

    hashes = {}
    for item in found:
        if item["record"] is not None:
            hashes.setdefault(item["configuration"], set()).add(item["record"]["netlist_sha256"])
    for cid, values in sorted(hashes.items()):
        if len(values) != 1:
            problems.append(f"{cid}: matrix records use {len(values)} netlist hashes for one synthesis identity")
    return found, problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="benchmarks/hardware_v2.json")
    args = ap.parse_args()
    m = load_manifest(ROOT / args.manifest)
    items, problems = resolve_route_records(m)
    statuses = {}
    per_config = {}
    for it in items:
        rec = it["record"]
        label = it["label"]
        if rec is None:
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
        planned = {it["route_key"] for it in items if it["route_key"] is not None}
        missing = planned - current
        print(f"CHECK hardware_v2_csv_current {len(planned) - len(missing)}/{len(items)}")
        if len(planned) != len(items):
            problems.append(f"derived CSV cannot be checked until all {len(items)} route identities resolve")
        elif missing:
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
