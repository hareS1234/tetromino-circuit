"""Accelerated bit-exact policy model on a column-bitmask representation.

Used for long software sweeps and as the software twin of the A1 datapath.
It uses the closed-form landing formula (exact heights + bottom offsets), a
parallel merge mask, full-row detection by AND-reduction, and popcount holes.
It is validated against model.policy / model.lookahead (literal descent) in
tests; it must never be the only reference.
"""
from __future__ import annotations

from .board import FULL_ROW, H, W
from .numeric import profile
from .pieces import candidate_ids, decode_candidate, shape

COL_MASK = (1 << H) - 1


def rows_to_cols(rows):
    cols = [0] * W
    for y in range(H):
        row = rows[y]
        if row:
            for x in range(W):
                if (row >> x) & 1:
                    cols[x] |= 1 << y
    return tuple(cols)


def cols_to_rows(cols):
    rows = [0] * H
    for x in range(W):
        col = cols[x]
        while col:
            low = col & -col
            y = low.bit_length() - 1
            rows[y] |= 1 << x
            col ^= low
    return tuple(rows)


def heights_of(cols):
    return [c.bit_length() for c in cols]


def _remove_rows(col: int, full_mask: int) -> int:
    """Delete the bit positions set in full_mask (highest first) and close the gaps."""
    m = full_mask
    while m:
        b = m.bit_length() - 1
        low = col & ((1 << b) - 1)
        col = low | ((col >> (b + 1)) << b)
        m &= ~(1 << b)
    return col


def features_cols(cols, prof):
    """(A, Q_used, U_used, Q_true, U_true) for scoring with a profile."""
    a = 0
    q = 0
    u = 0
    prev = None
    for c in cols:
        h = c.bit_length()
        a += h
        q += (((1 << h) - 1) & ~c).bit_count()
        if prev is not None:
            u += abs(h - prev)
        prev = h
    q_used = q if prof.q_cap is None else min(q, prof.q_cap)
    u_used = u if prof.use_u else 0
    return a, q_used, u_used, q, u


def _place(cols, heights, shp, x):
    """Landing + merge + clear on column masks.  Returns (y, new_cols, lines) or None."""
    y = 0
    for dx in range(shp.width):
        if (shp.colmask >> dx) & 1:
            d = heights[x + dx] - shp.bottom[dx]
            if d > y:
                y = d
    if y + shp.height > H:
        return None
    new = list(cols)
    full = COL_MASK
    for dx in range(shp.width):
        if (shp.colmask >> dx) & 1:
            new[x + dx] |= shp.colbits[dx] << y
    for c in new:
        full &= c
    lines = 0
    if full:
        lines = full.bit_count()
        new = [_remove_rows(c, full) for c in new]
    return y, new, lines


def evaluate_candidates_cols(cols, piece_id, prec: int = 0):
    """Yield (candidate_id, y, new_cols, lines, score, feats) for every legal candidate."""
    prof = profile(prec)
    heights = heights_of(cols)
    out = []
    for cid in candidate_ids(piece_id):
        rotation, x = decode_candidate(cid)
        shp = shape(piece_id, rotation)
        placed = _place(cols, heights, shp, x)
        if placed is None:
            continue
        y, new, lines = placed
        a, q_used, u_used, q, u = features_cols(new, prof)
        s = prof.wl * lines - prof.wa * a - prof.wq * q_used - prof.wu * u_used
        out.append((cid, y, new, lines, s, (a, q, u)))
    return out


def best_move_fast(rows, piece_id, precision: int = 0, cols=None):
    """Depth-one decision; same record shape as model.policy.best_move."""
    if cols is None:
        cols = rows_to_cols(rows)
    best = None
    for cid, y, new, lines, s, feats in evaluate_candidates_cols(cols, piece_id, precision):
        if best is None or s > best[4]:
            best = (cid, y, new, lines, s, feats)
    if best is None:
        return None
    cid, y, new, lines, s, feats = best
    rotation, x = decode_candidate(cid)
    return {"rotation": rotation, "x": x, "y": y, "candidate_id": cid, "lines": lines,
            "A": feats[0], "Q": feats[1], "U": feats[2], "score": s,
            "next_rows": cols_to_rows(new), "next_cols": tuple(new)}


def best_move_depth2_fast(rows, piece_id, next_piece_id, precision: int = 0, cols=None):
    if cols is None:
        cols = rows_to_cols(rows)
    prof = profile(precision)
    surv = None      # (S2, cid, record)
    fallback = None  # (S1, cid, record)
    for cid, y, b1, l1, s1, f1 in evaluate_candidates_cols(cols, piece_id, precision):
        bonus = prof.wl * l1
        branch = None
        leaf_count = 0
        for _cid2, _y2, _b2, _l2, s2_leaf, _f2 in evaluate_candidates_cols(b1, next_piece_id, precision):
            s2 = s2_leaf + bonus
            leaf_count += 1
            if branch is None or s2 > branch:
                branch = s2
        rotation, x = decode_candidate(cid)
        rec = {"rotation": rotation, "x": x, "y": y, "candidate_id": cid, "lines": l1,
               "A": f1[0], "Q": f1[1], "U": f1[2], "score_s1": s1,
               "next_rows": cols_to_rows(b1), "next_cols": tuple(b1), "leaf_count": leaf_count}
        if branch is not None:
            rec["score"] = branch
            rec["surviving"] = True
            if surv is None or branch > surv[0]:
                surv = (branch, cid, rec)
        else:
            rec["score"] = s1
            rec["surviving"] = False
        if fallback is None or s1 > fallback[0]:
            fallback = (s1, cid, rec)
    if surv is not None:
        return surv[2]
    if fallback is not None:
        rec = dict(fallback[2])
        rec["score"] = rec["score_s1"]
        rec["surviving"] = False
        return rec
    return None


def random_legal_fast(rows, piece_id, rng, precision: int = 0):
    """Same selection as model.policy.random_legal given the same rng state (rng.choice over
    the legal candidates in increasing candidate-ID order)."""
    recs = evaluate_candidates_cols(rows_to_cols(rows), piece_id, precision)
    if not recs:
        return None
    cid, y, new, lines, s, feats = rng.choice(recs)
    rotation, x = decode_candidate(cid)
    return {"rotation": rotation, "x": x, "y": y, "candidate_id": cid, "lines": lines,
            "A": feats[0], "Q": feats[1], "U": feats[2], "score": s, "next_rows": cols_to_rows(new)}


def lowest_stack_fast(rows, piece_id, precision: int = 0):
    recs = evaluate_candidates_cols(rows_to_cols(rows), piece_id, precision)
    if not recs:
        return None
    cid, y, new, lines, s, feats = min(recs, key=lambda r: (r[5][0], r[5][1], r[5][2], r[0]))
    rotation, x = decode_candidate(cid)
    return {"rotation": rotation, "x": x, "y": y, "candidate_id": cid, "lines": lines,
            "A": feats[0], "Q": feats[1], "U": feats[2], "score": s, "next_rows": cols_to_rows(new)}
