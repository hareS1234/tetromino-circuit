# Understanding the design — questions you can answer from the code

Each entry states the concept, where it lives, and a concrete question whose answer is in the
repository. These are the learning path, not a gate.

## Why entry from above matters (`docs/spec.md`, `model/game.py`, `rtl/drop_unit.sv`)

The original rule initialised a piece at `y = 20 - height` inside the board. With no hidden rows,
a piece whose columns have different bottom offsets could materialise with its short column already
beneath a block near the top — the fixture `spawn_under_overhang_J` (rows 15 and 18 = 4, J rotation
3 at x = 2) is accepted at y = 16 by the old rule and correctly rejected by descent from y = 20.
The A0 drop unit implements that descent literally (`drop_unit.sv`, states CHECK → DESCEND → FINISH);
A1 uses the closed form `max(0, max(hs[x+dx] − bottom[dx]))` (`drop_fast.sv`), which is exact only
because the action model has no lateral movement after entry.

*Question:* On the board with rows 15 and 18 equal to 4, what is J rotation 3's physical anchor at
x = 2 and why is the candidate illegal even though every cell it would occupy inside the board is
empty? (Answer: anchor 19; the three-row piece protrudes above row 19.)

## How ready/valid handles a stalled consumer (`rtl/tetris_core.sv`, `tb/tb_protocol.py`)

`req_ready` is high only in IDLE. After FINALIZE the core sits in RESPOND with `rsp_valid = 1`; the
response registers are written once and are not touched until `rsp_ready` is sampled high on a rising
edge, so a consumer that stalls for 1, 3, 17 or 100 cycles (`empty_board_all_pieces_and_stalls`) sees
identical fields. The latency counter stops counting in RESPOND, so `cycles_o` reports the compute time
independent of the stall.

*Question:* Why does `edge_counter_matches_with_stalled_response` pass for stall 50 without the core
knowing anything about the stall length?

## Where the slow evaluator spends its cycles (`results/stage_cycles_a0_repr0_p0.json`)

For a legal candidate without a clear, A0 spends 277 cycles: 25 in the descent, 7 in the four-cell
merge, 23 in the compactor, 213 in the one-cell-per-cycle feature scan, and the rest in control. A1
spends 39–40: the descent, merge and features become one, one and two cycles, and the reused
compactor's 23 cycles are now 58% of the total.

*Question:* If the compactor were replaced by a one-cycle parallel structure, what would A1's
per-candidate latency become, and why would that alone not give one candidate per cycle?

## Why cached heights cannot replace the bitmap (`rtl/board_profile.sv`, `docs/spec.md`)

Heights are lossy: two boards with identical heights can differ in holes and in which rows are one
cell from full. The cache (`BOARD_REPR=1`) therefore only replaces the *input-board* profile that the
landing formula needs; merge, clear and post-clear features still run on the bitmap, and the
post-clear board is re-profiled (`features_fast.sv`) because it is a different board.

*Question:* What in `candidate_eval.sv` guarantees that `heights_q` is never used to score the
post-clear board?

## Why depth two must not count intermediate penalties twice (`model/lookahead.py`, `rtl/search_depth2.sv`)

S2 evaluates the leaf board once: `wL·(L1+L2) − wA·A(B2) − wQ·Q(B2) − wU·U(B2)`. Adding S1 (which
already contains −wA·A(B1)…) to the leaf score would penalise the intermediate board as well as the
final one. In hardware the leaf evaluator returns its own score with L2 in 0–4 and the controller adds
`bonus = wL·L1` from a four-entry table, so the three-bit line input of the scorer is never overloaded.

*Question:* Which register in `search_depth2.sv` holds B1 while its leaves are evaluated, and why is a
separate register needed when the evaluator already outputs `board_o`?

## What the routed timing report does and does not establish (`results/implementation.csv`)

nextpnr reports a maximum frequency for the register-to-register paths of the clock domain under the
50 MHz constraint, with I/O auto-allocated and unconstrained. It establishes that the design's internal
paths fit the constraint on the modelled ECP5-85k speed grade 6 device for that seed. It does not
establish I/O timing, a pinout, power, or anything about a physical board — no board was used.

*Question:* Why did the single-stage `drop_fast` fail at 43.5 MHz while the same logic split into two
registered stages passes at 64 MHz, and what did that cost in cycles per candidate?
