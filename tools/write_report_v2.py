#!/usr/bin/env python3
"""Rebuild ``docs/results.md`` from committed records; nothing here runs an experiment."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import write_report as v1  # noqa: E402

OUT = ROOT / "docs" / "results.md"
SHORT = {"a0-bitmap-d1-p0-l1": "X0 A0 serial, bitmap", "a1-bitmap-d1-p0-l1": "X1 A1 fast, bitmap", "a1-cache-d1-p0-l1": "X2 A1 fast, height cache",
         "a1-cache-d1-p0-l2": "X3 A1 cache, 2 lanes", "a1-cache-d1-p0-l4": "X4 A1 cache, 4 lanes", "a2-cache-d1-p0-l1": "X5 A2 candidate pipeline",
         "a1-cache-d1-p1-l1": "A1 cache, P1 powers_of_two", "a1-cache-d1-p5-l1": "A1 cache, P5 coeff_u4", "a1-cache-d1-p6-l1": "A1 cache, P6 coeff_u3",
         "a1-cache-d1-p7-l1": "A1 cache, P7 coeff_u2"}
PATH_CATEGORIES = [
    ("u_drop", "landing (A1 closed-form drop / A0 descent)"), ("drop_fast", "landing (A1 closed-form drop / A0 descent)"),
    ("u_front", "A2 P0–P3 landing/merge front end"), ("hsel", "A2 P0–P3 landing/merge front end"),
    ("u_clear", "compactor (ranks/select)"), ("line_clear", "compactor (ranks/select)"), ("u_merge", "merge"),
    ("u_features", "feature extraction"), ("u_feat", "feature extraction"), ("features", "feature extraction"),
    ("u_score", "scorer"), ("score", "scorer"), ("u_search", "A2 enumeration / reducer"), ("cand", "candidate ROM / decode"),
    ("u_lane", "lane control"), ("lane", "lane control"), ("best", "reduction"), ("state", "core FSM"), ("cyc", "core counters"),
    ("board_q", "request latch"), ("heights", "height cache"), ("stream", "stream wrapper"), ("u_core", "core"),
]


def load_json(rel):
    p = ROOT / rel
    return json.loads(p.read_text()) if p.is_file() else None


def path_category(path: str) -> str:
    if not path:
        return "unknown"
    seg = path.split(".")
    inner = ".".join(seg[2:]) if len(seg) > 2 else path      # drop u_core.genblkN
    for needle, cat in PATH_CATEGORIES:
        if needle in inner:
            return cat
    return "other"


def fmt(x, nd=1):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:,.{nd}f}"
    return f"{x:,}"


def hardware_section() -> tuple[str, dict]:
    m = load_json("benchmarks/hardware_v2.json")
    summary = load_json("results/v2/summary/matrix_hardware-v2.json")
    csv_path = ROOT / "results" / "v2" / "summary" / "routes_hardware-v2.csv"
    out = ["## 1. Hardware matrix v2 (`benchmarks/hardware_v2.json`, U17)", ""]
    facts = {}
    if summary is None or not csv_path.is_file():
        out.append("*The 84-job release matrix has not completed yet (`make measure-v2 MODE=run`); this section is generated from "
                   "`results/v2/summary/routes_hardware-v2.csv` and `matrix_hardware-v2.json` when it has.*")
        return "\n".join(out) + "\n", facts
    with open(csv_path) as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("current") in ("True", "true", "1")]
    out.append(f"ECP5 LFE5U-85F CABGA381 speed 6, Yosys `synth_ecp5 -nodsp`, nextpnr-ecp5 with `--freq` as the clock constraint and "
               f"auto-allocated I/O; toolchain `{summary['toolchain_id']}`; one synthesis per configuration reused for every target and seed; "
               f"route budget {m['route_timeout_s']} s ({', '.join(f'{k} {v} s' for k, v in m.get('route_timeout_overrides', {}).items())}). "
               f"Raw: one `route-record-v2` per job under `results/v2/raw/routes/<route_key>.json`; derived CSV `results/v2/summary/routes_hardware-v2.csv` "
               f"(current attempts only are summarised here; every attempt is in the CSV). Statuses: met = routed and the report passes the constraint, "
               f"failed = routed but the reported fmax is below the constraint, timeout = the budget was exhausted (an observed resource limit, not proof "
               f"the design cannot route). Counts: {summary['counts']}.")
    out.append("")
    # per configuration x target
    by = defaultdict(list)
    for r in rows:
        by[(r["configuration_id"], float(r["target_mhz"]))].append(r)
    configs = list(dict.fromkeys(m["configurations"] + [j["configuration"] for j in m.get("extra_jobs", [])]))
    targets = sorted({float(r["target_mhz"]) for r in rows})
    out.append("### 1.1 Routing outcomes per configuration and clock constraint (seeds 11, 12, 13)")
    out.append("")
    out.append("| Configuration | LUT4 | FF | CCU2C | " + " | ".join(f"{t:g} MHz" for t in targets) + " |")
    out.append("|---|---:|---:|---:|" + "|".join("---" for _ in targets) + "|")
    for cid in configs:
        cells = []
        area = None
        for t in targets:
            rs = by.get((cid, t), [])
            if not rs:
                cells.append("—" if any(j["configuration"] == cid for j in m.get("extra_jobs", [])) else "not run")
                continue
            area = area or rs[0]
            met = sum(r["status"] == "routed_timing_met" for r in rs)
            failed = sum(r["status"] == "routed_timing_failed" for r in rs)
            to = sum(r["status"] == "route_timeout" for r in rs)
            fm = [float(r["reported_fmax_mhz"]) for r in rs if r.get("reported_fmax_mhz") not in ("", None, "None")]
            txt = f"{met}/{len(rs)} met" + (f", {failed} failed" if failed else "") + (f", {to} timeout" if to else "")
            if fm:
                txt += f"; fmax {min(fm):.1f}–{max(fm):.1f}" if len(fm) > 1 else f"; fmax {fm[0]:.1f}"
            cells.append(txt)
        if area is None:
            continue
        out.append(f"| {SHORT.get(cid, cid)} (`{cid}`) | {area['lut4']} | {area['ff']} | {area['carry']} | " + " | ".join(cells) + " |")
        facts[cid] = {"lut4": int(area["lut4"]), "ff": int(area["ff"]), "carry": int(area["carry"])}
    out.append("")
    # seed-level fmax table at 50 MHz + worst path categories
    out.append("### 1.2 Seed-level results at 50 MHz and worst-path categories")
    out.append("")
    out.append("| Configuration | seed 11 | seed 12 | seed 13 | worst-path categories (all routed records of the configuration) |")
    out.append("|---|---|---|---|---|")
    for cid in configs:
        rs50 = {int(r["seed"]): r for r in by.get((cid, 50.0), [])}
        if not rs50:
            continue
        cells = []
        for s in (11, 12, 13):
            r = rs50.get(s)
            if r is None:
                cells.append("—")
            elif r["status"] == "route_timeout":
                cells.append(f"timeout ({float(r['elapsed_s']):.0f} s)")
            else:
                cells.append(f"{float(r['reported_fmax_mhz']):.2f} MHz {'met' if r['status'] == 'routed_timing_met' else 'FAILED'} ({float(r['elapsed_s']):.0f} s)")
        cats = defaultdict(int)
        for t in targets:
            for r in by.get((cid, t), []):
                if r["status"] in ("routed_timing_met", "routed_timing_failed"):
                    cats[path_category(r.get("worst_path_from", ""))] += 1
        cat_txt = ", ".join(f"{k} ×{v}" for k, v in sorted(cats.items(), key=lambda kv: -kv[1])) or "—"
        out.append(f"| `{cid}` | {' | '.join(cells)} | {cat_txt} |")
        facts.setdefault(cid, {})["fmax50"] = {s: (float(r["reported_fmax_mhz"]) if r["status"] != "route_timeout" else None) for s, r in rs50.items()}
        facts[cid]["met50"] = sum(r["status"] == "routed_timing_met" for r in rs50.values())
    out.append("")
    # decisions and projection
    dec = summary.get("decisions") or {}
    out.append("### 1.3 Decision cycles on the common 1,000-state corpus and the 50 MHz projection")
    out.append("")
    out.append("| Configuration | decisions matched | min | median | mean | max | cycles by N = 9 / 17 / 34 (median) | projection at 50 MHz |")
    out.append("|---|---|---:|---:|---:|---:|---|---|")
    for cid in m.get("decisions", {}).get("configurations", []):
        meta = dec.get(cid) or {}
        csvp = ROOT / meta.get("csv", "") if meta.get("csv") else None
        if not csvp or not csvp.is_file():
            out.append(f"| `{cid}` | not run | | | | | | |")
            continue
        with open(csvp) as fh:
            drows = list(csv.DictReader(fh))
        cyc = [int(r["core_cycles"]) for r in drows]
        byn = defaultdict(list)
        for r in drows:
            byn[int(r["root_candidates"])].append(int(r["core_cycles"]))
        med = statistics.median(cyc)
        met = facts.get(cid, {}).get("met50", 0)
        proj = f"{med / 50:.1f} µs (median cycles ÷ 50 MHz; {met}/3 seeds met)" if met == 3 else f"withheld ({met}/3 seeds met 50 MHz)"
        out.append(f"| `{cid}` | {meta.get('status')} {len(drows)}/{len(drows)} | {min(cyc)} | {med:g} | {statistics.mean(cyc):.1f} | {max(cyc)} | "
                   + " / ".join(f"{statistics.median(byn[n]):g}" if n in byn else "—" for n in (9, 17, 34)) + f" | {proj} |")
        facts.setdefault(cid, {})["median_cycles"] = med
    out.append("")
    out.append("The projection is RTL-simulation cycles divided by a routed clock constraint on a device model; it is model-based, not a board "
               "measurement, and is withheld where any of the three seeds did not meet 50 MHz. Timing failures and timeouts are outcomes of the "
               "declared matrix, not missing work; missing/corrupt jobs would be reported by `make check-hardware-v2`.")
    out.append("")
    a2s = load_json("results/v2/raw/intervals/a2_candidate_stream.json")
    iv = load_json("results/v2/raw/intervals/a2-cache-d1-p0-l1.json")
    if a2s and iv:
        st = {s["phase"]: s for s in a2s["stats"]}
        out.append(f"A2 candidate stream (`results/v2/raw/intervals/a2_candidate_stream.json`, standalone pipeline harness): {st['stream']['tokens']} back-to-back tokens with "
                   f"acceptance spacing {st['stream']['accept_spacing']}, retirement spacing {st['stream']['retire_spacing']}, visible latency {st['stream']['visible_latency']}, "
                   f"transfer {st['stream']['transfer_latency']}, occupancy max {st['stream']['occupancy_max']} (mean {st['stream']['occupancy_mean']}); under {a2s['bubbles_pct']} % bubbles / "
                   f"{a2s['stalls_pct']} % stalls: acceptance spacing {st['traffic']['accept_spacing']}, occupancy mean {st['traffic']['occupancy_mean']}. "
                   f"Request interval (`a2-cache-d1-p0-l1.json`): {iv['agree_with_inferred']}/{len(iv['pairs'])} measured pairs equal the inferred interval, R(N) = N + 31.")
        out.append("")
    return "\n".join(out) + "\n", facts


def lanes_section() -> str:
    l4 = load_json("results/v2/lanes/lanes4_stats.json")
    l2 = load_json("results/v2/lanes/lanes2_stats.json")
    syn = load_json("results/v2/lanes/synth_l1_l2_l4.json")
    out = ["## 2. Evaluator replication (U13; `docs/lanes.md`)", ""]
    if l4 and l2:
        out.append("| Counter (`results/v2/lanes/lanes{L}_stats.json`) | LANES = 4 | LANES = 2 |")
        out.append("|---|---:|---:|")
        for k, lab in (("cases", "cases with a move"), ("cross_lane_ties", "cross-lane ties"), ("winner_lane_finished_strictly_last", "winner lane finished strictly last"),
                       ("winner_lane_finished_last_or_tied", "winner lane finished last or tied"), ("invalid_local_bests", "invalid local bests"), ("unequal_finish_cases", "unequal finish cases")):
            out.append(f"| {lab} | {l4[k]} | {l2[k]} |")
        out.append(f"| ownership (N = 9 / 17 / 34) | {l4['ownership']['9']} / {l4['ownership']['17']} / {l4['ownership']['34']} | {l2['ownership']['9']} / {l2['ownership']['17']} / {l2['ownership']['34']} |")
        out.append("")
    if syn:
        out.append("| Lanes (`results/v2/lanes/synth_l1_l2_l4.json`, `synth_ecp5 -nodsp`) | LUT4 | FF | CCU2C | FF added |")
        out.append("|---|---:|---:|---:|---:|")
        for r in syn["rows"]:
            added = "—" if r["ff_added_vs_l1"] == 0 else f"+{r['ff_added_vs_l1']:,}"
            out.append(f"| {r['lanes']} (`{r['configuration_id']}`) | {r['lut4']:,} | {r['ff']:,} | {r['ccu2c']:,} | {added} |")
        out.append("")
    out.append("Cycles on the common corpus: `45·⌈N/L⌉ + 7 + L` when every candidate is legal (11 cycles per illegal candidate); Σ speed-up 1.91× "
               "for two lanes and 3.36× for four (v1 records `results/decisions/a1-cache-d1-p0-l{1,2}_native_1000.csv`, U13 record under "
               "`results/v2/raw/decisions/a1-cache-d1-p0-l4/`). Development routes of the four-lane core: seed 1 `route_timeout` at 1,200 s and 3,600 s, "
               "seed 2 met 50 MHz at 65.96 MHz (`docs/lanes.md` §5).")
    return "\n".join(out) + "\n"


def precision_section() -> str:
    s = load_json("results/v2/precision/development/summary.json")
    st = load_json("results/v2/precision/scorer_study.json")
    out = ["## 3. Coefficient quantization ladder (U14; `docs/precision_v2.md`)", ""]
    if s:
        out.append(f"Common-state sensitivity, development split (`{s['corpora'][0]['corpus']}`, {s['corpora'][0]['states']} states; "
                   f"`{s['corpora'][1]['corpus']}`, {s['corpora'][1]['states']} states) — planning data, not a final evaluation:")
        out.append("")
        out.append("| Profile | coefficients | changed (corpus_d1) | changed (dev 2,000) | certified unchanged | not certified but unchanged | exact ties | ties introduced / broken | median exact gap changed / unchanged |")
        out.append("|---|---|---|---|---:|---:|---:|---|---|")
        for key, pp in s["corpora"][0]["profiles"].items():
            p2 = s["corpora"][1]["profiles"][key]
            prof = s["profiles"][key]
            out.append(f"| P{pp['precision']} `{prof['name']}` | {tuple(prof['coefficients'])} | {pp['changed']} / {pp['legal_states']} ({100 * pp['changed_rate']:.2f} %) | "
                       f"{p2['changed']} / {p2['legal_states']} ({100 * p2['changed_rate']:.2f} %) | {pp['certified_unchanged']} | {pp['not_certified_but_unchanged']} | {pp['exact_ties']} | "
                       f"{pp['ties_introduced']} / {pp['ties_broken']} | {(pp['exact_gap_changed'] or {}).get('median')} / {(pp['exact_gap_unchanged'] or {}).get('median')} |")
        out.append("")
    if st:
        out.append("Scorer microbenchmarks and complete A1/cache cores (`results/v2/precision/scorer_study.json`, `synth_ecp5 -nodsp`; scorer-only savings are not core savings):")
        out.append("")
        out.append("| Profile | scorer LUT4 | scorer FF | scorer CCU2C | core LUT4 | core FF | core CCU2C | Δ core LUT4 vs P0 |")
        out.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        sc = {r["precision"]: r for r in st["scorer_microbenchmarks"]["rows"]}
        for k, c in st["cores"]["rows"].items():
            p = int(k[1:])
            r = sc.get(p, {})
            out.append(f"| P{p} `{st['profiles'][k]['name']}` | {r.get('lut4', '—')} | {r.get('ff', '—')} | {r.get('ccu2c', '—')} | {c['lut4']:,} | {c['ff']:,} | {c['ccu2c']} | {c.get('delta_vs_p0', {}).get('lut4', 0):+d} |")
        ref = st["scorer_microbenchmarks"]["p0_constant_multiply_reference"]
        out.append(f"| P0 with constant multiplies, DSP allowed (reference only) | {ref['lut4']} | {ref['ff']} | {ref['ccu2c']} | — | — | — | DSP {ref['dsp']} |")
        out.append("")
    return "\n".join(out) + "\n"


def quality_section() -> tuple[str, dict]:
    q = load_json("results/v2/summary/quality.json")
    pilot = load_json("results/v2/summary/analysis_pilot.json")
    out = ["## 4. Quality study v2 (U16; `docs/quality_v2.md`)", ""]
    facts = {}
    if q:
        out.append(f"Protocol `{q['protocol_name']}` (`{q['protocol_path']}`, hash `{q['protocol_sha256'][:12]}…`, frozen {q['freeze']['frozen_utc']}), suite `{q['suite']}` "
                   f"({q['role']}): streams {q['streams'][0]}–{q['streams'][1]} ({q['n_streams']} paired seven-bag streams), cap {q['cap']:,} locked pieces, "
                   f"{q['statistics']['bootstrap_resamples']:,} paired bootstrap resamples (seed {q['statistics']['bootstrap_seed']}). Raw: one `quality-record-v2` per game under "
                   f"`results/v2/raw/quality/`; analysis `results/v2/summary/quality.json`; figure `results/v2/figures/survival_bag50k.png`.")
        out.append("")
        out.append("| Policy | restricted mean pieces (to C) | mean lines | median lines [IQR] | cap hit | top-outs | median survival | duration quartiles |")
        out.append("|---|---:|---:|---|---:|---:|---|---|")
        for k, p in q["policies"].items():
            lq = p["lines_quartiles"]
            dq = p["duration_quartiles"]
            cap_hits = round(p["cap_hit_fraction"]["value"] * p["games"])
            out.append(f"| `{k}`{' (' + p['profile_name'] + ')' if p.get('profile_name') else ''} | {p['restricted_mean_pieces']['value']:,.1f} | {p['mean_lines']:,.1f} | "
                       f"{p['median_lines']:,.1f} [{lq[0]:,.1f}, {lq[2]:,.1f}] | {cap_hits}/{p['games']} | {p['top_outs_observed']} | {p['median_statement'].split(' (')[0]} | "
                       f"[{dq[0]:,.0f}, {dq[1]:,.0f}, {dq[2]:,.0f}] |")
            facts[k] = {"restricted_mean_pieces": p["restricted_mean_pieces"]["value"], "mean_lines": p["mean_lines"], "cap_hit": p["cap_hit_fraction"]["exact"]}
        out.append("")
        out.append(f"| Policy vs `{q['baseline']}` | Δ restricted mean pieces [CI95] | Δ mean lines [CI95] | Δ cap-hit fraction [CI95] | streams won / lost / tied (pieces) |")
        out.append("|---|---|---|---|---|")
        for k, c in q["comparisons"].items():
            rm, ln, ch, w = c["restricted_mean_pieces"], c["lines"], c["cap_hit_fraction"], c["wins_by_stream_pieces"]
            out.append(f"| `{k}` | {rm['mean_diff']:+,.1f} [{rm['ci95'][0]:,.1f}, {rm['ci95'][1]:,.1f}] | {ln['mean_diff']:+,.1f} [{ln['ci95'][0]:,.1f}, {ln['ci95'][1]:,.1f}] | "
                       f"{ch['mean_diff']:+.2f} [{ch['ci95'][0]:.2f}, {ch['ci95'][1]:.2f}] | {w['policy']} / {w['baseline']} / {w['ties']} |")
            facts[k]["delta_pieces"] = rm["mean_diff"]
            facts[k]["delta_pieces_ci"] = rm["ci95"]
        out.append("")
        out.append("Every median is reached within the horizon; restricted means are means to the cap (an estimate of the restricted mean, not of unbounded survival). "
                   "The development pilot (seeds 10000–10019, `results/v2/summary/analysis_pilot.json`, `analysis_pilot50k.json`) is reported in `docs/quality_v2.md` §4 and was used only to size the study.")
        out.append("")
    return "\n".join(out) + "\n", facts


def verification_section() -> str:
    out = ["## 5. A2 verification and timing evidence (U05–U12, U18)", ""]
    formal = []
    for name in ("compactor", "reducer", "control"):
        d = load_json(f"results/formal/{name}.json")
        if d:
            formal.append(f"`{name}` {d['status']} ({d['engine']}, depth {d.get('depth')})")
    mut = load_json("results/evidence/U11/mutations.json")
    out.append(f"Formal (`results/formal/*.json`): {'; '.join(formal)}. Mutations (`results/evidence/U11/mutations.json`): "
               f"{mut['killed']}/{mut['total']} killed." if mut else "")
    out.append("")
    out.append("| Check | Count | Where |")
    out.append("|---|---|---|")
    for job, label in (("U05", "compactor exhaustive masks + random boards"), ("U09", "candidate pipeline streams"), ("U10", "A2 core corpus"), ("U11", "verification release gate"),
                       ("U12", "A2 routes"), ("U13", "four-lane gate"), ("U14", "quantization gate"), ("U15", "benchmark machinery"), ("U16", "held-out study"), ("U18", "replay traces")):
        d = load_json(f"results/evidence/{job}/summary.json")
        if not d:
            continue
        counts = {}
        for c in d["commands"]:
            for k, v in c["counts"].items():
                counts[k] = v
        skip = ("pytest_failed", "rtl_failed", "check_a2_stages", "check_a2_widths", "check_a2_identity", "check_a2_latency", "check_a2_elaboration", "check_a2_lane_guards")
        keys = [f"{k.replace('check_', '')} {v}" for k, v in counts.items() if k not in skip]
        out.append(f"| {job} {label} ({d['status']}) | {'; '.join(keys[:8])} | `results/evidence/{job}/summary.json` |")
    out.append("")
    out.append("Timing journal of the A2 development routes (worst paths before/after the P14 regrouping, 71.77 → 76.36 MHz at the 50 MHz constraint, seed 1): "
               "`docs/timing_journal.md`. Replay traces validated by `tools/check_trace.py`: `docs/replay.md`.")
    return "\n".join(out) + "\n"


def build() -> str:
    hw, hwf = hardware_section()
    ql, qf = quality_section()
    head = ["# Results", "",
            "Generated by `tools/write_report_v2.py` from the committed result files; do not edit by hand (`make check-report-v2` regenerates and compares). "
            "Measurement definitions used throughout: **cycles** are RTL-simulation counts under the documented request/response protocol (Verilator, native driver); "
            "**routed fmax** is nextpnr-ecp5's reported maximum frequency for the routed netlist on the LFE5U-85F device model with auto-allocated I/O — a model-based "
            "figure, never a board measurement; a **projection** divides median cycles by a clock constraint that every seed met; **host wall time** is the runner "
            "process's wall clock; **restricted mean** and **survival** follow the censoring definitions of `docs/quality_v2.md` §3. Every table names its raw source.", ""]
    v1_block = v1.block(*v1.load())
    doc = "\n".join(head) + "\n" + hw + "\n" + lanes_section() + "\n" + precision_section() + "\n" + ql + "\n" + verification_section() + "\n"
    doc += ("## 6. Frozen v1 experiment (E00–E19)\n\nGenerated by `tools/write_report.py` from `results/implementation.csv`, `results/decisions/`, `results/quality.csv` and "
            "`results/quality_summary.json` (v1 toolchain lock and default DSP policy: a different identity from the v2 matrix above; validated by `make check-v1-results`).\n\n"
            + v1.START + "\n" + v1_block + v1.END + "\n")
    facts = {"hardware": hwf, "quality": qf}
    (ROOT / "results" / "v2" / "summary" / "report_facts.json").write_text(json.dumps(facts, indent=1, sort_keys=True) + "\n")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text = build()
    if args.check:
        if not OUT.is_file() or OUT.read_text() != text:
            print("docs/results.md is stale (run make results-v2)")
            return 1
        print("docs/results.md is current")
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
