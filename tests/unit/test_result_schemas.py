"""Result schemas and the grimier corners of nextpnr status parsing."""
import csv
import json
import os
import subprocess
from pathlib import Path

import pytest

from tools import bench, check_hardware_v2 as hwcheck, check_v1_results as v1check, identity, pnr
from tools.measure_matrix import ROUTE_CSV_FIELDS, derive_route_csv, expand_jobs, route_row

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "pnr_logs"


def parsed(name):
    return pnr.parse_route_log((FIX / f"{name}.log").read_text())


def report(name):
    return pnr.parse_report(FIX / f"{name}_report.json")


# Parser and status classification

def test_success_log_and_report_agree():
    p = parsed("success")
    assert p["routing_complete"] and p["final_fmax"]["met"] and p["final_fmax"]["fmax_mhz"] == 66.49
    assert p["placement_fmax"]["fmax_mhz"] == 63.25, "placement estimate is kept separately"
    assert p["utilisation"]["TRELLIS_COMB"]["used"] == 3744
    assert p["critical_path"]["logic_ns"] == 4.57 and p["critical_path"]["routing_ns"] == 10.47
    assert p["critical_path"]["from"].endswith("y_q_TRELLIS_FF_Q_5.Q") and p["critical_path"]["to"].endswith(".CE")
    c = pnr.classify(0, False, False, p, report("success"))
    assert c["status"] == "routed_timing_met" and c["timing"]["report_available"] and c["timing"]["source"] == "report-json+final-log"
    assert c["timing"]["reported_fmax_mhz"] == 66.49 and c["completed"]


def test_timing_failure_is_a_completed_route_not_a_tool_error():
    p = parsed("timing_fail")
    assert p["routing_complete"] and p["final_fmax"]["met"] is False and p["final_fmax"]["constraint_mhz"] == 200.0
    assert any(e.startswith("ERROR: Max frequency") for e in p["errors"])
    c = pnr.classify(1, False, False, p, report("timing_fail"))
    assert c["status"] == "routed_timing_failed" and c["timing"]["met"] is False and c["timing"]["report_available"]
    assert "return code 1" in c["reason"]
    # --timing-allow-fail: return code 0 does not turn a failure into a pass
    assert pnr.classify(0, False, False, p, None)["status"] == "routed_timing_failed"


def test_partial_run_never_reports_the_placement_estimate():
    p = parsed("timeout_partial")
    assert not p["routing_complete"] and p["final_fmax"] is None and p["placement_fmax"]["fmax_mhz"] == 65.07
    c = pnr.classify(None, True, False, p, None)
    assert c["status"] == "route_timeout" and c["timing"]["met"] is None and c["timing"]["reported_fmax_mhz"] is None
    assert c["timing"]["placement_estimate_mhz"] == 65.07 and not c["completed"]
    assert "resource limit" in c["reason"]
    # the same log with a nonzero exit and no timeout is a tool error, still without fmax
    c2 = pnr.classify(137, False, False, p, None)
    assert c2["status"] == "tool_error" and c2["timing"]["reported_fmax_mhz"] is None


def test_missing_clock_and_missing_final_report_are_tool_errors():
    c = pnr.classify(0, False, False, parsed("missing_clock"), None)
    assert c["status"] == "tool_error" and "no final clock frequency" in c["reason"]
    c = pnr.classify(0, False, False, parsed("no_final_report"), None)
    assert c["status"] == "tool_error" and c["timing"]["met"] is None


def test_cancelled_and_report_disagreement():
    assert pnr.classify(None, False, True, parsed("success"), None)["status"] == "cancelled"
    rep = {"clocks": {"clk": {"achieved_mhz": 40.0, "constraint_mhz": 50.0}}, "utilization": {}, "critical_path_count": 0}
    c = pnr.classify(0, False, False, parsed("success"), rep)
    assert c["status"] == "routed_timing_failed" and "disagree" in c["timing"]["source"]


def test_parse_report_handles_absent_or_invalid_files(tmp_path):
    assert pnr.parse_report(tmp_path / "none.json") is None
    (tmp_path / "bad.json").write_text("{")
    assert pnr.parse_report(tmp_path / "bad.json") is None
    assert report("success")["clocks"]["$glbnet$clk$TRELLIS_IO_IN"]["constraint_mhz"] == 50


# Records and derived CSV

