"""Shared cocotb helpers: manually stepped clock, reset, start/busy/done transactions, and
access to the Python reference model.  Inputs are presented while the clock is low; registered
results are sampled after the rising edge has settled."""
from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

import cocotb
from cocotb.triggers import Timer

ROOT = Path(os.environ.get("TETROMINO_ROOT", Path(__file__).resolve().parents[1]))
for extra in (ROOT, ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

HALF_NS = 5


def params() -> dict:
    """Top-level parameters the runner compiled with (NAME=value,...)."""
    out = {}
    for item in os.environ.get("TETROMINO_PARAMS", "").split(","):
        if "=" in item:
            k, v = item.split("=", 1)
            out[k] = int(v)
    return out


def param(name: str, default: int) -> int:
    return params().get(name, default)


async def fall(dut):
    dut.clk.value = 0
    await Timer(HALF_NS, unit="ns")


async def rise(dut):
    dut.clk.value = 1
    await Timer(HALF_NS, unit="ns")


async def cycle(dut, n: int = 1):
    for _ in range(n):
        await fall(dut)
        await rise(dut)


async def reset(dut, cycles: int = 2):
    dut.clk.value = 0
    dut.rst.value = 1
    await cycle(dut, cycles)
    dut.rst.value = 0
    await cycle(dut)


class Timeout(AssertionError):
    pass


async def run_transaction(dut, set_inputs, timeout: int, name: str = "module"):
    """Assert start_i for one cycle after presenting inputs; step until done_o.  Returns the
    number of rising edges from the accepting edge to the edge on which done_o was observed."""
    set_inputs()
    dut.start_i.value = 1
    await cycle(dut)            # accepting edge
    dut.start_i.value = 0
    n = 0
    while True:
        await cycle(dut)
        n += 1
        if int(dut.done_o.value):
            return n
        if n > timeout:
            raise Timeout(f"{name}: no done within {timeout} cycles")


def signed32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v if v < 2**31 else v - 2**32


def rows_of(spec: dict):
    rows = [0] * 20
    for k, v in spec.items():
        rows[int(k)] = v
    return tuple(rows)


def load_fixtures():
    return json.loads((ROOT / "tests" / "fixtures" / "hand_fixtures.json").read_text())


def pack(rows) -> int:
    return sum(rows[y] << (10 * y) for y in range(20))


def unpack(value: int):
    return tuple((value >> (10 * y)) & 1023 for y in range(20))


def pack_heights(heights) -> int:
    return sum(h << (5 * i) for i, h in enumerate(heights))


def rng(seed: int) -> random.Random:
    return random.Random(seed)
