"""A0 merge unit: exactly four previously-zero bits become one, for all legal fixtures and
random legal placements; inputs are latched at start."""
import cocotb

from common import cycle, pack, reset, run_transaction, unpack
from model.boards import mixed_boards
from model.game import drop_y, merged_board
from model.pieces import all_candidates, shape


async def merge(dut, rows, piece, rot, x, y):
    s = shape(piece, rot)

    def set_inputs():
        dut.board_i.value = pack(rows)
        dut.dx_i.value = sum(c[0] << (2 * k) for k, c in enumerate(s.cells))
        dut.dy_i.value = sum(c[1] << (2 * k) for k, c in enumerate(s.cells))
        dut.x_i.value = x
        dut.y_i.value = y
    n = await run_transaction(dut, set_inputs, 16, "merge_unit")
    return unpack(int(dut.board_o.value)), n


@cocotb.test()
async def random_legal_placements(dut):
    await reset(dut)
    boards = mixed_boards(99, 30)
    count = 0
    for rows in boards:
        for piece, rot, x in all_candidates():
            y = drop_y(rows, piece, rot, x)
            if y is None:
                continue
            got, n = await merge(dut, rows, piece, rot, x, y)
            exp = merged_board(rows, piece, rot, x, y)
            assert got == exp, f"piece {piece} rot {rot} x {x} y {y}"
            before = sum(bin(r).count("1") for r in rows)
            after = sum(bin(r).count("1") for r in got)
            assert after == before + 4
            assert n <= 8
            count += 1
    assert count > 1000


@cocotb.test()
async def same_row_cells_survive(dut):
    """Four cells of a horizontal I in one row must all be written (nonblocking-write hazard)."""
    await reset(dut)
    rows = tuple([0] * 20)
    got, _ = await merge(dut, rows, 0, 0, 3, 7)
    assert got[7] == 0b1111000 and sum(got) == got[7]


@cocotb.test()
async def latches_inputs(dut):
    await reset(dut)
    rows = tuple([0] * 20)
    s = shape(1, 0)
    dut.board_i.value = pack(rows)
    dut.dx_i.value = sum(c[0] << (2 * k) for k, c in enumerate(s.cells))
    dut.dy_i.value = sum(c[1] << (2 * k) for k, c in enumerate(s.cells))
    dut.x_i.value = 4; dut.y_i.value = 2
    dut.start_i.value = 1
    await cycle(dut)
    dut.start_i.value = 0
    dut.x_i.value = 0; dut.y_i.value = 0; dut.board_i.value = (1 << 200) - 1
    n = 0
    while not int(dut.done_o.value):
        await cycle(dut)
        n += 1
        assert n < 16
    assert unpack(int(dut.board_o.value)) == merged_board(rows, 1, 0, 4, 2)
