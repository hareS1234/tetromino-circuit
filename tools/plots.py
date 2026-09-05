#!/usr/bin/env python3
"""Rebuild every figure from committed result files (no simulation or synthesis here).

  assets/plots/area_vs_cycles.png        exact designs: LUT4 vs median decision cycles, projected latency
  assets/plots/precision_area_lines.png  P0-P4: LUT4 vs held-out mean lines (cap 2,000) with IQR
  assets/plots/depth_quality_cost.png    D1 vs D2 on the 20-stream, cap-500 paired study
  assets/plots/board_access.png          bitmap vs exact height cache: cycles, LUT4, FF
  assets/plots/fmax_seeds.png            routed Fmax per configuration across route seeds
  assets/plots/divergence_p1.png         candidate scores at the first exact-vs-powers_of_two divergence
  assets/plots/stage_cycles.png          where A0 and A1 spend a candidate's cycles
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "plots"
sys.path.insert(0, str(ROOT))

# reference categorical palette (fixed order, never cycled) and neutral ink
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
LABELS = {"a0-bitmap-d1-p0-l1": "A0 serial", "a1-bitmap-d1-p0-l1": "A1 bitmap", "a1-cache-d1-p0-l1": "A1 cache",
          "a1-cache-d1-p0-l2": "A1 cache, 2 lanes", "a1-cache-d2-p0-l1": "A1 cache, depth 2",
          "a1-cache-d1-p1-l1": "P1 powers_of_two", "a1-cache-d1-p2-l1": "P2 two_terms",
          "a1-cache-d1-p3-l1": "P3 cap_holes", "a1-cache-d1-p4-l1": "P4 no_bumpiness"}
plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2,
                     "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
                     "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 150})


def cfg_id(row):
    return f"a{row['arch']}-{'cache' if row['board_repr'] == '1' else 'bitmap'}-d{row['depth']}-p{row['precision']}-l{row['lanes']}"


def implementation():
    path = ROOT / "results" / "implementation.csv"
    if not path.is_file():
        return {}
    rows = list(csv.DictReader(open(path)))
    by = {}
    for r in rows:
        by.setdefault(cfg_id(r), []).append(r)
    return by


def decisions(cid):
    files = sorted((ROOT / "results" / "decisions").glob(f"{cid}_native_*.csv"))
    if not files:
        return []
    return [int(r["core_cycles"]) for r in csv.DictReader(open(files[-1]))]


def synth_number(rows, key):
    vals = [int(r[key]) for r in rows if r.get(key)]
    return vals[0] if vals else None


def best_fmax(rows):
    met = [float(r["reported_fmax_mhz"]) for r in rows if r["timing_met"] == "True" and r["reported_fmax_mhz"]]
    return (min(met), max(met), len(met), len(rows)) if met else (None, None, 0, len(rows))


def fig_area_vs_cycles(impl):
    ids = ["a0-bitmap-d1-p0-l1", "a1-bitmap-d1-p0-l1", "a1-cache-d1-p0-l1", "a1-cache-d1-p0-l2", "a1-cache-d2-p0-l1"]
    short = {"a0-bitmap-d1-p0-l1": "A0", "a1-bitmap-d1-p0-l1": "A1 bitmap", "a1-cache-d1-p0-l1": "A1 cache",
             "a1-cache-d1-p0-l2": "2 lanes", "a1-cache-d2-p0-l1": "depth 2"}
    offsets = {"a0-bitmap-d1-p0-l1": (10, -4), "a1-bitmap-d1-p0-l1": (10, 6), "a1-cache-d1-p0-l1": (-8, -16),
               "a1-cache-d1-p0-l2": (-70, 8), "a1-cache-d2-p0-l1": (10, -4)}
    fig, (ax, tx) = plt.subplots(1, 2, figsize=(10, 4.6), gridspec_kw={"width_ratios": [3, 2]})
    lines = []
    for i, cid in enumerate(ids):
        rows = impl.get(cid)
        cyc = decisions(cid)
        if not rows or not cyc:
            continue
        lut = synth_number(rows, "lut4")
        med = statistics.median(cyc)
        fmin, fmax, n_met, n_all = best_fmax(rows)
        ax.scatter([lut], [med], s=70, color=SERIES[i], zorder=3, edgecolor="white", linewidth=1.5)
        ax.annotate(short[cid], (lut, med), textcoords="offset points", xytext=offsets[cid], fontsize=9, color=INK)
        proj = f"{med / 50:.1f} µs at 50 MHz" if n_met == n_all else "projection withheld"
        lines.append((SERIES[i], f"{short[cid]}: {lut} LUT4, {med:.0f} cycles, {proj}; {n_met}/{n_all} seeds met timing"))
    ax.set_yscale("log")
    ax.set_xlabel("LUT4 after synth_ecp5 (stream_wrapper)")
    ax.set_ylabel("median core cycles per decision (log)")
    ax.set_title("Exact architectures: area versus latency", color=INK, loc="left")
    tx.axis("off")
    for j, (col, text) in enumerate(lines):
        tx.scatter([0.02], [0.9 - 0.16 * j], color=col, s=50, transform=tx.transAxes, clip_on=False)
        tx.text(0.08, 0.9 - 0.16 * j, text, transform=tx.transAxes, fontsize=8, va="center", color=INK, wrap=True)
    tx.text(0.02, 0.05, "identical decisions on the 1,000-request corpus;\nlatency = RTL cycles ÷ routed constraint, no board", transform=tx.transAxes, fontsize=7.5, color=INK2)
    fig.tight_layout()
    fig.savefig(OUT / "area_vs_cycles.png")
    plt.close(fig)


def fig_precision(impl, summary):
    prec = summary.get("precision", {}).get("policies", {})
    names = {0: "P0 exact", 1: "P1 powers\nof two", 2: "P2 two\nterms", 3: "P3 cap\nholes", 4: "P4 no\nbumpiness"}
    luts, means, lo, hi, caps, xs = [], [], [], [], [], []
    for p in range(5):
        cid = f"a1-cache-d1-p{p}-l1"
        rows = impl.get(cid)
        stat = prec.get(f"heuristic-d1-p{p}")
        if not rows or not stat or stat.get("status") != "complete":
            continue
        xs.append(p); luts.append(synth_number(rows, "lut4")); means.append(stat["mean_lines"])
        lo.append(stat["iqr"][0]); hi.append(stat["iqr"][1]); caps.append(stat["cap_hit_fraction"])
    if not xs:
        return
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4.2))
    a1.bar(range(len(xs)), luts, color=[SERIES[p] for p in xs], width=0.6)
    a1.set_ylim(0, max(luts) * 1.12)
    for i, v in enumerate(luts):
        a1.text(i, v, f"{v}", ha="center", va="bottom", fontsize=9, color=INK)
    a1.set_xticks(range(len(xs))); a1.set_xticklabels([names[p] for p in xs], fontsize=8)
    a1.set_ylabel("LUT4 after synth_ecp5")
    a1.set_title("area: a 2% spread across profiles", loc="left", color=INK)
    a2.bar(range(len(xs)), means, color=[SERIES[p] for p in xs], width=0.6)
    for i, (m, l, h, c) in enumerate(zip(means, lo, hi, caps)):
        a2.plot([i, i], [l, h], color=INK, linewidth=1.5)
        a2.text(i, m + 15, f"{m:.0f} lines\ncap-hit {c:.0%}", ha="center", va="bottom", fontsize=8, color=INK)
    a2.set_xticks(range(len(xs))); a2.set_xticklabels([names[p] for p in xs], fontsize=8)
    a2.set_ylim(0, max(means) * 1.25)
    a2.set_ylabel("mean lines per game (IQR bars)")
    a2.set_title("strength: 100 held-out streams, cap 2,000", loc="left", color=INK)
    fig.suptitle("Numerical profiles on A1 cache (Python bit-exact policies; RTL verified per profile)", x=0.01, ha="left", color=INK, fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "precision_area_lines.png")
    plt.close(fig)


def fig_depth(impl, summary):
    d = summary.get("depth", {}).get("policies", {})
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.8))
    names, means, iqr_lo, iqr_hi, cyc = [], [], [], [], []
    for depth, cid in ((1, "a1-cache-d1-p0-l1"), (2, "a1-cache-d2-p0-l1")):
        stat = d.get(f"heuristic-d{depth}-p0")
        c = decisions(cid)
        if not stat or stat.get("status") != "complete" or not c:
            continue
        names.append(f"depth {depth}")
        means.append(stat["mean_lines"]); iqr_lo.append(stat["iqr"][0]); iqr_hi.append(stat["iqr"][1])
        cyc.append(statistics.median(c))
    if names:
        x = range(len(names))
        axes[0].bar(x, means, color=[SERIES[0], SERIES[1]][:len(names)], width=0.5)
        for i, m in enumerate(means):
            axes[0].plot([i, i], [iqr_lo[i], iqr_hi[i]], color=INK, linewidth=1.5)
            axes[0].text(i, m, f"{m:.1f}", ha="center", va="bottom", fontsize=9, color=INK)
        axes[0].set_xticks(list(x)); axes[0].set_xticklabels(names)
        axes[0].set_ylabel("mean lines, 20 streams, cap 500 (IQR)")
        axes[0].set_title("quality (paired streams)", loc="left", color=INK)
        axes[1].bar(x, cyc, color=[SERIES[0], SERIES[1]][:len(names)], width=0.5)
        for i, m in enumerate(cyc):
            axes[1].text(i, m, f"{m:.0f}", ha="center", va="bottom", fontsize=9, color=INK)
        axes[1].set_xticks(list(x)); axes[1].set_xticklabels(names)
        axes[1].set_ylabel("median core cycles per decision (RTL)")
        axes[1].set_title("cost", loc="left", color=INK)
    vs = d.get("heuristic-d2-p0", {}).get("vs_baseline")
    sub = f"depth 2 minus depth 1: {vs['mean_diff']:+.2f} lines, 95% CI {vs['ci95']}" if vs else ""
    fig.suptitle(f"Two-piece lookahead on A1 cache. {sub}", x=0.01, ha="left", color=INK, fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "depth_quality_cost.png")
    plt.close(fig)


def fig_board_access(impl):
    pairs = [("a1-bitmap-d1-p0-l1", "bitmap only"), ("a1-cache-d1-p0-l1", "bitmap + height cache")]
    fig, axes = plt.subplots(1, 3, figsize=(9, 3.4))
    metrics = [("median cycles / decision", lambda cid: statistics.median(decisions(cid)) if decisions(cid) else None),
               ("LUT4", lambda cid: synth_number(impl.get(cid, []), "lut4")),
               ("flip-flops", lambda cid: synth_number(impl.get(cid, []), "ff"))]
    for ax, (name, fn) in zip(axes, metrics):
        vals = [fn(cid) for cid, _ in pairs]
        if any(v is None for v in vals):
            continue
        ax.bar(range(2), vals, color=[SERIES[0], SERIES[2]], width=0.55)
        for i, v in enumerate(vals):
            ax.text(i, v, f"{v:.0f}", ha="center", va="bottom", fontsize=9, color=INK)
        ax.set_xticks([0, 1]); ax.set_xticklabels([p[1] for p in pairs], fontsize=8)
        ax.set_title(name, loc="left", color=INK)
        ax.set_ylim(0, max(vals) * 1.15)
    fig.suptitle("Board access: per-candidate profiling versus one exact height cache per request (A1, one lane)",
                 x=0.01, ha="left", color=INK, fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "board_access.png")
    plt.close(fig)


def fig_fmax(impl):
    ids = [c for c in LABELS if c in impl]
    fig, ax = plt.subplots(figsize=(8, 4))
    for i, cid in enumerate(ids):
        rows = impl[cid]
        for r in rows:
            if r["reported_fmax_mhz"]:
                f = float(r["reported_fmax_mhz"])
                ax.scatter([i], [f], color=SERIES[0] if r["timing_met"] == "True" else SERIES[7], s=28, zorder=3)
    ax.axhline(50, color=INK2, linewidth=1, linestyle="--")
    ax.text(len(ids) - 0.5, 50.5, "50 MHz constraint", ha="right", fontsize=8, color=INK2)
    ax.set_xticks(range(len(ids))); ax.set_xticklabels([LABELS[c] for c in ids], rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("reported Fmax (MHz), nextpnr-ecp5, seeds 1-5")
    ax.set_title("Routed timing per configuration (blue: met; red: failed)", loc="left", color=INK)
    fig.tight_layout()
    fig.savefig(OUT / "fmax_seeds.png")
    plt.close(fig)


def fig_divergence():
    path = ROOT / "results" / "precision_divergence_p1.json"
    if not path.is_file():
        return
    d = json.loads(path.read_text())
    ex = {c["candidate_id"]: c["score"] for c in d["candidates_exact"]}
    pr = {c["candidate_id"]: c["score"] for c in d["candidates_profile"]}
    ids = sorted(ex)
    fig, ax = plt.subplots(figsize=(8, 3.8))
    x = range(len(ids))
    ax.plot(x, [ex[i] for i in ids], marker="o", markersize=4, linewidth=1.5, color=SERIES[0], label="exact (76,51,36,18)")
    ax.plot(x, [pr[i] for i in ids], marker="o", markersize=4, linewidth=1.5, color=SERIES[1], label="powers_of_two (64,64,32,16)")
    ce, cp = d["exact_choice"], d["profile_choice"]
    ie = ids.index(10 * ce["rotation"] + ce["x"]); ip = ids.index(10 * cp["rotation"] + cp["x"])
    ax.annotate(f"exact picks rot {ce['rotation']} x {ce['x']}", (ie, ex[ids[ie]]), textcoords="offset points", xytext=(6, 10), fontsize=8, color=INK)
    ax.annotate(f"P1 picks rot {cp['rotation']} x {cp['x']}", (ip, pr[ids[ip]]), textcoords="offset points", xytext=(6, -14), fontsize=8, color=INK)
    ax.set_xticks(list(x)); ax.set_xticklabels([str(i) for i in ids], fontsize=7)
    ax.set_xlabel("candidate_id (10*rotation + x), legal candidates only")
    ax.set_ylabel("score")
    ax.legend(frameon=False, fontsize=8)
    ax.set_title(f"First divergence on validation seed {d['seed']}: move {d['move_index']}, piece {d['piece']}", loc="left", color=INK)
    fig.tight_layout()
    fig.savefig(OUT / "divergence_p1.png")
    plt.close(fig)


def fig_stages():
    files = {"A0 serial": "stage_cycles_a0_repr0_p0.json", "A1 bitmap": "stage_cycles_a1_repr0_p0.json", "A1 cache": "stage_cycles_a1_repr1_p0.json"}
    stages = [("DROP", ["DROP_START", "DROP_WAIT", "PROFILE"]), ("MERGE", ["MERGE_START", "MERGE_WAIT"]),
              ("CLEAR", ["CLEAR_START", "CLEAR_WAIT"]), ("FEATURES", ["FEAT_START", "FEAT_WAIT"]),
              ("SCORE+CTRL", ["SCORE_START", "SCORE_WAIT", "DECODE", "FINISH"])]
    data = {}
    for label, f in files.items():
        p = ROOT / "results" / f
        if p.is_file():
            prof = json.loads(p.read_text())["profiles"]["legal_no_clear"]
            data[label] = [sum(prof.get(s, 0) for s in group) for _, group in stages]
    if not data:
        return
    fig, ax = plt.subplots(figsize=(8, 3.2))
    for i, (label, vals) in enumerate(data.items()):
        left = 0
        for j, v in enumerate(vals):
            ax.barh(i, v, left=left, color=SERIES[j], edgecolor="white", linewidth=1, label=stages[j][0] if i == 0 else None)
            if v >= 20:
                ax.text(left + v / 2, i, f"{stages[j][0]} {v}", ha="center", va="center", fontsize=7, color="white")
            left += v
        ax.text(left + 2, i, f"{left} cycles", va="center", fontsize=8, color=INK)
    ax.set_yticks(range(len(data))); ax.set_yticklabels(list(data))
    ax.set_xlabel("cycles for one legal candidate (no line clear)")
    ax.set_title("Where a candidate's cycles go", loc="left", color=INK)
    ax.legend(frameon=False, fontsize=7, ncol=5, loc="lower right")
    fig.tight_layout()
    fig.savefig(OUT / "stage_cycles.png")
    plt.close(fig)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    impl = implementation()
    summary = json.loads((ROOT / "results" / "quality_summary.json").read_text()) if (ROOT / "results" / "quality_summary.json").is_file() else {}
    fig_area_vs_cycles(impl)
    fig_precision(impl, summary)
    fig_depth(impl, summary)
    fig_board_access(impl)
    fig_fmax(impl)
    fig_divergence()
    fig_stages()
    print("plots ->", sorted(p.name for p in OUT.glob("*.png")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
