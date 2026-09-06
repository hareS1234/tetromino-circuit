"""Ready/valid driver for the core, with an edge counter independent of the RTL."""
from __future__ import annotations

from common import cycle, fall, pack, rise, signed32


class ProtocolError(AssertionError):
    pass


def response_fields(dut) -> dict:
    return {
        "error": int(dut.error_o.value), "no_move": int(dut.no_move_o.value),
        "rotation": int(dut.rotation_o.value), "x": int(dut.x_o.value), "y": int(dut.y_o.value),
        "score": signed32(int(dut.score_o.value)), "cycles": int(dut.cycles_o.value),
    }


def idle_inputs(dut):
    dut.req_valid.value = 0
    dut.rsp_ready.value = 0
    dut.board_i.value = 0
    dut.piece_i.value = 0
    dut.next_piece_i.value = 0


async def request(dut, rows, piece, next_piece=0, *, stall=0, timeout=60000, scramble_while_busy=False,
                  accept_timeout=64):
    """Submit one request and consume its response.  Returns (fields, measured_edges,
    accept_wait) where measured_edges is the rising-edge count from acceptance to the first
    settled rsp_valid.  With scramble_while_busy the inputs are changed after acceptance."""
    dut.board_i.value = pack(rows)
    dut.piece_i.value = piece
    dut.next_piece_i.value = next_piece
    dut.req_valid.value = 1
    dut.rsp_ready.value = 0
    # wait for req_ready (sampled before the rising edge)
    waited = 0
    while True:
        await fall(dut)
        if int(dut.req_ready.value):
            break
        await rise(dut)
        waited += 1
        if waited > accept_timeout:
            raise ProtocolError("core never became ready")
    await rise(dut)                      # acceptance edge (t0)
    dut.req_valid.value = 0
    if scramble_while_busy:
        dut.board_i.value = (1 << 200) - 1
        dut.piece_i.value = 7
        dut.next_piece_i.value = 7
    edges = 0
    while not int(dut.rsp_valid.value):
        await cycle(dut)
        edges += 1
        if edges > timeout:
            raise ProtocolError(f"no response within {timeout} cycles")
        if int(dut.req_ready.value):
            raise ProtocolError("req_ready asserted while a request is outstanding")
    fields = response_fields(dut)
    # backpressure: every field must hold while rsp_ready is low
    for _ in range(stall):
        await cycle(dut)
        if not int(dut.rsp_valid.value) or response_fields(dut) != fields:
            raise ProtocolError("response changed during a stall")
        if int(dut.req_ready.value):
            raise ProtocolError("req_ready asserted while a response is pending")
    dut.rsp_ready.value = 1
    await cycle(dut)                     # consumption edge
    dut.rsp_ready.value = 0
    if int(dut.rsp_valid.value):
        raise ProtocolError("rsp_valid still high after consumption")
    return fields, edges, waited
