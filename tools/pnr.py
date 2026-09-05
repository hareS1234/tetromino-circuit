#!/usr/bin/env python3
"""nextpnr-ecp5 place and route keyed by the complete route identity (ECP5 85k, CABGA381, speed 6).

    python tools/pnr.py --arch 1 --board-repr 1 --seed 1 --freq 50
    python tools/pnr.py --arch 0 --board-repr 0 --seed 1 --freq 200 --timeout 600

Synthesis is reused or run through tools/synth.py (synth_key), then the route runs in
build/route/<route_key>/ and its record is written atomically to results/v2/raw/routes/<route_key>.json
(schema route-record-v2).  route_key covers synth_key, netlist hash, nextpnr identity, device,
target frequency, seed, I/O constraint policy, options, timeout and script version; a parser
change re-analyses the retained log under a new analysis_key instead of re-routing.

Statuses (guide §10.3): routed_timing_met, routed_timing_failed, route_timeout, tool_error,
cancelled.  Timing is parsed only from the final section after "Routing complete." (and the
--report JSON when present); a placement-stage frequency line never establishes routed timing.
Return code zero alone is never the timing gate.  I/O is auto-allocated (--lpf-allow-unconstrained):
this is an implementation experiment, not a board pinout.  Nothing is appended to the frozen v1
results/implementation.csv.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.config import Config, add_config_arguments, validate  # noqa: E402
from tools.identity import (DEVICE_ECP5_85F, PNR_PARSER_VERSION, ROUTE_SCRIPT_VERSION, analysis_identity,  # noqa: E402
                            route_identity, sha256_file, source_closure_sha256, toolchain_identity)
from tools.synth import synthesize  # noqa: E402

DEVICE = DEVICE_ECP5_85F
ROUTE_TIMEOUT_S = 600          # v2 default budget (guide §10.1); v1 used 1800
RAW_ROUTES = ROOT / "results" / "v2" / "raw" / "routes"
STATUSES = ("routed_timing_met", "routed_timing_failed", "route_timeout", "tool_error", "cancelled")
FMAX_RE = re.compile(r"^(?:Info|Warning|ERROR):\s+Max frequency for clock\s+'([^']+)':\s+([\d.]+) MHz \((PASS|FAIL) at ([\d.]+) MHz\)", re.M)
UTIL_RE = re.compile(r"^\s*Info:\s+(\S+):\s+(\d+)/\s*(\d+)", re.M)


# ---- parsing (parser version PNR_PARSER_VERSION) -----------------------------------------------------

def parse_route_log(text: str) -> dict:
    """Facts from a nextpnr log.  Only the section after 'Routing complete.' establishes routed timing."""
    idx = text.find("Routing complete.")
    routing_complete = idx >= 0
    final = text[idx:] if routing_complete else ""
    pre = text[:idx] if routing_complete else text
    out = {"routing_complete": routing_complete, "final_fmax": None, "placement_fmax": None, "utilisation": {},
           "critical_path": None, "errors": [l.strip() for l in text.splitlines() if l.startswith("ERROR")][-5:]}
    m = FMAX_RE.findall(final)
    if m:
        clock, fmax, status, constraint = m[-1]
        out["final_fmax"] = {"clock": clock, "fmax_mhz": float(fmax), "constraint_mhz": float(constraint), "met": status == "PASS"}
    m = FMAX_RE.findall(pre)
    if m:
        clock, fmax, status, constraint = m[-1]
        out["placement_fmax"] = {"clock": clock, "fmax_mhz": float(fmax), "constraint_mhz": float(constraint), "met": status == "PASS",
                                 "note": "placement-stage estimate; not routed timing"}
    for name, used, avail in UTIL_RE.findall(text):
        out["utilisation"][name] = {"used": int(used), "available": int(avail)}
    if routing_complete:
        cp = re.search(r"Critical path report for clock '([^']+)' \(posedge -> posedge\):\n(.*?)\n\n", final, re.S)
        if cp:
            body = cp.group(2)
            src = re.search(r"Source (\S+)", body)
            sinks = re.findall(r"Sink (\S+)", body)
            tot = re.search(r"([\d.]+) ns logic, ([\d.]+) ns routing", body)
            total = re.findall(r"^\s*Info:\s+\S+\s+[\d.]+\s+([\d.]+)\s", body, re.M)
            out["critical_path"] = {"clock": cp.group(1), "from": src.group(1) if src else None,
                                    "to": sinks[-1] if sinks else None,
                                    "logic_ns": float(tot.group(1)) if tot else None,
                                    "routing_ns": float(tot.group(2)) if tot else None,
                                    "total_ns": float(total[-1]) if total else None}
    return out


def parse_report(report: Path) -> dict | None:
    """The --report JSON is written only by a completed run; fmax entries are routed results."""
    if not report.is_file():
        return None
    try:
        doc = json.loads(report.read_text())
    except (OSError, ValueError):
        return None
    fmax = doc.get("fmax") or {}
    clocks = {k: {"achieved_mhz": v.get("achieved"), "constraint_mhz": v.get("constraint")} for k, v in fmax.items()}
    return {"clocks": clocks, "utilization": {k: v.get("used") for k, v in (doc.get("utilization") or {}).items()},
            "critical_path_count": len(doc.get("critical_paths") or [])}


def classify(return_code: int | None, timed_out: bool, cancelled: bool, parsed: dict, report: dict | None) -> dict:
    """Separate fields for completion, timeout, timing result and report availability (guide §10.3)."""
    final = parsed.get("final_fmax")
    report_ok = bool(report and report.get("clocks"))
    met = None
    fmax = None
    clock = None
    source = None
    if final is not None:
        met, fmax, clock, source = final["met"], final["fmax_mhz"], final["clock"], "final-log"
    if report_ok:
        clock_name, entry = next(iter(report["clocks"].items()))
        if entry.get("achieved_mhz") is not None and entry.get("constraint_mhz") is not None:
            r_met = entry["achieved_mhz"] >= entry["constraint_mhz"]
            if met is None:
                met, fmax, clock, source = r_met, entry["achieved_mhz"], clock_name, "report-json"
            else:
                source = "report-json+final-log"
                if r_met != met:
                    source += " (disagree: report used)"
                    met, fmax = r_met, entry["achieved_mhz"]
    if cancelled:
        status, reason = "cancelled", "run cancelled before completion"
    elif timed_out:
        status, reason = "route_timeout", "declared route budget exhausted (a resource limit, not proof the design cannot route)"
    elif not parsed.get("routing_complete"):
        status, reason = "tool_error", f"routing did not complete (return code {return_code})"
    elif met is None:
        status, reason = "tool_error", "routing completed but no final clock frequency was reported"
    else:
        status = "routed_timing_met" if met else "routed_timing_failed"
        reason = f"final routed timing {'PASS' if met else 'FAIL'} from {source}" + ("" if return_code == 0 else f" (return code {return_code})")
    return {"status": status, "reason": reason,
            "completed": bool(parsed.get("routing_complete")) and not timed_out and not cancelled,
            "timing": {"report_available": report_ok, "met": met, "reported_fmax_mhz": fmax, "clock": clock, "source": source,
                       "worst_path": parsed.get("critical_path"),
                       "placement_estimate_mhz": (parsed.get("placement_fmax") or {}).get("fmax_mhz")}}


# ---- routing ---------------------------------------------------------------------------------------------

def route_dir(key: str) -> Path:
    return ROOT / "build" / "route" / key


def raw_path(key: str, attempt: int = 1) -> Path:
    """Attempt 1 is <key>.json; a deliberate retry is <key>.a<n>.json so no failure is replaced."""
    return RAW_ROUTES / (f"{key}.json" if attempt == 1 else f"{key}.a{attempt}.json")


def all_attempts(key: str) -> list[dict]:
    out = []
    for p in sorted(RAW_ROUTES.glob(f"{key}*.json")):
        try:
            doc = json.loads(p.read_text())
        except ValueError:
            continue
        if doc.get("route_key") == key:
            out.append(doc)
    return sorted(out, key=lambda d: d.get("attempt", {}).get("number", 1))


def atomic_write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    tmp.replace(path)


def peak_rss_mb(pid: int) -> float | None:
    try:
        for line in open(f"/proc/{pid}/status"):
            if line.startswith("VmHWM:"):
                return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        pass
    return None


def plan_route(cfg: Config, seed: int, freq: float, timeout_s: int = ROUTE_TIMEOUT_S, dsp_policy: str = "default",
               top: str = "stream_wrapper", synth_doc: dict | None = None) -> dict:
    """Identity for a route without running anything (synthesis is reused or run if synth_doc is None)."""
    if synth_doc is None:
        synth_doc = synthesize(top, cfg, dsp_policy=dsp_policy, quiet=True)
    ident = route_identity(synth_doc["synth_key"], synth_doc["netlist_sha256"], freq, seed, DEVICE, timeout_s)
    return {"identity": ident, "synth": synth_doc, "route_key": ident["route_key"]}


def existing_record(key: str) -> dict | None:
    """The latest attempt's record, or None."""
    attempts = all_attempts(key)
    return attempts[-1] if attempts else None


