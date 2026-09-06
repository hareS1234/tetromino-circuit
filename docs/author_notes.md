# Author notes

These notes collect the choices that mattered, the evidence behind them, and a few ideas worth
revisiting before I call the design finished.

## Measurement boundaries

Each numbered job has its commands, exit codes, and check counts under `results/evidence/`; the
progress logs name the last passing gate and the next one.

There was no FPGA board in the loop. Hardware numbers are Yosys/nextpnr estimates for the ECP5
device model. The long game runs use the Python policy model. The supported Mac toolchain passed a
clean-clone check, and the remote `fast` and `hdl` jobs passed at the recorded commit. These results
still describe a routed model and a software policy study, not measurements from a physical board.

## Decisions recorded during the build

| After | Decision | Evidence behind it | Loose end |
|---|---|---|---|
| U04 | Use 23 banks, one global `advance`, candidate-private boards after P3, prefix/select compaction, and a one-register best feedback path. Declare only `Config(2, 1, 1, 1, 0)`. | A1 spends 23 of its 40 candidate cycles in the compactor; the ownership argument is in `docs/design_a2.md` §3. | Routing at 50 MHz was still unknown. U12 later reached 76 MHz on seed 1. |
| U06 | Five prefix strides and a match/select network, not a procedural scatter. | The actual HDL passed all 2^20 keep masks and an unbounded miter proof. | Nothing local to the block; whole-core equivalence still relies on simulation. |
| U10 | Keep the public core single-outstanding. Put A2 in lane slot 0 and reuse `REDUCE/FINALIZE/RESPOND`. | `D(N) = N + 29` on 3,000 states and `R(N) = N + 31` on 200 request pairs. | A multi-context core might improve board throughput, but it is a different ownership problem. |
| U12 | Replace the P14 maximum tree with a one-hot priority select; do not add a bank. | The first route put the worst path in the P14 comparator tree (13.93 ns). After the change it moved to candidate enumeration (13.10 ns, 76.36 MHz). | Reaching 80 MHz probably means registering `j → cand_rom → shape_rom → hsel`. |
| U17 | Measure six configurations at four clocks and three seeds, plus P1/P5–P7 at 50 MHz. Keep four-lane timeouts as results. | Four-lane pilots ranged from a 214 s pass to a 3,600 s non-converging run. | Three seeds cannot tell placement luck from a repeatable fan-out problem. |

## Code-reading checklist

1. Follow a candidate through `rtl/tetris_core.sv`, `rtl/search_pipeline.sv`, and
   `rtl/candidate_pipe.sv`. Confirm that `advance = !rst && (!valid[22] || m_ready)` keeps every bank
   in step.
2. Compare `model/game.py` with `tests/reference_grid.py`. Identify the oracle of record and the
   failures that the second implementation can catch.
3. Pick one route record and one quality record under `results/v2/raw/`. Trace their source, tool,
   and protocol identities. Then make a temporary edit and confirm that the checker rejects it.
4. Design an experiment that separates a lucky P1 policy from a useful coefficient pattern.

Later experiments could include a coefficient search restricted to development streams, a shared
board store for replicated lanes, and one more A2 bank for the enumeration chain. A physical board
would be fun too.
