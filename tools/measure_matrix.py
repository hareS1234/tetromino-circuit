#!/usr/bin/env python3
"""Plan, resume, and summarise the identity-keyed v2 hardware matrix.

Completed outcomes are reused by full route key, including honest timing failures and timeouts.
Retries need a reason and become separate attempts. A lock keeps two local runners from colliding;
the v1 matrix is strictly off-limits.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.config import SUPPORTED_IDS  # noqa: E402
from tools.identity import native_identity, source_closure_sha256, toolchain_identity  # noqa: E402
from tools import pnr  # noqa: E402
from tools.pnr import ROUTE_TIMEOUT_S, all_attempts, existing_record, plan_route, route  # noqa: E402
from tools.synth import synthesize  # noqa: E402

V2 = ROOT / "results" / "v2"
LOCK = V2 / "runner.lock"
HEARTBEAT = V2 / "runner.heartbeat.json"
SUMMARY_DIR = V2 / "summary"
RAW_DECISIONS = V2 / "raw" / "decisions"
HEARTBEAT_S = 60
ROUTE_CSV_FIELDS = ["configuration_id", "target_mhz", "seed", "dsp_policy", "attempt", "current", "status", "timing_met", "reported_fmax_mhz",
                    "lut4", "ff", "carry", "bram", "dsp", "trellis_comb", "trellis_ff", "elapsed_s", "peak_rss_mb",
                    "route_timeout_s", "worst_path_from", "worst_path_to", "logic_ns", "routing_ns", "toolchain_id",
                    "synth_key", "route_key", "source_sha256"]


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Manifest

def load_manifest(path: Path) -> dict:
    doc = json.loads(path.read_text())
    if doc.get("schema") != "hardware-matrix-v2":
        raise SystemExit(f"{path}: schema must be hardware-matrix-v2")
    for cid in doc.get("configurations", []) + [j["configuration"] for j in doc.get("extra_jobs", [])]:
        if cid not in SUPPORTED_IDS:
            raise SystemExit(f"{path}: unsupported configuration {cid}")
    doc.setdefault("dsp_policy", "default")
    doc.setdefault("top", "stream_wrapper")
    doc.setdefault("route_timeout_s", ROUTE_TIMEOUT_S)
    doc.setdefault("route_timeout_overrides", {})
    for cid, t in doc["route_timeout_overrides"].items():
        if cid not in SUPPORTED_IDS or int(t) <= 0:
            raise SystemExit(f"{path}: bad route_timeout_overrides entry {cid}: {t}")
    doc["_path"] = str(path.relative_to(ROOT)) if path.is_absolute() and path.is_relative_to(ROOT) else str(path)
    doc["_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return doc


def expand_jobs(m: dict) -> list[dict]:
    """Deterministic, duplicate-free job list: product block first, then extra jobs, sorted."""
    jobs = {}
    for cid in m.get("configurations", []):
        for f in m.get("targets_mhz", []):
            for s in m.get("seeds", []):
                jobs[(cid, float(f), int(s))] = {"configuration": cid, "target_mhz": float(f), "seed": int(s)}
    for j in m.get("extra_jobs", []):
        jobs[(j["configuration"], float(j["target_mhz"]), int(j["seed"]))] = {
            "configuration": j["configuration"], "target_mhz": float(j["target_mhz"]), "seed": int(j["seed"])}
    return [jobs[k] for k in sorted(jobs)]


def job_label(j: dict) -> str:
    return f"{j['configuration']}:{j['target_mhz']:g}:{j['seed']}"


def job_timeout(m: dict, cid: str) -> int:
    """Route budget for a configuration: the manifest default or its declared override (part of the route identity)."""
    return int(m.get("route_timeout_overrides", {}).get(cid, m["route_timeout_s"]))


# Runner lock and heartbeat

def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_lock(manifest_path: str) -> None:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if LOCK.is_file():
        try:
            doc = json.loads(LOCK.read_text())
        except ValueError:
            doc = {}
        if doc.get("pid") and pid_alive(int(doc["pid"])):
            raise SystemExit(f"another matrix runner (pid {doc['pid']}, manifest {doc.get('manifest')}, started {doc.get('started_utc')}) "
                             f"holds {LOCK.relative_to(ROOT)}; not launching a duplicate")
        print(f"[matrix] removing stale lock from pid {doc.get('pid')} (not running)")
        LOCK.unlink()
    LOCK.write_text(json.dumps({"pid": os.getpid(), "manifest": manifest_path, "started_utc": now_utc()}, indent=1) + "\n")


def release_lock() -> None:
    try:
        if LOCK.is_file() and json.loads(LOCK.read_text()).get("pid") == os.getpid():
            LOCK.unlink()
    except (OSError, ValueError):
        pass


def write_heartbeat(state: dict) -> None:
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    tmp = HEARTBEAT.with_suffix(".part")
    tmp.write_text(json.dumps({**state, "heartbeat_utc": now_utc(), "pid": os.getpid()}, indent=1) + "\n")
    tmp.replace(HEARTBEAT)


# Summaries

def route_row(rec: dict) -> dict:
    wp = (rec.get("timing") or {}).get("worst_path") or {}
    a = rec.get("area") or {}
    return {"configuration_id": rec["configuration_id"], "target_mhz": rec["target_mhz"], "seed": rec["seed"],
            "dsp_policy": rec.get("dsp_policy"), "attempt": rec["attempt"]["number"], "status": rec["status"],
            "timing_met": rec["timing"].get("met"), "reported_fmax_mhz": rec["timing"].get("reported_fmax_mhz"),
            "lut4": a.get("lut4"), "ff": a.get("ff"), "carry": a.get("carry"), "bram": a.get("bram"), "dsp": a.get("dsp"),
            "trellis_comb": a.get("trellis_comb"), "trellis_ff": a.get("trellis_ff"), "elapsed_s": rec["process"]["elapsed_s"],
            "peak_rss_mb": rec["process"].get("peak_rss_mb"), "route_timeout_s": rec["route_timeout_s"],
            "worst_path_from": wp.get("from"), "worst_path_to": wp.get("to"), "logic_ns": wp.get("logic_ns"),
            "routing_ns": wp.get("routing_ns"), "toolchain_id": rec["toolchain_id"], "synth_key": rec["synth_key"],
            "route_key": rec["route_key"], "source_sha256": rec["source_sha256"]}


def derive_route_csv(records: list[dict], path: Path, current_keys: dict | None = None) -> None:
    """Write every route attempt, marking which key belongs to the current source and toolchain."""
    rows = []
    for r in records:
        row = route_row(r)
        label = f"{r['configuration_id']}:{r['target_mhz']:g}:{r['seed']}"
        if current_keys is None or label not in current_keys:
            row["current"] = ""
        else:
            row["current"] = current_keys[label] == r["route_key"]
        rows.append(row)
    rows.sort(key=lambda r: (r["configuration_id"], r["target_mhz"], r["seed"], r["attempt"], r["route_key"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with open(tmp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ROUTE_CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in ROUTE_CSV_FIELDS})
    tmp.replace(path)


def load_raw_records() -> list[dict]:
    out = []
    if pnr.RAW_ROUTES.is_dir():
        for p in sorted(pnr.RAW_ROUTES.glob("*.json")):
            try:
                d = json.loads(p.read_text())
            except ValueError:
                continue
            if d.get("schema") == "route-record-v2":
                out.append(d)
    return out


def eta_range(done: list[dict], remaining: list[dict]) -> dict | None:
    """Per-configuration min/max of completed elapsed times applied to the remaining jobs."""
    if not done:
        return None
    by_cfg = {}
    for r in done:
        by_cfg.setdefault(r["configuration_id"], []).append(r["process"]["elapsed_s"])
    all_times = [t for ts in by_cfg.values() for t in ts]
    lo = hi = 0.0
    for j in remaining:
        ts = by_cfg.get(j["configuration"], all_times)
        lo += min(ts)
        hi += max(ts)
    return {"low_s": round(lo), "high_s": round(hi), "comparable_jobs": len(done)}


# Decision corpora

def corpus_hash(depth: int, count: int) -> str:
    path = ROOT / "benchmarks" / "states" / ("corpus_d2.jsonl" if depth == 2 else "corpus_d1.jsonl")
    h = hashlib.sha256(path.read_bytes())
    h.update(f":count={count}".encode())
    return h.hexdigest()[:16]


def run_decisions(cid: str, count: int, force: bool = False) -> dict:
    cfg = SUPPORTED_IDS[cid]
    nkey = native_identity(cfg)["native_key"]
    chash = corpus_hash(cfg.depth, count)
    out_dir = RAW_DECISIONS / cid
    csv_path = out_dir / f"{chash}.csv"
    meta_path = out_dir / f"{chash}.json"
    if meta_path.is_file() and not force:
        meta = json.loads(meta_path.read_text())
        if meta.get("native_key") == nkey and meta.get("status") == "matched" and csv_path.is_file():
            meta["reused"] = True
            return meta
    cmd = ["bash", str(ROOT / "scripts/env.sh"), "python", "tools/test_core.py", "--arch", str(cfg.arch), "--board-repr",
           str(cfg.board_repr), "--lanes", str(cfg.lanes), "--depth", str(cfg.depth), "--precision", str(cfg.precision),
           "--count", str(count), "--driver", "native", "--out", str(csv_path.relative_to(ROOT))]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    lines = [l for l in proc.stdout.splitlines() if l.startswith("native: all")]
    meta = {"schema": "decision-record-v2", "configuration_id": cid, "count": count, "corpus_hash": chash, "native_key": nkey,
            "source_sha256": source_closure_sha256(), "status": "matched" if proc.returncode == 0 and lines else "failed",
            "result": lines[-1] if lines else proc.stdout[-500:] + proc.stderr[-500:], "csv": str(csv_path.relative_to(ROOT)),
            "elapsed_s": round(time.perf_counter() - t0, 1), "recorded_utc": now_utc(), "reused": False}
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = meta_path.with_suffix(".part")
    tmp.write_text(json.dumps(meta, indent=1) + "\n")
    tmp.replace(meta_path)
    if meta["status"] != "matched":
        raise SystemExit(f"decision corpus failed for {cid}: {meta['result'][-800:]}")
    return meta


# Commands

def plan(m: dict, only: set[str] | None, retry: str | None, do_synth: bool = True) -> list[dict]:
    """Resolve each job's identity (synthesis reused or run) and whether a record already exists."""
    jobs = expand_jobs(m)
    synth_cache = {}
    out = []
    for j in jobs:
        label = job_label(j)
        if only and label not in only:
            continue
        cfg = SUPPORTED_IDS[j["configuration"]]
        if j["configuration"] not in synth_cache:
            synth_cache[j["configuration"]] = synthesize(m["top"], cfg, dsp_policy=m["dsp_policy"], quiet=True) if do_synth else None
        sdoc = synth_cache[j["configuration"]]
        if sdoc is None:
            out.append({**j, "label": label, "route_key": None, "existing": None, "action": "synthesis pending"})
            continue
        p = plan_route(cfg, j["seed"], j["target_mhz"], job_timeout(m, j["configuration"]), m["dsp_policy"], m["top"], sdoc)
        rec = existing_record(p["route_key"])
        action = "run" if rec is None else ("retry" if retry else "reuse")
        out.append({**j, "label": label, "route_key": p["route_key"], "synth_key": sdoc["synth_key"],
                    "existing": None if rec is None else {"status": rec["status"], "attempt": rec["attempt"]["number"],
                                                          "fmax": rec["timing"].get("reported_fmax_mhz")},
                    "action": action})
    return out


