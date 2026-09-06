#!/usr/bin/env python3
"""Audit the v2 release manifest without manufacturing missing evidence.

The checker re-plans expensive identities, verifies U00–U20 records, and runs the exact-membership
subchecks. A blocked gate remains unsatisfied. ``--expect-blocked`` records the honest U20 local
result and cannot produce a release verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ugate import count_ok  # noqa: E402

MANIFEST_SCHEMA = "release-manifest-v2"
EVIDENCE_SCHEMA = "upgrade-evidence-v1"


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_manifest(root: Path, rel: str = "benchmarks/release_v2.json") -> dict:
    doc = json.loads((root / rel).read_text())
    if doc.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"{rel}: schema {doc.get('schema')!r} is not {MANIFEST_SCHEMA}")
    doc["_path"] = rel
    return doc


# Pure checks (no subprocesses; unit tests use temporary trees)

def check_frozen_inputs(root: Path, m: dict) -> list[str]:
    problems = []
    for item in m.get("frozen_inputs", []):
        p = root / item["path"]
        if not p.is_file():
            problems.append(f"frozen input missing: {item['path']}")
            continue
        got = sha256_file(p)
        if got != item["sha256"]:
            problems.append(f"frozen input changed: {item['path']} sha256 {got[:12]} != declared {item['sha256'][:12]}")
    return problems


def check_artifacts(root: Path, m: dict) -> list[str]:
    problems = []
    for rel in m.get("required_artifacts", []):
        p = root / rel
        if not p.is_file():
            problems.append(f"artifact missing: {rel}")
        elif p.stat().st_size == 0:
            problems.append(f"artifact empty: {rel}")
    return problems


def check_evidence(root: Path, m: dict) -> tuple[list[str], dict]:
    """Every declared job has a record with real commands; statuses as declared (passed / blocked)."""
    problems, statuses = [], {}
    ev = m.get("evidence", {})
    for job, want in ev.items():
        p = root / "results" / "evidence" / job / "summary.json"
        if not p.is_file():
            if want.get("self"):          # the record this validator's own gate writes: absent while that gate runs
                statuses[job] = "pending (written by this gate)"
                continue
            problems.append(f"evidence {job}: no summary.json")
            statuses[job] = "missing"
            continue
        try:
            d = json.loads(p.read_text())
        except json.JSONDecodeError as exc:
            problems.append(f"evidence {job}: corrupt summary.json ({exc})")
            statuses[job] = "corrupt"
            continue
        st = d.get("status")
        statuses[job] = st
        if d.get("schema") != EVIDENCE_SCHEMA:
            problems.append(f"evidence {job}: schema {d.get('schema')!r}")
        if d.get("job") != job:
            problems.append(f"evidence {job}: record is for job {d.get('job')!r}")
        allowed = tuple(want.get("status", ["passed"]))
        if st not in allowed:
            problems.append(f"evidence {job}: status {st!r} not in {list(allowed)}")
        cmds = d.get("commands") or []
        if not cmds:
            problems.append(f"evidence {job}: zero commands")
        for c in cmds:
            if c.get("exit_code") != 0:
                problems.append(f"evidence {job}: command {' '.join(c.get('argv', []))[:60]!r} exited {c.get('exit_code')}")
            log = c.get("log")
            digest = c.get("log_sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                problems.append(f"evidence {job}: command log has no valid SHA-256 digest")
            if log:
                log_path = Path(log)
                if not log_path.is_absolute():
                    log_path = root / log_path
                if log_path.is_file() and digest and sha256_file(log_path) != digest:
                    problems.append(f"evidence {job}: log {log} differs from its recorded SHA-256")
            else:
                problems.append(f"evidence {job}: command has no log path")
        checks = d.get("checks") or []
        if checks and not all(ch.get("ok") for ch in checks if isinstance(ch, dict)):
            problems.append(f"evidence {job}: a named check is not ok")
        counted = any(count_ok(v) for c in cmds for v in (c.get("counts") or {}).values())
        if st == "passed" and not counted:
            problems.append(f"evidence {job}: passed without a nonzero test/check count in any command")
        if st == "blocked" and not (d.get("limitations") or d.get("note")):
            problems.append(f"evidence {job}: blocked without a reason")
    return problems, statuses


def check_platforms(root: Path, m: dict) -> tuple[list[str], list[str]]:
    """Executed platforms need a real fresh-clone record; blocked ones need a reason and a visible row."""
    problems, blocked = [], []
    table = (root / "docs" / "release_v2.md").read_text() if (root / "docs" / "release_v2.md").is_file() else ""
    for pf in m.get("platforms", []):
        fam, st = pf["family"], pf["status"]
        if st == "executed":
            rel = pf.get("evidence")
            p = root / rel if rel else None
            if p is None or not p.is_file():
                problems.append(f"platform {fam}: executed without an evidence record ({rel})")
                continue
            try:
                d = json.loads(p.read_text())
            except json.JSONDecodeError as exc:
                problems.append(f"platform {fam}: corrupt record ({exc})")
                continue
            if d.get("schema") == "remote-ci-run-v1":
                if not (d.get("url") and d.get("sha") and d.get("ok") is True):
                    problems.append(f"platform {fam}: remote CI record lacks a successful run url/sha")
                continue
            if d.get("schema") != "fresh-clone-check-v2" or d.get("family") != fam:
                problems.append(f"platform {fam}: record schema/family {d.get('schema')}/{d.get('family')}")
            steps = d.get("steps") or []
            if not steps or not d.get("ok") or any(s.get("exit_code") != 0 for s in steps):
                problems.append(f"platform {fam}: fresh-clone record does not show every step passing")
            for key in ("os", "cpu", "python", "compiler", "tools"):
                if not d.get("host", {}).get(key):
                    problems.append(f"platform {fam}: host fact '{key}' not recorded")
        elif st == "blocked":
            blocked.append(fam)
            if not pf.get("reason"):
                problems.append(f"platform {fam}: blocked without a reason")
            row = [ln for ln in table.splitlines() if fam in ln and "blocked" in ln.lower()]
            if not row:
                problems.append(f"platform {fam}: docs/release_v2.md has no row marking it blocked")
        else:
            problems.append(f"platform {fam}: unknown status {st!r}")
    return problems, blocked


def check_progress_rows(root: Path, m: dict) -> list[str]:
    """docs/upgrade_progress.md names every job; blocked items are called blocked there, never done."""
    problems = []
    p = root / "docs" / "upgrade_progress.md"
    if not p.is_file():
        return ["docs/upgrade_progress.md missing"]
    text = p.read_text()
    for job in m.get("evidence", {}):
        if not re.search(rf"^\|\s*{job}\b", text, re.M):
            problems.append(f"docs/upgrade_progress.md has no row for {job}")
    for pf in m.get("platforms", []):
        if pf["status"] == "blocked" and not re.search(rf"{re.escape(pf['family'])}.*blocked|blocked.*{re.escape(pf['family'])}", text, re.I):
            problems.append(f"docs/upgrade_progress.md does not record {pf['family']} as blocked")
    return problems


def check_tag(root: Path, m: dict, blocked: list[str], problems_so_far: list[str]) -> list[str]:
    tag = m.get("tag")
    if not tag:
        return []
    out = subprocess.run(["git", "-C", str(root), "tag", "-l", tag], capture_output=True, text=True)
    exists = out.returncode == 0 and tag in out.stdout.split()
    if exists and (blocked or problems_so_far):
        return [f"tag {tag} exists although the release is not releasable"]
    return []


# Identity checks against live sources

def check_identities(root: Path, m: dict) -> list[str]:
    problems = []
    from tools.identity import model_closure_sha256, native_identity, source_closure_sha256  # noqa: E402
    live_source = source_closure_sha256(root)
    # hardware matrix summary: its manifest hash must be the frozen manifest, its route keys are re-planned by
    # check_hardware_v2 (sub-check); here we relate the summary to the declared manifest and record the source
    hw = m.get("expensive_measurements", {}).get("hardware")
    if hw:
        s = root / hw["summary"]
        if not s.is_file():
            problems.append(f"hardware summary missing: {hw['summary']}")
        else:
            d = json.loads(s.read_text())
            if d.get("manifest_sha256") != sha256_file(root / hw["manifest"]):
                problems.append("hardware summary was produced from another manifest than the frozen one")
            n_expected = len(d.get("expected_jobs", []))
            if n_expected != hw.get("jobs"):
                problems.append(f"hardware summary declares {n_expected} jobs, release manifest expects {hw.get('jobs')}")
            if d.get("counts", {}).get("errors", 0):
                problems.append(f"hardware summary records {d['counts']['errors']} tool errors")
    q = m.get("expensive_measurements", {}).get("quality")
    if q:
        s = root / q["summary"]
        if not s.is_file():
            problems.append(f"quality summary missing: {q['summary']}")
        else:
            d = json.loads(s.read_text())
            from tools.bench import load_protocol  # noqa: E402  (canonical-JSON protocol hash, as bench.py records it)
            if d.get("protocol_sha256") != load_protocol(root / q["protocol"])["_sha256"]:
                problems.append("quality summary was produced from another protocol than the frozen one")
            if d.get("model_closure") != model_closure_sha256(root):
                problems.append("quality summary's model closure differs from the checked-out model/ (policy source changed since the study)")
            if d.get("n_streams") != q.get("streams") or d.get("cap") != q.get("cap"):
                problems.append(f"quality summary scope {d.get('n_streams')} streams / cap {d.get('cap')} != declared {q.get('streams')} / {q.get('cap')}")
            fz = root / q["freeze"]
            if fz.is_file():
                f = json.loads(fz.read_text())
                if f.get("protocol_sha256") != d.get("protocol_sha256") or f.get("model_closure") != d.get("model_closure"):
                    problems.append("freeze record and quality summary disagree on protocol/model identity")
            else:
                problems.append(f"freeze record missing: {q['freeze']}")
    tr = m.get("expensive_measurements", {}).get("traces")
    if tr:
        from tools.build_native import NATIVE_FLAGS  # noqa: E402
        from tools.trace_a2 import A2, PUBLIC  # noqa: E402
        core_key = native_identity(A2.params(), "rtl/files_core.f", root=root, driver="sim/trace_main.cpp", top="tetris_core",
                                   flags=NATIVE_FLAGS + PUBLIC)["native_key"]
        pipe_key = native_identity({}, "rtl/files_candidate_pipe.f", root=root, driver="sim/pipe_trace_main.cpp", top="candidate_pipe",
                                   flags=NATIVE_FLAGS + PUBLIC)["native_key"]
        for rel in tr:
            p = root / rel
            if not p.is_file():
                problems.append(f"trace missing: {rel}")
                continue
            d = json.loads(p.read_text())
            want = pipe_key if d.get("top") == "candidate_pipe" else core_key
            if d.get("native_key") != want:
                problems.append(f"trace {rel}: native key {str(d.get('native_key'))[:12]} is not the live harness identity {want[:12]} (RTL or harness changed since the trace)")
    # Broad source closure is informative. The precise identities above decide validity.
    notes = []
    for label, rel in (("hardware", (hw or {}).get("summary")), ("quality", (q or {}).get("summary"))):
        if rel and (root / rel).is_file():
            rec = json.loads((root / rel).read_text()).get("source_sha256")
            if rec and rec != live_source:
                notes.append(f"{label} summary source closure {rec[:12]} != live {live_source[:12]} (measurement identities checked above)")
    return problems + [f"note: {n}" for n in notes]


# Exact-membership subchecks

SUBCHECKS = [
    ("v1_release", [sys.executable, "tools/check_release.py"]),
    ("generated_geometry", [sys.executable, "tools/gen_shapes.py", "--check"]),
    ("streams_v1", [sys.executable, "tools/make_streams.py", "--check"]),
    ("streams_v2", [sys.executable, "tools/streams_v2.py", "check"]),
    ("hardware_v2", [sys.executable, "tools/check_hardware_v2.py", "--manifest", "benchmarks/hardware_v2.json"]),
    ("quality_v2", [sys.executable, "tools/analyze_quality_v2.py", "--config", "benchmarks/config_v2.json", "--suite", "bag50k", "--check"]),
    ("traces", [sys.executable, "tools/check_trace.py"]),
    ("viewer", [sys.executable, "tools/check_viewer.py"]),
    ("report_v1", [sys.executable, "tools/write_report.py", "--check"]),
    ("report_v2", [sys.executable, "tools/write_report_v2.py", "--check"]),
    ("links", [sys.executable, "tools/check_links.py"]),
    ("claims", [sys.executable, "tools/check_claims.py"]),
    ("ci_workflow", [sys.executable, "tools/ci_local.py", "--validate"]),
    ("ci_workflow_release", [sys.executable, "tools/ci_local.py", "--workflow", "release-check.yml", "--validate"]),
]


def run_subchecks(root: Path) -> tuple[list[str], list[str]]:
    problems, lines = [], []
    for name, cmd in SUBCHECKS:
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip().splitlines()
        checks = [ln for ln in out if ln.startswith("CHECK ")]
        lines.append(f"subcheck {name}: exit {r.returncode}" + (f"; {'; '.join(checks)}" if checks else ""))
        if r.returncode != 0:
            detail = [ln.strip() for ln in out if ln.strip().startswith("- ")] or out[-2:]
            problems.append(f"sub-check {name} failed: {'; '.join(d[:120] for d in detail[:6])}")
    return problems, lines


def git_facts(root: Path) -> dict:
    def g(*a):
        r = subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    head = g("rev-parse", "HEAD")
    status = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True)
    dirty = status.stdout.rstrip("\n") if status.returncode == 0 else ""
    return {"head": head, "dirty_tracked": [ln[3:] for ln in (dirty or "").splitlines()], "tags": (g("tag") or "").split()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="benchmarks/release_v2.json")
    ap.add_argument("--no-subchecks", action="store_true", help="skip the sub-validators (fast structural check)")
    ap.add_argument("--json", default=None, help="write the outcome record here")
    ap.add_argument("--expect-blocked", action="store_true",
                    help="for the U20 evidence record: exit 0 when every executed check passed and the only remaining items are the "
                         "declared blocked ones (the NOT RELEASABLE verdict is still printed and recorded); never use for a release decision")
    args = ap.parse_args()
    root = ROOT
    m = load_manifest(root, args.manifest)
    problems = []
    problems += check_frozen_inputs(root, m)
    problems += check_artifacts(root, m)
    ev_problems, statuses = check_evidence(root, m)
    problems += ev_problems
    pf_problems, blocked = check_platforms(root, m)
    problems += pf_problems
    problems += check_progress_rows(root, m)
    id_notes = check_identities(root, m)
    notes = [n for n in id_notes if n.startswith("note: ")]
    problems += [n for n in id_notes if not n.startswith("note: ")]
    sub_lines = []
    if not args.no_subchecks:
        sub_problems, sub_lines = run_subchecks(root)
        problems += sub_problems
    blocked_gates = [g["name"] for g in m.get("gates", []) if g.get("status") == "blocked"]
    problems += check_tag(root, m, blocked + blocked_gates, problems)
    git = git_facts(root)
    n_art = len(m.get("required_artifacts", []))
    print(f"CHECK release_v2_frozen_inputs {len(m.get('frozen_inputs', [])) - sum(p.startswith('frozen input') for p in problems)}/{len(m.get('frozen_inputs', []))}")
    print(f"CHECK release_v2_artifacts {n_art - sum(p.startswith('artifact ') for p in problems)}/{n_art}")
    n_ev = len(m.get("evidence", {}))
    print(f"CHECK release_v2_evidence {sum(1 for j, s in statuses.items() if s in m['evidence'][j].get('status', ['passed']))}/{n_ev}")
    n_pf = len(m.get("platforms", []))
    print(f"CHECK release_v2_platforms_executed {sum(1 for pf in m.get('platforms', []) if pf['status'] == 'executed')}/{n_pf} (blocked: {', '.join(blocked) or 'none'})")
    for ln in sub_lines:
        print("  ", ln)
    for n in notes:
        print("  ", n)
    for p in problems:
        print("  -", p)
    record = {"schema": "release-check-v2", "manifest": args.manifest, "manifest_sha256": sha256_file(root / args.manifest),
              "git": git, "evidence_statuses": statuses, "blocked_platforms": blocked, "blocked_gates": blocked_gates,
              "problems": problems, "notes": notes, "subchecks": sub_lines, "releasable": not problems and not blocked and not blocked_gates}
    if args.json:
        out = root / args.json
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record, indent=1) + "\n")
    if git["dirty_tracked"]:
        print(f"   note: working tree has {len(git['dirty_tracked'])} modified tracked file(s); validate a clean checkout for the release")
    if problems:
        print(f"check-release-v2: FAIL ({len(problems)} problem(s))")
        return 1
    if blocked or blocked_gates:
        print(f"check-release-v2: NOT RELEASABLE (blocked: {', '.join(blocked + blocked_gates)}); every executed check passed, "
              f"tag {m.get('tag')} must not be created until the blocked items are executed and recorded")
        if args.expect_blocked:
            print("CHECK release_v2_executed_checks_passed 1/1 (blocked items recorded, not satisfied)")
            return 0
        return 1
    if args.expect_blocked:
        print("check-release-v2: --expect-blocked was given but nothing is blocked; run without it for the release decision")
        return 1
    print(f"check-release-v2: OK: releasable at {git['head']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
