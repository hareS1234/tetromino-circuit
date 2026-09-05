"""Feature extractor vs model.features: all 200 one-hot boards, the single-hole fixture,
alternating tall/empty columns, and 500 generated boards.  A, Q, U checked individually;
PRECISION 3 expects min(Q,15), PRECISION 4 expects U=0."""
import cocotb

from common import pack, param, reset, run_transaction
from model.boards import mixed_boards
from model.features import column_heights, features
from model.numeric import features_used

PREC = param("PRECISION", 0)


async def feat(dut, rows):
    n = await run_transaction(dut, lambda: setattr(dut.board_i, "value", pack(rows)), 260, "features")
    heights = [(int(dut.heights_o.value) >> (5 * i)) & 31 for i in range(10)]
    return int(dut.a_o.value), int(dut.q_o.value), int(dut.u_o.value), heights, n


def check(rows, a, q, u, heights):
    ea, eq, eu = features_used(features(rows), PREC)
    assert (a, q, u) == (ea, eq, eu), f"A/Q/U {(a, q, u)} != {(ea, eq, eu)} for {rows}"
    assert heights == column_heights(rows)


@cocotb.test()
async def one_hot_boards(dut):
    await reset(dut)
    for y in range(20):
        for x in range(10):
            rows = [0] * 20
            rows[y] = 1 << x
            a, q, u, h, n = await feat(dut, tuple(rows))
            check(tuple(rows), a, q, u, h)
            assert n <= 216, f"scan took {n} cycles"


@cocotb.test()
async def directed_boards(dut):
    await reset(dut)
    cases = [
        tuple([0, 1] + [0] * 18),                      # single hole under (0,1): (2,1,2)
        tuple([1] * 20),                               # full column 0: (20,0,20)
        tuple([0b0101010101] * 20),                    # alternating full-height columns
        tuple([0b1010101010] * 19 + [0]),
        tuple([0, 1, 0, 0, 0, 1] + [0] * 14),          # separated blocks: holes counted once per empty cell
        tuple([1023 & ~1] * 18 + [0, 0]),
        tuple([0] * 19 + [1023 & ~512]),               # occupied top row with everything below empty
    ]
    for rows in cases:
        a, q, u, h, _ = await feat(dut, rows)
        check(rows, a, q, u, h)


@cocotb.test()
async def generated_boards_500(dut):
    await reset(dut)
    for rows in mixed_boards(31337, 500):
        a, q, u, h, _ = await feat(dut, rows)
        check(rows, a, q, u, h)
