"""Stable row compaction by inclusive prefix ranks and a guarded selection network (guide §6).

This is the DUT-shaped reference for rtl/row_rank20.sv and rtl/line_clear_parallel.sv: an
explicit five-level scan in which every node of one level reads only the previous level, then a
match/select network `match[d][s] = keep[s] and prefix[s] == d + 1`.  The independent oracle is the
list filter (`compact_filter`, also re-implemented locally in the tests without calling anything
here).  Boards are 20 rows of 10-bit integers, row 0 at the bottom; a row is full when it equals
1023.  Empty rows are survivors and keep their order; only full rows are removed.
"""
from __future__ import annotations

FULL = 0x3FF
ROWS = 20
STRIDES = (1, 2, 4, 8, 16)


def keep_mask(rows) -> list[bool]:
    return [int(r) != FULL for r in rows]


def prefix_levels(keep) -> list[list[int]]:
    """Return the six level vectors p0..p5 of the explicit inclusive scan (p5 = final ranks)."""
    levels = [[1 if k else 0 for k in keep]]
    for stride in STRIDES:
        prev = levels[-1]
        levels.append([prev[s] + (prev[s - stride] if s >= stride else 0) for s in range(ROWS)])
    return levels


def inclusive_prefix(keep) -> list[int]:
    return prefix_levels(keep)[-1]


def match_matrix(keep, ranks) -> list[list[bool]]:
    """match[d][s] for destination d and source s (20 x 20)."""
    return [[bool(keep[s]) and ranks[s] == d + 1 for s in range(ROWS)] for d in range(ROWS)]


def select_rows(rows, match) -> list[int]:
    """out_row[d] = OR over s of (row[s] & replicate(match[d][s])), formed as five groups of four."""
    out = []
    for d in range(ROWS):
        partials = []
        for g in range(5):
            acc = 0
            for s in range(4 * g, 4 * g + 4):
                acc |= int(rows[s]) if match[d][s] else 0
            partials.append(acc)
        # balanced OR of five partials: ((p0|p1) | (p2|p3)) | p4
        out.append(((partials[0] | partials[1]) | (partials[2] | partials[3])) | partials[4])
    return out


def compact_prefix(rows):
    """(compacted rows, cleared count, survivors) through the prefix/select network."""
    keep = keep_mask(rows)
    ranks = inclusive_prefix(keep)
    survivors = ranks[ROWS - 1]
    out = select_rows(rows, match_matrix(keep, ranks))
    return out, ROWS - survivors, survivors


def compact_filter(rows):
    """Independent oracle: the stable list filter, zero-padded at the top."""
    kept = [int(r) for r in rows if int(r) != FULL]
    return kept + [0] * (ROWS - len(kept)), ROWS - len(kept)


def pack_keep(keep) -> int:
    return sum(1 << s for s, k in enumerate(keep) if k)


def pack_ranks(ranks) -> int:
    return sum(int(r) << (5 * s) for s, r in enumerate(ranks))
