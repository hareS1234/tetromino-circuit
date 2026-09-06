# Design notes from code inspection

Each entry states the concept, points to its implementation, and ends with a small code-reading
exercise. These notes form a learning path and do not act as a release gate.

## Entry from above (`docs/spec.md`, `model/game.py`, `rtl/drop_unit.sv`)

The original rule initialised a piece at `y = 20 - height` inside the board. With no hidden rows,
a piece whose columns have different bottom offsets could materialise with its short column already
beneath a block near the top: the fixture `spawn_under_overhang_J` (rows 15 and 18 = 4, J rotation
3 at x = 2) is accepted at y = 16 by the old rule and correctly rejected by descent from y = 20.
The A0 drop unit implements that descent literally (`drop_unit.sv`, states CHECK → DESCEND → FINISH);
A1 uses the closed form `max(0, max(hs[x+dx] − bottom[dx]))` (`drop_fast.sv`), which is exact only
because the action model has no lateral movement after entry.

*Exercise:* Find the physical anchor for J rotation 3 at x = 2 when rows 15 and 18 equal 4. The answer
is 19, which makes the three-row piece protrude above row 19.

## Ready/valid with a stalled consumer (`rtl/tetris_core.sv`, `tb/tb_protocol.py`)

`req_ready` is high only in IDLE. After FINALIZE the core sits in RESPOND with `rsp_valid = 1`; the
response registers are written once and are not touched until `rsp_ready` is sampled high on a rising
edge, so a consumer that stalls for 1, 3, 17 or 100 cycles (`empty_board_all_pieces_and_stalls`) sees
identical fields. The latency counter stops counting in RESPOND, so `cycles_o` reports the compute time
independent of the stall.

*Exercise:* Trace the counter and response registers during the 50-cycle stall in
`edge_counter_matches_with_stalled_response`.

## Sequential evaluator cycle cost (`results/stage_cycles_a0_repr0_p0.json`)

For a legal candidate without a clear, A0 spends 277 cycles: 25 in the descent, 7 in the four-cell
merge, 23 in the compactor, 213 in the one-cell-per-cycle feature scan, and the rest in control. A1
spends 39–40: the descent, merge and features become one, one and two cycles, and the reused
compactor's 23 cycles are now 58% of the total.

*Exercise:* Calculate A1's per-candidate latency with a one-cycle compactor. Then trace the control
states that still prevent an initiation interval of one.

## Bitmap and height cache roles (`rtl/board_profile.sv`, `docs/spec.md`)

Heights are lossy: two boards with identical heights can differ in holes and in which rows are one
cell from full. The cache (`BOARD_REPR=1`) therefore only replaces the *input-board* profile that the
landing formula needs; merge, clear and post-clear features still run on the bitmap, and the
post-clear board is re-profiled (`features_fast.sv`) because it is a different board.

*Exercise:* Find the paths in `candidate_eval.sv` that keep `heights_q` out of post-clear scoring.

## Depth-two scoring (`model/lookahead.py`, `rtl/search_depth2.sv`)

S2 evaluates the leaf board once: `wL·(L1+L2) − wA·A(B2) − wQ·Q(B2) − wU·U(B2)`. Adding S1 (which
already contains −wA·A(B1)…) to the leaf score would penalise the intermediate board as well as the
final one. In hardware the leaf evaluator returns its own score with L2 in 0–4 and the controller adds
`bonus = wL·L1` from a four-entry table, so the three-bit line input of the scorer is never overloaded.

*Exercise:* Find the B1 register in `search_depth2.sv`, then trace its lifetime across the leaf
evaluations.

## Limits of routed timing (`results/implementation.csv`)

nextpnr reports a maximum frequency for register-to-register paths under the 50 MHz constraint. I/O
is auto-allocated and unconstrained. The result covers internal paths on the modeled ECP5-85k speed
grade 6 device for that seed. It provides no I/O timing, pinout, power, or physical-board data.

*Exercise:* Compare the single-stage and two-stage `drop_fast` paths. Record the clock gain and added
cycles per candidate.
