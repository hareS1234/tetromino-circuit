"""Ready/valid, backpressure, reset, and bad-input checks independent of game logic."""
import cocotb

from common import cycle, fall, load_fixtures, pack, param, reset, rise, rows_of
from core_driver import ProtocolError, idle_inputs, request, response_fields
from model import policy

DEPTH = param("DEPTH", 1)
ARCH = param("ARCH", 0)
TIMEOUT = 25000 if ARCH == 0 else 5000
EMPTY = tuple([0] * 20)


def expect(rows, piece):
    rec = policy.best_move(rows, piece)
    return None if rec is None else (rec["rotation"], rec["x"], rec["y"], rec["score"])


@cocotb.test()
async def empty_board_all_pieces_and_stalls(dut):
    idle_inputs(dut)
    await reset(dut)
    fx = load_fixtures()
    for e, stall in zip(fx["empty_board_best"], (0, 1, 3, 17, 100, 0, 2)):
        fields, edges, _ = await request(dut, EMPTY, e["piece"], stall=stall, timeout=TIMEOUT)
        assert (fields["rotation"], fields["x"], fields["y"], fields["score"]) == (e["rotation"], e["x"], e["y"], e["score"])
        assert fields["cycles"] == edges and fields["error"] == 0 and fields["no_move"] == 0


@cocotb.test()
async def held_valid_accepts_exactly_once(dut):
    idle_inputs(dut)
    await reset(dut)
    dut.board_i.value = pack(EMPTY)
    dut.piece_i.value = 1
    dut.req_valid.value = 1
    accepted = 0
    for _ in range(40):
        await fall(dut)
        if int(dut.req_ready.value) and int(dut.req_valid.value):
            accepted += 1
        await rise(dut)
    dut.req_valid.value = 0
    assert accepted == 1, f"accepted {accepted} times while req_valid was held"
    n = 0
    while not int(dut.rsp_valid.value):
        await cycle(dut)
        n += 1
        assert n < TIMEOUT
    assert int(dut.req_ready.value) == 0
    dut.rsp_ready.value = 1
    await cycle(dut)
    dut.rsp_ready.value = 0
    await fall(dut)
    assert int(dut.req_ready.value) == 1 and int(dut.rsp_valid.value) == 0
    await rise(dut)


@cocotb.test()
async def latched_request_survives_input_changes(dut):
    idle_inputs(dut)
    await reset(dut)
    rows = tuple([1008] + [0] * 19)
    fields, edges, _ = await request(dut, rows, 0, scramble_while_busy=True, timeout=TIMEOUT)
    assert (fields["rotation"], fields["x"], fields["y"], fields["score"]) == expect(rows, 0)
    assert fields["error"] == 0


@cocotb.test()
async def request_while_busy_waits_for_ready(dut):
    idle_inputs(dut)
    await reset(dut)
    # first request accepted
    dut.board_i.value = pack(EMPTY); dut.piece_i.value = 2; dut.req_valid.value = 1
    await cycle(dut)
    # present a second request immediately; it must not be accepted until ready returns
    dut.piece_i.value = 3
    n = 0
    while True:
        await fall(dut)
        assert int(dut.req_ready.value) == 0
        if int(dut.rsp_valid.value):
            break
        await rise(dut)
        n += 1
        assert n < TIMEOUT
    await rise(dut)
    first = response_fields(dut)
    assert (first["rotation"], first["x"], first["y"], first["score"]) == expect(EMPTY, 2)
    dut.rsp_ready.value = 1
    await cycle(dut)
    dut.rsp_ready.value = 0
    # now the held second request is accepted on the next idle cycle
    await fall(dut)
    assert int(dut.req_ready.value) == 1
    await rise(dut)
    dut.req_valid.value = 0
    n = 0
    while not int(dut.rsp_valid.value):
        await cycle(dut)
        n += 1
        assert n < TIMEOUT
    second = response_fields(dut)
    assert (second["rotation"], second["x"], second["y"], second["score"]) == expect(EMPTY, 3)
    dut.rsp_ready.value = 1
    await cycle(dut)
    dut.rsp_ready.value = 0


