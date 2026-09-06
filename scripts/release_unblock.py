#!/usr/bin/env python3
"""Record the two U20 items that had to be executed by the maintainer (docs/release_v2.md, "Executing the blocked items").

    python3 scripts/release_unblock.py verify-lock      # after `bash scripts/bootstrap.sh --enroll` on the Mac: mark darwin-arm64 verified
    python3 scripts/release_unblock.py ci-record URL SHA # write results/evidence/U20/remote_ci.json for a successful `checks` run
    python3 scripts/release_unblock.py mark-executed     # flip the two platform rows + gates to executed once both records exist
    python3 scripts/release_unblock.py status            # show what is still blocked

Standard library only (runs with the system python3, before any venv exists).  Each command refuses to
proceed when its precondition is missing, and edits only the release manifest, the lock status, and the
two documents that state the platform status.  It never creates or modifies a measurement.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks" / "release_v2.json"
LOCK = ROOT / "toolchains" / "oss_cad_suite.lock.json"
EVIDENCE = {"darwin-arm64": "results/evidence/U20/fresh_clone_darwin-arm64.json", "remote-ci": "results/evidence/U20/remote_ci.json"}


def load(p: pathlib.Path) -> dict:
    return json.loads(p.read_text())


def save(p: pathlib.Path, doc: dict) -> None:
    p.write_text(json.dumps(doc, indent=1) + "\n")


def verify_lock() -> int:
    d = load(LOCK)
    e = d["assets"]["darwin-arm64"]
    if not e.get("sha256"):
        print("darwin-arm64 is not enrolled yet: run  bash scripts/bootstrap.sh --enroll  on the Mac first")
        return 1
    e["status"] = "verified"
    save(LOCK, d)
    t = ROOT / "docs" / "toolchain.md"
    t.write_text(t.read_text().replace(
        "| Darwin-arm64 (Apple silicon) | darwin-arm64 | `oss-cad-suite-darwin-arm64-20260904.tgz` | unenrolled |",
        "| Darwin-arm64 (Apple silicon) | darwin-arm64 | `oss-cad-suite-darwin-arm64-20260904.tgz` | verified (enrolled on the maintainer's Mac, U20) |"))
    print(f"lock: darwin-arm64 = verified, sha256 {e['sha256'][:16]}…  (commit toolchains/oss_cad_suite.lock.json, docs/toolchain.md, results/host/Darwin-arm64.json)")
    return 0


def ci_record(url: str, sha: str) -> int:
    if not url.startswith("https://github.com/") or "/actions/runs/" not in url:
        print("URL must be the GitHub Actions run page, e.g. https://github.com/<owner>/<repo>/actions/runs/<id>")
        return 1
    if len(sha) < 7:
        print("SHA must be the commit the run checked out (at least 7 hex characters)")
        return 1
    out = ROOT / EVIDENCE["remote-ci"]
    out.parent.mkdir(parents=True, exist_ok=True)
    save(out, {"schema": "remote-ci-run-v1", "url": url, "sha": sha, "ok": True, "jobs": ["fast", "hdl"], "conclusion": "success",
               "workflow": ".github/workflows/ci.yml", "recorded_by": "maintainer"})
    print(f"wrote {out.relative_to(ROOT)} (commit it)")
    return 0


def mark_executed() -> int:
    missing = [rel for rel in EVIDENCE.values() if not (ROOT / rel).is_file()]
    if missing:
        print("cannot mark executed, these records do not exist yet:", ", ".join(missing))
        return 1
    ci = load(ROOT / EVIDENCE["remote-ci"])
    mac = load(ROOT / EVIDENCE["darwin-arm64"])
    if not mac.get("ok") or mac.get("family") != "darwin-arm64":
        print("the Mac fresh-clone record does not show every step passing (ok != true) — fix and re-run scripts/fresh_clone_check.sh")
        return 1
    m = load(MANIFEST)
    for pf in m["platforms"]:
        if pf["family"] in EVIDENCE:
            pf["status"] = "executed"
            pf["evidence"] = EVIDENCE[pf["family"]]
            pf.pop("reason", None)
    for g in m["gates"]:
        if g["name"] == "mac-reproduction":
            g.update(status="executed", evidence=EVIDENCE["darwin-arm64"]); g.pop("reason", None)
        if g["name"] == "remote-ci-run":
            g.update(status="executed", evidence=EVIDENCE["remote-ci"]); g.pop("reason", None)
    save(MANIFEST, m)
    d = ROOT / "docs" / "release_v2.md"
    lines = d.read_text().splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("| `darwin-arm64` |"):
            lines[i] = ("| `darwin-arm64` | the maintainer's Apple-silicon Mac (demonstration machine) | **executed** | "
                        "`bash scripts/bootstrap.sh --enroll`, then `bash scripts/fresh_clone_check.sh` from a clean clone: bootstrap, doctor, tests, smoke, "
                        "directed RTL, the native A2 subset, trace/demo regeneration, viewer and report checks; viewer and GIF inspected | "
                        f"`{EVIDENCE['darwin-arm64']}`, `results/host/Darwin-arm64.json` |")
        if ln.startswith("| `remote-ci` ("):
            lines[i] = (f"| `remote-ci` (`.github/workflows/ci.yml`) | GitHub Actions at the release commit | **executed** | "
                        f"`fast` and `hdl` tiers passed at `{ci['sha'][:12]}` ({ci['url']}) | `{EVIDENCE['remote-ci']}` |")
        if ln.startswith("| The maintainer's actual demo machine and remote CI have passed their stated checks |"):
            lines[i] = "| The maintainer's actual demo machine and remote CI have passed their stated checks | satisfied (see the platform table) | `results/evidence/U20/` |"
    d.write_text("\n".join(lines) + "\n")
    u = ROOT / "docs" / "upgrade_progress.md"
    t = u.read_text()
    t = t.replace("| U20 Mac + remote release | **blocked** (darwin-arm64 Mac reproduction and remote-ci run not executed) — local gates passed |",
                  f"| U20 Mac + remote release | passed (darwin-arm64 reproduction executed on the maintainer's Mac; remote-ci run `{ci['sha'][:12]}` recorded) |", 1)
    u.write_text(t)
    print("marked executed: benchmarks/release_v2.json, docs/release_v2.md, docs/upgrade_progress.md — commit, push, then dispatch the "
          "release-check workflow; tag v2.0-a2 only after it prints 'OK — releasable'")
    return 0


def status() -> int:
    m = load(MANIFEST)
    for pf in m["platforms"]:
        rec = ROOT / EVIDENCE.get(pf["family"], pf.get("evidence") or "")
        print(f"{pf['family']:14s} {pf['status']:9s} record {'present' if rec.is_file() else 'absent '}  {pf.get('evidence') or ''}")
    lock = load(LOCK)["assets"]["darwin-arm64"]
    print(f"lock darwin-arm64: {lock['status']}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 1 and argv[0] == "verify-lock":
        return verify_lock()
    if len(argv) == 3 and argv[0] == "ci-record":
        return ci_record(argv[1], argv[2])
    if len(argv) >= 1 and argv[0] == "mark-executed":
        return mark_executed()
    if len(argv) >= 1 and argv[0] == "status":
        return status()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
