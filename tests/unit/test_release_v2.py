"""Release checks should fail closed on missing, changed, blocked, or bogus evidence."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools import check_release_v2 as rel  # noqa: E402


def write(root: Path, rel_path: str, content) -> Path:
    p = root / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (dict, list)):
        p.write_text(json.dumps(content, indent=1) + "\n")
    else:
        p.write_text(content)
    return p


def good_evidence(job: str) -> dict:
    return {"schema": "upgrade-evidence-v1", "job": job, "status": "passed",
            "commands": [{"argv": ["make", "x"], "exit_code": 0, "elapsed_s": 1.0, "log": f"results/evidence/{job}/cmd00.log",
                          "counts": {"pytest_passed": 12}}],
            "checks": [{"name": "tests", "ok": True}], "artifacts": [], "limitations": [], "note": None}


def manifest(**over) -> dict:
    m = {"schema": "release-manifest-v2", "tag": "vX-test", "frozen_inputs": [], "required_artifacts": [], "evidence": {},
         "expensive_measurements": {}, "platforms": [], "gates": []}
    m.update(over)
    return m


@pytest.fixture
def tree(tmp_path):
    write(tmp_path, "docs/release_v2.md", "| `darwin-arm64` | Mac | **blocked** | nothing yet |\n| remote-ci | CI | blocked |\n")
    write(tmp_path, "docs/upgrade_progress.md", "| U00 | passed |\n| U20 | darwin-arm64 blocked; remote-ci blocked |\n")
    return tmp_path


def test_frozen_input_hash_and_presence(tree):
    p = write(tree, "benchmarks/x.json", '{"a": 1}\n')
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    m = manifest(frozen_inputs=[{"path": "benchmarks/x.json", "sha256": sha}, {"path": "benchmarks/missing.json", "sha256": sha}])
    probs = rel.check_frozen_inputs(tree, m)
    assert probs == ["frozen input missing: benchmarks/missing.json"]
    p.write_text('{"a": 2}\n')
    probs = rel.check_frozen_inputs(tree, m)
    assert any("frozen input changed: benchmarks/x.json" in x for x in probs)


def test_required_artifacts_must_exist_and_be_nonempty(tree):
    write(tree, "results/ok.json", "{}")
    write(tree, "results/empty.json", "")
    m = manifest(required_artifacts=["results/ok.json", "results/empty.json", "results/absent.json"])
    probs = rel.check_artifacts(tree, m)
    assert probs == ["artifact empty: results/empty.json", "artifact missing: results/absent.json"]


def test_evidence_failure_modes(tree):
    m = manifest(evidence={"U00": {"status": ["passed"]}, "U01": {"status": ["passed"]}, "U02": {"status": ["passed"]},
                           "U03": {"status": ["passed"]}, "U04": {"status": ["passed"]}, "U20": {"status": ["passed", "blocked"]}})
    ev = good_evidence("U00")
    write(tree, "results/evidence/U00/summary.json", ev)
    write(tree, "results/evidence/U00/cmd00.log", "12 passed\n")
    # U01: zero commands; U02: failed command; U03: passed without any count; U04: missing; U20: blocked with a reason
    e1 = good_evidence("U01"); e1["commands"] = []
    write(tree, "results/evidence/U01/summary.json", e1)
    e2 = good_evidence("U02"); e2["commands"][0]["exit_code"] = 2
    write(tree, "results/evidence/U02/summary.json", e2)
    write(tree, "results/evidence/U02/cmd00.log", "boom\n")
    e3 = good_evidence("U03"); e3["commands"][0]["counts"] = {"pytest_passed": 0}; e3["checks"] = []
    write(tree, "results/evidence/U03/summary.json", e3)
    write(tree, "results/evidence/U03/cmd00.log", "0 passed\n")
    e20 = good_evidence("U20"); e20["status"] = "blocked"; e20["limitations"] = ["blocked: no Mac"]
    write(tree, "results/evidence/U20/summary.json", e20)
    write(tree, "results/evidence/U20/cmd00.log", "12 passed\n")
    probs, statuses = rel.check_evidence(tree, m)
    assert statuses == {"U00": "passed", "U01": "passed", "U02": "passed", "U03": "passed", "U04": "missing", "U20": "blocked"}
    assert "evidence U01: zero commands" in probs
    assert any(p.startswith("evidence U02: command") and "exited 2" in p for p in probs)
    assert "evidence U03: passed without a nonzero test/check count in any command" in probs
    assert "evidence U04: no summary.json" in probs
    assert not [p for p in probs if p.startswith("evidence U00") or p.startswith("evidence U20")]


def test_evidence_status_must_be_declared_status(tree):
    m = manifest(evidence={"U05": {"status": ["passed"]}})
    e = good_evidence("U05"); e["status"] = "blocked"; e["limitations"] = ["blocked: x"]
    write(tree, "results/evidence/U05/summary.json", e)
    write(tree, "results/evidence/U05/cmd00.log", "x\n")
    probs, _ = rel.check_evidence(tree, m)
    assert "evidence U05: status 'blocked' not in ['passed']" in probs


def test_platforms_blocked_is_not_satisfied_and_needs_reason_and_row(tree):
    m = manifest(platforms=[
        {"family": "darwin-arm64", "status": "blocked", "reason": "no Mac"},
        {"family": "linux-arm64", "status": "blocked"},                     # no reason, no row
        {"family": "remote-ci", "status": "blocked", "reason": "no remote"},
    ])
    probs, blocked = rel.check_platforms(tree, m)
    assert blocked == ["darwin-arm64", "linux-arm64", "remote-ci"]
    assert "platform linux-arm64: blocked without a reason" in probs
    assert "platform linux-arm64: docs/release_v2.md has no row marking it blocked" in probs
    assert not [p for p in probs if "darwin-arm64" in p or "remote-ci" in p]


def test_platform_executed_requires_a_complete_record(tree):
    m = manifest(platforms=[{"family": "linux-x64", "status": "executed", "evidence": "results/evidence/U20/fresh_clone_linux-x64.json"}])
    probs, blocked = rel.check_platforms(tree, m)
    assert blocked == [] and any("executed without an evidence record" in p for p in probs)
    rec = {"schema": "fresh-clone-check-v2", "family": "linux-x64", "ok": True,
           "host": {"os": "Linux", "cpu": "x", "python": "3.11.15", "compiler": "c++ 13", "tools": {"yosys": "Yosys 0.68"}},
           "steps": [{"name": "bootstrap", "exit_code": 0}, {"name": "smoke", "exit_code": 0}]}
    write(tree, "results/evidence/U20/fresh_clone_linux-x64.json", rec)
    assert rel.check_platforms(tree, m) == ([], [])
    rec["steps"][1]["exit_code"] = 1
    write(tree, "results/evidence/U20/fresh_clone_linux-x64.json", rec)
    probs, _ = rel.check_platforms(tree, m)
    assert any("does not show every step passing" in p for p in probs)
    rec["steps"][1]["exit_code"] = 0
    rec["host"]["tools"] = None
    write(tree, "results/evidence/U20/fresh_clone_linux-x64.json", rec)
    probs, _ = rel.check_platforms(tree, m)
    assert "platform linux-x64: host fact 'tools' not recorded" in probs


def test_remote_ci_record_needs_url_and_sha(tree):
    m = manifest(platforms=[{"family": "remote-ci", "status": "executed", "evidence": "results/evidence/U20/remote_ci.json"}])
    write(tree, "results/evidence/U20/remote_ci.json", {"schema": "remote-ci-run-v1", "url": "", "sha": "abc", "ok": True})
    probs, _ = rel.check_platforms(tree, m)
    assert any("lacks a successful run url/sha" in p for p in probs)
    write(tree, "results/evidence/U20/remote_ci.json", {"schema": "remote-ci-run-v1", "url": "https://example/run/1", "sha": "abc", "ok": True})
    assert rel.check_platforms(tree, m) == ([], [])


def test_progress_rows_and_blocked_mentions(tree):
    m = manifest(evidence={"U00": {}, "U07": {}}, platforms=[{"family": "darwin-arm64", "status": "blocked", "reason": "r"},
                                                              {"family": "linux-arm64", "status": "blocked", "reason": "r"}])
    probs = rel.check_progress_rows(tree, m)
    assert "docs/upgrade_progress.md has no row for U07" in probs
    assert "docs/upgrade_progress.md does not record linux-arm64 as blocked" in probs
    assert not [p for p in probs if "darwin-arm64" in p or "U00" in p]


def test_tag_must_not_exist_while_blocked(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    m = manifest(tag="vX-test")
    assert rel.check_tag(tmp_path, m, ["darwin-arm64"], []) == []          # tag absent: fine
    subprocess.run(["git", "-C", str(tmp_path), "tag", "vX-test"], check=True)
    assert rel.check_tag(tmp_path, m, ["darwin-arm64"], []) == ["tag vX-test exists although the release is not releasable"]
    assert rel.check_tag(tmp_path, m, [], ["some problem"]) == ["tag vX-test exists although the release is not releasable"]
    assert rel.check_tag(tmp_path, m, [], []) == []


def test_real_manifest_structure():
    m = rel.load_manifest(ROOT)
    assert [f"U{i:02d}" for i in range(21)] == list(m["evidence"])
    assert m["evidence"]["U20"]["status"] == ["passed", "blocked"]
    for pf in m["platforms"]:
        assert pf["status"] in ("executed", "blocked")
        if pf["status"] == "blocked":
            assert pf["reason"]
    assert {pf["family"] for pf in m["platforms"] if pf["status"] == "blocked"} <= {"darwin-arm64", "remote-ci"}
    for pf in m["platforms"]:
        if pf["status"] == "executed":
            assert pf.get("evidence"), f"{pf['family']}: executed without an evidence path"
    for fi in m["frozen_inputs"]:
        assert (ROOT / fi["path"]).is_file(), fi["path"]
        assert hashlib.sha256((ROOT / fi["path"]).read_bytes()).hexdigest() == fi["sha256"], f"{fi['path']} changed since the manifest was written"
    assert "results/v2/summary/matrix_hardware-v2.json" in m["required_artifacts"]
    assert m["expensive_measurements"]["hardware"]["jobs"] == 84


def test_structural_run_verdict_matches_exit_code():
    """The real manifest, structural checks only: exactly one verdict line, and exit 0 iff it says releasable."""
    r = subprocess.run([sys.executable, "tools/check_release_v2.py", "--no-subchecks"], cwd=ROOT, capture_output=True, text=True)
    out = r.stdout
    assert "CHECK release_v2_platforms_executed" in out
    verdicts = [ln for ln in out.splitlines() if ln.startswith("check-release-v2:")]
    assert len(verdicts) == 1
    if "OK: releasable" in verdicts[0]:
        assert r.returncode == 0 and "(blocked: none)" in out
    else:
        assert r.returncode != 0 and ("NOT RELEASABLE" in verdicts[0] or "FAIL" in verdicts[0])


def test_expect_blocked_returns_zero_only_for_the_blocked_only_outcome():
    r = subprocess.run([sys.executable, "tools/check_release_v2.py", "--no-subchecks", "--expect-blocked"], cwd=ROOT, capture_output=True, text=True)
    if "NOT RELEASABLE" in r.stdout:
        assert r.returncode == 0 and "CHECK release_v2_executed_checks_passed 1/1" in r.stdout
    else:
        assert r.returncode != 0          # problems remain, or nothing is blocked (then the flag itself is refused)


def test_release_manifest_is_not_part_of_the_source_closure(tmp_path):
    """Editing the release scope (blocked -> executed) must not change the closure that relates the measurements."""
    from tools.identity import SOURCE_EXCLUDE, source_closure_sha256
    assert "benchmarks/release_v2.json" in SOURCE_EXCLUDE
    (tmp_path / "benchmarks").mkdir()
    (tmp_path / "benchmarks" / "hardware.json").write_text("{}")
    (tmp_path / "benchmarks" / "release_v2.json").write_text('{"a": 1}')
    before = source_closure_sha256(tmp_path)
    (tmp_path / "benchmarks" / "release_v2.json").write_text('{"a": 2}')
    assert source_closure_sha256(tmp_path) == before
    (tmp_path / "benchmarks" / "hardware.json").write_text('{"changed": true}')
    assert source_closure_sha256(tmp_path) != before
