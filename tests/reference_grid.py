"""Slow, independent set-of-occupied-cells reference for drop-v1.1.

Literal descent from anchor y=20 with above-board cells empty.  It does not use
the bitboard helpers, the closed-form landing, or any packed representation, so
it can catch a shared mistake in those implementations.
"""
from __future__ import annotations

W, H = 10, 20


def cells_from_rows(rows):
    return {(x, y) for y in range(H) for x in range(W) if (rows[y] >> x) & 1}


def rows_from_cells(cells):
    rows = [0] * H
    for x, y in cells:
        rows[y] |= 1 << x
    return tuple(rows)


def piece_cells(shape_cells, x, y):
    return [(x + dx, y + dy) for dx, dy in shape_cells]


def collides(occupied, placed):
    for cx, cy in placed:
        if cx < 0 or cx >= W or cy < 0:
            return True
        if cy >= H:
            continue
        if (cx, cy) in occupied:
            return True
    return False


def ref_landing(occupied, shape_cells, width, x):
    """(physical_anchor, legal).  Descent from y=20, above-board cells empty."""
    if x < 0 or x + width > W:
        return None, False
    y = H
    while y > 0 and not collides(occupied, piece_cells(shape_cells, x, y - 1)):
        y -= 1
    placed = piece_cells(shape_cells, x, y)
    legal = all(0 <= cy < H for _, cy in placed)
    return y, legal


def ref_lock_and_clear(occupied, shape_cells, x, y):
    merged = set(occupied)
    for c in piece_cells(shape_cells, x, y):
        assert c not in merged
        merged.add(c)
    full_rows = [yy for yy in range(H) if all((xx, yy) in merged for xx in range(W))]
    out = set()
    for (cx, cy) in merged:
        if cy in full_rows:
            continue
        shift = sum(1 for fy in full_rows if fy < cy)
        out.add((cx, cy - shift))
    return out, len(full_rows)


def ref_features(occupied):
    heights = []
    holes = 0
    for x in range(W):
        col = [y for (cx, y) in occupied if cx == x]
        h = (max(col) + 1) if col else 0
        heights.append(h)
        for y in range(h):
            if (x, y) not in occupied:
                holes += 1
    a = sum(heights)
    u = sum(abs(heights[i] - heights[i - 1]) for i in range(1, W))
    return a, holes, u
