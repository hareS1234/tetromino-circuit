"""U02: v2 quality runs write one atomic record per game keyed by quality_key, resume by identity,
never touch the frozen v1 files, and summarise only rows of one source/protocol identity."""
import json
from pathlib import Path

import pytest

from tools import bench

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def proto():
    p = bench.load_protocol(ROOT / "benchmarks" / "quality_smoke_v2.json")
    assert bench.check_protocol(p) == []
    return p


def test_v2_run_records_resume_and_summary(tmp_path, proto):
    out = tmp_path / "v2"
    r = bench.run_suite_v2(proto, "smoke", out, seeds=[2000, 2001], cap=20)
    assert (r["run"], r["reused"], r["failed"]) == (6, 0, 0)
    recs = bench.v2_records(out)
    assert len(recs) == 6
    for key, d in recs.items():
        assert d["schema"] == "quality-record-v2" and d["quality_key"] == key and (out / "raw" / "quality" / f"{key}.json").is_file()
        assert d["cap"] == 20 and d["protocol_sha256"] == proto["_sha256"] and len(d["model_closure"]) == 64
        assert d["policy"]["policy"] in ("heuristic", "random_legal") and d["terminal_reason"] in ("cap_reached", "top_out")
    # same protocol/policy/streams/cap: nothing re-run
    again = bench.run_suite_v2(proto, "smoke", out, seeds=[2000, 2001], cap=20)
    assert (again["run"], again["reused"]) == (0, 6)
    # a different cap is a different identity: new records, old ones kept
    more = bench.run_suite_v2(proto, "smoke", out, seeds=[2000, 2001], cap=25)
    assert (more["run"], more["reused"]) == (6, 0)
    assert len(bench.v2_records(out)) == 12
    csv_path = bench.derive_v2_csv(out)
    assert csv_path.read_text().count("\n") == 13
    suite = dict(proto["suites"]["smoke"], cap=20, streams={"split": "validation", "seeds": [2000, 2001]})
    rows = [bench.v2_row(d) for d in bench.v2_records(out).values()]
    s = bench.summarise(rows, suite, source=bench.model_closure_sha256(), protocol_sha256=proto["_sha256"], resamples=100,
                        bootstrap_seed=1, suite_name="smoke")
    assert all(v["status"] == "complete" for v in s["policies"].values())
    assert s["policies"]["random_legal-d1-p0"]["vs_baseline"]["mean_diff"] < 0


def test_rows_from_another_model_closure_are_rejected(tmp_path, proto):
    out = tmp_path / "v2"
    bench.run_suite_v2(proto, "smoke", out, seeds=[2000], cap=10)
    rows = [bench.v2_row(d) for d in bench.v2_records(out).values()]
    rows[0]["source"] = "another-model-closure"
    suite = dict(proto["suites"]["smoke"], cap=10, streams={"split": "validation", "seeds": [2000, 2000]})
    with pytest.raises(bench.SummaryConflict):
        bench.summarise(rows, suite, source=bench.model_closure_sha256(), protocol_sha256=proto["_sha256"], resamples=10,
                        bootstrap_seed=1, suite_name="smoke")


def test_v1_files_are_untouched_by_a_v2_run(tmp_path, proto):
    before = (ROOT / "results" / "quality.csv").read_bytes(), (ROOT / "results" / "quality_summary.json").read_bytes()
    bench.run_suite_v2(proto, "smoke", tmp_path / "v2", seeds=[2002], cap=10)
    assert ((ROOT / "results" / "quality.csv").read_bytes(), (ROOT / "results" / "quality_summary.json").read_bytes()) == before


def test_v1_protocol_cannot_be_rerun_and_results_root_is_refused():
    import subprocess
    r = subprocess.run(["bash", str(ROOT / "scripts" / "env.sh"), "python", "tools/bench.py", "--suite", "precision"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode != 0 and "frozen" in r.stderr
    r = subprocess.run(["bash", str(ROOT / "scripts" / "env.sh"), "python", "tools/bench.py", "--suite", "smoke", "--config",
                        "benchmarks/quality_smoke_v2.json", "--out-root", "results"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode != 0 and "must not be the frozen" in r.stderr
