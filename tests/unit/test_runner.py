"""U02: matrix runner v2 on a fake route function — resume by complete identity, documentation
edits versus RTL edits, deliberate retries as distinct attempts, the runner lock, heartbeat and
status, and the derived summary."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from tools import measure_matrix as mm
from tools import pnr

MANIFEST = {"schema": "hardware-matrix-v2", "name": "t", "top": "stream_wrapper", "dsp_policy": "default", "route_timeout_s": 600,
            "configurations": ["a0-bitmap-d1-p0-l1"], "targets_mhz": [50, 60], "seeds": [1], "extra_jobs": []}


class Args:
    def __init__(self, **kw):
        self.manifest = "m.json"
        self.only = None
        self.retry = None
        self.skip_decisions = True
        self.no_synth = False
        self.__dict__.update(kw)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Redirect every output path to tmp and replace synthesis/route with fakes driven by a fake RTL tree."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.sv").write_text("module top; endmodule\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "design.md").write_text("# design\n")
    (tmp_path / "m.json").write_text(json.dumps(MANIFEST))
    v2 = tmp_path / "results" / "v2"
    monkeypatch.setattr(mm, "ROOT", tmp_path)
    monkeypatch.setattr(mm, "V2", v2)
    monkeypatch.setattr(mm, "LOCK", v2 / "runner.lock")
    monkeypatch.setattr(mm, "HEARTBEAT", v2 / "runner.heartbeat.json")
    monkeypatch.setattr(mm, "SUMMARY_DIR", v2 / "summary")
    monkeypatch.setattr(mm, "RAW_DECISIONS", v2 / "raw" / "decisions")
    monkeypatch.setattr(pnr, "RAW_ROUTES", v2 / "raw" / "routes")
    monkeypatch.setattr(mm, "toolchain_identity", lambda: "fake-toolchain")
    monkeypatch.setattr(mm, "source_closure_sha256", lambda: "f" * 64)
    calls = {"routes": [], "heartbeats": 0}

    def fake_synth(top, cfg, dsp_policy="default", quiet=False, **kw):
        key = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(rtl.glob("*.sv"))) + dsp_policy.encode()).hexdigest()
        return {"synth_key": key, "netlist_sha256": "n" * 64, "netlist": "build/x/netlist.json", "yosys": "fake yosys",
                "lut4": 1, "ff": 1, "ccu2c": 0, "bram": 0, "dsp": 0, "cells_total": 2}

    def fake_route(cfg, seed, freq, timeout_s, dsp_policy, top, heartbeat=None, heartbeat_s=30, retry_reason=None, synth_doc=None, quiet=False):
        plan = pnr.plan_route(cfg, seed, freq, timeout_s, dsp_policy, top, synth_doc or fake_synth(top, cfg, dsp_policy))
        key = plan["route_key"]
        prior = pnr.existing_record(key)
        if prior is not None and retry_reason is None:
            prior["reused"] = True
            return prior
        if heartbeat:
            heartbeat({"config_id": cfg.id, "seed": seed, "target_mhz": freq, "elapsed_s": 1.0, "peak_rss_mb": 10.0, "route_key": key})
            calls["heartbeats"] += 1
        n = (prior["attempt"]["number"] + 1) if prior else 1
        status = "routed_timing_met" if freq <= 50 else "routed_timing_failed"
        rec = {"schema": "route-record-v2", "route_key": key, "synth_key": plan["synth"]["synth_key"], "analysis_key": "a" * 64,
               "configuration_id": cfg.id, "params": cfg.params(), "target_mhz": float(freq), "seed": seed, "dsp_policy": dsp_policy,
               "route_timeout_s": timeout_s, "toolchain_id": "fake-toolchain", "source_sha256": "f" * 64, "netlist_sha256": "n" * 64,
               "attempt": {"number": n, "id": f"{key[:12]}-a{n}", "reason": retry_reason, "previous_status": prior["status"] if prior else None},
               "process": {"return_code": 0, "completed": True, "timed_out": False, "cancelled": False, "elapsed_s": 5.0, "peak_rss_mb": 10.0},
               "timing": {"met": status == "routed_timing_met", "reported_fmax_mhz": 55.5, "report_available": True, "worst_path": None},
               "status": status, "area": {}, "files": {}, "reused": False}
        pnr.atomic_write_json(pnr.raw_path(key, n), rec)
        calls["routes"].append((cfg.id, freq, seed, n))
        return rec

    monkeypatch.setattr(mm, "synthesize", fake_synth)
    monkeypatch.setattr(mm, "route", fake_route)
    return tmp_path, calls


def test_run_then_resume_reuses_by_identity(sandbox, capsys):
    root, calls = sandbox
    assert mm.cmd_run(Args()) == 0
    assert [c[:3] for c in calls["routes"]] == [("a0-bitmap-d1-p0-l1", 50.0, 1), ("a0-bitmap-d1-p0-l1", 60.0, 1)]
    out = capsys.readouterr().out
    assert "job 1/2 start" in out and "job 2/2 done" in out and "…" in out, out
    summary = json.loads((root / "results" / "v2" / "summary" / "matrix_t.json").read_text())
    assert summary["counts"] == {"completed": 2, "reused": 0, "successes": 1, "failures": 1, "timeouts": 0, "errors": 0}
    assert set(summary["latest_status"].values()) == {"routed_timing_met", "routed_timing_failed"}
    # second run: both records reused (the failure too — a completed failure is a result)
    assert mm.cmd_run(Args()) == 0
    assert len(calls["routes"]) == 2
    summary = json.loads((root / "results" / "v2" / "summary" / "matrix_t.json").read_text())
    assert summary["counts"]["reused"] == 2
    csv_text = (root / "results" / "v2" / "summary" / "routes_t.csv").read_text().splitlines()
    assert len(csv_text) == 3 and csv_text[1].startswith("a0-bitmap-d1-p0-l1,50.0,1,default,1,True,routed_timing_met")


def test_documentation_edit_reuses_but_rtl_edit_reroutes(sandbox):
    root, calls = sandbox
    mm.cmd_run(Args())
    (root / "docs" / "design.md").write_text("# design, revised\n")
    items = mm.plan(mm.load_manifest(root / "m.json"), None, None)
    assert [it["action"] for it in items] == ["reuse", "reuse"]
    (root / "rtl" / "top.sv").write_text("module top; wire x; endmodule\n")
    items = mm.plan(mm.load_manifest(root / "m.json"), None, None)
    assert [it["action"] for it in items] == ["run", "run"]
    mm.cmd_run(Args())
    assert len(calls["routes"]) == 4
    assert len(list((root / "results" / "v2" / "raw" / "routes").glob("*.json"))) == 4, "old records are kept, not replaced"


def test_clock_or_timeout_change_is_a_new_job(sandbox):
    root, calls = sandbox
    mm.cmd_run(Args())
    m = dict(MANIFEST, targets_mhz=[50], route_timeout_s=1800)
    (root / "m.json").write_text(json.dumps(m))
    items = mm.plan(mm.load_manifest(root / "m.json"), None, None)
    assert [it["action"] for it in items] == ["run"], "a different route budget is a different identity"
    m = dict(MANIFEST, targets_mhz=[80])
    (root / "m.json").write_text(json.dumps(m))
    assert [it["action"] for it in mm.plan(mm.load_manifest(root / "m.json"), None, None)] == ["run"]


def test_retry_needs_only_and_creates_a_distinct_attempt(sandbox):
    root, calls = sandbox
    mm.cmd_run(Args())
    with pytest.raises(SystemExit, match="--retry requires --only"):
        mm.cmd_run(Args(retry="seed exploration"))
    mm.cmd_run(Args(retry="seed exploration", only="a0-bitmap-d1-p0-l1:60:1"))
    files = sorted(p.name for p in (root / "results" / "v2" / "raw" / "routes").glob("*.json"))
    assert len(files) == 3 and any(f.endswith(".a2.json") for f in files)
    key = mm.plan(mm.load_manifest(root / "m.json"), None, None)[1]["route_key"]
    attempts = pnr.all_attempts(key)
    assert [a["attempt"]["number"] for a in attempts] == [1, 2] and attempts[1]["attempt"]["reason"] == "seed exploration"
    assert attempts[1]["attempt"]["previous_status"] == "routed_timing_failed"
    rows = (root / "results" / "v2" / "summary" / "routes_t.csv").read_text().splitlines()
    assert len(rows) == 4, "the derived CSV lists every attempt"


def test_runner_lock_prevents_duplicates_and_clears_stale_locks(sandbox, capsys):
    root, calls = sandbox
    mm.acquire_lock("m.json")
    with pytest.raises(SystemExit, match="not launching a duplicate"):
        mm.cmd_run(Args())
    mm.release_lock()
    mm.LOCK.parent.mkdir(parents=True, exist_ok=True)
    mm.LOCK.write_text(json.dumps({"pid": 2 ** 22 + 12345, "manifest": "old", "started_utc": "x"}))
    assert mm.cmd_run(Args()) == 0
    assert "removing stale lock" in capsys.readouterr().out
    assert not mm.LOCK.exists(), "lock released after the run"


def test_heartbeat_and_status(sandbox, capsys):
    root, calls = sandbox
    mm.cmd_run(Args())
    hb = json.loads(mm.HEARTBEAT.read_text())
    assert hb["phase"] == "finished" and hb["completed"] == 2 and hb["pid"] == os.getpid() and calls["heartbeats"] == 2
    mm.cmd_status(Args())
    out = capsys.readouterr().out
    assert "lock: none" in out and "phase finished" in out and "raw route records: 2" in out


def test_manifest_validation(sandbox):
    root, _ = sandbox
    (root / "bad.json").write_text(json.dumps({"schema": "hardware-matrix-v1"}))
    with pytest.raises(SystemExit, match="schema must be"):
        mm.load_manifest(root / "bad.json")
    (root / "bad.json").write_text(json.dumps(dict(MANIFEST, configurations=["a2-bitmap-d1-p0-l1"])))
    with pytest.raises(SystemExit, match="unsupported configuration"):
        mm.load_manifest(root / "bad.json")


def test_per_configuration_timeout_override_is_part_of_the_identity(sandbox):
    root, calls = sandbox
    m = dict(MANIFEST, configurations=["a0-bitmap-d1-p0-l1", "a1-cache-d1-p0-l4"], targets_mhz=[50],
             route_timeout_overrides={"a1-cache-d1-p0-l4": 1200})
    (root / "m.json").write_text(json.dumps(m))
    loaded = mm.load_manifest(root / "m.json")
    assert mm.job_timeout(loaded, "a1-cache-d1-p0-l4") == 1200 and mm.job_timeout(loaded, "a0-bitmap-d1-p0-l1") == 600
    items = mm.plan(loaded, None, None)
    keys = {it["configuration"]: it["route_key"] for it in items}
    m2 = dict(m, route_timeout_overrides={"a1-cache-d1-p0-l4": 2400})
    (root / "m.json").write_text(json.dumps(m2))
    items2 = mm.plan(mm.load_manifest(root / "m.json"), None, None)
    keys2 = {it["configuration"]: it["route_key"] for it in items2}
    assert keys["a0-bitmap-d1-p0-l1"] == keys2["a0-bitmap-d1-p0-l1"] and keys["a1-cache-d1-p0-l4"] != keys2["a1-cache-d1-p0-l4"]
    bad = dict(m, route_timeout_overrides={"nope": 5})
    (root / "m.json").write_text(json.dumps(bad))
    with pytest.raises(SystemExit):
        mm.load_manifest(root / "m.json")
    # the release manifest expands to the declared 84 unique jobs
    real = mm.load_manifest(Path(__file__).resolve().parents[2] / "benchmarks" / "hardware_v2.json")
    jobs = mm.expand_jobs(real)
    assert len(jobs) == 84 and len({mm.job_label(j) for j in jobs}) == 84
    assert sum(1 for j in jobs if j["configuration"].startswith("a1-cache-d1-p") and j["configuration"] not in ("a1-cache-d1-p0-l1",)
               and "-l1" in j["configuration"]) == 12
    assert real["dsp_policy"] == "nodsp" and mm.job_timeout(real, "a1-cache-d1-p0-l4") == 1200 and mm.job_timeout(real, "a2-cache-d1-p0-l1") == 600
