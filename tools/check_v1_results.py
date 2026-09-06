#!/usr/bin/env python3
"""Demand exact jobs, identities, and summaries from the read-only v1 experiment."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.config import SUPPORTED_IDS  # noqa: E402
from tools.bench import SummaryConflict, load_protocol, summarise, v1_rows  # noqa: E402

V1_ROUTE_STATUSES = {"routed", "timing_failed", "killed_no_convergence"}


def expected_quality_jobs(cfg: dict) -> set[tuple]:
    jobs = set()
    for name, suite in cfg["suites"].items():
        lo, hi = suite["streams"]["seeds"]
        for pol in suite["policies"]:
            for seed in range(lo, hi + 1):
                jobs.add((name, pol["policy"], pol["depth"], pol["precision"], seed, suite["cap"]))
    return jobs


def expected_route_jobs(cfg: dict) -> set[tuple]:
    hw = cfg["hardware_matrix"]
    return {(cid, seed) for cid in hw["configurations"] for seed in hw["route_seeds"]}


def expected_decision_files(cfg: dict) -> dict[str, int]:
    out = {}
    for cid in cfg["hardware_matrix"]["configurations"]:
        count = 250 if SUPPORTED_IDS[cid].depth == 2 else 1000
        out[f"results/decisions/{cid}_native_{count}.csv"] = count
    return out


def check_quality(cfg: dict, problems: list, checks: list, root: Path = ROOT) -> None:
    rows = v1_rows(root / "results" / "quality.csv")
    held = [r for r in rows if r["suite"] in cfg["suites"]]
    expected = expected_quality_jobs(cfg)
    seen = {}
    for r in held:
        key = (r["suite"], r["policy"], r["depth"], r["precision"], r["stream_seed"], r["cap"])
        seen.setdefault(key, []).append(r)
    missing = sorted(expected - set(seen))
    extra = sorted(set(seen) - expected)
    dup = sorted(k for k, v in seen.items() if len(v) > 1)
    sources = sorted({r["source"] for r in held})
    if missing:
        problems.append(f"quality: {len(missing)} expected jobs missing, e.g. {missing[:3]}")
    if extra:
        problems.append(f"quality: {len(extra)} rows outside the frozen protocol, e.g. {extra[:3]}")
    if dup:
        problems.append(f"quality: duplicate rows for {len(dup)} jobs, e.g. {dup[:3]}")
    if len(sources) != 1:
        problems.append(f"quality: held-out rows come from {len(sources)} source identities {sources}")
    checks.append(("quality_jobs", len(expected) - len(missing), len(expected)))
    summary_path = root / "results" / "quality_summary.json"
    committed = json.loads(summary_path.read_text()) if summary_path.is_file() else {}
    agree = total = 0
    for name, suite in cfg["suites"].items():
        try:
            s = summarise(held, suite, source=sources[0] if sources else "", protocol_sha256="v1-frozen",
                          resamples=cfg["statistics"]["bootstrap_resamples"], bootstrap_seed=cfg["statistics"]["bootstrap_seed"],
                          suite_name=name)
        except SummaryConflict as exc:
            problems.append(f"quality {name}: {exc}")
            continue
        for k, v in s["policies"].items():
            total += 1
            c = committed.get(name, {}).get("policies", {}).get(k)
            if v.get("status") != "complete":
                problems.append(f"quality {name}: {k} incomplete ({v.get('missing_count')} missing)")
            elif c is None:
                problems.append(f"quality {name}: {k} absent from the committed summary")
            elif (c.get("mean_lines"), c.get("median_lines"), (c.get("vs_baseline") or {}).get("ci95")) != \
                    (v["mean_lines"], v["median_lines"], (v.get("vs_baseline") or {}).get("ci95")):
                problems.append(f"quality {name}: {k} recomputed {v['mean_lines']} / {(v.get('vs_baseline') or {}).get('ci95')} "
                                f"differs from committed {c.get('mean_lines')} / {(c.get('vs_baseline') or {}).get('ci95')}")
            else:
                agree += 1
    checks.append(("quality_summary_recomputed", agree, total))


def check_routes(cfg: dict, problems: list, checks: list, root: Path = ROOT) -> None:
    path = root / "results" / "implementation.csv"
    if not path.is_file():
        problems.append("missing results/implementation.csv")
        checks.append(("route_jobs", 0, len(expected_route_jobs(cfg))))
        return
    rows = list(csv.DictReader(open(path)))
    by_params = {(c.arch, c.board_repr, c.lanes, c.depth, c.precision): cid for cid, c in SUPPORTED_IDS.items()}
    seen = {}
    for r in rows:
        params = (int(r["arch"]), int(r["board_repr"]), int(r["lanes"]), int(r["depth"]), int(r["precision"]))
        cid = by_params.get(params)
        if cid is None:
            problems.append(f"implementation.csv: row with unsupported parameters {params}")
            continue
        seen.setdefault((cid, int(r["route_seed"])), []).append(r)
    expected = expected_route_jobs(cfg)
    missing = sorted(expected - set(seen))
    extra = sorted(set(seen) - expected)
    dup = sorted(k for k, v in seen.items() if len(v) > 1)
    if missing:
        problems.append(f"routes: {len(missing)} expected jobs missing: {missing[:5]}")
    if extra:
        problems.append(f"routes: {len(extra)} rows outside the frozen matrix: {extra[:5]}")
    if dup:
        problems.append(f"routes: duplicate rows for {dup[:5]}")
    tool_ids = sorted({r["toolchain_id"] for r in rows})
    if len(tool_ids) != 1:
        problems.append(f"routes: {len(tool_ids)} toolchain identities {tool_ids}")
    targets = sorted({(r["target"], r["package"], r["speed_grade"], r["target_mhz"]) for r in rows})
    hw = cfg["hardware_matrix"]
    if targets != [(hw["device"], hw["package"], hw["speed_grade"], f"{float(hw['target_mhz'])}")]:
        problems.append(f"routes: device/target columns {targets} do not match the frozen matrix")
    for r in rows:
        if r["status"] not in V1_ROUTE_STATUSES:
            problems.append(f"routes: unknown status {r['status']}")
        if r["status"] != "routed" and (r["timing_met"] == "True" or r["reported_fmax_mhz"] not in ("", None)):
            problems.append(f"routes: non-routed row claims timing/fmax: {r['status']} {r['reported_fmax_mhz']}")
        if r["status"] == "routed" and r["timing_met"] != "True":
            problems.append("routes: routed row without timing_met")
    checks.append(("route_jobs", len(expected) - len(missing), len(expected)))
    manifest = root / "results" / "implementation_manifest.json"
    if manifest.is_file():
        m = json.loads(manifest.read_text())
        att = m.get("attempts", {})
        hashes = sorted({a.get("rtl_hash") for a in att.values()})
        if len(att) != len(expected):
            problems.append(f"implementation_manifest.json records {len(att)} attempts, expected {len(expected)}")
        if len(hashes) != 1:
            problems.append(f"implementation_manifest.json attempts span rtl hashes {hashes}")
        for key, a in att.items():
            cid, seed = key.split(":s")
            row = seen.get((cid, int(seed)), [{}])[0]
            if row and (row.get("status") != a.get("status") or (row.get("timing_met") == "True") != bool(a.get("timing_met"))):
                problems.append(f"manifest/CSV disagree for {key}: {a.get('status')} vs {row.get('status')}")
    else:
        problems.append("missing results/implementation_manifest.json")


def check_decisions(cfg: dict, problems: list, checks: list, root: Path = ROOT) -> None:
    expected = expected_decision_files(cfg)
    ok = 0
    for rel, count in expected.items():
        p = root / rel
        if not p.is_file():
            problems.append(f"decisions: missing {rel}")
            continue
        rows = list(csv.DictReader(open(p)))
        cid = rel.split("/")[-1].split("_native_")[0]
        c = SUPPORTED_IDS[cid]
        bad = [r for r in rows if (int(r["arch"]), int(r["board_repr"]), int(r["lanes"]), int(r["depth"]), int(r["precision"])) !=
               (c.arch, c.board_repr, c.lanes, c.depth, c.precision)]
        ids = {r["state_id"] for r in rows}
        if len(rows) != count or bad or len(ids) != count:
            problems.append(f"decisions: {rel} has {len(rows)} rows ({len(ids)} distinct states, {len(bad)} foreign), expected {count}")
        else:
            ok += 1
    checks.append(("decision_files", ok, len(expected)))


def check_evidence(problems: list, checks: list, root: Path = ROOT) -> None:
    ok = 0
    for i in range(20):
        p = root / "results" / "evidence" / f"E{i:02d}" / "summary.json"
        if not p.is_file():
            problems.append(f"E{i:02d}: no evidence summary")
            continue
        s = json.loads(p.read_text())
        cmds = s.get("commands") or []
        if s.get("status") != "passed":
            problems.append(f"E{i:02d}: status {s.get('status')}")
        elif not cmds:
            problems.append(f"E{i:02d}: passed with zero commands (not evidence)")
        elif any(c.get("exit_code") != 0 for c in cmds):
            problems.append(f"E{i:02d}: passed with a nonzero exit code")
        elif not s.get("source_hash") or not s.get("commit"):
            problems.append(f"E{i:02d}: missing source/commit identity")
        else:
            ok += 1
    checks.append(("v1_evidence", ok, 20))


def run_checks(root: Path = ROOT) -> tuple[list, list]:
    problems, checks = [], []
    cfg = load_protocol(root / "benchmarks" / "config.json")
    check_quality(cfg, problems, checks, root)
    check_routes(cfg, problems, checks, root)
    check_decisions(cfg, problems, checks, root)
    check_evidence(problems, checks, root)
    return problems, checks


def main() -> int:
    problems, checks = run_checks()
    for name, ok, total in checks:
        print(f"CHECK {name} {ok}/{total}")
    if problems:
        print("check-v1-results: FAIL")
        for p in problems:
            print("  -", p)
        return 1
    print("check-v1-results: OK (frozen v1 experiment intact; identities are the v1 source/rtl hashes, not full job keys)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