def fake_record(status="routed_timing_met", seed=1, attempt=1, fmax=66.49):
    return {"schema": "route-record-v2", "route_key": f"k{seed}{attempt}" * 8, "synth_key": "s" * 64, "analysis_key": "a" * 64,
            "configuration_id": "a0-bitmap-d1-p0-l1", "target_mhz": 50.0, "seed": seed, "dsp_policy": "default",
            "route_timeout_s": 600, "toolchain_id": "oss-cad-suite-2026-09-04", "source_sha256": "x" * 64,
            "attempt": {"number": attempt, "id": f"k-a{attempt}", "reason": None if attempt == 1 else "retry"},
            "process": {"return_code": 0, "completed": True, "timed_out": False, "cancelled": False, "elapsed_s": 26.4, "peak_rss_mb": 456.2},
            "timing": {"met": status == "routed_timing_met", "reported_fmax_mhz": fmax, "report_available": True,
                       "worst_path": {"from": "a.Q", "to": "b.D", "logic_ns": 4.5, "routing_ns": 10.5}},
            "status": status, "area": {"lut4": 3070, "ff": 2416, "carry": 226, "bram": 0, "dsp": 0, "trellis_comb": 3744, "trellis_ff": 2416}}


def test_route_row_and_derived_csv_are_sorted_and_keep_all_attempts(tmp_path):
    recs = [fake_record(seed=2), fake_record(seed=1, attempt=2, status="routed_timing_failed"), fake_record(seed=1)]
    path = tmp_path / "routes.csv"
    derive_route_csv(recs, path)
    rows = list(csv.DictReader(open(path)))
    assert [(r["seed"], r["attempt"]) for r in rows] == [("1", "1"), ("1", "2"), ("2", "1")]
    assert list(rows[0].keys()) == ROUTE_CSV_FIELDS and rows[0]["route_key"] == "k11" * 8
    assert route_row(fake_record())["worst_path_from"] == "a.Q"


@pytest.mark.skipif(not (ROOT / "results" / "v2" / "raw" / "routes").is_dir(), reason="no v2 route records yet")
def test_real_route_records_follow_the_schema():
    for p in (ROOT / "results" / "v2" / "raw" / "routes").glob("*.json"):
        d = json.loads(p.read_text())
        assert d["schema"] == "route-record-v2" and d["status"] in pnr.STATUSES and len(d["route_key"]) == 64
        for key in ("synth_key", "analysis_key", "netlist_sha256", "toolchain_id", "source_sha256", "attempt", "process", "timing", "area", "files"):
            assert key in d, key
        assert d["route_key"] in p.name
        if d["status"].startswith("routed"):
            assert d["timing"]["reported_fmax_mhz"] is not None and d["process"]["completed"]
        else:
            assert d["timing"]["reported_fmax_mhz"] is None


def test_hardware_release_match_uses_the_recorded_netlist_hash():
    cid = "a0-bitmap-d1-p0-l1"
    tools = {"yosys": "Yosys test", "nextpnr-ecp5": "nextpnr test"}
    m = {"schema": "hardware-matrix-v2", "name": "test", "top": "stream_wrapper", "dsp_policy": "nodsp",
         "configurations": [cid], "targets_mhz": [50], "seeds": [11], "extra_jobs": [], "route_timeout_s": 600,
         "route_timeout_overrides": {}}
    synth = identity.synth_identity(cid, top=m["top"], dsp_policy=m["dsp_policy"], root=ROOT, tools=tools)
    netlist_sha = "a" * 64
    route = identity.route_identity(synth["synth_key"], netlist_sha, 50, 11, pnr.DEVICE, 600,
                                    ["--lpf-allow-unconstrained"], pnr.ROUTE_SCRIPT_VERSION, ROOT, tools)
    rec = {"schema": "route-record-v2", "configuration_id": cid, "target_mhz": 50.0, "seed": 11,
           "synth_key": synth["synth_key"], "route_key": route["route_key"], "netlist_sha256": netlist_sha,
           "yosys": tools["yosys"], "nextpnr": tools["nextpnr-ecp5"], "toolchain_id": identity.toolchain_identity(ROOT),
           "top": m["top"], "params": synth["params"], "device": pnr.DEVICE, "dsp_policy": m["dsp_policy"],
           "route_timeout_s": 600, "options": ["--lpf-allow-unconstrained"],
           "io_constraints": "auto-allocated (--lpf-allow-unconstrained)", "script_version": pnr.ROUTE_SCRIPT_VERSION,
           "attempt": {"number": 1}}
    found, problems = hwcheck.resolve_route_records(m, [rec], root=ROOT, tools=tools)
    assert problems == [] and found[0]["record"] is rec
    rec["route_key"] = "b" * 64
    found, problems = hwcheck.resolve_route_records(m, [rec], root=ROOT, tools=tools)
    assert found[0]["record"] is None and "no record matches" in problems[0]


