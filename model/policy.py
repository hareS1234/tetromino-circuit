"""Readable reference policies (depth one).  Built on the literal-descent oracle."""
from __future__ import annotations

import random

from .features import features
from .game import legal_actions, lock_and_clear
from .numeric import features_used, score_profile


def evaluate_candidates(rows, piece_id: int, precision: int = 0):
    """One record per legal candidate, in increasing candidate-ID order."""
    records = []
    for rotation, x, y in legal_actions(rows, piece_id):
        next_rows, lines = lock_and_clear(rows, piece_id, rotation, x, y)
        a, q, u = features(next_rows)
        a_used, q_used, u_used = features_used((a, q, u), precision)
        records.append({
            "rotation": rotation, "x": x, "y": y, "candidate_id": 10 * rotation + x,
            "lines": lines, "A": a, "Q": q, "U": u,
            "A_used": a_used, "Q_used": q_used, "U_used": u_used,
            "score": score_profile((a, q, u), lines, precision),
            "next_rows": next_rows,
        })
    return records


def best_move(rows, piece_id: int, precision: int = 0):
    """Highest score; ties go to the lower candidate ID.  None when no move exists."""
    best = None
    for rec in evaluate_candidates(rows, piece_id, precision):
        if best is None or rec["score"] > best["score"] or (
            rec["score"] == best["score"] and rec["candidate_id"] < best["candidate_id"]
        ):
            best = rec
    return best


def random_legal(rows, piece_id: int, rng: random.Random, precision: int = 0):
    recs = evaluate_candidates(rows, piece_id, precision)
    if not recs:
        return None
    return rng.choice(recs)


def lowest_stack(rows, piece_id: int, precision: int = 0):
    """Minimise (A, Q, U, candidate_id) lexicographically after the move."""
    recs = evaluate_candidates(rows, piece_id, precision)
    if not recs:
        return None
    return min(recs, key=lambda r: (r["A"], r["Q"], r["U"], r["candidate_id"]))


def random_seed_for_stream(stream_seed: int) -> int:
    """Convention recorded in the experiment manifest."""
    return stream_seed + 1_000_000
