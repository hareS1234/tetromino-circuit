"""Stream the pipelined compactor through stalls, bubbles, and every reset occupancy."""
from collections import deque

import cocotb

from common import cycle, fall, pack, reset, rise, rng, unpack

FULL = 1023
BANKS = 9


def oracle(rows):
    kept = [r for r in rows if r != FULL]
    return tuple(kept + [0] * (20 - len(kept))), 20 - len(kept)


class Scoreboard:
    def __init__(self, dut):
        self.dut = dut
        self.queue = deque()
        self.accepted = self.retired = 0
        self.accept_edges = []
        self.retire_edges = []
        self.edge = 0
        self.prev = None

    def present(self, token):
        d = self.dut
        if token is None:
            d.s_valid.value = 0
            return
        rows, legal, y, cid, tag, last = token
        d.s_board.value = pack(rows)
        d.s_legal.value = legal
        d.s_y.value = y
        d.s_id.value = cid
        d.s_tag.value = tag
        d.s_last.value = last
        d.s_valid.value = 1

    async def step(self, token, m_ready, rst=False):
        """Present inputs (clock low), sample handshakes, check output, then clock."""
        d = self.dut
        await fall(d)
        d.rst.value = int(rst)
        d.m_ready.value = int(m_ready)
        self.present(token)
        await fall(d)          # let combinational ready settle
        s_hand = bool(int(d.s_valid.value)) and bool(int(d.s_ready.value)) and not rst
        m_valid = bool(int(d.m_valid.value))
        m_hand = m_valid and m_ready and not rst
        out = (unpack(int(d.m_board.value)), int(d.m_cleared.value), int(d.m_legal.value), int(d.m_y.value),
               int(d.m_id.value), int(d.m_tag.value), int(d.m_last.value))
        if m_valid and self.prev is not None:
            assert out == self.prev, f"output changed while valid and not consumed at edge {self.edge}"
        if m_hand:
            assert self.queue, f"spurious output tag {out[5]} at edge {self.edge}"
            exp = self.queue.popleft()
            assert out == exp[0], f"edge {self.edge}: got {out[1:]} rows {out[0][:4]}… expected {exp[0][1:]} rows {exp[0][0][:4]}…"
            self.retired += 1
            self.retire_edges.append((self.edge, exp[1]))
        if s_hand:
            rows, legal, y, cid, tag, last = token
            board, cleared = oracle(rows)
            self.queue.append(((board, cleared, legal, y, cid, tag, last), self.edge))
            self.accepted += 1
            self.accept_edges.append(self.edge)
        self.prev = out if (m_valid and not m_hand and not rst) else None
        await rise(d)
        self.edge += 1
        return s_hand


def token(r, tag, mode="mixed", last=0):
    p_full = {"full": 1.0, "empty": 0.0, "mixed": r.choice((0.0, 0.1, 0.3, 0.6))}[mode]
    rows = tuple(FULL if r.random() < p_full else r.randrange(0, FULL) for _ in range(20))
    return rows, r.randrange(2), r.randrange(20), r.randrange(40), tag, last


async def run_stream(dut, tokens, ready_fn=lambda e: True, bubble_fn=lambda e: False, max_edges=20000):
    sb = Scoreboard(dut)
    i = 0
    while sb.retired < len(tokens) and sb.edge < max_edges:
        offer = tokens[i] if (i < len(tokens) and not bubble_fn(sb.edge)) else None
        if await sb.step(offer, ready_fn(sb.edge)):
            i += 1
    assert sb.retired == len(tokens), f"retired {sb.retired} of {len(tokens)}"
    assert not sb.queue
    return sb


@cocotb.test()
async def continuous_stream_latency_and_spacing(dut):
    await reset(dut)
    r = rng(11)
    toks = [token(r, t + 1) for t in range(200)]
    sb = await run_stream(dut, toks)
    spacing = {b - a for a, b in zip(sb.accept_edges, sb.accept_edges[1:])}
    assert spacing == {1}, f"acceptance spacing {spacing}"
    lat = {e - a for e, a in sb.retire_edges}
    assert lat == {BANKS}, f"transfer latency {lat} != {BANKS}"


@cocotb.test()
async def back_to_back_full_and_empty_boards(dut):
    await reset(dut)
    r = rng(12)
    toks = []
    for t in range(60):
        toks.append(token(r, 1000 + t, mode=("full", "empty", "mixed")[t % 3], last=int(t % 7 == 0)))
    await run_stream(dut, toks)


@cocotb.test()
async def stalls_and_bubbles(dut):
    await reset(dut)
    r = rng(13)
    toks = [token(r, 2000 + t) for t in range(150)]
    stall = {e for e in range(20000) if r.random() < 0.35}
    bubble = {e for e in range(20000) if r.random() < 0.25}
    sb = await run_stream(dut, toks, ready_fn=lambda e: e not in stall, bubble_fn=lambda e: e in bubble)
    assert min(e - a for e, a in sb.retire_edges) >= BANKS
    # long deterministic stall at the first output
    toks = [token(r, 3000 + t) for t in range(20)]
    first = {}

    def ready(e):
        return not (BANKS <= e - first.setdefault("start", e) < BANKS + 100)

    await run_stream(dut, toks, ready_fn=ready)


@cocotb.test()
async def reset_at_every_occupancy(dut):
    await reset(dut)
    r = rng(14)
    for occ in range(BANKS + 1):
        sb = Scoreboard(dut)
        for t in range(occ):
            await sb.step(token(r, 5000 + occ * 32 + t), True)
        await sb.step(None, True, rst=True)      # reset with priority over advance
        sb.queue.clear()
        sb.prev = None
        fresh = [token(r, 6000 + occ * 32 + t) for t in range(12)]
        i = 0
        start = sb.retired
        guard = 0
        while sb.retired - start < 12 and guard < 300:
            if await sb.step(fresh[i] if i < 12 else None, True):
                i += 1
            guard += 1
        assert sb.retired - start == 12, f"occupancy {occ}: {sb.retired - start} fresh tokens retired"
    await cycle(dut)
