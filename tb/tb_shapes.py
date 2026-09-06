"""All 32 shape-ROM addresses, bad rotations included."""
import cocotb
from cocotb.triggers import Timer

from common import ROOT  # noqa: F401  (sets sys.path)
from model.pieces import rotation_count, shape


@cocotb.test()
async def all_32_inputs(dut):
    checked = 0
    for piece in range(8):
        for rot in range(4):
            dut.piece_i.value = piece
            dut.rot_i.value = rot
            await Timer(1, unit="ns")
            valid = int(dut.valid_o.value)
            if piece == 7 or rot >= rotation_count(piece):
                assert valid == 0, f"piece {piece} rot {rot} should be invalid"
                for sig in ("dx_o", "dy_o", "width_o", "height_o", "bottom_o", "colmask_o"):
                    assert int(getattr(dut, sig).value) == 0, f"{sig} not zero for invalid input"
            else:
                s = shape(piece, rot)
                assert valid == 1
                dx = int(dut.dx_o.value); dy = int(dut.dy_o.value)
                cells = [((dx >> (2 * k)) & 3, (dy >> (2 * k)) & 3) for k in range(4)]
                assert cells == list(s.cells), f"piece {piece} rot {rot}: {cells} != {s.cells}"
                assert int(dut.width_o.value) == s.width and int(dut.height_o.value) == s.height
                bottom = int(dut.bottom_o.value)
                assert [(bottom >> (2 * k)) & 3 for k in range(4)] == list(s.bottom)
                assert int(dut.colmask_o.value) == s.colmask
            checked += 1
    assert checked == 32
