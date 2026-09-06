"""The 32-bit packet wrapper under pauses, reset, and back-to-back traffic."""
import json
import os

import cocotb

from common import ROOT, cycle, fall, param, reset, rise, rng, signed32
from model import policy
from model.board import board_words

DEPTH = param("DEPTH", 1)
ARCH = param("ARCH", 0)
TIMEOUT = 30000 if ARCH == 0 else 8000


def request_words(rows, piece, nxt=0):
    words = board_words(rows)
    return [(nxt << 3) | piece] + words[:6] + [words[6] & 0xFF]


async def send_packet(dut, words, pauses):
    for w, pause in zip(words, pauses):
        for _ in range(pause):
            dut.s_valid.value = 0
            await cycle(dut)
        dut.s_data.value = w
        dut.s_valid.value = 1
        n = 0
        while True:
            await fall(dut)
            ready = int(dut.s_ready.value)
            await rise(dut)
            if ready:
                break
            n += 1
            assert n < TIMEOUT, "s_ready never asserted"
        dut.s_valid.value = 0


async def receive_packet(dut, pauses):
    out = []
    n = 0
    for pause in pauses:
        while not int(dut.m_valid.value):
            await cycle(dut)
            n += 1
            assert n < TIMEOUT, "m_valid never asserted"
        held = int(dut.m_data.value)
        for _ in range(pause):
            dut.m_ready.value = 0
            await cycle(dut)
            assert int(dut.m_valid.value) == 1 and int(dut.m_data.value) == held, "output word changed while stalled"
        dut.m_ready.value = 1
        await cycle(dut)
        dut.m_ready.value = 0
        out.append(held)
    return out


def decode(words):
    w0, w1, w2 = words
    return {"error": w0 & 1, "no_move": (w0 >> 1) & 1, "rotation": (w0 >> 2) & 3, "x": (w0 >> 4) & 15,
            "y": (w0 >> 8) & 31, "score": signed32(w1), "cycles": w2, "reserved": w0 >> 13}


def expected(rows, piece):
    e = policy.best_move(rows, piece)
    if e is None:
        return {"error": 0, "no_move": 1, "rotation": 0, "x": 0, "y": 0, "score": 0}
    return {"error": 0, "no_move": 0, "rotation": e["rotation"], "x": e["x"], "y": e["y"], "score": e["score"]}


def corpus(n):
    path = ROOT / "benchmarks" / "states" / "corpus_d1.jsonl"
    recs = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return recs[:n]


def native_cycles():
    """cycles per corpus case from the native driver run, when it exists (E08 output)."""
    path = ROOT / "results" / "decisions" / "a0-bitmap-d1-p0-l1_native_1000.csv"
    if ARCH != 0 or not path.is_file():
        return {}
    import csv
    with open(path) as fh:
        return {int(r["state_id"]): int(r["core_cycles"]) for r in csv.DictReader(fh)}


@cocotb.test()
async def packets_with_pauses(dut):
    dut.s_valid.value = 0; dut.s_data.value = 0; dut.m_ready.value = 0
    await reset(dut)
    r = rng(11)
    known = native_cycles()
    for rec in corpus(12):
        rows, piece = tuple(rec["rows"]), rec["piece"]
        words = request_words(rows, piece, nxt=r.randrange(8))
        pauses_in = [r.choice([0, 0, 1, 3, 7]) for _ in words]
        await send_packet(dut, words, pauses_in)
        got = decode(await receive_packet(dut, [r.choice([0, 1, 5, 17]) for _ in range(3)]))
        exp = expected(rows, piece)
        assert {k: got[k] for k in exp} == exp, f"case {rec['id']}: {got} != {exp}"
        assert got["reserved"] == 0
        if rec["id"] in known:
            assert got["cycles"] == known[rec["id"]], f"case {rec['id']}: wrapper reported {got['cycles']} core cycles, native {known[rec['id']]}"


@cocotb.test()
async def back_to_back_packets(dut):
    dut.s_valid.value = 0; dut.s_data.value = 0; dut.m_ready.value = 0
    await reset(dut)
    empty = tuple([0] * 20)
    for piece in range(7):
        await send_packet(dut, request_words(empty, piece), [0] * 8)
        got = decode(await receive_packet(dut, [0, 0, 0]))
        exp = expected(empty, piece)
        assert {k: got[k] for k in exp} == exp
    # input readiness must be withheld until the whole response has been read
    await send_packet(dut, request_words(empty, 1), [0] * 8)
    n = 0
    while not int(dut.m_valid.value):
        await cycle(dut)
        n += 1
    await fall(dut)
    assert int(dut.s_ready.value) == 0, "s_ready asserted before the response was transmitted"
    await rise(dut)
    got = decode(await receive_packet(dut, [2, 2, 2]))
    assert {k: got[k] for k in expected(empty, 1)} == expected(empty, 1)


@cocotb.test()
async def reset_mid_packet_discards_it(dut):
    dut.s_valid.value = 0; dut.s_data.value = 0; dut.m_ready.value = 0
    await reset(dut)
    rows = tuple([1008] + [0] * 19)
    words = request_words(rows, 0)
    await send_packet(dut, words[:5], [0] * 5)
    dut.rst.value = 1
    await cycle(dut)
    dut.rst.value = 0
    await cycle(dut)
    assert int(dut.m_valid.value) == 0
    # a fresh complete packet is answered correctly
    await send_packet(dut, words, [0] * 8)
    got = decode(await receive_packet(dut, [0, 0, 0]))
    assert {k: got[k] for k in expected(rows, 0)} == expected(rows, 0)
    # reset while the core computes: no stale response may appear afterwards
    await send_packet(dut, request_words(rows, 2), [0] * 8)
    await cycle(dut, 30)
    dut.rst.value = 1
    await cycle(dut)
    dut.rst.value = 0
    for _ in range(50):
        await cycle(dut)
        assert int(dut.m_valid.value) == 0
    await send_packet(dut, request_words(rows, 2), [0] * 8)
    got = decode(await receive_packet(dut, [0, 0, 0]))
    assert {k: got[k] for k in expected(rows, 2)} == expected(rows, 2)


@cocotb.test()
async def invalid_piece_through_wrapper(dut):
    dut.s_valid.value = 0; dut.s_data.value = 0; dut.m_ready.value = 0
    await reset(dut)
    empty = tuple([0] * 20)
    await send_packet(dut, request_words(empty, 7), [0] * 8)
    got = decode(await receive_packet(dut, [0, 0, 0]))
    assert got["error"] == 1 and got["no_move"] == 0 and got["rotation"] == 0 and got["x"] == 0 and got["y"] == 0 and got["score"] == 0
