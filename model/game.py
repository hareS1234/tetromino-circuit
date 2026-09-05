"""drop-v1.1 placement rules: literal cell-by-cell descent from anchor y=20.

This is the Python oracle.  It deliberately does NOT use the closed-form
height formula (see model/fast.py); the two are compared in tests.
"""
from __future__ import annotations

from .board import FULL_ROW, H, W
from .pieces import candidate_ids, decode_candidate, shape


def fits(rows, cells, x: int, y: int) -> bool:
    """True when no piece cell collides during entry.

    Cells above the board (y>=20) are empty.  Cells below the floor or outside
    the side walls collide.  This does not enforce the final in-board lock rule.
    """
    for dx, dy in cells:
        cx = x + dx
        cy = y + dy
        if cx < 0 or cx >= W or cy < 0:
            return False
        if cy >= H:
            continue
        if (rows[cy] >> cx) & 1:
            return False
    return True


def physical_landing(rows, piece_id: int, rotation: int, x: int):
    """Anchor y where descent from y=20 first stops (may be above the board)."""
    shp = shape(piece_id, rotation)
    if x < 0 or x + shp.width > W:
        return None
    y = H
    while y > 0 and fits(rows, shp.cells, x, y - 1):
        y -= 1
    return y


def drop_y(rows, piece_id: int, rotation: int, x: int):
    """Landing anchor y, or None when the candidate is illegal."""
    shp = shape(piece_id, rotation)
    y = physical_landing(rows, piece_id, rotation, x)
    if y is None or y + shp.height > H:
        return None
    return y


def lock_and_clear(rows, piece_id: int, rotation: int, x: int, y: int):
    """Return (new_rows, lines_cleared).  Input board is not mutated."""
    shp = shape(piece_id, rotation)
    merged = list(rows)
    for dx, dy in shp.cells:
        cx, cy = x + dx, y + dy
        if not (0 <= cx < W and 0 <= cy < H):
            raise ValueError("landed cell outside the board")
        if (merged[cy] >> cx) & 1:
            raise ValueError("landed cell already occupied")
        merged[cy] |= 1 << cx
    survivors = [row for row in merged if row != FULL_ROW]
    cleared = H - len(survivors)
    return tuple(survivors + [0] * cleared), cleared


def merged_board(rows, piece_id: int, rotation: int, x: int, y: int):
    shp = shape(piece_id, rotation)
    merged = list(rows)
    for dx, dy in shp.cells:
        merged[y + dy] |= 1 << (x + dx)
    return tuple(merged)


def legal_actions(rows, piece_id: int):
    """(rotation, x, y) for every legal candidate, in increasing candidate-ID order."""
    out = []
    for cid in candidate_ids(piece_id):
        rotation, x = decode_candidate(cid)
        y = drop_y(rows, piece_id, rotation, x)
        if y is not None:
            out.append((rotation, x, y))
    return out
