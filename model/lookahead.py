"""Readable exhaustive depth-two reference (DEPTH=2).

S2 = wL*(L1+L2) - wA*A(B2) - wQ*Q(B2) - wU*U(B2), evaluated on the leaf board.
A root's achievable score is the maximum S2 over its legal second moves.  Roots
with at least one legal second move ("surviving") are preferred over roots with
none.  If no root survives but current moves exist, the highest S1 root wins.
All ties break by the lower candidate ID.
"""
from __future__ import annotations

from .features import features
from .game import legal_actions, lock_and_clear
from .numeric import profile, score_profile


def best_move_depth2(rows, piece_id: int, next_piece_id: int, precision: int = 0):
    p = profile(precision)
    survivors_best = None   # (S2, root_id, record)
    fallback_best = None    # (S1, root_id, record)
    for rotation, x, y in legal_actions(rows, piece_id):
        root_id = 10 * rotation + x
        b1, l1 = lock_and_clear(rows, piece_id, rotation, x, y)
        f1 = features(b1)
        s1 = score_profile(f1, l1, precision)
        branch_best = None  # (S2, leaf_id, leaf_record)
        leaf_count = 0
        for r2, x2, y2 in legal_actions(b1, next_piece_id):
            leaf_id = 10 * r2 + x2
            b2, l2 = lock_and_clear(b1, next_piece_id, r2, x2, y2)
            f2 = features(b2)
            # leaf score with its own L2 (0-4) plus wL*L1 added by the controller
            s2 = score_profile(f2, l2, precision) + p.wl * l1
            leaf_count += 1
            if branch_best is None or s2 > branch_best[0] or (s2 == branch_best[0] and leaf_id < branch_best[1]):
                branch_best = (s2, leaf_id, {"rotation": r2, "x": x2, "y": y2, "lines": l2,
                                             "A": f2[0], "Q": f2[1], "U": f2[2]})
        rec = {
            "rotation": rotation, "x": x, "y": y, "candidate_id": root_id,
            "lines": l1, "A": f1[0], "Q": f1[1], "U": f1[2], "score_s1": s1,
            "next_rows": b1, "leaf_count": leaf_count,
        }
        if branch_best is not None:
            rec["score"] = branch_best[0]
            rec["surviving"] = True
            rec["leaf"] = branch_best[2]
            if survivors_best is None or rec["score"] > survivors_best[0] or (
                rec["score"] == survivors_best[0] and root_id < survivors_best[1]
            ):
                survivors_best = (rec["score"], root_id, rec)
        else:
            rec["score"] = s1
            rec["surviving"] = False
        if fallback_best is None or s1 > fallback_best[0] or (s1 == fallback_best[0] and root_id < fallback_best[1]):
            fallback_best = (s1, root_id, rec)
    if survivors_best is not None:
        return survivors_best[2]
    if fallback_best is not None:
        rec = dict(fallback_best[2])
        rec["score"] = rec["score_s1"]
        rec["surviving"] = False
        return rec
    return None
