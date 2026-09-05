#!/usr/bin/env python3
"""Frozen software game-quality study with resume support and paired bootstrap statistics.

    python tools/bench.py --check-config
    python tools/bench.py --suite pilot          # validation streams, quick wall-time estimate
    python tools/bench.py --suite precision      # held-out: P0-P4 + random, 100 streams, cap 2000
    python tools/bench.py --suite depth          # held-out: D1 vs D2, 20 streams, cap 500

Per-game rows go to results/quality.csv (manual Section 7 columns) as each game finishes;
re-running skips rows whose (experiment, policy, depth, precision, seed, cap, source_hash)
already exist.  Summaries (mean, median, IQR, cap-hit fraction, paired bootstrap CI of the
mean-lines difference vs the suite baseline) go to results/quality_summary.json.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.config import SUPPORTED_IDS  # noqa: E402
from model.numeric import PROFILES  # noqa: E402
from model.replay import git_commit, make_decider, play_game  # noqa: E402
from model.streams import SPLITS, load_stream, stream_sha256  # noqa: E402

CONFIG = ROOT / "benchmarks" / "config.json"
QUALITY = ROOT / "results" / "quality.csv"
SUMMARY = ROOT / "results" / "quality_summary.json"
FIELDS = ["commit", "spec", "backend", "experiment", "policy", "depth", "precision", "stream_seed", "stream_sha256",
          "cap", "lines", "pieces_locked", "terminal_reason", "source_hash", "wall_seconds"]


def source_hash() -> str:
    h = hashlib.sha256()
    for p in sorted((ROOT / "model").glob("*.py")):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def load_config():
    return json.loads(CONFIG.read_text())


def check_config(cfg) -> list:
    problems = []
    manifest = json.loads((ROOT / "benchmarks" / "streams" / "manifest.json").read_text())
    for name, suite in cfg["suites"].items():
        lo, hi = suite["streams"]["seeds"]
        split = suite["streams"]["split"]
        for seed in range(lo, hi + 1):
            if seed not in SPLITS[split]:
                problems.append(f"{name}: seed {seed} not in split {split}")
            try:
                doc = load_stream(ROOT, seed)
            except (FileNotFoundError, ValueError) as exc:
                problems.append(f"{name}: {exc}")
                continue
            if manifest["streams"].get(str(seed)) != doc["sha256"] or doc["sha256"] != stream_sha256(doc["pieces"]):
                problems.append(f"{name}: stream {seed} hash mismatch with manifest")
            if suite["cap"] + 1 > doc["length"]:
                problems.append(f"{name}: cap {suite['cap']} exceeds stream length")
        for pol in suite["policies"]:
            if pol["precision"] not in PROFILES:
                problems.append(f"{name}: unknown precision {pol['precision']}")
        if suite["baseline"] not in suite["policies"]:
            problems.append(f"{name}: baseline is not one of the policies")
    for cid in cfg["hardware_matrix"]["configurations"]:
        if cid not in SUPPORTED_IDS:
            problems.append(f"hardware matrix: unsupported configuration {cid}")
    for cid in cfg["tournament"]["configurations"]:
        if cid not in cfg["hardware_matrix"]["configurations"]:
            problems.append(f"tournament: {cid} not in the hardware matrix")
    return problems


def existing_rows():
    if not QUALITY.is_file():
        return {}
    with open(QUALITY) as fh:
        rows = list(csv.DictReader(fh))
    return {(r["experiment"], r["policy"], int(r["depth"]), int(r["precision"]), int(r["stream_seed"]), int(r["cap"]), r["source_hash"]): r for r in rows}


def append_row(row):
    new = not QUALITY.is_file()
    with open(QUALITY, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
        fh.flush()


def run_suite(name, suite, seeds, cap, experiment):
    src = source_hash()
    commit = git_commit(ROOT)
    have = existing_rows()
    done = skipped = 0
    t_suite = time.perf_counter()
    for pol in suite["policies"]:
        for seed in seeds:
            key = (experiment, pol["policy"], pol["depth"], pol["precision"], seed, cap, src)
            if key in have:
                skipped += 1
                continue
            stream = load_stream(ROOT, seed)
            decide = make_decider(pol["policy"], pol["depth"], pol["precision"], seed, "fast")
            t0 = time.perf_counter()
            records, terminal = play_game(decide, stream, cap, depth=pol["depth"])
            append_row({"commit": commit, "spec": stream["spec"], "backend": "python-fast", "experiment": experiment,
                        "policy": pol["policy"], "depth": pol["depth"], "precision": pol["precision"], "stream_seed": seed,
                        "stream_sha256": stream["sha256"], "cap": cap, "lines": terminal["lines"],
                        "pieces_locked": terminal["pieces_locked"], "terminal_reason": terminal["reason"],
                        "source_hash": src, "wall_seconds": round(time.perf_counter() - t0, 3)})
            done += 1
        print(f"  {name}: {pol['policy']} d{pol['depth']} p{pol['precision']} complete ({time.perf_counter() - t_suite:.0f}s elapsed)")
    print(f"{name}: {done} games run, {skipped} already present")


def paired_bootstrap(a, b, n, seed):
    """CI of mean(b - a) resampling stream ids jointly."""
    rng = random.Random(seed)
    diffs = [y - x for x, y in zip(a, b)]
    k = len(diffs)
    means = []
    for _ in range(n):
        s = [diffs[rng.randrange(k)] for _ in range(k)]
        means.append(sum(s) / k)
    means.sort()
    return {"mean_diff": round(sum(diffs) / k, 3), "ci95": [round(means[int(0.025 * n)], 3), round(means[int(0.975 * n) - 1], 3)]}


def summarise(cfg, experiment, suite):
    rows = [r for r in existing_rows().values() if r["experiment"] == experiment and int(r["cap"]) == suite["cap"]]
    lo, hi = suite["streams"]["seeds"]
    seeds = list(range(lo, hi + 1))
    out = {"experiment": experiment, "cap": suite["cap"], "streams": [lo, hi], "n_streams": len(seeds), "policies": {}}
    base = suite["baseline"]

    def key(p):
        return f"{p['policy']}-d{p['depth']}-p{p['precision']}"

    series = {}
    for pol in suite["policies"]:
        sub = {int(r["stream_seed"]): r for r in rows if r["policy"] == pol["policy"] and int(r["depth"]) == pol["depth"] and int(r["precision"]) == pol["precision"]}
        if any(s not in sub for s in seeds):
            out["policies"][key(pol)] = {"status": "incomplete", "games": len(sub)}
            continue
        lines = [int(sub[s]["lines"]) for s in seeds]
        series[key(pol)] = lines
        q = statistics.quantiles(lines, n=4) if len(lines) >= 4 else [min(lines), statistics.median(lines), max(lines)]
        out["policies"][key(pol)] = {
            "status": "complete", "games": len(lines), "mean_lines": round(statistics.mean(lines), 3),
            "median_lines": statistics.median(lines), "iqr": [q[0], q[2]], "min_lines": min(lines), "max_lines": max(lines),
            "cap_hit_fraction": round(sum(sub[s]["terminal_reason"] == "cap_reached" for s in seeds) / len(seeds), 3),
            "top_out_fraction": round(sum(sub[s]["terminal_reason"] == "top_out" for s in seeds) / len(seeds), 3),
            "mean_pieces": round(statistics.mean(int(sub[s]["pieces_locked"]) for s in seeds), 2),
        }
    bkey = key(base)
    if bkey in series:
        for k, lines in series.items():
            if k != bkey:
                out["policies"][k]["vs_baseline"] = paired_bootstrap(series[bkey], lines, cfg["statistics"]["bootstrap_resamples"],
                                                                      cfg["statistics"]["bootstrap_seed"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-config", action="store_true")
    ap.add_argument("--suite", choices=["pilot", "precision", "depth"])
    args = ap.parse_args()
    cfg = load_config()
    problems = check_config(cfg)
    if problems:
        for p in problems:
            print("config problem:", p)
        return 1
    print(f"benchmarks/config.json OK: {len(cfg['hardware_matrix']['configurations'])} hardware configurations, "
          f"{sum(len(s['policies']) for s in cfg['suites'].values())} policy entries, source {source_hash()}, commit {git_commit(ROOT)}")
    if args.check_config and not args.suite:
        return 0
    if args.suite == "pilot":
        # validation streams only; the pilot estimates wall time and never opens the test split
        t0 = time.perf_counter()
        for name, suite in cfg["suites"].items():
            seeds = list(SPLITS["validation"])[:5]
            run_suite(name, suite, seeds, min(suite["cap"], 500), f"pilot_{name}")
        est = {}
        for name, suite in cfg["suites"].items():
            rows = [r for r in existing_rows().values() if r["experiment"] == f"pilot_{name}"]
            per_piece = sum(float(r["wall_seconds"]) for r in rows) / max(1, sum(int(r["pieces_locked"]) for r in rows))
            lo, hi = suite["streams"]["seeds"]
            est[name] = round(per_piece * suite["cap"] * (hi - lo + 1) * len(suite["policies"]), 1)
        print(f"pilot done in {time.perf_counter() - t0:.0f}s; estimated full-suite wall seconds (upper bound, every game at cap): {est}")
        (ROOT / "results" / "bench_pilot_estimate.json").write_text(json.dumps(est, indent=1) + "\n")
        return 0
    suite = cfg["suites"][args.suite]
    lo, hi = suite["streams"]["seeds"]
    run_suite(args.suite, suite, list(range(lo, hi + 1)), suite["cap"], args.suite)
    summary = json.loads(SUMMARY.read_text()) if SUMMARY.is_file() else {}
    summary[args.suite] = summarise(cfg, args.suite, suite)
    summary[args.suite]["commit"] = git_commit(ROOT)
    summary[args.suite]["source_hash"] = source_hash()
    SUMMARY.write_text(json.dumps(summary, indent=1) + "\n")
    for k, v in summary[args.suite]["policies"].items():
        if v.get("status") == "complete":
            vs = v.get("vs_baseline")
            print(f"  {k:24s} mean {v['mean_lines']:8.2f} median {v['median_lines']:7.1f} IQR {v['iqr']} cap_hit {v['cap_hit_fraction']:.2f}"
                  + (f"  diff vs baseline {vs['mean_diff']:+.2f} CI95 {vs['ci95']}" if vs else ""))
    print("->", SUMMARY.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
