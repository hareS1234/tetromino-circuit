"""Survival statistics on small cases where the answer fits on paper."""
from fractions import Fraction

import pytest

from model.survival import (NOT_REACHED, check_paired, kaplan_meier, median_survival, paired_bootstrap, restricted_mean,
                            rmst_from_survival, survival_points)


def test_restricted_mean_equals_sum_of_survival_with_common_cap():
    """mean(min(T, C)) == sum_{t<C} S(t) exactly when every censoring is at C (guide §9.5 identity)."""
    cap = 10
    cases = [
        ([0, 3, 5, 10, 10], [True, True, True, False, False]),          # events at zero and later, two censored at the cap
        ([10, 10, 10], [False, False, False]),                          # all censored
        ([0, 0, 0], [True, True, True]),                                # every game tops out immediately
        ([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], [True] * 9 + [False]),
        ([7, 7, 7, 2, 10, 10, 9], [True, True, True, True, False, False, True]),   # ties among event times
    ]
    for durations, events in cases:
        curve = kaplan_meier(durations, events, cap)
        assert curve[0] <= 1 and all(curve[t] >= curve[t + 1] for t in range(cap)) and len(curve) == cap + 1
        assert restricted_mean(durations) == rmst_from_survival(curve, cap)
        # with censoring only at C the product-limit estimate is the empirical P(T > t)
        n = len(durations)
        for t in range(cap):
            assert curve[t] == Fraction(sum(1 for d in durations if d > t), n)


def test_survival_extremes_and_median():
    cap = 100
    all_censored = kaplan_meier([cap] * 5, [False] * 5, cap)
    assert all(s == 1 for s in all_censored) and median_survival(all_censored, cap) == NOT_REACHED
    assert restricted_mean([cap] * 5) == cap
    immediate = kaplan_meier([0, 0, 0, 0], [True] * 4, cap)
    assert immediate[0] == 0 and median_survival(immediate, cap) == 0 and restricted_mean([0, 0, 0, 0]) == 0
    mixed = kaplan_meier([10, 20, 30, 100], [True, True, True, False], cap)
    assert mixed[9] == 1 and mixed[10] == Fraction(3, 4) and mixed[20] == Fraction(1, 2) and mixed[30] == Fraction(1, 4)
    assert median_survival(mixed, cap) == 20           # S(20) = 1/2 is the first t with S <= 1/2
    barely = kaplan_meier([60, 100, 100], [True, False, False], cap)
    assert median_survival(barely, cap) == NOT_REACHED  # S never drops to 1/2: 2/3 at the end
    pts = survival_points(mixed, cap, max_points=10)
    assert pts[0] == [0, 1.0] and pts[-1] == [cap, 0.25] and all(pts[i][0] < pts[i + 1][0] for i in range(len(pts) - 1))


def test_survival_with_censoring_before_the_cap_uses_product_limit():
    """Keep the KM estimator valid when observations are censored before the cap."""
    cap = 50
    curve = kaplan_meier([5, 10, 20, 50], [True, False, True, False], cap)     # one game censored at 10
    assert curve[4] == 1 and curve[5] == Fraction(3, 4)
    # at t = 20 the risk set is {20, 50} (the game censored at 10 left it): S = 3/4 * (1 - 1/2)
    assert curve[20] == Fraction(3, 8) and curve[49] == Fraction(3, 8)
    # the restricted-mean identity then does not hold (the guide's identity assumes a common cap)
    assert restricted_mean([5, 10, 20, 50]) != rmst_from_survival(curve, cap)


def test_invalid_inputs_are_rejected():
    with pytest.raises(ValueError):
        kaplan_meier([], [], 10)
    with pytest.raises(ValueError):
        kaplan_meier([11], [True], 10)                 # beyond the cap
    with pytest.raises(ValueError):
        kaplan_meier([10], [True], 10)                 # an observed event at the cap is impossible under the cap
    with pytest.raises(ValueError):
        kaplan_meier([1, 2], [True], 10)               # misaligned
    with pytest.raises(ValueError):
        restricted_mean([])
    with pytest.raises(ValueError):
        paired_bootstrap([1, 2], [1], 10, 0)


def test_paired_bootstrap_is_deterministic_and_paired():
    a = [100, 200, 300, 400, 500]
    b = [x + 10 for x in a]                            # constant paired difference: the CI collapses to it
    r1 = paired_bootstrap(a, b, 200, 7)
    r2 = paired_bootstrap(a, b, 200, 7)
    assert r1 == r2 and r1["mean_diff"] == 10 and r1["ci95"] == [10, 10] and r1["n_pairs"] == 5
    # unpaired variation is large, paired variation is small: the paired interval must not span zero here
    b2 = [x + 10 + (i % 2) for i, x in enumerate(a)]
    r3 = paired_bootstrap(a, b2, 500, 1)
    assert 10 <= r3["ci95"][0] <= r3["mean_diff"] <= r3["ci95"][1] <= 11
    assert paired_bootstrap(a, b, 200, 8)["ci95"] == [10, 10]


def test_check_paired_rejects_incomplete_duplicate_and_foreign_rows():
    rows = {"p0": [{"stream_seed": 1, "duration": 5, "event_observed": True, "lines": 2},
                   {"stream_seed": 2, "duration": 10, "event_observed": False, "lines": 4}],
            "p7": [{"stream_seed": 1, "duration": 3, "event_observed": True, "lines": 1}]}
    problems = check_paired(rows, [1, 2])
    assert any("p7" in p and "missing" in p for p in problems) and not any("p0" in p for p in problems)
    # consistent duplicates are tolerated, conflicting ones rejected
    rows["p7"].append({"stream_seed": 2, "duration": 10, "event_observed": False, "lines": 4})
    rows["p7"].append({"stream_seed": 2, "duration": 10, "event_observed": False, "lines": 4})
    assert check_paired(rows, [1, 2]) == []
    rows["p7"].append({"stream_seed": 2, "duration": 9, "event_observed": True, "lines": 4})
    assert any("conflicting duplicate" in p for p in check_paired(rows, [1, 2]))
    rows["p0"].append({"stream_seed": 3, "duration": 1, "event_observed": True, "lines": 0})
    assert any("unexpected streams" in p for p in check_paired(rows, [1, 2]))
