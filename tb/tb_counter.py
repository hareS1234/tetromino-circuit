import cocotb
from cocotb.triggers import Timer


async def tick(dut):
    dut.clk.value = 0
    await Timer(5, unit="ns")
    dut.clk.value = 1
    await Timer(5, unit="ns")


@cocotb.test()
async def reset_count_and_wrap(dut):
    dut.clk.value = 0
    dut.rst.value = 1
    await tick(dut)
    assert int(dut.count.value) == 0

    dut.rst.value = 0
    for expected in range(1, 261):
        await tick(dut)
        assert int(dut.count.value) == expected % 256

    dut.rst.value = 1
    await tick(dut)
    assert int(dut.count.value) == 0
