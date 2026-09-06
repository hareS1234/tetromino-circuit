"""Score-pipeline arithmetic and metadata, with stalls and signed edge cases."""
from collections import deque

import cocotb

from common import cycle, fall, reset, rise, rng, signed32
from model.features import score

BANKS = 3


def expected_score(a, q, u, l, legal):
    return score((a, q, u), l) if legal else 0


class Bench:
    def __init__(self, dut):
        self.dut = dut
        self.queue = deque()
        self.edge = 0
        self.retired = 0
        self.prev = None
        self.retire_edges = []

    async def step(self, tok, m_ready=True, rst=False):
        d = self.dut
        await fall(d)
        d.rst.value = int(rst)
        d.m_ready.value = int(m_ready)
        if tok is None:
            d.s_valid.value = 0
        else:
            a, q, u, l, legal, y, cid, tag, last = tok
            d.s_a.value, d.s_q.value, d.s_u.value, d.s_l.value = a, q, u, l
            d.s_legal.value, d.s_y.value, d.s_id.value, d.s_tag.value, d.s_last.value = legal, y, cid, tag, last
            d.s_valid.value = 1
        await fall(d)
        s_hand = tok is not None and bool(int(d.s_ready.value)) and not rst
        m_valid = bool(int(d.m_valid.value))
        m_hand = m_valid and m_ready and not rst
        out = (signed32(int(d.m_score.value)), int(d.m_legal.value), int(d.m_y.value), int(d.m_id.value), int(d.m_tag.value), int(d.m_last.value))
        if m_valid and self.prev is not None:
            assert out == self.prev
        if m_hand:
            assert self.queue
            exp, a_edge, tok0 = self.queue.popleft()
            assert out == exp, f"tuple {tok0}: got {out} expected {exp}"
            self.retired += 1
            self.retire_edges.append((self.edge, a_edge))
        if s_hand:
            a, q, u, l, legal, y, cid, tag, last = tok
            self.queue.append(((expected_score(a, q, u, l, legal), legal, y, cid, tag, last), self.edge, tok))
        self.prev = out if (m_valid and not m_hand and not rst) else None
        await rise(d)
        self.edge += 1
        return s_hand

    async def stream(self, toks, ready_fn=lambda e: True):
        i = 0
        start = self.retired
        guard = 0
        while self.retired - start < len(toks) and guard < 50 * len(toks) + 100:
            if await self.step(toks[i] if i < len(toks) else None, ready_fn(self.edge)):
                i += 1
            guard += 1
        assert self.retired - start == len(toks) and not self.queue


def tok(a, q, u, l, legal=1, tag=0, last=0):
    return (a, q, u, l, legal, tag % 20, tag % 40, tag & 0xFFFF, last)


@cocotb.test()
async def bounds_and_signs(dut):
    await reset(dut)
    b = Bench(dut)
    toks = []
    t = 1
    for a in (0, 1, 200):
        for q in (0, 1, 190, 200):
            for u in (0, 1, 180):
                for l in range(5):
                    toks.append(tok(a, q, u, l, 1, t)); t += 1
                    toks.append(tok(a, q, u, l, 0, t)); t += 1      # illegal: canonical zero
    toks[-1] = toks[-1][:8] + (1,)
    await b.stream(toks)
    lat = {e - a for e, a in b.retire_edges}
    assert lat == {BANKS}
    # extreme values by hand
    assert expected_score(200, 200, 180, 0, 1) == -20640 and expected_score(0, 0, 0, 4, 1) == 304
    # negative scores compare as signed: -100 > -20000 must be decided by the consumer on signed values
    assert signed32(0xFFFFFF9C) == -100


@cocotb.test()
async def random_tuples(dut):
    await reset(dut)
    b = Bench(dut)
    r = rng(41)
    toks = [tok(r.randint(0, 200), r.randint(0, 200), r.randint(0, 180), r.randint(0, 4), r.randrange(2), 1000 + i) for i in range(10000)]
    await b.stream(toks)


@cocotb.test()
async def stalls_and_reset(dut):
    await reset(dut)
    b = Bench(dut)
    r = rng(42)
    toks = [tok(r.randint(0, 200), r.randint(0, 200), r.randint(0, 180), r.randint(0, 4), 1, 30000 + i) for i in range(200)]
    stall = {e for e in range(5000) if r.random() < 0.5}
    await b.stream(toks, ready_fn=lambda e: e not in stall)
    for occ in range(BANKS + 1):
        for t in range(occ):
            await b.step(toks[t], True)
        await b.step(None, True, rst=True)
        b.queue.clear()
        b.prev = None
        await b.stream(toks[:6])
    await cycle(dut)
