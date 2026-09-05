"""Board features on the post-clear board and the baseline score."""
from __future__ import annotations

from .board import H, W

COEFFICIENTS = (76, 51, 36, 18)  # wL, wA, wQ, wU


def column_heights(rows):
    heights = []
    for x in range(W):
        h = 0
        for y in range(H - 1, -1, -1):
            if (rows[y] >> x) & 1:
                h = y + 1
                break
        heights.append(h)
    return heights


def features(rows):
    """(A, Q, U): aggregate height, holes, bumpiness."""
    heights = column_heights(rows)
    a = sum(heights)
    q = 0
    for x in range(W):
        for y in range(heights[x]):
            if not (rows[y] >> x) & 1:
                q += 1
    u = sum(abs(heights[x] - heights[x - 1]) for x in range(1, W))
    return a, q, u


def score(feats, lines: int) -> int:
    a, q, u = feats
    wl, wa, wq, wu = COEFFICIENTS
    return wl * lines - wa * a - wq * q - wu * u
