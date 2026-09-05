"""Board packing helpers.  A board is a tuple of twenty row integers, bottom row
first; bit x of rows[y] is one when cell (x,y) is occupied."""
from __future__ import annotations

W = 10
H = 20
FULL_ROW = (1 << W) - 1  # 1023
EMPTY_BOARD = tuple([0] * H)


def pack_rows(rows) -> int:
    validate_board(rows, normalized=False)
    return sum(rows[y] << (10 * y) for y in range(H))


def unpack_rows(value: int):
    if value < 0 or value >> (10 * H):
        raise ValueError("packed board out of range")
    return tuple((value >> (10 * y)) & FULL_ROW for y in range(H))


def validate_board(rows, normalized: bool = True) -> None:
    if len(rows) != H:
        raise ValueError(f"board must have {H} rows, got {len(rows)}")
    for y, row in enumerate(rows):
        if not isinstance(row, int) or isinstance(row, bool):
            raise ValueError(f"row {y} is not an int")
        if row < 0 or row > FULL_ROW:
            raise ValueError(f"row {y} value {row} outside 0..{FULL_ROW}")
        if normalized and row == FULL_ROW:
            raise ValueError(f"row {y} is full; normalized boards contain no full rows")


def board_words(rows):
    """Seven little-endian 32-bit words of the packed board (word 6 uses 8 bits)."""
    packed = pack_rows(rows)
    return [(packed >> (32 * i)) & 0xFFFFFFFF for i in range(7)]


def rows_from_words(words):
    packed = 0
    for i, w in enumerate(words):
        packed |= (w & 0xFFFFFFFF) << (32 * i)
    return unpack_rows(packed & ((1 << 200) - 1))


def occupied_count(rows) -> int:
    return sum(bin(r).count("1") for r in rows)


def render_text(rows) -> str:
    lines = []
    for y in range(H - 1, -1, -1):
        lines.append(f"{y:2d} " + "".join("#" if (rows[y] >> x) & 1 else "." for x in range(W)))
    return "\n".join(lines)
