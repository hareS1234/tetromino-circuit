#!/usr/bin/env python3
"""Recount the archived v1 results and note any live-checkout differences."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.identity import source_closure_sha256, toolchain_identity  # noqa: E402


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def main() -> int:
    problems = []
    inv = {"schema": "u00-inventory-v1"}
    inv["git"] = {"branch": git("branch", "--show-current"), "commit": git("rev-parse", "HEAD"),
                  "tags": git("tag").split(), "remotes": git("remote", "-v").splitlines(),
                  "dirty": bool(git("status", "--porcelain"))}
    inv["source_sha256"] = source_closure_sha256()
    inv["toolchain_id"] = toolchain_identity()
    lock = json.loads((ROOT / "toolchain.lock.json").read_text())
    inv["v1_toolchain_lock"] = {k: lock.get(k) for k in ("suite_release", "asset", "archive_sha256", "os", "arch", "python", "verilator", "yosys", "nextpnr_ecp5")}
    inv["v1_protocol_sha256"] = hashlib.sha256((ROOT / "benchmarks" / "config.json").read_bytes()).hexdigest()

    # routing attempts
    rows = list(csv.DictReader(open(ROOT / "results" / "implementation.csv")))
    keys = collections.Counter((r["arch"], r["board_repr"], r["lanes"], r["depth"], r["precision"], r["route_seed"]) for r in rows)
    statuses = collections.Counter(r["status"] for r in rows)
    inv["routing"] = {"rows": len(rows), "unique_config_seed": len(keys), "duplicates": [k for k, v in keys.items() if v > 1],
                      "status": dict(statuses), "timing_met": sum(r["timing_met"] == "True" for r in rows),
                      "non_routed": [{"config": f"a{r['arch']}-{'cache' if r['board_repr'] == '1' else 'bitmap'}-d{r['depth']}-p{r['precision']}-l{r['lanes']}",
                                      "seed": r["route_seed"], "status": r["status"], "elapsed_s": r["elapsed_s"]} for r in rows if r["status"] != "routed"]}
    if len(rows) != 45 or len(keys) != 45 or statuses.get("routed") != 44 or statuses.get("killed_no_convergence") != 1:
        problems.append(f"routing recount does not match the reported 44 routed + 1 non-converged: {dict(statuses)}")
    manifest = json.loads((ROOT / "results" / "implementation_manifest.json").read_text())
    inv["routing"]["manifest_summary"] = manifest.get("summary")
    inv["routing"]["manifest_rtl_hash"] = manifest.get("rtl_hash")
    if manifest.get("summary", {}).get("routing_attempts") != 45 or manifest.get("summary", {}).get("timing_met") != 44:
        problems.append("implementation_manifest summary disagrees with the CSV recount")

    # quality rows
    q = list(csv.DictReader(open(ROOT / "results" / "quality.csv")))
    held = [r for r in q if r["experiment"] in ("precision", "depth")]
    uniq = {(r["experiment"], r["policy"], r["depth"], r["precision"], r["stream_seed"]) for r in held}
    inv["quality"] = {"rows": len(q), "by_experiment": dict(collections.Counter(r["experiment"] for r in q)),
                      "held_out_rows": len(held), "held_out_unique_jobs": len(uniq),
                      "source_hashes": dict(collections.Counter(r["source_hash"] for r in held))}
    if len(held) != 640 or len(uniq) != 640 or len(inv["quality"]["source_hashes"]) != 1:
        problems.append("held-out quality rows are not exactly 640 unique jobs from one source hash")

    # P2 disagreement numerator/denominator
    dis = json.loads((ROOT / "results" / "precision_disagreement.json").read_text())
    inv["p2_disagreement"] = dis["2"]
    if dis["2"]["disagree_with_p0"] != 0 or dis["2"]["legal_states"] != 981:
        problems.append("P2 disagreement record differs from the reported 0/981")

    # decisions files
    dec = {}
    for f in sorted((ROOT / "results" / "decisions").glob("*_native_*.csv")):
        cid = f.name.split("_native_")[0]
        n = sum(1 for _ in open(f)) - 1
        dec[cid] = max(dec.get(cid, 0), n)
    inv["decision_files"] = dec
    if len(dec) != 9:
        problems.append(f"expected decision files for nine configurations, found {len(dec)}")

    # evidence records
    ev = {}
    for i in range(20):
        p = ROOT / "results" / "evidence" / f"E{i:02d}" / "summary.json"
        ev[f"E{i:02d}"] = json.loads(p.read_text()).get("status") if p.is_file() else "missing"
    inv["v1_evidence"] = ev
    if any(v != "passed" for v in ev.values()):
        problems.append("not every E-job evidence record is passed")

    # archive vs live checkout
    tracked = git("ls-files").splitlines()
    inv["tracked_files"] = len(tracked)
    inv["tracked_inspection_pngs"] = [t for t in tracked if t.startswith("results/inspection/")]
    archive = Path("/mnt/user-data/outputs/tetromino-circuit.tar.gz")
    if archive.is_file():
        import tarfile
        with tarfile.open(archive) as tf:
            names = [m.name for m in tf.getmembers() if m.isfile()]
        stripped = [n.split("/", 1)[1] if "/" in n else n for n in names]
        missing = sorted(set(tracked) - set(stripped))
        inv["delivered_archive"] = {"path": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                                    "files": len(names), "tracked_files_missing_from_archive": missing}
    else:
        inv["delivered_archive"] = {"path": str(archive), "note": "archive not present in this environment"}
    inv["problems"] = problems
    out = ROOT / "results" / "evidence" / "U00" / "inventory.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(inv, indent=1) + "\n")
    print(json.dumps({k: inv[k] for k in ("routing", "quality", "p2_disagreement", "tracked_inspection_pngs")}, indent=1))
    print(f"CHECK inventory_consistency {0 if problems else 1}/1")
    for p in problems:
        print("PROBLEM:", p)
    print("->", out.relative_to(ROOT))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
