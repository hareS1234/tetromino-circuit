"""Canonical numerical profile table (PRECISION 0-4).

score = wL*L - wA*A - wQ*Q_used - wU*U_used
P3 replaces Q by min(Q,15) for scoring only; P4 omits U from scoring.  Physical
landing, collision and line clearing are never affected by a profile.
"""
from __future__ import annotations

from dataclasses import dataclass


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

    @property
    def coefficients(self):
        return (self.wl, self.wa, self.wq, self.wu)


PROFILES = {
    0: Profile(0, "exact", 76, 51, 36, 18, None, True),
    1: Profile(1, "powers_of_two", 64, 64, 32, 16, None, True),
    2: Profile(2, "two_terms", 80, 48, 36, 18, None, True),
    3: Profile(3, "cap_holes", 76, 51, 36, 18, 15, True),
    4: Profile(4, "no_bumpiness", 76, 51, 36, 0, None, False),
}

PRECISION_IDS = tuple(sorted(PROFILES))


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