def test_expand_jobs_is_deterministic_and_duplicate_free():
    m = {"configurations": ["a1-cache-d1-p0-l1", "a0-bitmap-d1-p0-l1"], "targets_mhz": [60, 50], "seeds": [2, 1],
         "extra_jobs": [{"configuration": "a0-bitmap-d1-p0-l1", "target_mhz": 50, "seed": 1},
                        {"configuration": "a1-cache-d1-p1-l1", "target_mhz": 50, "seed": 1}]}
    jobs = expand_jobs(m)
    assert len(jobs) == 9 and jobs[0] == {"configuration": "a0-bitmap-d1-p0-l1", "target_mhz": 50.0, "seed": 1}
    assert jobs[-1]["configuration"] == "a1-cache-d1-p1-l1"


# Summaries

SUITE = {"policies": [{"policy": "heuristic", "depth": 1, "precision": 0}, {"policy": "heuristic", "depth": 1, "precision": 1}],
         "streams": {"split": "test", "seeds": [3000, 3003]}, "cap": 100, "baseline": {"policy": "heuristic", "depth": 1, "precision": 0}}


def row(precision, seed, lines, source="old", proto="p1", cap=100, suite="s"):
    return {"suite": suite, "policy": "heuristic", "depth": 1, "precision": precision, "stream_seed": seed, "stream_sha256": "h",
            "cap": cap, "lines": lines, "pieces_locked": 100, "terminal_reason": "cap_reached", "wall_seconds": 0.1,
            "source": source, "protocol_sha256": proto}


def clean_rows(source="old"):
    return [row(p, s, 10 * s % 7 + p, source=source) for p in (0, 1) for s in range(3000, 3004)]


def summarise(rows, **kw):
    args = dict(source="old", protocol_sha256="p1", resamples=200, bootstrap_seed=1, suite_name="s")
    args.update(kw)
    return bench.summarise(rows, SUITE, **args)


def test_summary_is_complete_and_deterministic():
    s = summarise(clean_rows())
    assert s["policies"]["heuristic-d1-p0"]["status"] == "complete" and s["policies"]["heuristic-d1-p1"]["vs_baseline"]["mean_diff"] == 1.0
    assert summarise(clean_rows()) == s


def test_mixed_source_rows_are_rejected_instead_of_silently_combined():
    rows = clean_rows()
    rows[2]["source"] = "new"          # the pre-U02 summariser would have combined this row with the others
    with pytest.raises(bench.SummaryConflict, match="other source identities \\['new'\\]"):
        summarise(rows)
    # selecting the new source rejects the old rows just the same
    with pytest.raises(bench.SummaryConflict):
        summarise(rows, source="new")


def test_foreign_protocol_duplicates_and_missing_streams():
    rows = clean_rows()
    rows[0]["protocol_sha256"] = "p2"
    with pytest.raises(bench.SummaryConflict, match="other protocols"):
        summarise(rows)
    rows = clean_rows() + [row(0, 3000, 999)]
    with pytest.raises(bench.SummaryConflict, match="duplicate rows disagree"):
        summarise(rows)
    rows = clean_rows() + [row(0, 3000, clean_rows()[0]["lines"])]   # identical duplicate is tolerated
    assert summarise(rows)["policies"]["heuristic-d1-p0"]["status"] == "complete"
    rows = [r for r in clean_rows() if not (r["precision"] == 1 and r["stream_seed"] == 3002)]
    s = summarise(rows)
    assert s["policies"]["heuristic-d1-p1"] == {"status": "incomplete", "games": 3, "missing_streams": [3002], "missing_count": 1}
    assert "vs_baseline" not in s["policies"]["heuristic-d1-p1"]


def test_exact_join_ignores_streams_and_caps_outside_the_suite():
    rows = clean_rows() + [row(0, 3999, 5), row(0, 3000, 77, cap=500), row(0, 3000, 88, suite="other")]
    s = summarise(rows)
    assert s["policies"]["heuristic-d1-p0"]["games"] == 4 and s["policies"]["heuristic-d1-p0"]["mean_lines"] == bench.statistics.mean(
        [r["lines"] for r in clean_rows() if r["precision"] == 0])


def test_frozen_v1_results_validate_exactly():
    problems, checks = v1check.run_checks()
    assert problems == []
    assert dict((n, (ok, tot)) for n, ok, tot in checks) == {"quality_jobs": (640, 640), "quality_summary_recomputed": (8, 8),
                                                            "route_jobs": (45, 45), "decision_files": (9, 9), "v1_evidence": (20, 20)}


