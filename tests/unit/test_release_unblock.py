"""U20: the maintainer's unblocking helper refuses to run ahead of its evidence and edits only the scope files."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_helper(root: Path):
    spec = importlib.util.spec_from_file_location("release_unblock", root / "scripts" / "release_unblock.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_tree(tmp_path: Path) -> Path:
    for d in ("docs", "benchmarks", "toolchains", "scripts"):
        shutil.copytree(ROOT / d, tmp_path / d, ignore=shutil.ignore_patterns("__pycache__", "history", "streams_v2", "states"))
    (tmp_path / "results" / "evidence" / "U20").mkdir(parents=True)
    return tmp_path


def test_helper_refuses_without_evidence_and_then_marks_executed(tmp_path, capsys):
    root = make_tree(tmp_path)
    h = load_helper(root)
    assert h.mark_executed() == 1                                    # no records yet
    assert h.verify_lock() == 1                                      # not enrolled yet
    assert h.ci_record("https://example.org/not-github", "abc1234") == 1
    lock = json.loads((root / "toolchains/oss_cad_suite.lock.json").read_text())
    lock["assets"]["darwin-arm64"].update(sha256="b" * 64, status="enrolled-unreviewed")
    (root / "toolchains/oss_cad_suite.lock.json").write_text(json.dumps(lock))
    assert h.verify_lock() == 0
    assert json.loads((root / "toolchains/oss_cad_suite.lock.json").read_text())["assets"]["darwin-arm64"]["status"] == "verified"
    assert "verified (enrolled on the maintainer's Mac, U20)" in (root / "docs/toolchain.md").read_text()
    assert h.ci_record("https://github.com/o/r/actions/runs/42", "deadbeef1234") == 0
    (root / "results/evidence/U20/fresh_clone_darwin-arm64.json").write_text(json.dumps(
        {"schema": "fresh-clone-check-v2", "family": "darwin-arm64", "ok": False, "steps": []}))
    assert h.mark_executed() == 1                                    # a failed Mac run is not evidence
    (root / "results/evidence/U20/fresh_clone_darwin-arm64.json").write_text(json.dumps(
        {"schema": "fresh-clone-check-v2", "family": "darwin-arm64", "ok": True, "steps": [{"name": "bootstrap", "exit_code": 0}]}))
    assert h.mark_executed() == 0
    m = json.loads((root / "benchmarks/release_v2.json").read_text())
    assert all(p["status"] == "executed" for p in m["platforms"]) and all(g["status"] == "executed" for g in m["gates"])
    assert all("reason" not in p for p in m["platforms"])
    rel = (root / "docs/release_v2.md").read_text()
    assert "| `remote-ci` (`.github/workflows/ci.yml`) | GitHub Actions at the release commit | **executed** |" in rel
    assert "deadbeef1234" in rel and "blocked" not in rel.split("## Release readiness")[1].split("## Where the validator")[0]
    assert "| U20 Mac + remote release | passed (" in (root / "docs/upgrade_progress.md").read_text()
    # the manifest is not part of the source closure, so this edit changes no measurement identity
    sys.path.insert(0, str(ROOT))
    from tools.identity import SOURCE_EXCLUDE
    assert "benchmarks/release_v2.json" in SOURCE_EXCLUDE
