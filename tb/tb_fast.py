"""A1 datapath modules vs the oracle: column transpose, heights (0,15,16,19,20 and one-hot
boards), hole masks and counts, closed-form landing on the full candidate corpus including the
high-overhang regression, one-cycle mask merge, and two-stage parallel features."""
import cocotb
from cocotb.triggers import Timer

from common import cycle, load_fixtures, pack, pack_heights, param, reset, rows_of, unpack
from model import fast
from model.boards import mixed_boards
from model.features import column_heights, features
from model.game import drop_y, merged_board, physical_landing
from model.numeric import features_used
from model.pieces import all_candidates, rotation_count

PREC = param("PRECISION", 0)


def hole_mask(rows, c):
    h = column_heights(rows)[c]
    col = sum(((rows[y] >> c) & 1) << y for y in range(20))
    return ((1 << h) - 1) & ~col & 0xFFFFF


@cocotb.test()
async def profile_heights_columns_holes(dut):
    await reset(dut)
    cases = list(mixed_boards(5150, 300))
    for y in range(20):
        for x in range(10):
            rows = [0] * 20
            rows[y] = 1 << x
            cases.append(tuple(rows))
    cases += [tuple([0] * 20), tuple([1023 & ~1] * 20), tuple([1] * 15 + [0] * 5), tuple([1] * 16 + [0] * 4),
              tuple([1] * 19 + [0]), tuple([0] * 19 + [1]), tuple([0] * 4 + [1023 & ~2] + [0] * 15)]
    for rows in cases:
        dut.board_i.value = pack(rows)
        await Timer(1, unit="ns")
        got_h = [(int(dut.heights_o.value) >> (5 * i)) & 31 for i in range(10)]
        assert got_h == column_heights(rows), f"heights {got_h} != {column_heights(rows)}"
        cols = int(dut.columns_o.value)
        holes = int(dut.holes_o.value)
        for c in range(10):
            col = sum(((rows[y] >> c) & 1) << y for y in range(20))
            assert (cols >> (20 * c)) & 0xFFFFF == col, f"column {c} transpose"
            assert (holes >> (20 * c)) & 0xFFFFF == hole_mask(rows, c), f"column {c} hole mask"


async def drop(dut, rows, piece, rot, x):
    dut.board_i.value = pack(rows)
    dut.drop_heights_i.value = pack_heights(column_heights(rows))
    dut.piece_i.value = piece; dut.rot_i.value = rot; dut.x_i.value = x
    dut.drop_start_i.value = 1
    await cycle(dut)
    dut.drop_start_i.value = 0
    await cycle(dut)
    assert int(dut.drop_done_o.value) == 1, "drop_fast must complete two cycles after start"
    return int(dut.drop_legal_o.value), int(dut.drop_y_o.value), int(dut.drop_phys_o.value)


@cocotb.test()
async def closed_form_landing(dut):
    await reset(dut)
    fx = load_fixtures()
    for f in fx["placements"]:
        rows = rows_of(f["rows"])
        legal, y, phys = await drop(dut, rows, f["piece"], f["rotation"], f["x"])
        e = f["expected"]
        if e["legal"]:
            assert legal == 1 and y == e["y"], f["name"]
        else:
            assert legal == 0 and y == 0, f["name"]
    count = 0
    for rows in mixed_boards(8080, 60):
        for piece, rot, x in all_candidates():
            legal, y, phys = await drop(dut, rows, piece, rot, x)
            exp = drop_y(rows, piece, rot, x)
            assert legal == (exp is not None), f"piece {piece} rot {rot} x {x} rows {rows}"
            if exp is not None:
                assert y == exp
                assert phys == physical_landing(rows, piece, rot, x)
            count += 1
        # invalid geometry
        for piece in range(7):
            for rot in range(rotation_count(piece), 4):
                legal, y, _ = await drop(dut, rows, piece, rot, 0)
                assert legal == 0 and y == 0
    assert count == 9720


@cocotb.test()
async def mask_merge(dut):
    await reset(dut)
    n = 0
    for rows in mixed_boards(9090, 40):
        for piece, rot, x in all_candidates():
            y = drop_y(rows, piece, rot, x)
            if y is None:
                continue
            dut.board_i.value = pack(rows)
            dut.piece_i.value = piece; dut.rot_i.value = rot; dut.x_i.value = x; dut.merge_y_i.value = y
            dut.merge_start_i.value = 1
            await cycle(dut)
            dut.merge_start_i.value = 0
            assert int(dut.merge_done_o.value) == 1
            assert unpack(int(dut.merged_o.value)) == merged_board(rows, piece, rot, x, y)
            n += 1
    assert n > 1000
    # horizontal I: all four same-row cells present
    dut.board_i.value = 0; dut.piece_i.value = 0; dut.rot_i.value = 0; dut.x_i.value = 6; dut.merge_y_i.value = 12
    dut.merge_start_i.value = 1
    await cycle(dut)
    dut.merge_start_i.value = 0
    assert unpack(int(dut.merged_o.value))[12] == 0b1111000000


@cocotb.test()
async def parallel_features(dut):
    await reset(dut)
    cases = list(mixed_boards(7070, 500))
    for y in range(20):
        for x in range(10):
            rows = [0] * 20
            rows[y] = 1 << x
            cases.append(tuple(rows))
    cases += [tuple([0, 1] + [0] * 18), tuple([1] * 20), tuple([0b0101010101] * 20), tuple([0b1010101010] * 19 + [0])]
    for rows in cases:
        dut.board_i.value = pack(rows)
        dut.feat_start_i.value = 1
        await cycle(dut)
        dut.feat_start_i.value = 0
        await cycle(dut)
        assert int(dut.feat_done_o.value) == 1, "features_fast must complete two cycles after start"
        got = (int(dut.a_o.value), int(dut.q_o.value), int(dut.u_o.value))
        exp = features_used(features(rows), PREC)
        assert got == exp, f"features {got} != {exp} for {rows}"
        h = [(int(dut.feat_heights_o.value) >> (5 * i)) & 31 for i in range(10)]
        assert h == column_heights(rows)
