import pytest

from model.board import (EMPTY_BOARD, FULL_ROW, board_words, pack_rows, rows_from_words,
                         unpack_rows, validate_board)


def test_pack_unpack_round_trip_random():
    import random
    rng = random.Random(7)
    for _ in range(500):
        rows = tuple(rng.randrange(0, 1023) for _ in range(20))
        assert unpack_rows(pack_rows(rows)) == rows
        assert rows_from_words(board_words(rows)) == rows


def test_every_one_hot_cell_maps_to_bit_10y_plus_x():
    for y in range(20):
        for x in range(10):
            rows = [0] * 20
            rows[y] = 1 << x
            packed = pack_rows(tuple(rows))
            assert packed == 1 << (10 * y + x)
            assert unpack_rows(packed) == tuple(rows)
            words = board_words(tuple(rows))
            bit = 10 * y + x
            assert words[bit // 32] == 1 << (bit % 32)
            assert sum(words) == 1 << (bit % 32)


def test_validate_rejects_bad_boards():
    with pytest.raises(ValueError):
        validate_board(tuple([0] * 19))
    with pytest.raises(ValueError):
        validate_board(tuple([-1] + [0] * 19))
    with pytest.raises(ValueError):
        validate_board(tuple([1024] + [0] * 19))
    with pytest.raises(ValueError):
        validate_board(tuple([FULL_ROW] + [0] * 19), normalized=True)
    validate_board(tuple([FULL_ROW] + [0] * 19), normalized=False)
    validate_board(EMPTY_BOARD)


def test_unpack_rejects_out_of_range():
    with pytest.raises(ValueError):
        unpack_rows(1 << 200)
    with pytest.raises(ValueError):
        unpack_rows(-1)