def cmd_plan(args) -> int:
    m = load_manifest(ROOT / args.manifest)
    only = set(args.only.split(",")) if args.only else None
    items = plan(m, only, args.retry, do_synth=not args.no_synth)
    print(f"[matrix] manifest {m['_path']} ({m['_sha256'][:12]}): {len(items)} jobs, dsp {m['dsp_policy']}, timeout {m['route_timeout_s']} s"
          + (f", overrides {m['route_timeout_overrides']}" if m.get("route_timeout_overrides") else ""))
    print(f"[matrix] unique route jobs: {len(items)} ({len({(it['configuration']) for it in items})} configurations, "
          f"targets {sorted({it['target_mhz'] for it in items})}, seeds {sorted({it['seed'] for it in items})})")
    counts = {}
    for it in items:
        counts[it["action"]] = counts.get(it["action"], 0) + 1
        ex = f" existing {it['existing']['status']} a{it['existing']['attempt']} fmax {it['existing']['fmax']}" if it["existing"] else ""
        print(f"  {it['label']:32s} {it['action']:8s} route {it['route_key'][:12] if it['route_key'] else '-'}{ex}")
    print(f"[matrix] actions: {counts}")
    if m.get("decisions"):
        print(f"[matrix] decisions: {m['decisions']}")
    return 0


