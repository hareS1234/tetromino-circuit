#!/usr/bin/env python3
"""Architecture figures from the raw v2 records, every point traceable to a job key (U17 step 5-6).

    python tools/plots_v2.py --manifest benchmarks/hardware_v2.json          # figures + <figure>.points.json
    python tools/plots_v2.py --manifest benchmarks/hardware_v2.json --verify # re-open every plotted point's record

Figures (results/v2/figures/):
  area_vs_latency.png      LUT4 (routed area of the 50 MHz seed-11 record, else any completed route of the
                           configuration) against the median decision cycles of the 1,000-state corpus; the
                           secondary axis converts cycles at 50 MHz only for configurations whose 50 MHz routes met
                           timing (a conditional projection, labelled)
  lane_scaling.png         one/two/four-lane cycles (median) and LUT4/FF
  cycles_by_family.png     median cycles by dense candidate count N (9 / 17 / 34) per configuration
  timing_outcomes.png      met / failed / timeout counts per configuration and clock target
  fmax_by_seed.png         reported fmax per seed and target (routed records only)
Missing measurements are left blank and listed in the points file; nothing is interpolated.
"""
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

from model.config import SUPPORTED_IDS  # noqa: E402
from tools import pnr  # noqa: E402
from tools.measure_matrix import RAW_DECISIONS, corpus_hash, expand_jobs, job_label, load_manifest, plan  # noqa: E402

FIG = ROOT / "results" / "v2" / "figures"
SHORT = {"a0-bitmap-d1-p0-l1": "X0 A0", "a1-bitmap-d1-p0-l1": "X1 A1 bitmap", "a1-cache-d1-p0-l1": "X2 A1 cache",
         "a1-cache-d1-p0-l2": "X3 A1 ×2", "a1-cache-d1-p0-l4": "X4 A1 ×4", "a2-cache-d1-p0-l1": "X5 A2",
         "a1-cache-d1-p1-l1": "P1", "a1-cache-d1-p5-l1": "P5", "a1-cache-d1-p6-l1": "P6", "a1-cache-d1-p7-l1": "P7"}


def latest_records(m: dict) -> dict:
    """{label: (route_key, record)} for every job that has a record under the current identity."""
    out = {}
    for it in plan(m, None, None):
        rec = pnr.existing_record(it["route_key"])
        if rec is not None:
            out[it["label"]] = (it["route_key"], rec)
    return out


def decision_stats(cid: str, count: int) -> dict | None:
    cfg = SUPPORTED_IDS[cid]
    chash = corpus_hash(cfg.depth, count)
    meta_path = RAW_DECISIONS / cid / f"{chash}.json"
    if not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text())
    if meta.get("status") != "matched":
        return None
    with open(ROOT / meta["csv"]) as fh:
        rows = list(csv.DictReader(fh))
    cyc = [int(r["core_cycles"]) for r in rows]
    by_n = defaultdict(list)
    for r in rows:
        by_n[int(r["root_candidates"])].append(int(r["core_cycles"]))
    return {"key": f"{cid}/{chash}", "count": len(rows), "median": statistics.median(cyc), "mean": statistics.mean(cyc), "min": min(cyc), "max": max(cyc),
            "by_n": {n: statistics.median(v) for n, v in sorted(by_n.items())}, "native_key": meta.get("native_key")}


