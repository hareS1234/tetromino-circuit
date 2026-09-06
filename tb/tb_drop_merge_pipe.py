"""Landing/merge front end against literal descent and an independent lock operation."""
from collections import deque

import cocotb

from common import ROOT, cycle, fall, load_fixtures, pack, pack_heights, reset, rise, rng, rows_of, unpack
from model.boards import mixed_boards
from model.features import column_heights
from model.game import drop_y, merged_board
from model.pieces import all_candidates, candidate_ids, decode_candidate, rotation_count

BANKS = 4


def expected(rows, piece, rot, x):
    if rot >= rotation_count(piece):
        return (tuple([0] * 20), 0, 0)
    y = drop_y(rows, piece, rot, x)
    if y is None:
        return (tuple([0] * 20), 0, 0)
    return (merged_board(rows, piece, rot, x, y), 1, y)


class Bench:
    def __init__(self, dut):
        self.dut = dut
        self.queue = deque()
        self.edge = 0
        self.accepted = self.retired = 0
        self.accept_edges = []
        self.retire_edges = []
        self.prev = None

    def context(self, rows, piece):
        self.dut.ctx_board.value = pack(rows)
        self.dut.ctx_heights.value = pack_heights(column_heights(rows))
        self.dut.ctx_piece.value = piece
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
            d.s_rotation.value = rot
            d.s_x.value = x
            d.s_id.value = cid
            d.s_tag.value = tag
            d.s_last.value = last
            d.s_valid.value = 1
        await fall(d)
        s_hand = cand is not None and bool(int(d.s_ready.value)) and not rst
        m_valid = bool(int(d.m_valid.value))
        m_hand = m_valid and m_ready and not rst
        out = (unpack(int(d.m_board.value)), int(d.m_legal.value), int(d.m_y.value), int(d.m_id.value), int(d.m_tag.value), int(d.m_last.value))
        if m_valid and self.prev is not None:
            assert out == self.prev, f"output changed while valid and unconsumed at edge {self.edge}"
        if m_hand:
            assert self.queue, f"spurious output tag {out[4]} at edge {self.edge}"
            exp, a_edge, desc = self.queue.popleft()
            assert out == exp, f"{desc}: got legal {out[1]} y {out[2]} id {out[3]} tag {out[4]} last {out[5]} rows {out[0][:5]}… expected legal {exp[1]} y {exp[2]} id {exp[3]} tag {exp[4]} rows {exp[0][:5]}…"
            self.retired += 1
            self.retire_edges.append((self.edge, a_edge))
        if s_hand:
            rot, x, cid, tag, last = cand
            board, legal, y = expected(self.rows, self.piece, rot, x)
            self.queue.append(((board, legal, y, cid, tag, last), self.edge, f"piece {self.piece} rot {rot} x {x} rows {self.rows}"))
            self.accepted += 1
            self.accept_edges.append(self.edge)
        self.prev = out if (m_valid and not m_hand and not rst) else None
        await rise(d)
        self.edge += 1
        return s_hand

    async def stream(self, cands, ready_fn=lambda e: True, bubble_fn=lambda e: False):
        i = 0
        start = self.retired
        guard = 0
        while self.retired - start < len(cands) and guard < 50 * len(cands) + 200:
            offer = cands[i] if (i < len(cands) and not bubble_fn(self.edge)) else None
            if await self.step(offer, ready_fn(self.edge)):
                i += 1
            guard += 1
        assert self.retired - start == len(cands) and not self.queue


def dense_candidates(piece, tag_base):
    ids = candidate_ids(piece)
    out = []
    for j, cid in enumerate(ids):
        rot, x = decode_candidate(cid)
        out.append((rot, x, cid, (tag_base + j) & 0xFFFF, int(j == len(ids) - 1)))
    return out