@cocotb.test()
async def piece_seven_is_a_defined_error(dut):
    idle_inputs(dut)
    await reset(dut)
    fields, edges, _ = await request(dut, EMPTY, 7, timeout=TIMEOUT)
    assert fields == {"error": 1, "no_move": 0, "rotation": 0, "x": 0, "y": 0, "score": 0, "cycles": edges}
    fields, edges, _ = await request(dut, EMPTY, 1, timeout=TIMEOUT)      # core still works afterwards
    assert fields["error"] == 0 and (fields["rotation"], fields["x"], fields["y"], fields["score"]) == expect(EMPTY, 1)


@cocotb.test()
async def no_move_response(dut):
    idle_inputs(dut)
    await reset(dut)
    rows = tuple([0] * 18 + [341, 341])
    fields, edges, _ = await request(dut, rows, 1, stall=3, timeout=TIMEOUT)
    assert fields == {"error": 0, "no_move": 1, "rotation": 0, "x": 0, "y": 0, "score": 0, "cycles": edges}


@cocotb.test()
async def preview_does_not_change_depth_one(dut):
    if DEPTH != 1:
        return
    idle_inputs(dut)
    await reset(dut)
    rows = tuple([0] * 14 + [0b0111111110, 0b0011111100, 0, 0, 0, 0])
    base = None
    for nxt in range(8):
        fields, edges, _ = await request(dut, rows, 4, next_piece=nxt, timeout=TIMEOUT)
        key = (fields["error"], fields["no_move"], fields["rotation"], fields["x"], fields["y"], fields["score"])
        if base is None:
            base = key
        assert key == base, f"preview {nxt} changed a depth-one result"
    assert base[0] == 0


@cocotb.test()
async def reset_in_every_major_state(dut):
    idle_inputs(dut)
    await reset(dut)
    rows = tuple([1008] + [0] * 19)
    # find the response latency first
    _, latency, _ = await request(dut, rows, 0, timeout=TIMEOUT)
    points = sorted({2, 5, latency // 4, latency // 2, (3 * latency) // 4, latency - 1})
    for after in points:
        dut.board_i.value = pack(rows); dut.piece_i.value = 0; dut.req_valid.value = 1
        await cycle(dut)
        dut.req_valid.value = 0
        await cycle(dut, after)
        assert int(dut.rsp_valid.value) == 0 or after >= latency
        dut.rst.value = 1
        await cycle(dut)
        dut.rst.value = 0
        assert int(dut.rsp_valid.value) == 0
        await fall(dut)
        assert int(dut.req_ready.value) == 1, f"not ready after reset at cycle {after}"
        await rise(dut)
        fields, edges, _ = await request(dut, rows, 0, timeout=TIMEOUT)
        assert (fields["rotation"], fields["x"], fields["y"], fields["score"]) == expect(rows, 0)
        assert fields["cycles"] == edges
    # reset while a response is pending
    dut.board_i.value = pack(rows); dut.piece_i.value = 0; dut.req_valid.value = 1
    await cycle(dut)
    dut.req_valid.value = 0
    n = 0
    while not int(dut.rsp_valid.value):
        await cycle(dut)
        n += 1
    await cycle(dut, 3)
    assert int(dut.rsp_valid.value) == 1
    dut.rst.value = 1
    await cycle(dut)
    dut.rst.value = 0
    assert int(dut.rsp_valid.value) == 0
    fields, edges, _ = await request(dut, rows, 0, timeout=TIMEOUT)
    assert (fields["rotation"], fields["x"], fields["y"], fields["score"]) == expect(rows, 0)


@cocotb.test()
async def edge_counter_matches_with_stalled_response(dut):
    idle_inputs(dut)
    await reset(dut)
    for stall in (0, 7, 50):
        fields, edges, _ = await request(dut, EMPTY, 5, stall=stall, timeout=TIMEOUT)
        assert fields["cycles"] == edges, f"stall {stall}: cycles_o {fields['cycles']} != {edges}"
