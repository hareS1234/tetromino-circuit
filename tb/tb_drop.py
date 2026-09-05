"""A0 drop unit vs the literal-descent oracle: fixtures, walls/floor/tall columns, blocked entry,
both overhang fixtures, and every orientation/x on 50 mixed boards (8,100 candidates)."""
import cocotb

from common import cycle, load_fixtures, pack, reset, rows_of, run_transaction
from model.boards import mixed_boards
from model.game import drop_y, physical_landing
from model.pieces import all_candidates, rotation_count, shape

TIMEOUT = 64


async def drop(dut, rows, piece, rot, x):
    valid = rot < rotation_count(piece)
    s = shape(piece, rot) if valid else None

    def set_inputs():
        dut.board_i.value = pack(rows)
        dut.dx_i.value = sum(c[0] << (2 * k) for k, c in enumerate(s.cells)) if valid else 0
        dut.dy_i.value = sum(c[1] << (2 * k) for k, c in enumerate(s.cells)) if valid else 0
        dut.width_i.value = s.width if valid else 0
        dut.height_i.value = s.height if valid else 0
        dut.shape_valid_i.value = 1 if valid else 0
        dut.x_i.value = x
    n = await run_transaction(dut, set_inputs, TIMEOUT, "drop_unit")
    return int(dut.legal_o.value), int(dut.y_o.value), int(dut.phys_y_o.value), n


def check(rows, piece, rot, x, legal, y, phys):
    exp = drop_y(rows, piece, rot, x) if rot < rotation_count(piece) else None
    exp_phys = physical_landing(rows, piece, rot, x) if rot < rotation_count(piece) else None
    assert legal == (exp is not None), f"piece {piece} rot {rot} x {x}: legal {legal}, oracle {exp} rows {rows}"
    if exp is not None:
        assert y == exp, f"piece {piece} rot {rot} x {x}: y {y} != {exp}"
        assert phys == exp
    else:
        assert y == 0
        if exp_phys is not None:
            assert phys == exp_phys, f"physical anchor {phys} != {exp_phys}"


@cocotb.test()
async def hand_fixtures(dut):
    await reset(dut)
    fx = load_fixtures()
    for f in fx["placements"]:
        rows = rows_of(f["rows"])
        legal, y, phys, _ = await drop(dut, rows, f["piece"], f["rotation"], f["x"])
        e = f["expected"]
        if e["legal"]:
            assert legal == 1 and y == e["y"], f["name"]
        else:
            assert legal == 0 and y == 0 and phys == e["physical_y"], f["name"]


@cocotb.test()
async def walls_floor_and_geometry(dut):
    await reset(dut)
    empty = tuple([0] * 20)
    # every candidate on an empty board lands at y=0; x past the wall or a bad rotation is illegal
    for piece in range(7):
        for rot in range(4):
            for x in range(10):
                legal, y, phys, n = await drop(dut, empty, piece, rot, x)
                check(empty, piece, rot, x, legal, y, phys)
                assert n <= 26, f"descent took {n} cycles"
    # a full-height column at x=0 and a tall stack: O next to it and on top of it
    rows = tuple([1] * 20)
    for x in range(9):
        legal, y, phys, _ = await drop(dut, rows, 1, 0, x)
        check(rows, piece := 1, 0, x, legal, y, phys)
    stack = tuple([1023 & ~1] * 18 + [0, 0])   # 18 rows full except column 0
    for piece in range(7):
        for rot in range(rotation_count(piece)):
            for x in range(10):
                legal, y, phys, _ = await drop(dut, stack, piece, rot, x)
                check(stack, piece, rot, x, legal, y, phys)


@cocotb.test()
async def mixed_boards_all_candidates(dut):
    await reset(dut)
    boards = mixed_boards(777, 50)
    cands = all_candidates()
    count = 0
    for rows in boards:
        for piece, rot, x in cands:
            legal, y, phys, _ = await drop(dut, rows, piece, rot, x)
            check(rows, piece, rot, x, legal, y, phys)
            count += 1
    assert count == 8100


@cocotb.test()
async def latching_and_reset(dut):
    await reset(dut)
    rows = tuple([0] * 20)
    s = shape(1, 0)
    dut.board_i.value = pack(rows)
    dut.dx_i.value = sum(c[0] << (2 * k) for k, c in enumerate(s.cells))
    dut.dy_i.value = sum(c[1] << (2 * k) for k, c in enumerate(s.cells))
    dut.width_i.value = s.width; dut.height_i.value = s.height; dut.shape_valid_i.value = 1; dut.x_i.value = 3
    dut.start_i.value = 1
    await cycle(dut)
    dut.start_i.value = 0
    # change every input while busy: the latched request must still decide the answer
    dut.board_i.value = pack(tuple([1023 & ~8] * 19 + [0]))
    dut.x_i.value = 9
    dut.shape_valid_i.value = 0
    n = 0
    while not int(dut.done_o.value):
        await cycle(dut)
        n += 1
        assert n < TIMEOUT
    assert int(dut.legal_o.value) == 1 and int(dut.y_o.value) == 0
    # reset in the middle of a descent
    dut.board_i.value = pack(rows); dut.shape_valid_i.value = 1; dut.x_i.value = 0
    dut.start_i.value = 1
    await cycle(dut)
    dut.start_i.value = 0
    await cycle(dut, 5)
    assert int(dut.busy_o.value) == 1
    dut.rst.value = 1
    await cycle(dut)
    dut.rst.value = 0
    assert int(dut.busy_o.value) == 0 and int(dut.done_o.value) == 0
    legal, y, phys, _ = await drop(dut, rows, 1, 0, 0)
    assert legal == 1 and y == 0
