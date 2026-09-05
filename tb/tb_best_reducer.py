"""U11 (V10): winner hazards on the reducer alone — all illegal, one legal, last wins, exact score
ties (lower id wins whatever the arrival order, highest id first), signed comparisons between
negative scores, clear between searches, and a randomized shadow model."""
import cocotb

from common import cycle, fall, reset, rise, rng, signed32


async def push(dut, valid, legal, score, cid, y, clear=0):
    await fall(dut)
    dut.clear_i.value = clear
    dut.valid_i.value = valid
    dut.legal_i.value = legal
    dut.score_i.value = score & 0xFFFFFFFF
    dut.id_i.value = cid
    dut.y_i.value = y
    await rise(dut)


def best(dut):
    return (int(dut.best_valid_o.value), signed32(int(dut.best_score_o.value)), int(dut.best_id_o.value), int(dut.best_y_o.value))


def shadow(tokens):
    b = None
    for valid, legal, score, cid, y in tokens:
        if valid and legal and (b is None or score > b[0] or (score == b[0] and cid < b[1])):
            b = (score, cid, y)
    return (0, 0, 0, 0) if b is None else (1, b[0], b[1], b[2])


@cocotb.test()
async def directed_hazards(dut):
    await reset(dut)
    # all illegal
    for i in range(6):
        await push(dut, 1, 0, 100 + i, i, 3)
    assert best(dut) == (0, 0, 0, 0)
    # one legal among illegal
    await push(dut, 1, 1, -300, 17, 4)
    await push(dut, 1, 0, 999, 2, 1)
    assert best(dut) == (1, -300, 17, 4)
    # last wins: strictly better score arriving last
    await push(dut, 1, 1, -299, 20, 5)
    assert best(dut) == (1, -299, 20, 5)
    # exact tie: highest id arrived first, lower id must win
    await push(dut, 1, 1, -299, 3, 6)
    assert best(dut) == (1, -299, 3, 6)
    # exact tie with a higher id later: unchanged
    await push(dut, 1, 1, -299, 30, 7)
    assert best(dut) == (1, -299, 3, 6)
    # signed: a small negative beats a large negative; a bubble changes nothing
    await push(dut, 0, 1, 5000, 0, 0)
    assert best(dut) == (1, -299, 3, 6)
    await push(dut, 1, 1, -20000, 1, 8)
    assert best(dut) == (1, -299, 3, 6)
    await push(dut, 1, 1, -5, 39, 9)
    assert best(dut) == (1, -5, 39, 9)
    await push(dut, 1, 1, 304, 38, 10)
    assert best(dut) == (1, 304, 38, 10)
    # clear restarts the reduction; a token on the clearing edge is ignored
    await push(dut, 1, 1, 0, 1, 1, clear=1)
    assert best(dut) == (0, 0, 0, 0)
    await push(dut, 1, 1, -20640, 0, 0)
    assert best(dut) == (1, -20640, 0, 0)
    await cycle(dut)


@cocotb.test()
async def random_sequences_match_shadow(dut):
    await reset(dut)
    r = rng(77)
    for seq in range(200):
        await push(dut, 0, 0, 0, 0, 0, clear=1)
        tokens = []
        for _ in range(r.randint(1, 40)):
            score = r.choice((r.randint(-20640, 304), r.choice((-20640, 304, 0, -1, 1))))
            tok = (r.randrange(2) if r.random() < 0.2 else 1, r.randrange(2) if r.random() < 0.4 else 1, score, r.randrange(40), r.randrange(20))
            tokens.append(tok)
            await push(dut, *tok)
        assert best(dut) == shadow(tokens), f"sequence {seq}: {best(dut)} != {shadow(tokens)}"
