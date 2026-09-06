"""Serial row compaction, with awkward full-row patterns and reset."""
import cocotb

from common import cycle, pack, reset, rng, run_transaction, unpack

FULL = 1023


def reference(rows):
    survivors = [r for r in rows if r != FULL]
    return tuple(survivors + [0] * (20 - len(survivors))), 20 - len(survivors)


async def clear(dut, rows):
    n = await run_transaction(dut, lambda: setattr(dut.board_i, "value", pack(rows)), 40, "line_clear")
    return unpack(int(dut.board_o.value)), int(dut.count_o.value), n


@cocotb.test()
async def directed_full_rows(dut):
    await reset(dut)
    r = rng(5)
    patterns = [
        [], [0], [19], [0, 1], [0, 19], [3, 7, 11], [0, 1, 2, 3], [16, 17, 18, 19], [2, 5, 9, 14],
        list(range(20)), list(range(0, 20, 2)), list(range(1, 20, 2)), [5, 6, 7, 8, 9, 10],
    ]
    for full_rows in patterns:
        rows = [r.randrange(0, FULL) for _ in range(20)]
        for y in full_rows:
            rows[y] = FULL
        rows = tuple(rows)
        got, count, n = await clear(dut, rows)
        exp, exp_count = reference(rows)
        assert got == exp and count == exp_count, f"full rows {full_rows}: got count {count}"
        assert n <= 24, f"compaction took {n} cycles"


@cocotb.test()
async def random_boards(dut):
    await reset(dut)
    r = rng(6)
    for _ in range(300):
        rows = tuple(FULL if r.random() < 0.15 else r.randrange(0, FULL) for _ in range(20))
        got, count, _ = await clear(dut, rows)
        exp, exp_count = reference(rows)
        assert got == exp and count == exp_count


@cocotb.test()
async def reset_mid_scan_and_latching(dut):
    await reset(dut)
    rows = tuple([FULL] * 20)
    dut.board_i.value = pack(rows)
    dut.start_i.value = 1
    await cycle(dut)
    dut.start_i.value = 0
    dut.board_i.value = 0
    await cycle(dut, 5)
    assert int(dut.busy_o.value) == 1
    dut.rst.value = 1
    await cycle(dut)
    dut.rst.value = 0
    assert int(dut.busy_o.value) == 0
    got, count, _ = await clear(dut, rows)
    assert count == 20 and got == tuple([0] * 20)
    # latching: input changed after start must not affect the result
    rows = tuple([FULL, 5] + [0] * 18)
    dut.board_i.value = pack(rows)
    dut.start_i.value = 1
    await cycle(dut)
    dut.start_i.value = 0
    dut.board_i.value = 0
    n = 0
    while not int(dut.done_o.value):
        await cycle(dut)
        n += 1
        assert n < 40
    assert unpack(int(dut.board_o.value)) == tuple([5] + [0] * 19) and int(dut.count_o.value) == 1
