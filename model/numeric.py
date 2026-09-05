"""Canonical numerical profile table (PRECISION 0-7).

score = wL*L - wA*A - wQ*Q_used - wU*U_used
P3 replaces Q by min(Q,15) for scoring only; P4 omits U from scoring.  Physical
landing, collision and line clearing are never affected by a profile.

P5-P7 (v2, upgrade job U14; docs/A2_UPGRADE_GUIDE.md §9.1) are coefficient-magnitude
budgets of 4, 3 and 2 bits derived deterministically from the exact baseline by
`quantize_magnitudes`: for b bits, M = 2^b - 1 and q_i = round_half_up(w_i * M / 76).
Their raw scores are in their own units (the common positive scale 76/M is dropped
because it does not change the argmax); convert with `to_baseline_units` before
comparing a P5-P7 score with a P0 score.  `coeff_bits` and `score_width` are analysis
metadata (docs/precision_v2.md); the PRECISION id remains the configuration identity.
"""
from __future__ import annotations

from dataclasses import dataclass

EXACT_COEFFICIENTS = (76, 51, 36, 18)
# conservative feature bounds after a legal placement (docs/spec.md): A <= 200, Q <= 200, U <= 180, L <= 4
FEATURE_BOUNDS = {"L": 4, "A": 200, "Q": 200, "U": 180}


@dataclass(frozen=True)
class Profile:
    precision: int
    name: str
    wl: int
    wa: int
    wq: int
    wu: int
    q_cap: int | None   # None = exact Q
    use_u: bool
    coeff_bits: int | None = None   # P5-P7: magnitude budget in bits (M = 2^bits - 1); None = exact/structural
    score_width: int = 32           # sufficient signed width of the score in the profile's own units

    @property
    def coefficients(self):
        return (self.wl, self.wa, self.wq, self.wu)

    @property
    def levels(self) -> int | None:
        """M = 2^bits - 1 for a quantized profile, None otherwise."""
        return None if self.coeff_bits is None else (1 << self.coeff_bits) - 1


def quantize_magnitudes(bits: int) -> tuple[int, ...]:
    """Coefficient magnitudes for a b-bit budget: M = 2^b - 1, nearest rounding with positive
    half-ties upward, in integer arithmetic (guide §9.1)."""
    assert bits in (2, 3, 4)
    m = (1 << bits) - 1
    return tuple((2 * w * m + 76) // 152 for w in EXACT_COEFFICIENTS)


def sufficient_score_width(coefficients, q_cap=None, use_u=True, max_lines=4) -> int:
    """Smallest signed width holding every score for the conservative feature bounds."""
    wl, wa, wq, wu = coefficients
    qmax = FEATURE_BOUNDS["Q"] if q_cap is None else q_cap
    lo = -(wa * FEATURE_BOUNDS["A"] + wq * qmax + (wu * FEATURE_BOUNDS["U"] if use_u else 0))
    hi = wl * max_lines
    width = 1
    while not (-(1 << (width - 1)) <= lo and hi <= (1 << (width - 1)) - 1):
        width += 1
    return width


def _quantized(precision: int, name: str, bits: int) -> Profile:
    wl, wa, wq, wu = quantize_magnitudes(bits)
    return Profile(precision, name, wl, wa, wq, wu, None, True, bits, sufficient_score_width((wl, wa, wq, wu)))


PROFILES = {
    0: Profile(0, "exact", 76, 51, 36, 18, None, True),
    1: Profile(1, "powers_of_two", 64, 64, 32, 16, None, True),
    2: Profile(2, "two_terms", 80, 48, 36, 18, None, True),
    3: Profile(3, "cap_holes", 76, 51, 36, 18, 15, True),
    4: Profile(4, "no_bumpiness", 76, 51, 36, 0, None, False),
    5: _quantized(5, "coeff_u4", 4),   # (15, 10, 7, 4), score in [-4120, 60], 14 signed bits
    6: _quantized(6, "coeff_u3", 3),   # (7, 5, 3, 2),   score in [-1960, 28], 12 signed bits
    7: _quantized(7, "coeff_u2", 2),   # (3, 2, 1, 1),   score in [-780, 12],  11 signed bits
}

PRECISION_IDS = tuple(sorted(PROFILES))
V1_PRECISION_IDS = (0, 1, 2, 3, 4)
QUANTIZED_PRECISION_IDS = (5, 6, 7)

# the specification's frozen expectations (guide §9.1); checked in tests/unit/test_precision_v2.py
assert PROFILES[5].coefficients == (15, 10, 7, 4) and PROFILES[5].score_width == 14
assert PROFILES[6].coefficients == (7, 5, 3, 2) and PROFILES[6].score_width == 12
assert PROFILES[7].coefficients == (3, 2, 1, 1) and PROFILES[7].score_width == 11


def profile(precision: int) -> Profile:
    if precision not in PROFILES:
        raise ValueError(f"unknown PRECISION {precision}")
    return PROFILES[precision]


def features_used(feats, precision: int = 0):
    """Scoring features (A, Q_used, U_used) for a profile."""
    p = profile(precision)
    a, q, u = feats
    if p.q_cap is not None:
        q = min(q, p.q_cap)
    if not p.use_u:
        u = 0
    return a, q, u


def score_profile(feats, lines: int, precision: int = 0) -> int:
    p = profile(precision)
    a, q, u = features_used(feats, precision)
    return p.wl * lines - p.wa * a - p.wq * q - p.wu * u


def score_bounds(precision: int = 0, max_lines: int = 4):
    """Conservative (min, max) of the score with A<=200, Q<=200, U<=180."""
    p = profile(precision)
    qmax = 200 if p.q_cap is None else p.q_cap
    lo = -(p.wa * 200 + p.wq * qmax + (p.wu * 180 if p.use_u else 0))
    hi = p.wl * max_lines
    return lo, hi


def to_baseline_units(score: int, precision: int):
    """Exact rational conversion of a quantized profile's raw score into P0 units: 76 * score / M.
    Returns a `fractions.Fraction`; raw P5-P7 scores must not be compared with P0 scores directly."""
    from fractions import Fraction
    p = profile(precision)
    if p.levels is None:
        return Fraction(score)
    return Fraction(76 * score, p.levels)


def coefficient_perturbations(precision: int) -> tuple[int, ...]:
    """delta_i = 76 * q_i - M * w_i for a quantized profile (integers, guide §9.3)."""
    p = profile(precision)
    if p.levels is None:
        raise ValueError(f"PRECISION {precision} is not a quantized profile")
    return tuple(76 * q - p.levels * w for q, w in zip(p.coefficients, EXACT_COEFFICIENTS))


def error_bound(features_lqau, precision: int) -> int:
    """E(c) = sum |delta_i| * feature_i(c) for a candidate's (L, A, Q, U) in scaled units."""
    return sum(abs(d) * f for d, f in zip(coefficient_perturbations(precision), features_lqau))


def profile_metadata(precision: int) -> dict:
    """Configuration-record fields for a profile: id, name, coefficient vector, bits, widths, range."""
    p = profile(precision)
    lo, hi = score_bounds(precision)
    return {"precision": p.precision, "name": p.name, "coefficients": list(p.coefficients),
            "coeff_bits": p.coeff_bits, "levels": p.levels, "score_width": p.score_width,
            "score_range": [lo, hi], "q_cap": p.q_cap, "use_u": p.use_u,
            "units": "baseline" if p.levels is None else f"raw (76/{p.levels} of baseline)"}
