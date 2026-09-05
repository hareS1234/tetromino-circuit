#!/usr/bin/env python3
"""Headline tournament: actual RTL replays (native Verilator driver, checked against Python at
every move) for the frozen configurations on the frozen seed/cap, rendered 2x2 with the matching
implementation manifest.  Also renders a cycle-synchronised version of the same replays."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.config import SUPPORTED_IDS  # noqa: E402
from model.replay import read_replay, replay_decisions  # noqa: E402


def run(cmd):
    proc = subprocess.run(["bash", str(ROOT / "scripts/env.sh")] + cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout[-2000:], proc.stderr[-2000:])
        raise SystemExit(f"failed: {' '.join(cmd)}")
    return proc.stdout


def main() -> int:
    cfg = json.loads((ROOT / "benchmarks" / "config.json").read_text())["tournament"]
    replays = []
    for cid in cfg["configurations"]:
        c = SUPPORTED_IDS[cid]
        out = f"results/replays/tournament_{cid}_seed{cfg['seed']}_cap{cfg['cap']}.jsonl"
        print(run(["python", "tools/play_rtl.py", "--arch", str(c.arch), "--board-repr", str(c.board_repr), "--lanes", str(c.lanes),
                   "--depth", str(c.depth), "--precision", str(c.precision), "--driver", "native", "--seed", str(cfg["seed"]),
                   "--max-pieces", str(cfg["cap"]), "--out", out]).strip().splitlines()[-1])
        replays.append(out)
    # divergence report: first move where each variant departs from the first (exact A0) replay
    base = read_replay(ROOT / replays[0])[1]
    report = {"seed": cfg["seed"], "cap": cfg["cap"], "first_divergence_from_a0": {}}
    for cid, path in zip(cfg["configurations"], replays):
        recs = read_replay(ROOT / path)[1]
        first = next((i for i, (a, b) in enumerate(zip(replay_decisions(base), replay_decisions(recs))) if a != b), None)
        report["first_divergence_from_a0"][cid] = first
        report.setdefault("lines", {})[cid] = recs[-1]["cumulative_lines"] if recs else 0
        report.setdefault("median_cycles", {})[cid] = sorted(r["cycles"] for r in recs)[len(recs) // 2] if recs else None
    (ROOT / "results" / "tournament_report.json").write_text(json.dumps(report, indent=1) + "\n")
    print("tournament report:", report)
    print(run(["python", "tools/render_tournament.py", "--replays", *replays, "--implementation", "results/implementation.csv",
               "--sync", "pieces", "--out", "assets/tournament_rtl.gif", "--max-frames", "120"]).strip())
    print(run(["python", "tools/render_tournament.py", "--replays", *replays, "--implementation", "results/implementation.csv",
               "--sync", "cycles", "--out", "assets/tournament_rtl_cycles.gif", "--max-frames", "120"]).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
