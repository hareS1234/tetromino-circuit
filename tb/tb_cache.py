"""The cached heights must match the request board and be rebuilt for each request."""
import json

import cocotb

from common import ROOT, cycle, pack, param, reset
from core_driver import idle_inputs, request
from model import policy
from model.features import column_heights

assert param("BOARD_REPR", 0) == 1, "tb_cache requires BOARD_REPR=1"
TIMEOUT = 5000


@cocotb.test()
async def cache_matches_board_for_every_request(dut):
    idle_inputs(dut)
    await reset(dut)
    path = ROOT / "benchmarks" / "states" / "corpus_d1.jsonl"
    recs = [json.loads(line) for line in path.read_text().splitlines() if line.strip()][:120]
    for rec in recs:
        rows = tuple(rec["rows"])
        piece = rec["piece"]
        # submit and stop right after the cache has been registered (state CACHE -> SEARCH_START)
        dut.board_i.value = pack(rows); dut.piece_i.value = piece; dut.req_valid.value = 1
        await cycle(dut)          # acceptance edge
        dut.req_valid.value = 0
        dut.board_i.value = 0     # scramble: the cache must come from the latched board
        await cycle(dut)          # CACHE edge: heights_q <= profile(board_q)
        got = [(int(dut.heights_q.value) >> (5 * i)) & 31 for i in range(10)]
        assert got == column_heights(rows), f"case {rec['id']}: cache {got} != {column_heights(rows)}"
        n = 0
        while not int(dut.rsp_valid.value):
            await cycle(dut)
            n += 1
            assert n < TIMEOUT
        exp = policy.best_move(rows, piece)
        fields = {"rotation": int(dut.rotation_o.value), "x": int(dut.x_o.value), "y": int(dut.y_o.value)}
        if exp is not None:
            assert (fields["rotation"], fields["x"], fields["y"]) == (exp["rotation"], exp["x"], exp["y"])
        else:
            assert int(dut.no_move_o.value) == 1
        dut.rsp_ready.value = 1
        await cycle(dut)
        dut.rsp_ready.value = 0


@cocotb.test()
async def cache_is_rebuilt_per_request(dut):
    idle_inputs(dut)
    await reset(dut)
    tall = tuple([1] * 20)
    empty = tuple([0] * 20)
    for rows in (tall, empty, tall, empty):
        fields, edges, _ = await request(dut, rows, 1, timeout=TIMEOUT)
        got = [(int(dut.heights_q.value) >> (5 * i)) & 31 for i in range(10)]
        assert got == column_heights(rows)
        exp = policy.best_move(rows, 1)
        assert (fields["rotation"], fields["x"], fields["y"], fields["score"]) == (exp["rotation"], exp["x"], exp["y"], exp["score"])
