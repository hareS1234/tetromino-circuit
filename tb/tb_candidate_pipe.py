"""U09: candidate_pipe protocol checks in cocotb (the volume tests run natively, tools/a2_native.py).
Latency contract (visible 22 / transfer 23 / II 1), whole-pipeline freeze under an output stall,
consume-and-accept on one edge, illegal tokens keeping order and last, and reset at every
occupancy of the 23 banks."""
from collections import deque

import cocotb

from common import cycle, fall, pack, pack_heights, reset, rise, rng, signed32
from model.boards import mixed_boards
from model.features import column_heights, features, score
from model.game import drop_y, lock_and_clear
from model.pieces import candidate_ids, decode_candidate, rotation_count

BANKS = 23


def expected(rows, piece, rot, x):
    if rot >= rotation_count(piece):
        return (0, 0, 0)
    y = drop_y(rows, piece, rot, x)
    if y is None:
        return (0, 0, 0)
    after, lines = lock_and_clear(rows, piece, rot, x, y)
    return (1, y, score(features(after), lines))


class Bench:
    def __init__(self, dut):
        self.dut = dut
        self.queue = deque()
        self.edge = 0
        self.retired = 0
        self.prev = None
        self.accept_edges = []
        self.retire_edges = []
        self.first_visible = {}

    def context(self, rows, piece):
        self.dut.ctx_board_i.value = pack(rows)
        self.dut.ctx_heights_i.value = pack_heights(column_heights(rows))
        self.dut.ctx_piece_i.value = piece
        self.rows, self.piece = rows, piece

    async def step(self, cand, m_ready=True, rst=False):
        d = self.dut
        await fall(d)
        d.rst.value = int(rst)
        d.m_ready.value = int(m_ready)
        if cand is None:
            d.s_valid.value = 0
        else:
            rot, x, cid, tag, last = cand
            d.s_rotation.value, d.s_x.value, d.s_candidate_id.value, d.s_tag.value, d.s_last.value = rot, x, cid, tag, last
            d.s_valid.value = 1
        await fall(d)
        s_hand = cand is not None and bool(int(d.s_ready.value)) and not rst
        m_valid = bool(int(d.m_valid.value))
        m_hand = m_valid and m_ready and not rst
        out = (int(d.m_legal.value), int(d.m_y.value), signed32(int(d.m_score.value)), int(d.m_candidate_id.value), int(d.m_tag.value), int(d.m_last.value))
        if m_valid and self.prev is not None:
            assert out == self.prev, f"output changed while valid and unconsumed at edge {self.edge}"
        if m_hand:
            assert self.queue, f"spurious output tag {out[4]}"
            exp, a_edge = self.queue.popleft()
            assert out == exp, f"got {out} expected {exp}"
            self.retired += 1
            self.retire_edges.append((self.edge, a_edge))
        if s_hand:
            rot, x, cid, tag, last = cand
            legal, y, sc = expected(self.rows, self.piece, rot, x)
            self.queue.append(((legal, y, sc, cid, tag, last), self.edge))
            self.accept_edges.append(self.edge)
        self.prev = out if (m_valid and not m_hand and not rst) else None
        await rise(d)
        if bool(int(d.m_valid.value)):
            self.first_visible.setdefault(int(d.m_tag.value), self.edge)
        self.edge += 1
        return s_hand

    async def stream(self, cands, ready_fn=lambda e: True, bubble_fn=lambda e: False):
        i = 0
        start = self.retired
        guard = 0
        while self.retired - start < len(cands) and guard < 60 * len(cands) + 300:
            offer = cands[i] if (i < len(cands) and not bubble_fn(self.edge)) else None
            if await self.step(offer, ready_fn(self.edge)):
                i += 1
            guard += 1
        assert self.retired - start == len(cands) and not self.queue


def dense(piece, tag_base):
    ids = candidate_ids(piece)
    return [(decode_candidate(c)[0], decode_candidate(c)[1], c, (tag_base + j) & 0xFFFF, int(j == len(ids) - 1)) for j, c in enumerate(ids)]


@cocotb.test()
async def latency_contract(dut):
    await reset(dut)
    b = Bench(dut)
    rows = mixed_boards(2024, 4)[2]
    b.context(rows, 2)
    cands = dense(2, 1)
    await b.stream(cands)
    assert {y - x for x, y in zip(b.accept_edges, b.accept_edges[1:])} == {1}
    assert {e - a for e, a in b.retire_edges} == {BANKS}, "transfer latency must be 23"
    vis = {b.first_visible[c[3]] - a for c, a in zip(cands, b.accept_edges)}
    assert vis == {BANKS - 1}, f"visible latency {vis} must be 22"


@cocotb.test()
async def stall_freezes_everything_and_consume_accept_same_edge(dut):
    await reset(dut)
    b = Bench(dut)
    rows = mixed_boards(2024, 4)[0]
    b.context(rows, 5)
    cands = dense(5, 100)
    for c in cands[:BANKS]:
        assert await b.step(c, True)
    assert int(dut.m_valid.value) == 1 and int(dut.occupancy_o.value) == (1 << BANKS) - 1
    occ = int(dut.occupancy_o.value)
    accepted = await b.step(cands[BANKS], False)          # blocked output: nothing moves
    assert not accepted and int(dut.occupancy_o.value) == occ
    accepted = await b.step(cands[BANKS], True)           # consume and accept on the same edge
    assert accepted and int(dut.occupancy_o.value) == occ
    i = BANKS + 1
    guard = 0
    while (b.queue or i < len(cands)) and guard < 500:
        if await b.step(cands[i] if i < len(cands) else None, True):
            i += 1
        guard += 1
    assert b.retired == len(cands) and not b.queue


@cocotb.test()
async def illegal_tokens_keep_order_and_last(dut):
    await reset(dut)
    b = Bench(dut)
    rows = tuple([0] * 19 + [0b0000001111])                # blocks the right side at the top: some landings illegal
    rows = mixed_boards(99, 2)[1]
    b.context(rows, 0)
    cands = [(3, 9, 39, 900, 0), (0, 0, 0, 901, 0), (1, 12, 22, 902, 0), (0, 3, 3, 903, 0), (2, 0, 20, 904, 1)]   # invalid rotations/x mixed in
    await b.stream(cands)


@cocotb.test()
async def reset_at_every_occupancy(dut):
    await reset(dut)
    b = Bench(dut)
    rows = mixed_boards(2024, 4)[3]
    b.context(rows, 6)
    cands = dense(6, 2000)
    r = rng(5)
    for occ in range(BANKS + 1):
        stalled = occ % 2 == 1
        for t in range(occ):
            await b.step(cands[t % len(cands)], not stalled)
        await b.step(None, not stalled, rst=True)
        b.queue.clear()
        b.prev = None
        assert int(dut.occupancy_o.value) == 0
        await b.stream(cands[:8])
    await cycle(dut)
