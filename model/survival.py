"""Censoring-aware statistics for the v2 quality study (U15, guide §9.5).

Event time T = locked pieces before the first top-out decision.  A game stopped at the cap C
reports duration C with event_observed = False (right-censored at C).  Everything here is exact
integer/rational arithmetic (fractions) except the bootstrap, which is a fixed-seed resampling of
whole streams.

* restricted_mean(durations)          mean(min(T, C)) — the mean of the reported durations, an
                                        estimate of the restricted mean to C, never of unbounded survival
* kaplan_meier(durations, events)      discrete survival S(t) = P(T > t) for t = 0..C with product-limit
                                        estimation (censoring may occur at any time; a censored game at t is
                                        at risk at t)
* rmst_from_survival(curve, cap)       sum_{t=0}^{C-1} S(t): equals restricted_mean exactly when every
                                        censoring is at C (checked in tests/unit/test_statistics_v2.py)
* median_survival(curve, cap)          smallest t with S(t) <= 1/2 or 'not reached by C'
* paired_bootstrap(a, b, n, seed)      CI of mean(b - a) resampling paired stream ids jointly
"""
from __future__ import annotations

import random
from fractions import Fraction

NOT_REACHED = "not reached"


def restricted_mean(durations) -> Fraction:
    durations = list(durations)
    if not durations:
        raise ValueError("no games")
    return Fraction(sum(durations), len(durations))


def kaplan_meier(durations, events, cap: int) -> list[Fraction]:
    """S(t) = P(T > t) for t = 0..cap (list of cap+1 exact fractions), product-limit estimate.

    durations[i] is the reported duration of game i (event time or censoring time), events[i]
    whether the top-out was observed.  A game censored at time t is at risk for events at t.
    """
    durations, events = list(durations), list(events)
    if len(durations) != len(events) or not durations:
        raise ValueError("durations and events must be non-empty and aligned")
    if any(d < 0 or d > cap for d in durations):
        raise ValueError("a duration lies outside [0, cap]")
    if any(e and d == cap for d, e in zip(durations, events)):
        # duration counts locked pieces: an event at t = cap would be a top-out on decision cap+1,
        # which the cap prevents from being observed under a common administrative cap
        raise ValueError("an observed event cannot occur at the cap (the cap stops the game before that decision)")
    n = len(durations)
    curve = []
    s = Fraction(1)
    for t in range(cap + 1):
        at_risk = sum(1 for d in durations if d >= t)
        d_t = sum(1 for d, e in zip(durations, events) if e and d == t)
        if at_risk > 0 and d_t > 0:
            s = s * (1 - Fraction(d_t, at_risk))
        curve.append(s)
    assert len(curve) == cap + 1 and n > 0
    return curve


def rmst_from_survival(curve, cap: int) -> Fraction:
    """Discrete restricted mean survival time: sum_{t=0}^{C-1} S(t) where S(t) = P(T > t)."""
    return sum((Fraction(x) for x in curve[:cap]), Fraction(0))


def median_survival(curve, cap: int):
    """Smallest t with S(t) <= 1/2, or NOT_REACHED when the estimated survival never crosses 1/2 within [0, cap)."""
    for t in range(cap):
        if curve[t] <= Fraction(1, 2):
            return t
    return NOT_REACHED


def survival_points(curve, cap: int, max_points: int = 200) -> list[list]:
    """Down-sampled (t, S(t)) pairs for plotting/serialisation, always including t = 0 and t = cap."""
    step = max(1, cap // max_points)
    ts = sorted(set(list(range(0, cap + 1, step)) + [cap]))
    return [[t, float(curve[t])] for t in ts]


def paired_bootstrap(a, b, resamples: int, seed: int) -> dict:
    """CI of mean(b - a) resampling paired units (stream ids) jointly, fixed seed; effect = mean difference."""
    a, b = list(a), list(b)
    if len(a) != len(b) or not a:
        raise ValueError("paired series must be non-empty and equally long")
    rng = random.Random(seed)
    diffs = [y - x for x, y in zip(a, b)]
    k = len(diffs)
    means = []
    for _ in range(resamples):
        means.append(sum(diffs[rng.randrange(k)] for _ in range(k)) / k)
    means.sort()
    lo = means[int(0.025 * resamples)]
    hi = means[min(resamples - 1, int(0.975 * resamples))]
    return {"mean_diff": sum(diffs) / k, "ci95": [lo, hi], "n_pairs": k, "resamples": resamples, "seed": seed,
            "procedure": "paired bootstrap of mean(b - a): resample stream ids with replacement, 2.5/97.5 percentiles"}


def check_paired(rows_by_policy: dict, expected_streams) -> list[str]:
    """Problems that make a paired summary invalid: missing games, duplicates that disagree, unexpected streams."""
    problems = []
    expected = set(expected_streams)
    for pk, rows in rows_by_policy.items():
        seen = {}
        for r in rows:
            s = r["stream_seed"]
            key = (r["duration"], r["event_observed"], r["lines"])
            if s in seen and seen[s] != key:
                problems.append(f"{pk}: stream {s} has conflicting duplicate records {seen[s]} vs {key}")
            seen[s] = key
        missing = sorted(expected - set(seen))
        extra = sorted(set(seen) - expected)
        if missing:
            problems.append(f"{pk}: {len(missing)} streams missing ({missing[:5]}…)" if len(missing) > 5 else f"{pk}: streams missing {missing}")
        if extra:
            problems.append(f"{pk}: unexpected streams {extra[:5]}")
    return problems
