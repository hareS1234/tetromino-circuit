"""U08 (V05): feature pipeline P13-P19 behind its harness against direct hole counting
(model/features.py): empty, all 200 one-hot positions, top-bit rows, columns of height 20, holes,
checkerboards, and 10,000 arbitrary boards; tags/last alignment through stalls and reset."""
from collections import deque

import cocotb

from common import cycle, fall, pack, reset, rise, rng, unpack
from model.features import features

BANKS = 7


class Bench:
    def __init__(self, dut):
        self.dut = dut
        self.queue = deque()
        self.edge = 0
        self.retired = 0
        self.prev = None
        self.accept_edges = []
        self.retire_edges = []

    async def step(self, tok, m_ready=True, rst=False):
        d = self.dut
        await fall(d)
        d.rst.value = int(rst)
        d.m_ready.value = int(m_ready)
        if tok is None:
            d.s_valid.value = 0
        else:
            rows, cleared, legal, y, cid, tag, last = tok
            d.s_board.value = pack(rows)
            d.s_cleared.value = cleared
            d.s_legal.value = legal
            d.s_y.value = y
            d.s_id.value = cid
            d.s_tag.value = tag
            d.s_last.value = last
            d.s_valid.value = 1
        await fall(d)
        s_hand = tok is not None and bool(int(d.s_ready.value)) and not rst
        m_valid = bool(int(d.m_valid.value))
        m_hand = m_valid and m_ready and not rst
        out = (int(d.m_a.value), int(d.m_q.value), int(d.m_u.value), int(d.m_l.value), int(d.m_legal.value), int(d.m_y.value),
               int(d.m_id.value), int(d.m_tag.value), int(d.m_last.value))
        if m_valid and self.prev is not None:
            assert out == self.prev, f"output changed while valid and unconsumed at edge {self.edge}"
        if m_hand:
            assert self.queue, f"spurious output tag {out[7]}"
            exp, a_edge, rows = self.queue.popleft()
            assert out == exp, f"rows {rows}: got A/Q/U/L {out[:4]} meta {out[4:]} expected {exp[:4]} meta {exp[4:]}"
            self.retired += 1
            self.retire_edges.append((self.edge, a_edge))
        if s_hand:
            rows, cleared, legal, y, cid, tag, last = tok
            a, q, u = features(rows)
            self.queue.append(((a, q, u, cleared & 7, legal, y, cid, tag, last), self.edge, rows))
            self.accept_edges.append(self.edge)
        self.prev = out if (m_valid and not m_hand and not rst) else None
        await rise(d)
        self.edge += 1
        return s_hand

    async def stream(self, toks, ready_fn=lambda e: True, bubble_fn=lambda e: False):
        i = 0
        start = self.retired
        guard = 0
        while self.retired - start < len(toks) and guard < 50 * len(toks) + 200:
            offer = toks[i] if (i < len(toks) and not bubble_fn(self.edge)) else None
            if await self.step(offer, ready_fn(self.edge)):
                i += 1
            guard += 1
        assert self.retired - start == len(toks) and not self.queue


def tok(rows, tag, r=None, cleared=None, last=0):
    r = r or rng(tag)
    return (tuple(rows), r.randrange(5) if cleared is None else cleared, r.randrange(2), r.randrange(20), r.randrange(40), tag & 0xFFFF, last)


@cocotb.test()
async def directed_boards(dut):
    await reset(dut)
    b = Bench(dut)
    toks = [tok([0] * 20, 1)]
    for y in range(20):                                     # all 200 one-hot positions
        for x in range(10):
            rows = [0] * 20
            rows[y] = 1 << x
            toks.append(tok(rows, 100 + 10 * y + x))
    toks.append(tok([0] * 19 + [1023], 300))                 # top row full (a compacted board never has one, still defined)
    toks.append(tok([1 << 4] * 20, 301))                     # column of height 20
    toks.append(tok([1023 - (1 << 3)] * 20, 302))            # nine columns of height 20 with one empty column
    toks.append(tok([0x155 if y % 2 == 0 else 0x2AA for y in range(20)], 303))   # checkerboard
    toks.append(tok([0x2AA if y % 2 == 0 else 0x155 for y in range(20)], 304))
    toks.append(tok([0b1111111110] * 19 + [1], 305))         # holes under a single top cell
    toks.append(tok([1] * 20 + [], 306))
    toks.append(tok([3 << 8] * 10 + [0] * 10, 307, last=1))
    await b.stream(toks)
    lat = {e - a for e, a in b.retire_edges}
    assert lat == {BANKS}, f"transfer latency {lat}"
    assert {y - x for x, y in zip(b.accept_edges, b.accept_edges[1:])} == {1}


@cocotb.test()
async def arbitrary_boards(dut):
    await reset(dut)
    b = Bench(dut)
    r = rng(31)
    toks = []
    for i in range(10000):
        top = r.randint(0, 20)
        fill = r.choice((0.2, 0.5, 0.8, 0.95))
        rows = [sum(1 << x for x in range(10) if r.random() < fill) if y < top else 0 for y in range(20)]
        rows = [rw if rw != 1023 else rw & ~(1 << r.randrange(10)) for rw in rows]
        toks.append(tok(rows, 1000 + i, r))
    await b.stream(toks)
    dut._log.info("10,000 arbitrary boards matched direct hole counting")


@cocotb.test()
async def stalls_bubbles_and_reset(dut):
    await reset(dut)
    b = Bench(dut)
    r = rng(32)
    toks = [tok([sum(1 << x for x in range(10) if r.random() < 0.5) for _ in range(20)], 20000 + i, r) for i in range(300)]
    stall = {e for e in range(20000) if r.random() < 0.4}
    bubble = {e for e in range(20000) if r.random() < 0.3}
    await b.stream(toks, ready_fn=lambda e: e not in stall, bubble_fn=lambda e: e in bubble)
    for occ in range(BANKS + 1):
        for t in range(occ):
            await b.step(toks[t], True)
        await b.step(None, True, rst=True)
        b.queue.clear()
        b.prev = None
        await b.stream(toks[:10])
    await cycle(dut)