def save_points(name: str, points: list[dict], missing: list[str], manifest: dict) -> None:
    doc = {"schema": "figure-points-v1", "figure": f"results/v2/figures/{name}.png", "manifest": manifest["_path"], "manifest_sha256": manifest["_sha256"],
           "points": points, "missing": missing}
    (FIG / f"{name}.points.json").write_text(json.dumps(doc, indent=1) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="benchmarks/hardware_v2.json")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    m = load_manifest(ROOT / args.manifest)
    FIG.mkdir(parents=True, exist_ok=True)
    if args.verify:
        return verify()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    recs = latest_records(m)
    jobs = expand_jobs(m)
    configs = list(dict.fromkeys(j["configuration"] for j in jobs))
    targets = sorted({j["target_mhz"] for j in jobs})
    seeds = sorted({j["seed"] for j in jobs})
    dec_cfgs = m.get("decisions", {}).get("configurations", [])
    dec_count = int(m.get("decisions", {}).get("count", 1000))
    decisions = {cid: decision_stats(cid, dec_count) for cid in dec_cfgs}

    # ---- 1. area vs decision latency at 50 MHz --------------------------------------------------------------
    points, missing = [], []
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    for cid in dec_cfgs:
        d = decisions.get(cid)
        route = None
        for seed in seeds:
            cand = recs.get(f"{cid}:50:{seed}")
            if cand and cand[1]["status"] in ("routed_timing_met", "routed_timing_failed"):
                route = cand
                break
        if d is None or route is None:
            missing.append(f"{cid}: {'no decision record' if d is None else ''} {'no completed 50 MHz route' if route is None else ''}".strip())
            continue
        key, rec = route
        met = rec["status"] == "routed_timing_met"
        lut = rec["area"]["lut4"]
        ax.scatter([lut], [d["median"]], s=60, marker="o" if met else "x")
        ax.annotate(SHORT.get(cid, cid) + ("" if met else " (50 MHz not met)"), (lut, d["median"]), textcoords="offset points", xytext=(5, 4), fontsize=8)
        points.append({"configuration": cid, "route_key": key, "route_status": rec["status"], "lut4": lut, "ff": rec["area"]["ff"],
                       "median_cycles": d["median"], "decision_key": d["key"], "latency_us_at_50mhz": d["median"] / 50.0 if met else None})
    ax.set_yscale("log")
    ax.set_xlabel("LUT4 (routed, -nodsp)")
    ax.set_ylabel("median decision cycles (1,000-state corpus)")
    sec = ax.secondary_yaxis("right", functions=(lambda c: c / 50.0, lambda us: us * 50.0))
    sec.set_ylabel("µs at 50 MHz — only where the 50 MHz route met timing (projection)")
    ax.set_title("Area versus decision latency (exact configurations)")
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "area_vs_latency.png", dpi=120)
    plt.close(fig)
    save_points("area_vs_latency", points, missing, m)

    # ---- 2. lane scaling --------------------------------------------------------------------------------------
    points, missing = [], []
    lanes_cfg = [("a1-cache-d1-p0-l1", 1), ("a1-cache-d1-p0-l2", 2), ("a1-cache-d1-p0-l4", 4)]
    fig, ax1 = plt.subplots(figsize=(7, 4.2))
    ax2 = ax1.twinx()
    xs, cyc, lut, ff = [], [], [], []
    for cid, L in lanes_cfg:
        d = decisions.get(cid)
        route = next((recs[f"{cid}:{t:g}:{s}"] for t in (50,) for s in seeds if f"{cid}:{t:g}:{s}" in recs
                      and recs[f"{cid}:{t:g}:{s}"][1]["status"] in ("routed_timing_met", "routed_timing_failed", "route_timeout")), None)
        if d is None or route is None:
            missing.append(f"{cid}: decisions {'ok' if d else 'missing'}, route {'ok' if route else 'missing'}")
            continue
        xs.append(L); cyc.append(d["median"]); lut.append(route[1]["area"]["lut4"]); ff.append(route[1]["area"]["ff"])
        points.append({"configuration": cid, "lanes": L, "median_cycles": d["median"], "decision_key": d["key"], "route_key": route[0],
                       "lut4": route[1]["area"]["lut4"], "ff": route[1]["area"]["ff"]})
    if xs:
        ax1.plot(xs, cyc, "o-", label="median cycles")
        ax2.plot(xs, lut, "s--", color="tab:orange", label="LUT4")
        ax2.plot(xs, ff, "^--", color="tab:green", label="FF")
        for x, c in zip(xs, cyc):
            ax1.annotate(f"{c:g}", (x, c), textcoords="offset points", xytext=(4, 4), fontsize=8)
    ax1.set_xlabel("A1/cache evaluator lanes")
    ax1.set_ylabel("median decision cycles")
    ax2.set_ylabel("cells (synthesis area of the routed netlist)")
    ax1.set_xticks([1, 2, 4])
    ax1.set_title("Evaluator replication: cycles and area versus lanes")
    h1, l1 = ax1.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="center right", fontsize=8)
    ax1.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "lane_scaling.png", dpi=120)
    plt.close(fig)
    save_points("lane_scaling", points, missing, m)

    # ---- 3. cycles by piece family ----------------------------------------------------------------------------
    points, missing = [], []
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    fams = [9, 17, 34]
    width = 0.8 / max(1, len(dec_cfgs))
    for i, cid in enumerate(dec_cfgs):
        d = decisions.get(cid)
        if d is None:
            missing.append(f"{cid}: no decision record")
            continue
        vals = [d["by_n"].get(n) for n in fams]
        ax.bar([k + i * width for k in range(len(fams))], [v or 0 for v in vals], width=width, label=SHORT.get(cid, cid))
        points.append({"configuration": cid, "decision_key": d["key"], "median_cycles_by_N": {str(n): d["by_n"].get(n) for n in fams}})
    ax.set_xticks([k + 0.4 - width / 2 for k in range(len(fams))])
    ax.set_xticklabels([f"N = {n} ({'O' if n == 9 else 'I/S/Z' if n == 17 else 'T/J/L'})" for n in fams])
    ax.set_yscale("log")
    ax.set_ylabel("median decision cycles")
    ax.set_title("Decision cycles by dense candidate count (piece family)")
    ax.legend(fontsize=8)
    ax.grid(True, axis="y", which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "cycles_by_family.png", dpi=120)
    plt.close(fig)
    save_points("cycles_by_family", points, missing, m)

    # ---- 4. timing outcomes by clock constraint -------------------------------------------------------------------
    points, missing = [], []
    fig, ax = plt.subplots(figsize=(9, 4.5))
    colors = {"routed_timing_met": "tab:green", "routed_timing_failed": "tab:red", "route_timeout": "tab:grey"}
    labels_x, k = [], 0
    for cid in configs:
        for t in targets:
            counts = {s: 0 for s in colors}
            keys = []
            for s in seeds:
                lab = f"{cid}:{t:g}:{s}"
                if lab in recs and recs[lab][1]["status"] in counts:
                    counts[recs[lab][1]["status"]] += 1
                    keys.append(recs[lab][0])
                elif lab in {job_label(j) for j in jobs}:
                    missing.append(lab)
            if not keys and not any(job_label(j) == f"{cid}:{t:g}:{seeds[0]}" for j in jobs):
                continue
            bottom = 0
            for st, c in colors.items():
                if counts[st]:
                    ax.bar(k, counts[st], bottom=bottom, color=c, width=0.8)
                    bottom += counts[st]
            labels_x.append(f"{SHORT.get(cid, cid)}\n{t:g}")
            points.append({"configuration": cid, "target_mhz": t, "counts": counts, "route_keys": keys})
            k += 1
    ax.set_xticks(range(len(labels_x)))
    ax.set_xticklabels(labels_x, fontsize=6, rotation=90)
    ax.set_ylabel("routes (seeds)")
    ax.set_title("Routing outcomes by configuration and clock constraint (green met, red failed, grey timeout)")
    fig.tight_layout()
    fig.savefig(FIG / "timing_outcomes.png", dpi=120)
    plt.close(fig)
    save_points("timing_outcomes", points, missing, m)

    # ---- 5. seed-level fmax ---------------------------------------------------------------------------------------
    points, missing = [], []
    fig, ax = plt.subplots(figsize=(9, 4.5))
    x = 0
    ticks, ticklabels = [], []
    for cid in configs:
        for t in targets:
            ys = []
            for s in seeds:
                lab = f"{cid}:{t:g}:{s}"
                if lab in recs and recs[lab][1]["timing"].get("reported_fmax_mhz"):
                    f = recs[lab][1]["timing"]["reported_fmax_mhz"]
                    ys.append(f)
                    ax.scatter([x], [f], s=18, color="tab:green" if recs[lab][1]["status"] == "routed_timing_met" else "tab:red")
                    points.append({"configuration": cid, "target_mhz": t, "seed": s, "route_key": recs[lab][0], "reported_fmax_mhz": f,
                                   "status": recs[lab][1]["status"]})
                elif lab in {job_label(j) for j in jobs}:
                    missing.append(lab)
            if any(job_label(j) == f"{cid}:{t:g}:{seeds[0]}" for j in jobs):
                ax.plot([x - 0.4, x + 0.4], [t, t], color="grey", linewidth=1)
                ticks.append(x); ticklabels.append(f"{SHORT.get(cid, cid)}\n{t:g}")
                x += 1
    ax.set_xticks(ticks)
    ax.set_xticklabels(ticklabels, fontsize=6, rotation=90)
    ax.set_ylabel("reported fmax (MHz); grey bar = constraint")
    ax.set_title("Seed-level timing estimates per configuration and constraint (routed records only)")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "fmax_by_seed.png", dpi=120)
    plt.close(fig)
    save_points("fmax_by_seed", points, missing, m)
    n_points = sum(len(json.loads((FIG / f"{n}.points.json").read_text())["points"]) for n in
                   ("area_vs_latency", "lane_scaling", "cycles_by_family", "timing_outcomes", "fmax_by_seed"))
    print(f"figures written to {FIG.relative_to(ROOT)}: {n_points} plotted points with job keys")
    return verify()


