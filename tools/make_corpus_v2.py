#!/usr/bin/env python3
"""Build a seeded, quota-balanced 2,000-state corpus without touching the v1 fixtures."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import policy  # noqa: E402
from model.board import pack_rows  # noqa: E402
from model.boards import high_stack_board, overhang_board, random_board, trajectory_boards  # noqa: E402
from model.streams import SPLITS, seven_bag  # noqa: E402
from tools.identity import model_closure_sha256, sha256_file  # noqa: E402
from tools.make_corpus import equal_score_and_last_winner_cases, expected_d1, structured_cases  # noqa: E402

QUOTAS = {"heuristic_trajectory": 600, "random_trajectory": 600, "high_stack_holes": 400, "structured": 400}
RESERVED = {20260905}


def check_seeds(base: int) -> None:
    seeds = set(range(base, base + 100))
    for name, rng in SPLITS.items():
        if seeds & set(rng):
            raise SystemExit(f"seed range {base}-{base + 99} overlaps the {name} stream split")
    if seeds & RESERVED:
        raise SystemExit(f"seed range {base}-{base + 99} overlaps the v1 corpus seed")


def build(seed_base: int) -> tuple[list, dict]:
    check_seeds(seed_base)
    rng = random.Random(seed_base)
    seen = set()
    records = []
    counts = {k: 0 for k in QUOTAS}

    def add(cat, rows, piece, note):
        key = (pack_rows(rows), piece)
        if key in seen or counts[cat] >= QUOTAS[cat]:
            return False
        seen.add(key)
        counts[cat] += 1
        records.append((cat, tuple(rows), piece, note))
        return True

    # trajectories: seeds base+0..base+29 heuristic, base+30..base+69 random
    for k in range(30):
        seed = seed_base + k
        boards = trajectory_boards(seed, 400, "heuristic")
        pieces = seven_bag(seed, 401)
        idx = list(range(len(boards)))
        rng.shuffle(idx)
        for i in idx[:40]:
            add("heuristic_trajectory", boards[i], pieces[i], f"stream {seed} move {i}")
    for k in range(30, 70):
        seed = seed_base + k
        boards = trajectory_boards(seed, 150, "random_legal")
        pieces = seven_bag(seed, 151)
        idx = list(range(len(boards)))
        rng.shuffle(idx)
        for i in idx[:30]:
            add("random_trajectory", boards[i], pieces[i], f"stream {seed} move {i}")
    # generated boards
    tries = 0
    while counts["high_stack_holes"] < QUOTAS["high_stack_holes"] and tries < 20000:
        gen = (high_stack_board, overhang_board, random_board)[tries % 3]
        add("high_stack_holes", gen(rng), rng.randrange(7), "generated; potentially unreachable")
        tries += 1
    # structured edge cases: v1 helpers with fresh randomness plus tie/last-winner mining on dev trajectories
    structured = structured_cases(rng)
    for k in range(70, 100):
        seed = seed_base + k
        boards = trajectory_boards(seed, 300, "heuristic")
        pieces = seven_bag(seed, 301)
        structured += equal_score_and_last_winner_cases(rng, boards, pieces)
    rng.shuffle(structured)
    for cat, rows, piece, note in structured:
        add("structured", rows, piece, f"{cat}: {note}")
    tries = 0
    while counts["structured"] < QUOTAS["structured"] and tries < 20000:
        rows = overhang_board(rng)
        piece = rng.randrange(7)
        recs = policy.evaluate_candidates(rows, piece)
        if recs and len(recs) < len(policy.evaluate_candidates(tuple([0] * 20), piece)):
            add("structured", rows, piece, "blocked_spawn: generated")
        tries += 1
    missing = {k: QUOTAS[k] - v for k, v in counts.items() if v < QUOTAS[k]}
    if missing:
        raise SystemExit(f"could not meet category quotas: {missing} (dedup by board+piece; increase seeds or trajectory length)")
    return records, counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed-base", type=int, required=True)
    args = ap.parse_args()
    out = ROOT / args.out
    if out.name in ("corpus_d1.jsonl", "corpus_d2.jsonl"):
        raise SystemExit("refusing to overwrite the v1 corpora")
    records, counts = build(args.seed_base)
    out.parent.mkdir(parents=True, exist_ok=True)
    legal = no_move = 0
    with open(out, "w") as fh:
        for i, (cat, rows, piece, note) in enumerate(records):
            exp = expected_d1(rows, piece)
            no_move += int(exp["no_move"])
            legal += int(not exp["no_move"])
            fh.write(json.dumps({"id": i, "category": cat, "rows": list(rows), "piece": piece, "note": note, "expected": exp}) + "\n")
    meta = {"schema": "corpus-meta-v1", "corpus": str(out.relative_to(ROOT)), "seed_base": args.seed_base, "seeds": [args.seed_base, args.seed_base + 99],
            "quotas": QUOTAS, "counts": counts, "states": len(records), "unique_states": len({(tuple(r[1]), r[2]) for r in records}),
            "legal": legal, "no_move": no_move, "generator_sha256": sha256_file(ROOT / "tools" / "make_corpus_v2.py"),
            "v1_helpers_sha256": sha256_file(ROOT / "tools" / "make_corpus.py"), "model_closure": model_closure_sha256(),
            "corpus_sha256": sha256_file(out),
            "note": "category mixture is a test design, not the frequency of states in ordinary games"}
    Path(str(out) + ".meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    print(f"corpus {out.relative_to(ROOT)}: {counts}, {len(records)} states, {no_move} no-move, sha256 {meta['corpus_sha256'][:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
