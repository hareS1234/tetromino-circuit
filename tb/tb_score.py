"""Registered scorer vs model.numeric for the compiled PRECISION profile."""
import cocotb

from common import cycle, param, reset, rng, signed32
from model.numeric import profile, score_bounds, score_profile

PREC = param("PRECISION", 0)


async def score_of(dut, a, q, u, l):
    dut.a_i.value = a; dut.q_i.value = q; dut.u_i.value = u; dut.l_i.value = l
    dut.valid_i.value = 1
    await cycle(dut)
    dut.valid_i.value = 0
    assert int(dut.valid_o.value) == 1, "valid_o must follow valid_i by one cycle"
    got = signed32(int(dut.score_o.value))
    await cycle(dut)
    assert int(dut.valid_o.value) == 0
    assert signed32(int(dut.score_o.value)) == got, "score must hold after valid drops"
    return got


def expected(a, q, u, l):
    # the scorer receives Q_used / U_used already; for profile 3/4 the inputs are pre-processed
    p = profile(PREC)
    return p.wl * l - p.wa * a - p.wq * q - p.wu * u


@cocotb.test()
async def directed_boundaries(dut):
    await reset(dut)
    cases = [(0, 0, 0, 0), (0, 0, 0, 4), (200, 190, 180, 0), (200, 200, 180, 4), (127, 0, 0, 0), (128, 0, 0, 0),
             (0, 127, 0, 0), (0, 128, 0, 0), (0, 0, 127, 0), (0, 0, 128, 0), (190, 190, 0, 1), (255, 255, 255, 7),
             (0, 15, 0, 0), (0, 16, 0, 0), (0, 14, 0, 0)]
    if PREC >= 5:
        # P5-P7 form the sum at the profile's sufficient signed width (14/12/11 bits) and rely on the
        # feature-unit bounds A<=200, Q<=200, U<=180, L<=4 (asserted in the RTL); the out-of-contract
        # tuple (255,255,255,7) is not a valid input for them, the bounded extremes stay in the list
        cases = [c for c in cases if c != (255, 255, 255, 7)]
        cases += [(200, 0, 0, 0), (0, 200, 0, 0), (0, 0, 180, 0), (1, 1, 1, 4), (0, 0, 0, 1), (200, 200, 180, 0)]
    for a, q, u, l in cases:
        got = await score_of(dut, a, q, u, l)
        assert got == expected(a, q, u, l), f"({a},{q},{u},{l}): got {got} expected {expected(a, q, u, l)}"
    if PREC >= 5:
        # the extremes of the conservative range appear on the port sign-extended, not wrapped
        lo, hi = score_bounds(PREC)
        assert await score_of(dut, 200, 200, 180, 0) == lo and await score_of(dut, 0, 0, 0, 4) == hi
        assert -(1 << (profile(PREC).score_width - 1)) <= lo and hi < (1 << (profile(PREC).score_width - 1))


@cocotb.test()
async def random_tuples_1000(dut):
    await reset(dut)
    r = rng(1234 + PREC)
    for _ in range(1000):
        a, q, u, l = r.randint(0, 200), r.randint(0, 200), r.randint(0, 180), r.randint(0, 4)
        if PREC == 3:
            q = min(q, 15)
        if PREC == 4:
            u = 0
        got = await score_of(dut, a, q, u, l)
        assert got == expected(a, q, u, l), f"({a},{q},{u},{l}): got {got}"
        if PREC == 0:
            assert got == score_profile((a, q, u), l, 0)


@cocotb.test()
async def reset_clears_valid(dut):
    await reset(dut)
    dut.a_i.value = 1; dut.q_i.value = 0; dut.u_i.value = 0; dut.l_i.value = 0; dut.valid_i.value = 1
    dut.rst.value = 1
    await cycle(dut)
    assert int(dut.valid_o.value) == 0 and int(dut.score_o.value) == 0
    dut.rst.value = 0
    dut.valid_i.value = 0
    await cycle(dut)
    assert int(dut.valid_o.value) == 0