def route(cfg: Config, seed: int, freq: float = 50.0, timeout_s: int = ROUTE_TIMEOUT_S, dsp_policy: str = "default",
          top: str = "stream_wrapper", heartbeat=None, heartbeat_s: float = 30.0, retry_reason: str | None = None,
          synth_doc: dict | None = None, quiet: bool = False) -> dict:
    plan = plan_route(cfg, seed, freq, timeout_s, dsp_policy, top, synth_doc)
    ident, synth_doc, key = plan["identity"], plan["synth"], plan["route_key"]
    prior = existing_record(key)
    if prior is not None and retry_reason is None:
        if not quiet:
            print(f"{cfg.id} seed {seed} @ {freq:g} MHz: existing record {prior['status']} for route {key[:12]} (reused)")
        prior["reused"] = True
        return prior
    attempt_no = (prior["attempt"]["number"] + 1) if prior else 1
    rdir = route_dir(key) if attempt_no == 1 else route_dir(key) / f"attempt{attempt_no}"
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "identity.json").write_text(json.dumps(ident, indent=1) + "\n")
    log, report = rdir / "nextpnr.log", rdir / "timing.json"
    netlist = ROOT / synth_doc["netlist"]
    cmd = ["bash", str(ROOT / "scripts" / "env.sh"), "nextpnr-ecp5", DEVICE["flag"], "--package", DEVICE["package"],
           "--speed", DEVICE["speed"], "--json", str(netlist), "--freq", str(freq), "--seed", str(seed),
           *ident["options"], "--textcfg", str(rdir / "routed.config"), "--report", str(report), "--log", str(log)]
    (rdir / "command.txt").write_text(" ".join(cmd[2:]) + "\n")
    for stale in (log, report):
        stale.unlink(missing_ok=True)
    started = dt.datetime.now(dt.timezone.utc)
    t0 = time.perf_counter()
    timed_out = cancelled = False
    peak = None
    returncode = None
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        next_beat = t0 + heartbeat_s
        while True:
            try:
                returncode = proc.wait(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                pass
            now = time.perf_counter()
            rss = peak_rss_mb(proc.pid)
            if rss is not None:
                peak = max(peak or 0.0, rss)
            if now - t0 > timeout_s:
                timed_out = True
                os.killpg(proc.pid, signal.SIGKILL)
                returncode = proc.wait()
                break
            if heartbeat is not None and now >= next_beat:
                heartbeat({"config_id": cfg.id, "seed": seed, "target_mhz": freq, "elapsed_s": round(now - t0, 1),
                           "peak_rss_mb": peak, "route_key": key})
                next_beat = now + heartbeat_s
    except KeyboardInterrupt:
        cancelled = True
        os.killpg(proc.pid, signal.SIGKILL)
        returncode = proc.wait()
    elapsed = time.perf_counter() - t0
    text = log.read_text() if log.is_file() else ""
    parsed = parse_route_log(text)
    rep = parse_report(report)
    cls = classify(returncode, timed_out, cancelled, parsed, rep)
    util = parsed["utilisation"]
    record = {
        "schema": "route-record-v2", "route_key": key, "synth_key": synth_doc["synth_key"],
        "analysis_key": analysis_identity(key, PNR_PARSER_VERSION)["analysis_key"],
        "configuration_id": cfg.id, "params": cfg.params(), "top": top, "dsp_policy": dsp_policy,
        "device": dict(DEVICE), "target_mhz": float(freq), "seed": int(seed), "route_timeout_s": int(timeout_s),
        "options": ident["options"], "io_constraints": ident["io_constraints"], "script_version": ROUTE_SCRIPT_VERSION,
        "toolchain_id": toolchain_identity(), "nextpnr": ident["nextpnr"], "yosys": synth_doc.get("yosys"),
        "source_sha256": source_closure_sha256(), "netlist_sha256": synth_doc["netlist_sha256"],
        "attempt": {"number": attempt_no, "id": f"{key[:12]}-a{attempt_no}", "reason": retry_reason,
                    "previous_status": prior["status"] if prior else None},
        "process": {"return_code": returncode, "completed": cls["completed"], "timed_out": timed_out, "cancelled": cancelled,
                    "elapsed_s": round(elapsed, 1), "peak_rss_mb": peak, "started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "finished_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
        "timing": {**cls["timing"], "requested_mhz": float(freq), "freq_option_note": "--freq is nextpnr's default clock constraint for the selected clock"},
        "status": cls["status"], "status_reason": cls["reason"],
        "area": {"lut4": synth_doc.get("lut4"), "ff": synth_doc.get("ff"), "carry": synth_doc.get("ccu2c"), "bram": synth_doc.get("bram"),
                 "dsp": synth_doc.get("dsp"), "cells_total": synth_doc.get("cells_total"),
                 "trellis_comb": (util.get("TRELLIS_COMB") or {}).get("used"), "trellis_ff": (util.get("TRELLIS_FF") or {}).get("used"),
                 "dp16kd": (util.get("DP16KD") or {}).get("used"), "mult18x18d": (util.get("MULT18X18D") or {}).get("used")},
        "files": {"dir": str(rdir.relative_to(ROOT)), "log": str(log.relative_to(ROOT)) if log.is_file() else None,
                  "report": str(report.relative_to(ROOT)) if report.is_file() else None,
                  "config": str((rdir / "routed.config").relative_to(ROOT)) if (rdir / "routed.config").is_file() else None},
        "analysis": {"parser_version": PNR_PARSER_VERSION, "errors": parsed["errors"]},
        "reused": False,
    }
    atomic_write_json(raw_path(key, attempt_no), record)
    (rdir / "record.json").write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    if not quiet:
        t = record["timing"]
        print(f"{cfg.id} seed {seed} @ {freq:g} MHz: {record['status']}, fmax {t['reported_fmax_mhz']} MHz, "
              f"comb {record['area']['trellis_comb']} ff {record['area']['trellis_ff']} ({elapsed:.0f}s, rss {peak} MB) -> {raw_path(key, attempt_no).relative_to(ROOT)}")
    return record


def reanalyze(record: dict) -> dict:
    """Re-parse a retained log under the current parser version without re-routing."""
    log = ROOT / record["files"]["log"] if record["files"].get("log") else None
    report = ROOT / record["files"]["report"] if record["files"].get("report") else None
    text = log.read_text() if log and log.is_file() else ""
    parsed = parse_route_log(text)
    rep = parse_report(report) if report else None
    cls = classify(record["process"]["return_code"], record["process"]["timed_out"], record["process"]["cancelled"], parsed, rep)
    record = dict(record)
    record["timing"] = {**record["timing"], **cls["timing"]}
    record["status"] = cls["status"]
    record["status_reason"] = cls["reason"]
    record["analysis"] = {"parser_version": PNR_PARSER_VERSION, "errors": parsed["errors"]}
    record["analysis_key"] = analysis_identity(record["route_key"], PNR_PARSER_VERSION)["analysis_key"]
    atomic_write_json(raw_path(record["route_key"], record.get("attempt", {}).get("number", 1)), record)
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    add_config_arguments(ap)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--freq", type=float, default=50.0)
    ap.add_argument("--timeout", type=int, default=ROUTE_TIMEOUT_S)
    ap.add_argument("--dsp-policy", default="default", choices=["default", "nodsp"])
    ap.add_argument("--retry", default=None, metavar="REASON", help="record a new attempt even though a record exists")
    ap.add_argument("--print-key", action="store_true")
    ap.add_argument("--reanalyze", default=None, metavar="ROUTE_KEY", help="re-parse the retained log of an existing record")
    args = ap.parse_args()
    if args.reanalyze:
        rec = existing_record(args.reanalyze)
        if rec is None:
            raise SystemExit(f"no record for route {args.reanalyze}")
        rec = reanalyze(rec)
        print(f"{rec['configuration_id']} seed {rec['seed']} @ {rec['target_mhz']:g} MHz: {rec['status']} (parser {PNR_PARSER_VERSION}, analysis {rec['analysis_key'][:12]})")
        return 0
    cfg = validate(Config(args.arch, args.board_repr, args.lanes, args.depth, args.precision))
    if args.print_key:
        print(plan_route(cfg, args.seed, args.freq, args.timeout, args.dsp_policy)["route_key"])
        return 0
    rec = route(cfg, args.seed, args.freq, args.timeout, args.dsp_policy, retry_reason=args.retry,
                heartbeat=lambda h: print(f"  … {h['config_id']} seed {h['seed']} @ {h['target_mhz']:g} MHz, {h['elapsed_s']}s, rss {h['peak_rss_mb']} MB", flush=True))
    return 0 if rec["status"] == "routed_timing_met" else 1


if __name__ == "__main__":
    raise SystemExit(main())
