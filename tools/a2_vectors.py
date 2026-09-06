#!/usr/bin/env python3
"""Write A2 candidate vectors from the literal-descent oracle.

``C`` rows hold the 200-bit board, 50-bit heights, and piece. Their following ``T`` rows hold
rotation, x, candidate id, legality, landing y, and score. The native harness adds tags and
last-candidate flags.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.board import pack_rows  # noqa: E402
from model.boards import mixed_boards  # noqa: E402
from model.features import column_heights, features, score  # noqa: E402
from model.game import drop_y, lock_and_clear  # noqa: E402
from model.pieces import candidate_ids, decode_candidate, rotation_count  # noqa: E402


def expected(rows, piece, rot, x):
    if rot >= rotation_count(piece):
        return 0, 0, 0
    y = drop_y(rows, piece, rot, x)
    if y is None:
        return 0, 0, 0
    after, lines = lock_and_clear(rows, piece, rot, x, y)
    return 1, y, score(features(after), lines)


def write_vectors(path: Path, contexts: int, seed: int, invalid: int) -> dict:
    rng = random.Random(seed)
    boards = mixed_boards(seed, max(1, (contexts + 6) // 7))
    lines = [f"# a2-vectors-v1 seed={seed} contexts={contexts}"]
    n_tokens = n_legal = 0
    for i in range(contexts):
        rows = boards[i // 7]
        piece = i % 7
        heights = column_heights(rows)
        hval = sum(h << (5 * c) for c, h in enumerate(heights))
        lines.append(f"C {pack_rows(rows):050x} {hval:013x} {piece}")
        cands = [decode_candidate(c) for c in candidate_ids(piece)]
        extra = []
        for _ in range(invalid):
            rot, x = rng.randrange(4), rng.randrange(16)
            extra.append((rot, x))
        for rot, x in cands + extra:
            legal, y, sc = expected(rows, piece, rot, x)
            cid = (10 * rot + x) & 63
            lines.append(f"T {rot} {x} {cid} {legal} {y} {sc}")
            n_tokens += 1
            n_legal += legal
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return {"contexts": contexts, "tokens": n_tokens, "legal": n_legal}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--contexts", type=int, default=60)
    ap.add_argument("--seed", type=int, default=2024)
    ap.add_argument("--invalid", type=int, default=6, help="extra random (possibly invalid) geometric tokens per context")
    args = ap.parse_args()
    info = write_vectors(ROOT / args.out, args.contexts, args.seed, args.invalid)
    print(f"a2 vectors -> {args.out}: {info}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