@cocotb.test()
async def hand_fixtures_and_regressions(dut):
    await reset(dut)
    b = Bench(dut)
    fx = load_fixtures()
    for f in fx["placements"]:
        rows = rows_of(f["rows"])
        b.context(rows, f["piece"])
        await b.stream([(f["rotation"], f["x"], 10 * f["rotation"] + f["x"], 7, 1)])
        await b.stream([])
    # spawn under overhang: rows 15 and 18 equal 4, J rotation 3 at x = 2 must be illegal
    rows = rows_of({"15": 4, "18": 4})
    b.context(rows, 5)
    assert expected(rows, 5, 3, 2)[1] == 0
    await b.stream([(3, 2, 32, 9, 1)])
    # anchor height 20: a column filled to the top makes every candidate touching it illegal
    rows = tuple(1 << 4 for _ in range(20))          # column 4 full height (no full rows)
    b.context(rows, 0)
    await b.stream(dense_candidates(0, 100))
    # negative differences: empty board, pieces whose bottom offsets exceed the heights land at y = 0
    b.context(tuple([0] * 20), 2)
    await b.stream(dense_candidates(2, 200))
    # four cells sharing one row: horizontal I on an empty board at every x
    b.context(tuple([0] * 20), 0)
    await b.stream([(0, x, x, 300 + x, int(x == 6)) for x in range(7)])


@cocotb.test()
async def invalid_geometry_tokens(dut):
    await reset(dut)
    b = Bench(dut)
    b.context(tuple([0] * 20), 1)
    cands = [(rot, x, 10 * rot + x, 400 + 10 * rot + x, 0) for rot in range(4) for x in range(10)]
    cands[-1] = cands[-1][:4] + (1,)
    await b.stream(cands)


@cocotb.test()
async def mixed_corpus_all_candidates(dut):
    """250 mixed boards x 162 candidates = 40,500 tokens, one stable context per board."""
    await reset(dut)
    b = Bench(dut)
    boards = mixed_boards(2024, 250)
    n = 0
    for i, rows in enumerate(boards):
        for piece in range(7):
            b.context(rows, piece)
            cands = dense_candidates(piece, 1000 * (i % 60) + 100 * piece)
            await b.stream(cands)
            n += len(cands)
    assert n == 40500
    spacing = {y - x for x, y in zip(b.accept_edges, b.accept_edges[1:])}
    assert spacing <= {1, 2, 3, 4, 5, 6, 7}, spacing        # gaps only between contexts (drain)
    dut._log.info(f"mixed corpus: {n} candidate tokens checked")


@cocotb.test()
async def stalls_bubbles_and_spacing(dut):
    await reset(dut)
    b = Bench(dut)
    r = rng(21)
    rows = mixed_boards(77, 3)[1]
    b.context(rows, 2)
    cands = dense_candidates(2, 500)
    await b.stream(cands)
    lat = {e - a for e, a in b.retire_edges}
    assert lat == {BANKS}, f"transfer latency {lat}"
    spacing = {y - x for x, y in zip(b.accept_edges, b.accept_edges[1:])}
    assert spacing == {1}
    stall = {e for e in range(20000) if r.random() < 0.4}
    bubble = {e for e in range(20000) if r.random() < 0.3}
    b.context(rows, 5)
    await b.stream(dense_candidates(5, 600), ready_fn=lambda e: e not in stall, bubble_fn=lambda e: e in bubble)
    assert min(e - a for e, a in b.retire_edges) >= BANKS


@cocotb.test()
async def reset_at_every_occupancy(dut):
    await reset(dut)
    b = Bench(dut)
    rows = mixed_boards(88, 2)[0]
    b.context(rows, 6)
    cands = dense_candidates(6, 700)
    for occ in range(BANKS + 1):
        for t in range(occ):
            await b.step(cands[t], True)
        await b.step(None, True, rst=True)
        b.queue.clear()
        b.prev = None
        await b.stream(cands[:12])
    await cycle(dut)
