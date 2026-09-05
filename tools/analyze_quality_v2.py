#!/usr/bin/env python3
"""Censoring-aware analysis of a v2 quality suite (U15/U16, guide §9.5).

    python tools/analyze_quality_v2.py --config benchmarks/config_v2.json --suite bag50k            # analysis + figures
    python tools/analyze_quality_v2.py --config benchmarks/config_v2.json --suite bag50k --check    # validation only

Reads the per-game records of one suite (results/v2/raw/quality/<quality_key>.json), rejects
incomplete paired sets, conflicting duplicates, failed jobs and foreign protocol/source identities,
and reports per policy: restricted mean locked pieces (mean(min(T, C))), mean lines, cap-hit
fraction, the product-limit survival curve with the cap and censoring marked, the median only if the
curve crosses 1/2 within the horizon ("not reached by C" otherwise), and paired bootstrap intervals
of every policy against the baseline (whole streams resampled, fixed seed).  A software crash is a
failed job (raw/quality/<key>.failed.json) and blocks the analysis; it is never a censoring event.
Writes results/v2/summary/analysis_<suite>.json (schema quality-analysis-v2) and
results/v2/figures/survival_<suite>.png; for the held-out suite also results/v2/summary/quality.json.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.numeric import profile  # noqa: E402
from model.survival import (NOT_REACHED, check_paired, kaplan_meier, median_survival, paired_bootstrap, restricted_mean,  # noqa: E402
                            rmst_from_survival, survival_points)
from tools.bench import (failed_record_path, load_freeze, load_protocol, load_stream_any, model_closure_sha256, policy_key,  # noqa: E402
                         quality_identity, v2_records)
from model.streams_v2 import load_manifest as load_manifest_v2  # noqa: E402


def study_closure(proto: dict, suite_name: str, freeze: dict | None) -> str:
    """The model closure a suite's records must carry: the frozen one for a held-out suite (the study's
    identity survives later source changes), the live one for development suites."""
    if proto["suites"][suite_name].get("role") == "held-out" and freeze is not None and freeze.get("protocol_sha256") == proto["_sha256"]:
        return freeze["model_closure"]
    return model_closure_sha256()


def expected_jobs(proto: dict, suite_name: str, out_root: Path, closure: str | None = None) -> dict:
    """{(policy_key, seed): quality_key} for every job of the suite under the given (or live) model closure."""
    suite = proto["suites"][suite_name]
    lo, hi = suite["streams"]["seeds"]
    manifest = load_manifest_v2(ROOT) if proto.get("streams_manifest") else None
    body = {k: v for k, v in proto.items() if not k.startswith("_")}
    closure = closure or model_closure_sha256()
    jobs = {}
    for pol in suite["policies"]:
        for seed in range(lo, hi + 1):
            stream = load_stream_any(proto, seed, manifest)
            ident = quality_identity(body, pol, stream["sha256"], int(suite["cap"]), proto["_path"], model_closure=closure)
            jobs[(policy_key(pol), seed)] = {"key": ident["quality_key"], "stream_sha256": stream["sha256"], "policy": pol}
    return jobs


def collect(proto: dict, suite_name: str, out_root: Path, closure: str | None = None) -> tuple[dict, list[str]]:
    """Rows per policy for the suite; problems list (non-empty = do not summarise)."""
    suite = proto["suites"][suite_name]
    cap = int(suite["cap"])
    closure = closure or model_closure_sha256()
    jobs = expected_jobs(proto, suite_name, out_root, closure)
    have = v2_records(out_root)
    problems = []
    rows_by_policy = {policy_key(p): [] for p in suite["policies"]}
    for (pk, seed), job in jobs.items():
        rec = have.get(job["key"])
        if failed_record_path(out_root, job["key"]).is_file() and (rec is None or rec.get("status") != "complete"):
            problems.append(f"{pk} stream {seed}: failed job (raw/quality/{job['key'][:12]}….failed.json) — repair and re-run")
            continue
        if rec is None:
            continue    # reported by check_paired as missing
        if rec.get("status") != "complete":
            problems.append(f"{pk} stream {seed}: record status {rec.get('status')}")
            continue
        if rec["protocol_sha256"] != proto["_sha256"]:
            problems.append(f"{pk} stream {seed}: record from another protocol {rec['protocol_sha256'][:12]}")
            continue
        if rec["model_closure"] != closure:
            problems.append(f"{pk} stream {seed}: record from another model closure {rec['model_closure'][:12]}")
            continue
        if rec["stream_sha256"] != job["stream_sha256"] or int(rec["cap"]) != cap:
            problems.append(f"{pk} stream {seed}: stream hash or cap differs from the protocol")
            continue
        duration = rec.get("duration", rec["pieces_locked"])
        event = rec.get("event_observed", rec["terminal_reason"] == "top_out")
        if duration > cap or (event and duration == cap) or (not event and duration != cap):
            problems.append(f"{pk} stream {seed}: inconsistent duration/event ({duration}, {event}) for cap {cap}")
            continue
        rows_by_policy[pk].append({"stream_seed": seed, "duration": int(duration), "event_observed": bool(event), "lines": int(rec["lines"]),
                                   "wall_seconds": rec.get("wall_seconds"), "peak_rss_mb_process": rec.get("peak_rss_mb_process"),
                                   "quality_key": rec["quality_key"], "mode": rec.get("mode")})
    lo, hi = suite["streams"]["seeds"]
    problems += check_paired(rows_by_policy, range(lo, hi + 1))
    return rows_by_policy, problems


def fr(x: Fraction) -> dict:
    return {"value": float(x), "exact": f"{x.numerator}/{x.denominator}"}


def analyse(proto: dict, suite_name: str, rows_by_policy: dict, freeze: dict | None, closure: str | None = None) -> dict:
    suite = proto["suites"][suite_name]
    cap = int(suite["cap"])
    closure = closure or model_closure_sha256()
    lo, hi = suite["streams"]["seeds"]
    seeds = list(range(lo, hi + 1))
    stats = proto["statistics"]
    n_res, seed_b = int(stats["bootstrap_resamples"]), int(stats["bootstrap_seed"])
    per = {}
    series = {}
    for pol in suite["policies"]:
        pk = policy_key(pol)
        rows = {r["stream_seed"]: r for r in rows_by_policy[pk]}
        durations = [rows[s]["duration"] for s in seeds]
        events = [rows[s]["event_observed"] for s in seeds]
        lines = [rows[s]["lines"] for s in seeds]
        curve = kaplan_meier(durations, events, cap)
        rm = restricted_mean(durations)
        rmst = rmst_from_survival(curve, cap)
        if rm != rmst:      # with every censoring at C the two are identical; anything else is a bug
            raise AssertionError(f"{pk}: restricted mean {rm} != RMST from survival {rmst}")
        med = median_survival(curve, cap)
        walls = [r["wall_seconds"] for r in rows.values() if r.get("wall_seconds") is not None]
        rss = [r["peak_rss_mb_process"] for r in rows.values() if r.get("peak_rss_mb_process") is not None]
        series[pk] = {"pieces": durations, "lines": lines, "cap_hit": [0 if e else 1 for e in events]}
        per[pk] = {
            "policy": pol, "profile_name": profile(pol["precision"]).name if pol["policy"] == "heuristic" else None,
            "games": len(seeds), "cap": cap,
            "restricted_mean_pieces": fr(rm), "mean_lines": statistics.mean(lines), "median_lines": statistics.median(lines),
            "lines_quartiles": statistics.quantiles(lines, n=4) if len(lines) >= 4 else None,
            "cap_hit_fraction": fr(Fraction(sum(1 for e in events if not e), len(seeds))),
            "top_outs_observed": sum(events), "events_at_zero": sum(1 for d, e in zip(durations, events) if e and d == 0),
            "median_survival": med if med == NOT_REACHED else int(med),
            "median_statement": f"not reached by {cap}" if med == NOT_REACHED else f"{med} pieces (survival crosses 1/2 within the horizon)",
            "survival_points": survival_points(curve, cap),
            "duration_quartiles": statistics.quantiles(durations, n=4) if len(durations) >= 4 else None,
            "min_duration": min(durations), "max_duration": max(durations),
            "wall_seconds_total": round(sum(walls), 1) if walls else None,
            "wall_seconds_per_game_mean": round(statistics.mean(walls), 3) if walls else None,
            "peak_rss_mb_process_max": max(rss) if rss else None,
            "modes": sorted({r.get("mode") for r in rows.values() if r.get("mode")}),
        }
    bkey = policy_key(suite["baseline"])
    comparisons = {}
    for pk in per:
        if pk == bkey:
            continue
        comparisons[pk] = {
            "baseline": bkey,
            "restricted_mean_pieces": paired_bootstrap(series[bkey]["pieces"], series[pk]["pieces"], n_res, seed_b),
            "lines": paired_bootstrap(series[bkey]["lines"], series[pk]["lines"], n_res, seed_b + 1),
            "cap_hit_fraction": paired_bootstrap(series[bkey]["cap_hit"], series[pk]["cap_hit"], n_res, seed_b + 2),
            "wins_by_stream_pieces": {"policy": sum(1 for a, b in zip(series[bkey]["pieces"], series[pk]["pieces"]) if b > a),
                                      "baseline": sum(1 for a, b in zip(series[bkey]["pieces"], series[pk]["pieces"]) if a > b),
                                      "ties": sum(1 for a, b in zip(series[bkey]["pieces"], series[pk]["pieces"]) if a == b)},
        }
    return {"schema": "quality-analysis-v2", "protocol_name": proto.get("name"), "protocol_path": proto["_path"],
            "protocol_sha256": proto["_sha256"], "suite": suite_name, "role": suite.get("role"), "cap": cap, "streams": [lo, hi],
            "n_streams": len(seeds), "model_closure": closure, "live_model_closure": model_closure_sha256(),
            "sources_changed_since_study": closure != model_closure_sha256(),
            "freeze": {"present": freeze is not None, "protocol_sha256": freeze["protocol_sha256"] if freeze else None,
                       "matches_protocol": bool(freeze and freeze["protocol_sha256"] == proto["_sha256"]),
                       "frozen_utc": freeze["frozen_utc"] if freeze else None},
            "definitions": proto.get("outcomes"), "statistics": stats,
            "policies": per, "comparisons": comparisons, "baseline": bkey,
            "recorded_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def plot_survival(doc: dict, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cap = doc["cap"]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for pk, p in doc["policies"].items():
        pts = p["survival_points"]
        xs = [t for t, _ in pts]
        ys = [s for _, s in pts]
        label = f"{pk}" + (f" ({p['profile_name']})" if p.get("profile_name") else "")
        line, = ax.step(xs, ys, where="post", label=label)
        if p["cap_hit_fraction"]["value"] > 0:     # censoring marks at the cap
            ax.plot([cap], [ys[-1]], marker="+", color=line.get_color(), markersize=10)
    ax.axvline(cap, color="grey", linestyle="--", linewidth=1)
    ax.text(cap * 0.995, 0.60, f"cap C = {cap:,}\n(censoring, '+' marks)", ha="right", va="top", fontsize=8, color="grey")
    ax.axhline(0.5, color="lightgrey", linestyle=":", linewidth=1)
    ax.text(cap * 0.01, 0.51, "S = 1/2 (median)", fontsize=7, color="grey", va="bottom")
    ax.set_xlabel("locked pieces t (event: first top-out decision)")
    ax.set_ylabel("S(t) = P(T > t)")
    ax.set_ylim(0, 1.05)
    ax.set_xlim(0, cap * 1.02)
    ax.set_title(f"{doc['protocol_name']} / {doc['suite']} ({doc.get('role')}): product-limit survival, {doc['n_streams']} paired streams", fontsize=10)
    ax.legend(loc="upper right", bbox_to_anchor=(0.985, 0.90), fontsize=7.5, framealpha=0.9)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="benchmarks/config_v2.json")
    ap.add_argument("--suite", required=True)
    ap.add_argument("--out-root", default="results/v2")
    ap.add_argument("--check", action="store_true", help="validate the paired record set only")
    args = ap.parse_args()
    proto = load_protocol(ROOT / args.config)
    out_root = ROOT / args.out_root
    if args.suite not in proto["suites"]:
        raise SystemExit(f"unknown suite {args.suite}; suites: {', '.join(proto['suites'])}")
    freeze = load_freeze(out_root, proto)
    closure = study_closure(proto, args.suite, freeze)
    rows, problems = collect(proto, args.suite, out_root, closure)
    suite = proto["suites"][args.suite]
    expected = len(suite["policies"]) * (suite["streams"]["seeds"][1] - suite["streams"]["seeds"][0] + 1)
    present = sum(len(v) for v in rows.values())
    if suite.get("role") == "held-out":
        if freeze is None:
            problems.append("no freeze record for the protocol")
        elif freeze["protocol_sha256"] != proto["_sha256"]:
            problems.append("freeze record does not match the protocol (protocol edited after freezing)")
        elif freeze.get("model_closure") != model_closure_sha256():
            print(f"  note: model sources changed since the freeze (live closure {model_closure_sha256()[:12]}, study closure "
                  f"{closure[:12]}); the records are analysed under the frozen identity")
    print(f"CHECK quality_v2_{args.suite}_records {present}/{expected}")
    print(f"CHECK quality_v2_{args.suite}_paired {0 if problems else 1}/1")
    for p in problems:
        print("  -", p)
    if problems:
        print(f"analysis refused: the paired set is not complete/consistent ({len(problems)} problem(s))")
        return 1
    if args.check:
        print(f"check-quality-v2 {args.suite}: OK ({present} complete records, freeze {'matches' if freeze and freeze['protocol_sha256'] == proto['_sha256'] else 'absent/not required'})")
        return 0
    doc = analyse(proto, args.suite, rows, freeze, closure)
    out = out_root / "summary" / f"analysis_{args.suite}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.part")
    tmp.write_text(json.dumps(doc, indent=1) + "\n")
    tmp.replace(out)
    fig = out_root / "figures" / f"survival_{args.suite}.png"
    plot_survival(doc, fig)
    doc_paths = [out]
    if suite.get("role") == "held-out":
        primary = out_root / "summary" / "quality.json"
        primary.write_text(json.dumps(doc, indent=1) + "\n")
        doc_paths.append(primary)
    for pk, p in doc["policies"].items():
        print(f"  {pk:22s} restricted mean pieces {p['restricted_mean_pieces']['value']:9.1f}  mean lines {p['mean_lines']:9.1f}  "
              f"cap-hit {p['cap_hit_fraction']['value']:.2f}  median survival: {p['median_statement']}")
    for pk, c in doc["comparisons"].items():
        rm, ln = c["restricted_mean_pieces"], c["lines"]
        print(f"  {pk:22s} vs {c['baseline']}: pieces {rm['mean_diff']:+9.1f} CI95 [{rm['ci95'][0]:.1f}, {rm['ci95'][1]:.1f}]  "
              f"lines {ln['mean_diff']:+8.1f} CI95 [{ln['ci95'][0]:.1f}, {ln['ci95'][1]:.1f}]  streams won {c['wins_by_stream_pieces']}")
    print(f"CHECK quality_v2_{args.suite}_analysis {len(doc['policies'])}/{len(suite['policies'])}")
    print("->", ", ".join(str(p.relative_to(ROOT)) for p in doc_paths), "and", fig.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
