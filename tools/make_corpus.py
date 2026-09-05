#!/usr/bin/env python3
"""Build the committed 1,000-request differential corpus (depth one) and the 250-case
depth-two corpus.  Each record stores concrete rows, piece(s), category and the expected
decision from the literal-descent reference model.

Depth-one categories: 300 heuristic-trajectory states, 300 random-trajectory states,
200 generated high-stack/hole boards (labelled potentially unreachable), and 200 structured
edge cases (walls, wells, blocked spawns, equal scores, last-candidate winners, no-move).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import lookahead, policy  # noqa: E402
from model.board import EMPTY_BOARD, H, W  # noqa: E402
from model.boards import high_stack_board, overhang_board, random_board, trajectory_boards  # noqa: E402
from model.game import drop_y  # noqa: E402
from model.pieces import candidate_ids, decode_candidate  # noqa: E402

OUT_D1 = ROOT / "benchmarks" / "states" / "corpus_d1.jsonl"
OUT_D2 = ROOT / "benchmarks" / "states" / "corpus_d2.jsonl"


def expected_d1(rows, piece):
    rec = policy.best_move(rows, piece)
    if rec is None:
        return {"no_move": True, "rotation": 0, "x": 0, "y": 0, "score": 0, "candidate_id": None}
    return {"no_move": False, "rotation": rec["rotation"], "x": rec["x"], "y": rec["y"], "score": rec["score"],
            "candidate_id": rec["candidate_id"], "lines": rec["lines"]}


def record(idx, category, rows, piece, note=None):
    return {"id": idx, "category": category, "rows": list(rows), "piece": piece, "note": note, "expected": expected_d1(rows, piece)}


def sample_states(rng, boards, stream_pieces, n):
    out = []
    for _ in range(n):
        i = rng.randrange(len(boards))
        out.append((boards[i], stream_pieces[i]))
    return out


def structured_cases(rng):
    cases = []
    # walls: pieces that must go to the left or right wall to clear a line
    for piece in range(7):
        for side in ("left", "right"):
            rows = [0] * H
            for y in range(2):
                rows[y] = 1023 & ~(0b1111 if side == "left" else 0b1111000000)
            cases.append(("walls", tuple(rows), piece, f"open {side} slot"))
    # wells: a deep single-column well
    for well in (0, 2, 4, 7, 9):
        for piece in range(7):
            rows = [(1023 & ~(1 << well)) for _ in range(6)] + [0] * (H - 6)
            rows = [r & ~(1 << rng.randrange(W)) if rng.random() < 0.3 and r != 1023 else r for r in rows]
            cases.append(("wells", tuple(rows), piece, f"well at x={well}"))
    # blocked spawns: some geometric candidates illegal, a legal move exists
    for _ in range(90):
        rows = [0] * H
        for x in range(W):
            if rng.random() < 0.5:
                top = rng.randint(16, 19)
                rows[top] |= 1 << x
                for y in range(rng.randint(0, top)):
                    if rng.random() < 0.6:
                        rows[y] |= 1 << x
        rows = tuple(r if r != 1023 else r & ~1 for r in rows)
        piece = rng.randrange(7)
        legal = [cid for cid in candidate_ids(piece) if drop_y(rows, piece, *decode_candidate(cid)) is not None]
        if 0 < len(legal) < len(candidate_ids(piece)):
            cases.append(("blocked_spawn", rows, piece, f"{len(candidate_ids(piece)) - len(legal)} of {len(candidate_ids(piece))} candidates blocked"))
    # no-move cases
    cases.append(("no_move", tuple([0] * 18 + [341, 341]), 1, "O on alternating top rows"))
    for piece in range(7):
        rows = tuple([0] * 17 + [1023 & ~1, 341, 682])
        if policy.best_move(rows, piece) is None:
            cases.append(("no_move", rows, piece, "checkerboard top"))
    return cases


def equal_score_and_last_winner_cases(rng, boards, pieces):
    ties, last = [], []
    for rows, piece in zip(boards, pieces):
        recs = policy.evaluate_candidates(rows, piece)
        if not recs:
            continue
        best = max(r["score"] for r in recs)
        tied = [r for r in recs if r["score"] == best]
        if len(tied) >= 2 and len(ties) < 70:
            ties.append(("equal_scores", rows, piece, f"{len(tied)} candidates tie at {best}"))
        winner = min(tied, key=lambda r: r["candidate_id"])
        ids = candidate_ids(piece)
        if winner["candidate_id"] == ids[-1] and len(last) < 50:
            last.append(("last_candidate_winner", rows, piece, f"winner is dense index {len(ids) - 1}"))
    return ties + last


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260905)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    from model.streams import seven_bag

    records = []
    # 300 heuristic trajectory states from training streams
    for seed in (1000, 1001, 1002):
        boards = trajectory_boards(seed, 600, "heuristic")
        pieces = seven_bag(seed, 601)
        for rows, piece in sample_states(rng, boards, pieces, 100):
            records.append(("heuristic_trajectory", rows, piece, f"stream {seed}"))
    # 300 random-policy trajectory states
    for seed in (1003, 1004, 1005, 1006, 1007, 1008):
        boards = trajectory_boards(seed, 200, "random_legal")
        pieces = seven_bag(seed, 201)
        for rows, piece in sample_states(rng, boards, pieces, 50):
            records.append(("random_trajectory", rows, piece, f"stream {seed}"))
    # 200 high stacks and holes (potentially unreachable)
    for i in range(200):
        gen = (high_stack_board, overhang_board, random_board)[i % 3]
        records.append(("high_stack_holes", gen(rng), rng.randrange(7), "generated; potentially unreachable"))
    # 200 structured edge cases
    structured = structured_cases(rng)
    dev_boards = trajectory_boards(1010, 1500, "heuristic")
    dev_pieces = seven_bag(1010, 1501)
    structured += equal_score_and_last_winner_cases(rng, dev_boards, dev_pieces)
    rng.shuffle(structured)
    while len(structured) < 200:
        structured.append(("high_stack_holes", overhang_board(rng), rng.randrange(7), "filler"))
    records += structured[:200]
    assert len(records) == 1000, len(records)

    OUT_D1.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_D1, "w") as fh:
        for i, (cat, rows, piece, note) in enumerate(records):
            fh.write(json.dumps(record(i, cat, rows, piece, note)) + "\n")
    cats = {}
    for cat, *_ in records:
        cats[cat] = cats.get(cat, 0) + 1
    print("depth-one corpus:", cats, "->", OUT_D1.relative_to(ROOT))

    # ---- depth-two corpus: 250 board/current/preview cases with the required structures ----
    d2 = []
    seen = set()

    def add(cat, rows, piece, nxt, note):
        key = (rows, piece, nxt)
        if key in seen:
            return
        seen.add(key)
        rec = lookahead.best_move_depth2(rows, piece, nxt)
        exp = ({"no_move": True, "rotation": 0, "x": 0, "y": 0, "score": 0, "candidate_id": None, "surviving": False}
               if rec is None else
               {"no_move": False, "rotation": rec["rotation"], "x": rec["x"], "y": rec["y"], "score": rec["score"],
                "candidate_id": rec["candidate_id"], "surviving": rec["surviving"], "score_s1": rec["score_s1"]})
        d2.append({"id": len(d2), "category": cat, "rows": list(rows), "piece": piece, "next_piece": nxt, "note": note, "expected": exp})

    boards = trajectory_boards(1020, 1200, "heuristic")
    pieces = seven_bag(1020, 1202)
    # same board, different previews
    for i in range(0, 40, 4):
        for nxt in range(7):
            add("differing_previews", boards[i], pieces[i], nxt, "same board, every preview")
    # ordinary states from trajectories
    for i in rng.sample(range(len(boards)), 80):
        add("trajectory", boards[i], pieces[i], pieces[i + 1], "stream 1020")
    # root ties: trajectory states where two or more roots achieve the same best S2
    from model.game import legal_actions, lock_and_clear
    from model.features import features
    from model.numeric import score_profile

    def root_values(rows, piece, nxt):
        vals = []
        for r1, x1, y1 in legal_actions(rows, piece):
            b1, l1 = lock_and_clear(rows, piece, r1, x1, y1)
            best_s2 = None
            for r2, x2, y2 in legal_actions(b1, nxt):
                b2, l2 = lock_and_clear(b1, nxt, r2, x2, y2)
                s2 = score_profile(features(b2), l2) + 76 * l1
                if best_s2 is None or s2 > best_s2:
                    best_s2 = s2
            vals.append((10 * r1 + x1, best_s2))
        return vals

    for i in range(len(boards) - 1):
        if sum(1 for r in d2 if r["category"] == "root_ties") >= 20 or len(d2) >= 250:
            break
        rows, piece, nxt = boards[i], pieces[i], pieces[i + 1]
        vals = [v for v in root_values(rows, piece, nxt) if v[1] is not None]
        if not vals:
            continue
        top = max(v[1] for v in vals)
        if sum(1 for v in vals if v[1] == top) >= 2:
            add("root_ties", rows, piece, nxt, f"{sum(1 for v in vals if v[1] == top)} roots tie at S2={top}")
    # high stacks: root ties, all-terminal fallback, no current move, late winners
    tries = 0
    while len(d2) < 250 and tries < 20000:
        tries += 1
        rows = (high_stack_board, overhang_board)[tries % 2](rng)
        piece, nxt = rng.randrange(7), rng.randrange(7)
        rec = lookahead.best_move_depth2(rows, piece, nxt)
        if rec is None:
            if sum(1 for r in d2 if r["category"] == "no_current_move") < 15:
                add("no_current_move", rows, piece, nxt, "no legal root")
        elif not rec["surviving"]:
            if sum(1 for r in d2 if r["category"] == "all_terminal_fallback") < 25:
                add("all_terminal_fallback", rows, piece, nxt, "no root has a legal second move")
        else:
            ids = candidate_ids(piece)
            if rec["candidate_id"] == ids[-1] and sum(1 for r in d2 if r["category"] == "late_root_winner") < 20:
                add("late_root_winner", rows, piece, nxt, "winning root is the last dense index")
            elif sum(1 for r in d2 if r["category"] == "high_stack") < 40:
                add("high_stack", rows, piece, nxt, "generated")
    while len(d2) < 250:
        i = rng.randrange(len(boards) - 1)
        add("trajectory", boards[i], pieces[i], pieces[i + 1], "stream 1020 filler")
    with open(OUT_D2, "w") as fh:
        for r in d2:
            fh.write(json.dumps(r) + "\n")
    cats = {}
    for r in d2:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    print("depth-two corpus:", cats, "->", OUT_D2.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