def verify() -> int:
    """Every plotted point re-opens its record(s) and re-checks the plotted value."""
    ok = total = 0
    problems = []
    for name in ("area_vs_latency", "lane_scaling", "cycles_by_family", "timing_outcomes", "fmax_by_seed"):
        p = FIG / f"{name}.points.json"
        if not p.is_file():
            problems.append(f"{name}: no points file")
            continue
        doc = json.loads(p.read_text())
        for pt in doc["points"]:
            total += 1
            good = True
            for key in ([pt["route_key"]] if "route_key" in pt else []) + pt.get("route_keys", []):
                rec = pnr.existing_record(key)
                if rec is None:
                    good = False
                    problems.append(f"{name}: route {key[:12]} has no record")
                    continue
                if "reported_fmax_mhz" in pt and rec["timing"].get("reported_fmax_mhz") != pt["reported_fmax_mhz"]:
                    good = False
                if "lut4" in pt and rec["area"]["lut4"] != pt["lut4"]:
                    good = False
            if "decision_key" in pt:
                cid, chash = pt["decision_key"].split("/")
                meta_path = RAW_DECISIONS / cid / f"{chash}.json"
                if not meta_path.is_file():
                    good = False
                    problems.append(f"{name}: decisions {pt['decision_key']} missing")
                elif "median_cycles" in pt:
                    with open(ROOT / json.loads(meta_path.read_text())["csv"]) as fh:
                        med = statistics.median(int(r["core_cycles"]) for r in csv.DictReader(fh))
                    good = good and med == pt["median_cycles"]
            ok += good
        if doc["missing"]:
            print(f"  {name}: {len(doc['missing'])} missing measurement(s) left blank: {doc['missing'][:4]}{'…' if len(doc['missing']) > 4 else ''}")
    print(f"CHECK figure_points {ok}/{total}")
    for pr in problems[:10]:
        print("  -", pr)
    return 0 if ok == total and not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
