"""Deterministic board generators for tests and corpora (always normalized: no full rows)."""
from __future__ import annotations

import random

from .board import EMPTY_BOARD, FULL_ROW, H, W
from . import fast, policy
from .streams import seven_bag


def _unfill(rows, rng):
    return tuple(r if r != FULL_ROW else r & ~(1 << rng.randrange(W)) for r in rows)


def random_board(rng: random.Random, fill: float | None = None, top: int | None = None):
    """Independent random cells up to a random top row; may contain overhangs."""
    fill = rng.choice([0.2, 0.4, 0.6, 0.85]) if fill is None else fill
    top = rng.randint(0, H) if top is None else top
    rows = [0] * H
    for y in range(top):
        rows[y] = sum((1 << x) for x in range(W) if rng.random() < fill)
    return _unfill(tuple(rows), rng)


def high_stack_board(rng: random.Random):
    """Tall stacks with holes and wells, mostly dense near the top of the board."""
    heights = [rng.randint(12, 20) for _ in range(W)]
    if rng.random() < 0.5:
        heights[rng.randrange(W)] = rng.randint(0, 6)  # a well
    rows = [0] * H
    for x in range(W):
        for y in range(heights[x]):
            if rng.random() < 0.85:
                rows[y] |= 1 << x
    return _unfill(tuple(rows), rng)


def overhang_board(rng: random.Random):
    """Sparse tall columns with a cap block near the top to exercise entry-path collisions."""
    rows = [0] * H
    for x in range(W):
        h = rng.randint(0, 19)
        for y in range(h):
            if rng.random() < 0.5:
                rows[y] |= 1 << x
        if rng.random() < 0.7:
            cap = rng.randint(max(h, 14), 19)
            rows[cap] |= 1 << x
    return _unfill(tuple(rows), rng)


def trajectory_boards(seed: int, pieces: int, policy_name: str = "heuristic", precision: int = 0):
    """Boards visited while playing a seven-bag stream with a software policy."""
    stream = seven_bag(seed, pieces + 1)
    rng = random.Random(policy.random_seed_for_stream(seed))
    rows = EMPTY_BOARD
    out = [rows]
    for i in range(pieces):
        piece = stream[i]
        if policy_name == "heuristic":
            rec = fast.best_move_fast(rows, piece, precision)
        elif policy_name == "random_legal":
            rec = policy.random_legal(rows, piece, rng, precision)
        else:
            raise ValueError(policy_name)
        if rec is None:
            break
        rows = tuple(rec["next_rows"])
        out.append(rows)
    return out


def mixed_boards(seed: int, count: int):
    """count boards from four deterministic generators (round-robin)."""
    rng = random.Random(seed)
    traj_h = trajectory_boards(seed, 400, "heuristic")
    traj_r = trajectory_boards(seed + 1, 200, "random_legal")
    out = []
    i = 0
    while len(out) < count:
        kind = i % 4
        if kind == 0:
            out.append(random_board(rng))
        elif kind == 1:
            out.append(high_stack_board(rng))
        elif kind == 2:
            out.append(overhang_board(rng))
        else:
            src = traj_h if (i // 4) % 2 == 0 else traj_r
            out.append(src[rng.randrange(len(src))])
        i += 1
    return out