def cmd_run(args) -> int:
    m = load_manifest(ROOT / args.manifest)
    only = set(args.only.split(",")) if args.only else None
    if args.retry and not only:
        raise SystemExit("--retry requires --only to name the job(s) being retried")
    acquire_lock(m["_path"])
    t_start = time.perf_counter()
    state = {"manifest": m["_path"], "manifest_sha256": m["_sha256"], "phase": "planning", "active": None,
             "completed": 0, "total": 0, "reused": 0, "successes": 0, "failures": 0, "timeouts": 0, "errors": 0}
    try:
        write_heartbeat(state)
        items = plan(m, only, args.retry)
        state.update({"phase": "routing", "total": len(items)})
        done_records = []
        for k, it in enumerate(items, 1):
            cfg = SUPPORTED_IDS[it["configuration"]]
            remaining = items[k:]
            state["active"] = {"job": it["label"], "index": k, "route_key": it["route_key"], "started_utc": now_utc()}
            state["eta"] = eta_range(done_records, remaining)
            write_heartbeat(state)
            print(f"[matrix] job {k}/{len(items)} start {it['label']} route {it['route_key'][:12]} action {it['action']} "
                  f"(completed {state['completed']}, reused {state['reused']}, ok {state['successes']}, fail {state['failures']}, "
                  f"timeout {state['timeouts']}, error {state['errors']}; eta {state['eta']})", flush=True)

            def beat(h, _state=state):
                _state["active"]["elapsed_s"] = h["elapsed_s"]
                _state["active"]["peak_rss_mb"] = h["peak_rss_mb"]
                write_heartbeat(_state)
                print(f"[matrix] … {h['config_id']} seed {h['seed']} @ {h['target_mhz']:g} MHz running {h['elapsed_s']:.0f} s, "
                      f"rss {h['peak_rss_mb']} MB ({_state['completed']}/{_state['total']} done)", flush=True)

            rec = route(cfg, it["seed"], it["target_mhz"], job_timeout(m, it["configuration"]), m["dsp_policy"], m["top"], heartbeat=beat,
                        heartbeat_s=min(HEARTBEAT_S, 30), retry_reason=args.retry if it["action"] == "retry" else None, quiet=True)
            if rec.get("reused"):
                state["reused"] += 1
            else:
                done_records.append(rec)
            state["completed"] += 1
            key = {"routed_timing_met": "successes", "routed_timing_failed": "failures", "route_timeout": "timeouts"}.get(rec["status"], "errors")
            state[key] += 1
            t = rec["timing"]
            print(f"[matrix] job {k}/{len(items)} done  {it['label']} {rec['status']}{' (reused)' if rec.get('reused') else ''} "
                  f"fmax {t.get('reported_fmax_mhz')} MHz, {rec['process']['elapsed_s']} s, rss {rec['process'].get('peak_rss_mb')} MB", flush=True)
            state["active"] = None
            write_heartbeat(state)
        # decisions
        dec = m.get("decisions")
        dec_results = {}
        if dec and not args.skip_decisions:
            state["phase"] = "decisions"
            for cid in dec["configurations"]:
                if only and not any(l.startswith(cid + ":") for l in only):
                    continue
                state["active"] = {"job": f"decisions {cid}", "started_utc": now_utc()}
                write_heartbeat(state)
                print(f"[matrix] decisions {cid} x{dec['count']} (native)", flush=True)
                meta = run_decisions(cid, int(dec["count"]))
                dec_results[cid] = meta
                print(f"[matrix] decisions {cid}: {meta['status']}{' (reused)' if meta.get('reused') else ''}. {meta['result']}", flush=True)
        # summaries derived from every raw record of the manifest's jobs (all attempts, all identities)
        labels = {job_label(j) for j in expand_jobs(m)}
        records = [r for r in load_raw_records() if job_label({"configuration": r["configuration_id"], "target_mhz": r["target_mhz"],
                                                               "seed": r["seed"]}) in labels and r.get("dsp_policy") == m["dsp_policy"]]
        current_keys = {it["label"]: it["route_key"] for it in items}
        SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
        derive_route_csv(records, SUMMARY_DIR / f"routes_{m.get('name', 'matrix')}.csv", current_keys)
        summary = {"schema": "matrix-summary-v2", "manifest": m["_path"], "manifest_sha256": m["_sha256"], "name": m.get("name"),
                   "toolchain_id": toolchain_identity(), "source_sha256": source_closure_sha256(), "recorded_utc": now_utc(),
                   "expected_jobs": sorted(labels), "planned_jobs": [it["label"] for it in items], "route_keys": current_keys,
                   "latest_status": {it["label"]: (existing_record(it["route_key"]) or {}).get("status") for it in items},
                   "counts": {k: state[k] for k in ("completed", "reused", "successes", "failures", "timeouts", "errors")},
                   "decisions": dec_results, "elapsed_s": round(time.perf_counter() - t_start, 1)}
        tmp = SUMMARY_DIR / f"matrix_{m.get('name', 'matrix')}.json.part"
        tmp.write_text(json.dumps(summary, indent=1) + "\n")
        tmp.replace(SUMMARY_DIR / f"matrix_{m.get('name', 'matrix')}.json")
        state["phase"] = "finished"
        write_heartbeat(state)
        print(f"[matrix] finished: {summary['counts']} in {summary['elapsed_s']} s -> {SUMMARY_DIR.relative_to(ROOT)}/matrix_{m.get('name', 'matrix')}.json")
        bad = [l for l, s in summary["latest_status"].items() if s not in ("routed_timing_met", "routed_timing_failed", "route_timeout")]
        return 1 if bad else 0
    finally:
        release_lock()


