# Author notes

This page keeps two things apart: facts recorded while the jobs ran, and the understanding I still
need to put into my own words. The second part cannot be sensibly outsourced.

## Provenance

The `drop-v1.1` contract, the v1 build manual, and the A2 upgrade guide were drafted with planning notes and
then revised against the repository audits. Contributor ran the E00–E19 and U00–U20 implementation jobs
in a cloud sandbox. Each job has its commands, exit codes, and check counts under
`results/evidence/`; the progress logs name the last passing gate and the next one.

There was no FPGA board in the loop. Hardware numbers are Yosys/nextpnr estimates for the ECP5
device model, and the long game runs use the Python policy model. The Mac toolchain now enrolls and
passes its doctor, but its clean-clone record and the remote CI run do not exist yet. That distinction
is more important than making the project sound finished.

## Decisions recorded during the build

These are executor notes, not claims about what I personally understood at the time.

| After | Decision | Evidence behind it | Loose end |
|---|---|---|---|
| U04 | Use 23 banks, one global `advance`, candidate-private boards after P3, prefix/select compaction, and a one-register best feedback path. Declare only `Config(2, 1, 1, 1, 0)`. | A1 spends 23 of its 40 candidate cycles in the compactor; the ownership argument is in `docs/design_a2.md` §3. | Routing at 50 MHz was still unknown. U12 later reached 76 MHz on seed 1. |
| U06 | Five prefix strides and a match/select network, not a procedural scatter. | The actual HDL passed all 2^20 keep masks and an unbounded miter proof. | Nothing local to the block; whole-core equivalence still relies on simulation. |
| U10 | Keep the public core single-outstanding. Put A2 in lane slot 0 and reuse `REDUCE/FINALIZE/RESPOND`. | `D(N) = N + 29` on 3,000 states and `R(N) = N + 31` on 200 request pairs. | A multi-context core might improve board throughput, but it is a different ownership problem. |
| U12 | Replace the P14 maximum tree with a one-hot priority select; do not add a bank. | The first route put the worst path in the P14 comparator tree (13.93 ns). After the change it moved to candidate enumeration (13.10 ns, 76.36 MHz). | Reaching 80 MHz probably means registering `j → cand_rom → shape_rom → hsel`. |
| U17 | Measure six configurations at four clocks and three seeds, plus P1/P5–P7 at 50 MHz. Keep four-lane timeouts as results. | Four-lane pilots ranged from a 214 s pass to a 3,600 s non-converging run. | Three seeds cannot tell placement luck from a repeatable fan-out problem. |

## Questions for my own code-reading pass

1. Follow a candidate through `rtl/tetris_core.sv`, `rtl/search_pipeline.sv`, and
   `rtl/candidate_pipe.sv`. Why does `advance = !rst && (!valid[22] || m_ready)` keep every bank in
   step?
2. Compare `model/game.py` with `tests/reference_grid.py`. Which is the oracle of record, and what
   failure would the second implementation catch?
3. Pick one route record and one quality record under `results/v2/raw/`. Which fields tie it to the
   sources, tools, and protocol? What edit would make the checker reject it?
4. The P1 result is surprising. What experiment would distinguish a lucky fixed policy from a
   useful coefficient pattern?

Things worth considering after that pass: a coefficient search restricted to development streams,
a shared board store for replicated lanes, one more A2 bank for the enumeration chain, and—at some
point—the rather important business of putting it on a physical board.