# Release membership on a fake result tree

def fake_tree(tmp_path: Path) -> Path:
    root = tmp_path
    (root / "benchmarks").mkdir()
    (root / "results" / "decisions").mkdir(parents=True)
    cfg = {"suites": {"s": SUITE}, "statistics": {"bootstrap_resamples": 200, "bootstrap_seed": 1},
           "hardware_matrix": {"device": "LFE5U-85F", "package": "CABGA381", "speed_grade": "6", "target_mhz": 50.0,
                               "route_seeds": [1, 2], "configurations": ["a0-bitmap-d1-p0-l1"]}}
    (root / "benchmarks" / "config.json").write_text(json.dumps(cfg))
    with open(root / "results" / "quality.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=bench.V1_FIELDS)
        w.writeheader()
        for r in clean_rows():
            w.writerow({"commit": "c", "spec": "drop-v1.1", "backend": "python-fast", "experiment": "s", "policy": r["policy"],
                        "depth": r["depth"], "precision": r["precision"], "stream_seed": r["stream_seed"], "stream_sha256": "h",
                        "cap": r["cap"], "lines": r["lines"], "pieces_locked": 100, "terminal_reason": "cap_reached",
                        "source_hash": "old", "wall_seconds": 0.1})
    (root / "results" / "quality_summary.json").write_text(json.dumps({"s": summarise(clean_rows())}))
    fields = ["commit", "toolchain_id", "arch", "board_repr", "lanes", "depth", "precision", "target", "package", "speed_grade",
              "route_seed", "target_mhz", "timing_met", "reported_fmax_mhz", "status"]
    with open(root / "results" / "implementation.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for seed in (1, 2):
            w.writerow({"commit": "c", "toolchain_id": "t", "arch": 0, "board_repr": 0, "lanes": 1, "depth": 1, "precision": 0,
                        "target": "LFE5U-85F", "package": "CABGA381", "speed_grade": "6", "route_seed": seed, "target_mhz": 50.0,
                        "timing_met": "True", "reported_fmax_mhz": 60.0, "status": "routed"})
    (root / "results" / "implementation_manifest.json").write_text(json.dumps(
        {"attempts": {f"a0-bitmap-d1-p0-l1:s{s}": {"status": "routed", "timing_met": True, "rtl_hash": "r"} for s in (1, 2)}}))
    with open(root / "results" / "decisions" / "a0-bitmap-d1-p0-l1_native_1000.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["arch", "board_repr", "lanes", "depth", "precision", "state_id"])
        w.writeheader()
        for i in range(1000):
            w.writerow({"arch": 0, "board_repr": 0, "lanes": 1, "depth": 1, "precision": 0, "state_id": i})
    for i in range(20):
        d = root / "results" / "evidence" / f"E{i:02d}"
        d.mkdir(parents=True)
        (d / "summary.json").write_text(json.dumps({"job": f"E{i:02d}", "status": "passed", "commit": "c", "source_hash": "s",
                                                    "commands": [{"argv": ["make", "x"], "exit_code": 0}]}))
    return root


def test_release_membership_accepts_the_exact_expected_jobs(tmp_path):
    root = fake_tree(tmp_path)
    problems, checks = v1check.run_checks(root)
    assert problems == [], problems
    assert [(n, ok, tot) for n, ok, tot in checks] == [("quality_jobs", 8, 8), ("quality_summary_recomputed", 2, 2),
                                                       ("route_jobs", 2, 2), ("decision_files", 1, 1), ("v1_evidence", 20, 20)]


def test_release_membership_rejects_missing_duplicate_foreign_and_empty_evidence(tmp_path):
    root = fake_tree(tmp_path)
    q = root / "results" / "quality.csv"
    lines = q.read_text().splitlines()
    # a missing job is named, not counted
    q.write_text("\n".join(lines[:-1]) + "\n")
    problems, _ = v1check.run_checks(root)
    assert any("1 expected jobs missing" in p for p in problems)
    # a duplicate row and a row from another source
    q.write_text("\n".join(lines + [lines[-1], lines[1].replace(",old,", ",new,").replace(",3000,", ",3999,")]) + "\n")
    problems, _ = v1check.run_checks(root)
    assert any("duplicate rows" in p for p in problems) and any("2 source identities" in p for p in problems)
    assert any("outside the frozen protocol" in p for p in problems)
    q.write_text("\n".join(lines) + "\n")
    # a tampered committed summary is detected by recomputation
    s = json.loads((root / "results" / "quality_summary.json").read_text())
    s["s"]["policies"]["heuristic-d1-p1"]["mean_lines"] += 1
    (root / "results" / "quality_summary.json").write_text(json.dumps(s))
    problems, _ = v1check.run_checks(root)
    assert any("differs from committed" in p for p in problems)
    # route rows: a missing seed and a non-routed row claiming fmax
    impl = root / "results" / "implementation.csv"
    rows = impl.read_text().splitlines()
    impl.write_text("\n".join(rows[:-1] + [rows[-1].replace(",routed", ",killed_no_convergence")]) + "\n")
    problems, _ = v1check.run_checks(root)
    assert any("claims timing/fmax" in p for p in problems)
    # evidence with zero commands is not a pass
    (root / "results" / "evidence" / "E05" / "summary.json").write_text(json.dumps({"job": "E05", "status": "passed", "commit": "c",
                                                                                     "source_hash": "s", "commands": []}))
    problems, _ = v1check.run_checks(root)
    assert any("E05: passed with zero commands" in p for p in problems)


# Gate recorders

def run_recorder(tool, tmp_path, *args):
    env = {**os.environ, "TETROMINO_EVIDENCE_DIR": str(tmp_path)}
    return subprocess.run(["bash", str(ROOT / "scripts" / "env.sh"), "python", f"tools/{tool}", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True)


@pytest.mark.parametrize("tool", ["gate.py", "ugate.py"])
def test_recorders_reject_zero_commands(tool, tmp_path):
    r = run_recorder(tool, tmp_path, "T00")
    assert r.returncode != 0
    s = json.loads((tmp_path / "T00" / "summary.json").read_text())
    assert s["status"] == "failed" and s["commands"] == []
    assert "zero commands" in (s.get("note") or " ".join(s.get("limitations", [])))


def test_ugate_requires_nonzero_counts_and_records_identities(tmp_path):
    r = run_recorder("ugate.py", tmp_path, "T01", "--check", "tests=pytest_passed", "--", "python", "-c", "print('0 passed in 1s')")
    assert r.returncode != 0
    s = json.loads((tmp_path / "T01" / "summary.json").read_text())
    assert s["status"] == "failed" and s["checks"][0]["values"] == [0] and s["checks"][0]["ok"] is False
    r = run_recorder("ugate.py", tmp_path, "T02", "--check", "tests=pytest_passed", "--artifact", "Makefile",
                     "--", "python", "-c", "print('3 passed in 1s')", "--", "python", "-c", "print('CHECK thing 2/2')")
    assert r.returncode == 0, r.stdout + r.stderr
    s = json.loads((tmp_path / "T02" / "summary.json").read_text())
    assert s["status"] == "passed" and s["schema"] == "upgrade-evidence-v1" and len(s["commands"]) == 2
    assert len(s["source_sha256"]) == 64 and s["toolchain_id"].startswith("oss-cad-suite") and s["artifacts"][0]["exists"]
    assert len(s["commands"][0]["log_sha256"]) == 64
    assert s["commands"][1]["counts"]["check_thing"] == "2/2"
    # a failing command fails the job even with counts present
    r = run_recorder("ugate.py", tmp_path, "T03", "--", "python", "-c", "print('3 passed'); raise SystemExit(2)")
    assert r.returncode != 0 and json.loads((tmp_path / "T03" / "summary.json").read_text())["status"] == "failed"
    # blocked records run nothing
    r = run_recorder("ugate.py", tmp_path, "T04", "--blocked", "no remote configured")
    s = json.loads((tmp_path / "T04" / "summary.json").read_text())
    assert r.returncode == 0 and s["status"] == "blocked" and s["commands"] == [] and "no remote" in s["limitations"][0]


def test_ugate_count_parser_ignores_test_names_that_end_in_digits():
    """A cocotb test called random_tuples_1000 is not 1,000 passing pytest cases (U14 evidence fix)."""
    from tools.ugate import parse_counts
    text = ("tb_score.random_tuples_1000 passed\n10 passed in 0.9s\n3 passed, 1 failed in 2s\n"
            "RTL tests: 5 total, 0 failed (build 1s)\nnative: all 1000 decisions match\nCHECK thing 2/2\n")
    c = parse_counts(text)
    assert c["pytest_passed"] == 13 and c["pytest_failed"] == 1
    assert c["rtl_total"] == 5 and c["rtl_failed"] == 0 and c["native_decisions"] == 1000 and c["check_thing"] == "2/2"
