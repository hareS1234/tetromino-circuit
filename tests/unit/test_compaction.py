"""Prefix/select compaction against a deliberately boring local list filter."""
import random

import pytest

from model import compaction as cp

FULL = 0x3FF


def local_filter(rows):
    kept = []
    for r in rows:
        if r != FULL:
            kept.append(r)
    while len(kept) < 20:
        kept.append(0)
    return kept, sum(1 for r in rows if r == FULL)


FIXTURES = {
    "all_empty": [0] * 20,
    "all_full": [FULL] * 20,
    "bottom_full": [FULL] + [0] * 19,
    "top_full": [0] * 19 + [FULL],
    "alternating": [FULL if s % 2 == 0 else (s + 1) for s in range(20)],
    "survivor_at_top": [FULL] * 19 + [0x155],
    "survivor_at_bottom": [0x2AA] + [FULL] * 19,
    "zero_rows_between_survivors": [7, 0, 0, FULL, 9, 0, FULL, FULL, 0, 11] + [0] * 10,
    "four_full_spread": [1, FULL, 2, 3, FULL, 4, FULL, 5, 6, 7, 8, FULL, 9, 10, 11, 12, 13, 14, 15, 16],
}


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_fixture_matches_local_filter(name):
    rows = FIXTURES[name]
    out, cleared, survivors = cp.compact_prefix(rows)
    exp_rows, exp_cleared = local_filter(rows)
    assert out == exp_rows and cleared == exp_cleared and survivors == 20 - exp_cleared, name
    assert (out, cleared) == cp.compact_filter(rows)


def test_prefix_levels_read_only_the_previous_level():
    keep = [True] * 20
    levels = cp.prefix_levels(keep)
    assert len(levels) == 6 and levels[0] == [1] * 20
    for l, stride in enumerate(cp.STRIDES):
        prev, nxt = levels[l], levels[l + 1]
        assert nxt == [prev[s] + (prev[s - stride] if s >= stride else 0) for s in range(20)]
        assert max(nxt) <= 20
    assert levels[-1] == list(range(1, 21))
    # a level computed in place would differ: check the stride-1 level against an in-place scan
    inplace = [1] * 20
    for s in range(1, 20):
        inplace[s] = inplace[s] + inplace[s - 1]
    assert inplace != levels[1], "in-place accumulation is not the explicit level structure"


def test_ranks_are_unique_ordered_and_cover_survivors():
    rng = random.Random(1)
    for _ in range(5000):
        keep = [rng.random() < 0.6 for _ in range(20)]
        ranks = cp.inclusive_prefix(keep)
        survivors = [s for s in range(20) if keep[s]]
        assert ranks[19] == len(survivors)
        assert [ranks[s] for s in survivors] == list(range(1, len(survivors) + 1))
        for s in range(1, 20):
            assert ranks[s] - ranks[s - 1] == (1 if keep[s] else 0)


def test_match_has_at_most_one_source_per_destination():
    rng = random.Random(2)
    for _ in range(2000):
        keep = [rng.random() < 0.5 for _ in range(20)]
        m = cp.match_matrix(keep, cp.inclusive_prefix(keep))
        for d in range(20):
            assert sum(m[d]) <= 1
            assert sum(m[d]) == (1 if d < sum(keep) else 0)
        for s in range(20):
            assert sum(m[d][s] for d in range(20)) == (1 if keep[s] else 0)
        # destination never exceeds source: d <= s whenever match
        assert all(d <= s for d in range(20) for s in range(20) if m[d][s])


def test_random_boards_match_local_filter():
    rng = random.Random(3)
    n = 0
    for _ in range(12000):
        p_full = rng.choice((0.0, 0.1, 0.3, 0.6, 0.9))
        rows = [FULL if rng.random() < p_full else rng.randrange(0, FULL) for _ in range(20)]
        out, cleared, survivors = cp.compact_prefix(rows)
        assert (out, cleared) == local_filter(rows)
        assert survivors + cleared == 20
        n += 1
    assert n == 12000


def test_random_masks_with_tagged_rows():
    """Deletion pattern check (the native harness does all 2^20; here 20,000 random masks)."""
    rng = random.Random(4)
    for _ in range(20000):
        mask = rng.randrange(0, 1 << 20)
        rows = [(s + 1) if (mask >> s) & 1 else FULL for s in range(20)]  # unique non-full tags for survivors
        out, cleared, _ = cp.compact_prefix(rows)
        expected = [s + 1 for s in range(20) if (mask >> s) & 1]
        assert out == expected + [0] * (20 - len(expected)) and cleared == 20 - len(expected)


def test_packing_helpers():
    keep = [True, False] * 10
    assert cp.pack_keep(keep) == 0x55555
    assert cp.pack_ranks([1] * 20) == sum(1 << (5 * s) for s in range(20))