def cmd_status(args) -> int:
    if LOCK.is_file():
        doc = json.loads(LOCK.read_text())
        alive = pid_alive(int(doc.get("pid", 0)))
        print(f"[matrix] lock: pid {doc.get('pid')} ({'running' if alive else 'not running: stale'}), manifest {doc.get('manifest')}, started {doc.get('started_utc')}")
    else:
        print("[matrix] lock: none (no runner active)")
    if HEARTBEAT.is_file():
        hb = json.loads(HEARTBEAT.read_text())
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.strptime(hb["heartbeat_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)).total_seconds()
        print(f"[matrix] heartbeat {hb['heartbeat_utc']} ({age:.0f} s ago): phase {hb.get('phase')}, {hb.get('completed')}/{hb.get('total')} done, "
              f"ok {hb.get('successes')} fail {hb.get('failures')} timeout {hb.get('timeouts')} error {hb.get('errors')}, active {hb.get('active')}, eta {hb.get('eta')}")
    else:
        print("[matrix] heartbeat: none")
    recs = load_raw_records()
    counts = {}
    for r in recs:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"[matrix] raw route records: {len(recs)} {counts}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    for name in ("plan", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("--manifest", required=True)
        sp.add_argument("--only", default=None, help="comma-separated job labels configuration:target:seed")
        sp.add_argument("--retry", default=None, metavar="REASON")
        if name == "plan":
            sp.add_argument("--no-synth", action="store_true", help="list jobs without resolving synthesis identities")
        else:
            sp.add_argument("--skip-decisions", action="store_true")
    sub.add_parser("status")
    sd = sub.add_parser("decisions", help="one native common-state decision record for a configuration (decision-record-v2)")
    sd.add_argument("--config", required=True, help="configuration id, e.g. a1-cache-d1-p5-l1")
    sd.add_argument("--count", type=int, default=1000)
    sd.add_argument("--force", action="store_true", help="re-run even if a matching record exists")
    args = ap.parse_args()
    if args.cmd == "plan":
        return cmd_plan(args)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "decisions":
        if args.config not in SUPPORTED_IDS:
            raise SystemExit(f"configuration {args.config} is not supported; see python -m model.config --list")
        meta = run_decisions(args.config, args.count, force=args.force)
        print(f"[matrix] decisions {args.config} x{args.count}: {meta['status']} ({'reused' if meta.get('reused') else meta['elapsed_s']} s) "
              f"-> {meta['csv']}")
        print(meta["result"])
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
