#!/usr/bin/env python3
"""Software game-quality studies with identity-keyed results and paired bootstrap statistics.

    python tools/bench.py --check-config                                   # frozen v1 protocol (benchmarks/config.json)
    python tools/bench.py --check-config --config benchmarks/quality_smoke_v2.json
    python tools/bench.py --suite smoke --config benchmarks/quality_smoke_v2.json --out-root results/v2
    python tools/bench.py --summarise-v1 precision                        # recompute a frozen v1 summary from results/quality.csv

v2 protocols (schema quality-protocol-v2) write one atomic record per game to
<out-root>/raw/quality/<quality_key>.json (quality_key from tools/identity.py: protocol content,
policy/profile, stream hash, cap, model closure, runtime) and derive <out-root>/summary/quality.csv
and <out-root>/summary/quality_<suite>.json from those records.  Nothing is appended to the frozen
v1 files results/quality.csv and results/quality_summary.json; they are read only as historical inputs.

`summarise` requires one explicit source identity and one protocol identity, joins the exact expected
stream ids, and raises SummaryConflict on mixed sources, duplicate conflicting rows or foreign protocols.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
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
from tools.identity import model_closure_sha256, quality_identity, sha256_of, source_closure_sha256  # noqa: E402

V1_CONFIG = ROOT / "benchmarks" / "config.json"
V1_QUALITY = ROOT / "results" / "quality.csv"
V1_SUMMARY = ROOT / "results" / "quality_summary.json"
V1_FIELDS = ["commit", "spec", "backend", "experiment", "policy", "depth", "precision", "stream_seed", "stream_sha256",
             "cap", "lines", "pieces_locked", "terminal_reason", "source_hash", "wall_seconds"]
V2_CSV_FIELDS = ["suite", "policy", "depth", "precision", "stream_seed", "stream_sha256", "cap", "lines", "pieces_locked",
                 "terminal_reason", "wall_seconds", "protocol_sha256", "model_closure", "source", "quality_key", "git_commit"]


class SummaryConflict(Exception):
    """Rows that must not be combined (different sources/protocols, or contradictory duplicates)."""


def v1_source_hash() -> str:
    """The v1 identity of model/*.py (16 hex chars); kept so frozen rows can be re-validated."""
    h = hashlib.sha256()
    for p in sorted((ROOT / "model").glob("*.py")):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


# ---- protocols ------------------------------------------------------------------------------------------------

def load_protocol(path: Path) -> dict:
    doc = json.loads(path.read_text())
    doc["_path"] = str(path.relative_to(ROOT)) if path.is_absolute() and path.is_relative_to(ROOT) else str(path)
    doc["_sha256"] = sha256_of({k: v for k, v in doc.items() if not k.startswith("_")})
    return doc


def check_protocol(cfg: dict) -> list[str]:
    """Structural checks shared by the frozen v1 config and v2 protocols."""
    problems = []
    manifest = json.loads((ROOT / "benchmarks" / "streams" / "manifest.json").read_text())
    for name, suite in cfg["suites"].items():
        lo, hi = suite["streams"]["seeds"]
        split = suite["streams"]["split"]
        for seed in range(lo, hi + 1):
            if split in SPLITS and seed not in SPLITS[split]:
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
    if "hardware_matrix" in cfg:
        for cid in cfg["hardware_matrix"]["configurations"]:
            if cid not in SUPPORTED_IDS:
                problems.append(f"hardware matrix: unsupported configuration {cid}")
    if "tournament" in cfg:
        for cid in cfg["tournament"]["configurations"]:
            if cid not in cfg["hardware_matrix"]["configurations"]:
                problems.append(f"tournament: {cid} not in the hardware matrix")
    if cfg.get("schema") == "quality-protocol-v2":
        for key in ("name", "spec", "statistics"):
            if key not in cfg:
                problems.append(f"v2 protocol lacks '{key}'")
    return problems


# ---- rows and identity ---------------------------------------------------------------------------------------

def policy_key(p: dict) -> str:
    return f"{p['policy']}-d{p['depth']}-p{p['precision']}"


def v1_rows(path: Path = V1_QUALITY, experiment: str | None = None) -> list[dict]:
    """Frozen v1 rows normalised to the summariser's shape; `source` is the v1 model source hash."""
    if not path.is_file():
        return []
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        if experiment is not None and r["experiment"] != experiment:
            continue
        out.append({"suite": r["experiment"], "policy": r["policy"], "depth": int(r["depth"]), "precision": int(r["precision"]),
                    "stream_seed": int(r["stream_seed"]), "stream_sha256": r["stream_sha256"], "cap": int(r["cap"]),
                    "lines": int(r["lines"]), "pieces_locked": int(r["pieces_locked"]), "terminal_reason": r["terminal_reason"],
                    "wall_seconds": float(r["wall_seconds"]), "source": r["source_hash"], "protocol_sha256": "v1-frozen",
                    "commit": r["commit"]})
    return out


def v2_records(out_root: Path) -> dict[str, dict]:
    raw = out_root / "raw" / "quality"
    recs = {}
    if raw.is_dir():
        for p in sorted(raw.glob("*.json")):
            try:
                d = json.loads(p.read_text())
            except ValueError:
                continue
            if d.get("schema") == "quality-record-v2":
                recs[d["quality_key"]] = d
    return recs


def v2_row(rec: dict) -> dict:
    return {"suite": rec["suite"], "policy": rec["policy"]["policy"], "depth": rec["policy"]["depth"],
            "precision": rec["policy"]["precision"], "stream_seed": rec["stream_seed"], "stream_sha256": rec["stream_sha256"],
            "cap": rec["cap"], "lines": rec["lines"], "pieces_locked": rec["pieces_locked"], "terminal_reason": rec["terminal_reason"],
            "wall_seconds": rec["wall_seconds"], "source": rec["model_closure"], "protocol_sha256": rec["protocol_sha256"],
            "quality_key": rec["quality_key"], "commit": rec["git_commit"]}


def atomic_write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    tmp.replace(path)


# ---- statistics -------------------------------------------------------------------------------------------------------

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


def summarise(rows: list[dict], suite: dict, *, source: str, protocol_sha256: str, resamples: int, bootstrap_seed: int,
              suite_name: str | None = None) -> dict:
    """Summary over exactly the expected (policy, stream) jobs of one source and one protocol identity.

    rows: normalised rows (see v1_rows / v2_row).  Raises SummaryConflict when a row of the selected
    suite/cap carries another source or protocol identity, or when duplicates disagree."""
    lo, hi = suite["streams"]["seeds"]
    seeds = list(range(lo, hi + 1))
    cap = int(suite["cap"])
    selected = [r for r in rows if int(r["cap"]) == cap and (suite_name is None or r.get("suite") == suite_name)]
    foreign_sources = sorted({r["source"] for r in selected if r["source"] != source})
    if foreign_sources:
        raise SummaryConflict(f"rows from other source identities {foreign_sources} would be combined with {source}")
    foreign_protocols = sorted({r["protocol_sha256"] for r in selected if r["protocol_sha256"] != protocol_sha256})
    if foreign_protocols:
        raise SummaryConflict(f"rows from other protocols {foreign_protocols} would be combined with {protocol_sha256}")
    out = {"suite": suite_name, "cap": cap, "streams": [lo, hi], "n_streams": len(seeds), "source": source,
           "protocol_sha256": protocol_sha256, "policies": {}}
    series = {}
    for pol in suite["policies"]:
        sub = {}
        for r in selected:
            if r["policy"] == pol["policy"] and int(r["depth"]) == pol["depth"] and int(r["precision"]) == pol["precision"]:
                s = int(r["stream_seed"])
                if s in sub and (sub[s]["lines"], sub[s]["pieces_locked"], sub[s]["terminal_reason"]) != (r["lines"], r["pieces_locked"], r["terminal_reason"]):
                    raise SummaryConflict(f"{policy_key(pol)} stream {s}: duplicate rows disagree ({sub[s]['lines']} vs {r['lines']} lines)")
                sub[s] = r
        missing = [s for s in seeds if s not in sub]
        if missing:
            out["policies"][policy_key(pol)] = {"status": "incomplete", "games": len(seeds) - len(missing), "missing_streams": missing[:20],
                                                "missing_count": len(missing)}
            continue
        lines = [int(sub[s]["lines"]) for s in seeds]
        series[policy_key(pol)] = lines
        q = statistics.quantiles(lines, n=4) if len(lines) >= 4 else [min(lines), statistics.median(lines), max(lines)]
        out["policies"][policy_key(pol)] = {
            "status": "complete", "games": len(lines), "mean_lines": round(statistics.mean(lines), 3),
            "median_lines": statistics.median(lines), "iqr": [q[0], q[2]], "min_lines": min(lines), "max_lines": max(lines),
            "cap_hit_fraction": round(sum(sub[s]["terminal_reason"] == "cap_reached" for s in seeds) / len(seeds), 3),
            "top_out_fraction": round(sum(sub[s]["terminal_reason"] == "top_out" for s in seeds) / len(seeds), 3),
            "mean_pieces": round(statistics.mean(int(sub[s]["pieces_locked"]) for s in seeds), 2),
        }
    bkey = policy_key(suite["baseline"])
    if bkey in series:
        for k, lines in series.items():
            if k != bkey:
                out["policies"][k]["vs_baseline"] = paired_bootstrap(series[bkey], lines, resamples, bootstrap_seed)
    return out


# ---- v2 execution ----------------------------------------------------------------------------------------------------------

def run_suite_v2(proto: dict, suite_name: str, out_root: Path, seeds: list[int] | None = None, cap: int | None = None) -> dict:
    suite = proto["suites"][suite_name]
    lo, hi = suite["streams"]["seeds"]
    seeds = seeds if seeds is not None else list(range(lo, hi + 1))
    cap = cap if cap is not None else int(suite["cap"])
    closure = model_closure_sha256()
    src = source_closure_sha256()
    commit = git_commit(ROOT)
    protocol_body = {k: v for k, v in proto.items() if not k.startswith("_")}
    have = v2_records(out_root)
    done = skipped = 0
    t_suite = time.perf_counter()
    for pol in suite["policies"]:
        for seed in seeds:
            stream = load_stream(ROOT, seed)
            ident = quality_identity(protocol_body, pol, stream["sha256"], cap, proto["_path"], model_closure=closure)
            key = ident["quality_key"]
            if key in have and have[key].get("status") == "complete":
                skipped += 1
                continue
            decide = make_decider(pol["policy"], pol["depth"], pol["precision"], seed, "fast")
            t0 = time.perf_counter()
            records, terminal = play_game(decide, stream, cap, depth=pol["depth"])
            rec = {"schema": "quality-record-v2", "status": "complete", "quality_key": key, "protocol_path": proto["_path"],
                   "protocol_sha256": ident["protocol_sha256"], "protocol_name": proto.get("name"), "suite": suite_name,
                   "spec": stream["spec"], "backend": "python-fast", "policy": dict(pol), "stream_seed": seed,
                   "stream_sha256": stream["sha256"], "cap": cap, "lines": terminal["lines"], "pieces_locked": terminal["pieces_locked"],
                   "terminal_reason": terminal["reason"], "model_closure": closure, "source_sha256": src, "git_commit": commit,
                   "runtime": ident["runtime"], "wall_seconds": round(time.perf_counter() - t0, 3),
                   "recorded_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
            atomic_write_json(out_root / "raw" / "quality" / f"{key}.json", rec)
            done += 1
        print(f"  {suite_name}: {policy_key(pol)} complete ({time.perf_counter() - t_suite:.0f}s elapsed)")
    print(f"{suite_name}: {done} games run, {skipped} already recorded")
    return {"run": done, "skipped": skipped}


def derive_v2_csv(out_root: Path) -> Path:
    rows = sorted((v2_row(r) for r in v2_records(out_root).values()),
                  key=lambda r: (r["suite"], r["policy"], r["depth"], r["precision"], r["cap"], r["stream_seed"], r["quality_key"]))
    path = out_root / "summary" / "quality.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with open(tmp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=V2_CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in V2_CSV_FIELDS})
    tmp.replace(path)
    return path


def print_summary(summary: dict) -> None:
    for k, v in summary["policies"].items():
        if v.get("status") == "complete":
            vs = v.get("vs_baseline")
            print(f"  {k:24s} mean {v['mean_lines']:8.2f} median {v['median_lines']:7.1f} IQR {v['iqr']} cap_hit {v['cap_hit_fraction']:.2f}"
                  + (f"  diff vs baseline {vs['mean_diff']:+.2f} CI95 {vs['ci95']}" if vs else ""))
        else:
            print(f"  {k:24s} incomplete: {v['games']} games, {v['missing_count']} missing")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(V1_CONFIG.relative_to(ROOT)), help="protocol path (v1 config or quality-protocol-v2)")
    ap.add_argument("--out-root", default="results/v2", help="v2 output root (never the frozen v1 results/)")
    ap.add_argument("--check-config", action="store_true")
    ap.add_argument("--suite", default=None)
    ap.add_argument("--seeds", default=None, help="comma-separated subset for development runs")
    ap.add_argument("--cap", type=int, default=None, help="override cap for development runs")
    ap.add_argument("--summarise-v1", default=None, metavar="EXPERIMENT", help="recompute a frozen v1 summary (precision|depth) from results/quality.csv")
    args = ap.parse_args()
    proto = load_protocol(ROOT / args.config)
    problems = check_protocol(proto)
    if problems:
        for p in problems:
            print("config problem:", p)
        return 1
    print(f"{proto['_path']} OK ({proto['_sha256'][:12]}): {sum(len(s['policies']) for s in proto['suites'].values())} policy entries, "
          f"model closure {model_closure_sha256()[:12]}, commit {git_commit(ROOT)}")
    if args.summarise_v1:
        suite = proto["suites"][args.summarise_v1]
        rows = v1_rows(V1_QUALITY, args.summarise_v1)
        s = summarise(rows, suite, source=v1_source_hash() if not rows else rows[0]["source"], protocol_sha256="v1-frozen",
                      resamples=proto["statistics"]["bootstrap_resamples"], bootstrap_seed=proto["statistics"]["bootstrap_seed"],
                      suite_name=args.summarise_v1)
        print_summary(s)
        print(json.dumps({k: v for k, v in s.items() if k != "policies"}))
        return 0
    if args.check_config and not args.suite:
        return 0
    if not args.suite:
        ap.error("--suite is required to run games")
    if proto.get("schema") != "quality-protocol-v2":
        raise SystemExit("running games requires a quality-protocol-v2 file; the v1 protocol benchmarks/config.json is frozen "
                         "(its results are read with --summarise-v1)")
    out_root = ROOT / args.out_root
    if out_root.resolve() == (ROOT / "results").resolve():
        raise SystemExit("--out-root must not be the frozen v1 results/ directory")
    seeds = [int(s) for s in args.seeds.split(",")] if args.seeds else None
    run_suite_v2(proto, args.suite, out_root, seeds, args.cap)
    csv_path = derive_v2_csv(out_root)
    suite = dict(proto["suites"][args.suite])
    if args.cap is not None:
        suite["cap"] = args.cap
    if seeds is not None:
        suite = {**suite, "streams": {**suite["streams"], "seeds": [min(seeds), max(seeds)]}}
    rows = [v2_row(r) for r in v2_records(out_root).values()]
    summary = summarise(rows, suite, source=model_closure_sha256(), protocol_sha256=proto["_sha256"],
                        resamples=proto["statistics"]["bootstrap_resamples"], bootstrap_seed=proto["statistics"]["bootstrap_seed"],
                        suite_name=args.suite)
    summary.update({"schema": "quality-summary-v2", "protocol_path": proto["_path"], "git_commit": git_commit(ROOT),
                    "source_sha256": source_closure_sha256(), "derived_csv": str(csv_path.relative_to(ROOT)),
                    "recorded_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    atomic_write_json(out_root / "summary" / f"quality_{args.suite}.json", summary)
    print_summary(summary)
    print("->", (out_root / "summary" / f"quality_{args.suite}.json").relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
