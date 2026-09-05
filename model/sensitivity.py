"""Decision sensitivity of the quantized profiles P5-P7 on a common state (guide §9.3, U14).

Everything here is integer arithmetic on the literal-descent candidate records of
`model.policy.evaluate_candidates`.  For a quantized profile with M = 2^bits - 1 levels and
magnitudes q_i (model.numeric), the exact score S(c) = 76L - 51A - 36Q - 18U and the raw quantized
score S_q(c) = q_L L - q_A A - q_Q Q - q_U U satisfy

    76 * S_q(c) - M * S(c) = sum_i (+/-) delta_i * f_i(c),   delta_i = 76 q_i - M w_i,

so |76 S_q(c) - M S(c)| <= E(c) = sum_i |delta_i| f_i(c).  If the exact winner g satisfies
M (S(g) - S(c)) > E(g) + E(c) for every other legal candidate c, then S_q(g) > S_q(c) for all of
them and g is certified to remain the (unique) winner under that quantization.  A failed
certificate means "not certified", not "changed"; the actual decision is always computed as well.
Exact ties (several candidates at the maximal exact score) can never be certified: the exact
winner is then the lowest candidate id, and the bound cannot separate it from its equals.
"""
from __future__ import annotations

from .numeric import (EXACT_COEFFICIENTS, coefficient_perturbations, error_bound, profile, score_profile)
from .policy import evaluate_candidates


def candidate_table(rows, piece: int, precisions=(5, 6, 7)) -> list[dict]:
    """One row per legal candidate with the exact features, the exact score, each quantized raw score
    and each profile's error bound E(c)."""
    table = []
    for rec in evaluate_candidates(rows, piece, 0):
        feats = (rec["lines"], rec["A"], rec["Q"], rec["U"])
        row = {"candidate_id": rec["candidate_id"], "rotation": rec["rotation"], "x": rec["x"], "y": rec["y"],
               "lines": rec["lines"], "A": rec["A"], "Q": rec["Q"], "U": rec["U"], "score_p0": rec["score"]}
        for p in precisions:
            row[f"score_p{p}"] = score_profile((rec["A"], rec["Q"], rec["U"]), rec["lines"], p)
            row[f"E_p{p}"] = error_bound(feats, p)
        table.append(row)
    return table


def winner(table: list[dict], key: str) -> dict | None:
    """Highest score under `key`; ties to the lower candidate id (the hardware rule)."""
    best = None
    for row in table:
        if best is None or row[key] > best[key] or (row[key] == best[key] and row["candidate_id"] < best["candidate_id"]):
            best = row
    return best


def gap(table: list[dict], key: str) -> int | None:
    """Best minus runner-up score under `key` (0 for an exact tie, None with fewer than two candidates)."""
    if len(table) < 2:
        return None
    scores = sorted((row[key] for row in table), reverse=True)
    return scores[0] - scores[1]


def certify(table: list[dict], precision: int, exact_winner: dict | None = None) -> dict:
    """Integer certificate that the exact winner g survives quantization `precision`."""
    p = profile(precision)
    if p.levels is None:
        raise ValueError(f"PRECISION {precision} is not a quantized profile")
    m = p.levels
    if not table:
        return {"certified": False, "reason": "no legal candidate", "margin_min": None}
    g = exact_winner or winner(table, "score_p0")
    eg = g[f"E_p{precision}"]
    margin_min = None
    blocking = None
    for c in table:
        if c["candidate_id"] == g["candidate_id"]:
            continue
        lhs = m * (g["score_p0"] - c["score_p0"])
        rhs = eg + c[f"E_p{precision}"]
        margin = lhs - rhs                       # certificate holds for c iff margin > 0
        if margin_min is None or margin < margin_min:
            margin_min, blocking = margin, c["candidate_id"]
    if margin_min is None:                       # a single legal candidate cannot be displaced
        return {"certified": True, "reason": "single legal candidate", "margin_min": None}
    return {"certified": margin_min > 0, "reason": "bound" if margin_min > 0 else f"bound fails against candidate {blocking}",
            "margin_min": margin_min, "blocking_candidate": None if margin_min > 0 else blocking}


def analyze_state(rows, piece: int, precision: int, table: list[dict] | None = None) -> dict:
    """Exact-versus-quantized comparison of one common state for one quantized profile."""
    table = table if table is not None else candidate_table(rows, piece, (precision,))
    key = f"score_p{precision}"
    g = winner(table, "score_p0")
    h = winner(table, key)
    if g is None:
        return {"precision": precision, "legal_candidates": 0, "no_move": True}
    top_exact = [c["candidate_id"] for c in table if c["score_p0"] == g["score_p0"]]
    top_quant = [c["candidate_id"] for c in table if c[key] == h[key]]
    cert = certify(table, precision, g)
    changed = h["candidate_id"] != g["candidate_id"]
    if cert["certified"] and changed:
        raise AssertionError(f"certificate soundness violated: certified {g['candidate_id']} but P{precision} chose {h['candidate_id']}")
    return {
        "precision": precision, "legal_candidates": len(table), "no_move": False,
        "exact_winner": g["candidate_id"], "quantized_winner": h["candidate_id"], "changed": changed,
        "exact_gap": gap(table, "score_p0"), "quantized_gap_raw": gap(table, key),
        "exact_tie_size": len(top_exact), "quantized_tie_size": len(top_quant),
        "tie_introduced": len(top_exact) == 1 and len(top_quant) > 1,
        "tie_broken": len(top_exact) > 1 and len(top_quant) == 1,
        "certified": cert["certified"], "certificate_margin_min": cert["margin_min"], "certificate_reason": cert["reason"],
        # the exact winner's rank under quantization (0 = still first), for the score-gap narrative
        "exact_winner_quantized_rank": sorted(table, key=lambda c: (-c[key], c["candidate_id"])).index(g),
        "exact_winner_score_loss_p0": g["score_p0"] - h["score_p0"],     # >= 0: P0 score given up by the quantized choice
    }


def perturbation_summary(precision: int) -> dict:
    p = profile(precision)
    return {"precision": precision, "name": p.name, "levels": p.levels, "coefficients": list(p.coefficients),
            "exact_coefficients": list(EXACT_COEFFICIENTS), "delta": list(coefficient_perturbations(precision)),
            "max_error_bound": error_bound((4, 200, 200, 180), precision)}
