# Author notes

*These notes are the author's to write, in the author's own words, after reviewing the RTL and the
evidence. Nothing below invents a personal debugging story; the sections marked "to be written by
the author" are deliberately left as instructions rather than filled in by the helper that executed
the jobs.*

## How this repository was made (provenance, stated plainly)

* The game contract (`drop-v1.1`), the v1 build manual (`docs/history/BUILD_MANUAL.md`) and the v2
  upgrade guide (`docs/A2_UPGRADE_GUIDE.md`) were written with planning notes and revised after audits
  (`docs/history/PROBLEMS_FOUND.md`, `docs/history/audit_response.md`).
* The implementation jobs E00–E19 and U00–U20 were executed with Contributor in a cloud sandbox, one
  job at a time, each closed by a gate whose commands, exit codes and counts are recorded under
  `results/evidence/` (schemas `gate-v1` for v1 and `upgrade-evidence-v1` for v2). The progress logs
  (`docs/history/progress.md`, `docs/upgrade_progress.md`) name the last passing job and the next
  command at every step.
* No FPGA board was used. Every hardware figure is a Yosys/nextpnr result on the ECP5 device model;
  every quality figure comes from the Python model whose decisions passed their own-reference RTL
  tests. The blocked items (a remote CI run, a Mac reproduction) are recorded as blocked, not done.

## Decision records at the guide's checkpoints (executor's record, for the author to review)

Guide §12.5 asks for brief notes after U04, U06, U10, U12 and U17: what was chosen, what evidence
affected it, what remains uncertain. These are the records kept by the helper that executed
the jobs; they are facts about the decisions, not the author's understanding.

| After | What was chosen | Evidence that affected it | Still uncertain |
|---|---|---|---|
| U04 | 23 banks with one global `advance`, candidate-private boards from P3, prefix/select compaction, a one-register best feedback; A2 declared only as `Config(2, 1, 1, 1, 0)` | A1's residency (23 of 40 cycles in the 20-iteration compactor); the hazard argument in `docs/design_a2.md` §3 | whether 23 banks would route at 50 MHz (answered in U12: yes, 76 MHz at seed 1) |
| U06 | five prefix strides + one match/select network instead of a scatter, verified exhaustively on all 2^20 keep masks and by an unbounded miter | the exhaustive native run and the k-induction proof both passed on the actual HDL | none for the block; whole-core equivalence rests on simulation (V11–V14) |
| U10 | the public core stays single-outstanding; A2 occupies lane slot 0 and reuses the v1 `REDUCE/FINALIZE/RESPOND` path | measured `D(N) = N + 29` on 3,000 states and `R(N) = N + 31` on 200 request pairs | a multi-context core would raise throughput; excluded by the ownership argument, not measured |
| U12 | one logic change (P14 maximum tree → one-hot priority select), no bank added | route 1 worst path was the P14 comparator tree (13.93 ns); route 2 moved it to the enumeration chain (13.10 ns, 76.36 MHz) | 80 MHz needs the `j → cand_rom → shape_rom → hsel` chain registered (one more bank; not made) |
| U17 | six exact configurations × four clocks × three seeds plus the P1/P5–P7 cores at 50 MHz, `-nodsp`, 600 s budget with 1,200 s for four lanes; timeouts kept as outcomes | U13's four-lane routes (seed 1 non-converging at 3,600 s, seed 2 met in 214 s) fixed the four-lane budget and the "timeouts are outcomes" rule | whether the four-lane timeouts are placement luck or a fan-out property; not resolved by three seeds |

## What I checked myself — to be written by the author

Instructions, to be answered in the first person after reading the code:

1. Open `rtl/tetris_core.sv`, `rtl/search_pipeline.sv` and `rtl/candidate_pipe.sv`. Can you follow
   a candidate from `s_valid` to `best_reducer` and explain why `advance = !rst && (!valid[22] ||
   m_ready)` keeps every bank consistent? (`viewer/demo.html` replays a real trace.)
2. Open `model/game.py` and `tests/reference_grid.py`. Why are two independent references kept, and
   which one is the oracle of record?
3. Pick one route record under `results/v2/raw/routes/` and one quality record under
   `results/v2/raw/quality/`. Which fields make the record reproducible, and what would have to change
   in the repository for `make check-hardware-v2` or `make check-quality-v2` to reject it?
4. Which result surprised you (the U16 P1-versus-P0 outcome is a candidate), and what would you run
   next to understand it?

## What I would do differently — to be written by the author

(coefficient search on the development streams; a shared board store for lanes; registering the
`j → cand_rom → shape_rom → hsel` chain for A2 at 80 MHz; a physical board.)
