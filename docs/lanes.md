# Evaluator replication: one, two and four A1 lanes (U13)

The A1 fast evaluator (`rtl/lane_player.sv`) evaluates one candidate at a time; `tetris_core`
instantiates `LANES` copies, each owning every `LANES`-th entry of the dense candidate list, and
reduces the local winners in a separate state. v1 verified one and two lanes
(`a1-cache-d1-p0-l1`, `a1-cache-d1-p0-l2`). U13 adds exactly `Config(1, 1, 4, 1, 0)`
(`a1-cache-d1-p0-l4`) as a verified configuration and records what four lanes actually buy.
Every number below is from the commands listed in `results/evidence/U13/summary.json`; the frozen
v1 files are untouched.

## 1. What changed

* `model/config.py`: `Config(1, 1, 4, 1, 0)` added to `SUPPORTED` (eleven verified identities;
  `V1_SUPPORTED_IDS` remains the frozen nine). Four lanes with the bitmap representation, depth two,
  an approximate profile or A0/A2 stay unsupported in Python and in elaboration.
* `rtl/tetris_core.sv`: `CFG_OK` accepts `ARCH == 1 && BOARD_REPR == 1 && LANES == 4 && DEPTH == 1
  && PRECISION == 0`. Nothing else in the core changed: the lane array, `lane_done` accumulation
  (`lane_done_seen | lane_done`), the `REDUCE` state (one lane per cycle in index order, global
  tie-break on the lower candidate id) and `RKW = $clog2(LANES)` were already parameterised.
* `rtl/lane_player.sv`: unchanged. Its dense-index arithmetic (`LANE_INDEX + k*LANES`) was audited
  against the ownership check below rather than rewritten.
* `tb/tb_lanes.py` and `make test-lanes LANES=…`: the two-lane-only test (fixed `range(2)`,
  `% 2`, `ids[k::2]`, two-entry statistics) is parameterised for `LANES` 2 and 4 and made stricter
  (see §2). It writes per-lane counters to `results/v2/lanes/lanes<L>_stats.json`.

## 2. Ownership and lane-interaction checks (`make test-lanes LANES=4`)

300 corpus states (`benchmarks/states/corpus_d1.jsonl`, the categories `equal_scores`,
`last_candidate_winner`, `no_move` and `blocked_spawn` first, then the rest), one cocotb test,
Verilator. For every state the test asserts:

* the sets `ids[k::LANES]` are disjoint and their union is the dense candidate list, and their
  sizes are exactly O `[3, 2, 2, 2]`, N = 17 `[5, 4, 4, 4]`, N = 34 `[9, 9, 8, 8]` (two lanes:
  `[5, 4]`, `[9, 8]`, `[17, 17]`);
* each lane's `evaluated_o` equals the size of its set (the RTL evaluated exactly the candidates it
  owns, no more);
* the core's decision equals the literal reference (`model/policy.best_move`), including `no_move`
  states where every lane must report an invalid local best.

Counted over the run and required to be nonzero:

| Counter | LANES = 4 | LANES = 2 | Meaning |
|---|---|---|---|
| cases with a move | 293 | 293 | 7 `no_move` states excluded from the winner statistics |
| cross-lane ties | 74 | 58 | the maximal score is shared by candidates owned by different lanes; the global tie-break (lowest candidate id) decides |
| winner lane finished strictly last | 95 | 134 | the winning lane's `active_cycles_o` is strictly greater than every other lane's — the strict witness the guide asks for |
| winner lane finished last or tied | 156 | 230 | the former `>=` count, kept for comparison; it includes equal finish times |
| invalid local bests | 62 | 17 | lane/state pairs where a lane owned no legal candidate (`best_valid_o = 0`) and must not influence the reduction |
| unequal finish cases | 300 / 300 | 202 / 300 | states where the lanes' active cycle counts differ (four lanes always differ because 9, 17 and 34 do not divide by 4) |

Two-lane figures are the same test run with `LANES=2` (`results/v2/lanes/lanes2_stats.json`), a
regression of the v1 configuration under the stricter test.

## 3. Decisions and cycles on the common corpus

`make test-core ARCH=1 BOARD_REPR=1 LANES=4 COUNT=1000 DRIVER=native`: all 1,000 v1 corpus states
match the literal reference and, decision for decision, the one-lane and A2 records of the same
corpus (1,000/1,000 identical rotation/x/y/no_move). Cycle counts (`core_cycles`, request accepted
to response valid):

| Configuration | min | median | mean | max | Σ cycles | speed-up vs one lane (Σ) |
|---|---|---|---|---|---|---|
| `a1-cache-d1-p0-l1` (v1, `results/decisions/`) | 107 | 773 | 887.5 | 1538 | 887,469 | 1.00× |
| `a1-cache-d1-p0-l2` (v1, `results/decisions/`) | 64 | 414 | 463.6 | 774 | 463,569 | 1.91× |
| `a1-cache-d1-p0-l4` (U13, `build/decisions/`) | 44 | 236 | 264.1 | 416 | 264,092 | 3.36× |
| `a2-cache-d1-p0-l1` (U10–U12) | 38 | 46 | 51.9 | 63 | 51,943 | 17.1× |

For the 654 states in which every candidate is legal the count is exactly
`45·⌈N/L⌉ + 7 + L` (N ∈ {9, 17, 34} dense candidates, L lanes): 45 cycles per legal candidate
as seen from the lane (the evaluator's own states plus the lane FSM's `NEXT`/`EVAL_START`/`UPDATE`
steps), a fixed request/cache/finalise overhead of 7 and one `REDUCE` cycle per lane. An
illegal candidate costs 11 cycles (the 7 `no_move` states take `11·⌈N/L⌉ + 7 + L`), so
mixed states finish earlier. Per state the four-lane speed-up ranges from 1.56× (states with few
legal candidates, where the fixed overhead dominates) to 3.74×, median 3.28×. Four lanes do not
give a fourfold speed-up for three reasons that are all visible in the equation: the ceiling
(9 → 3, 17 → 5, 34 → 9 candidates per lane), the extra reduction cycles, and the fixed overhead.
The pipelined evaluator (A2) processes one candidate per cycle after a 29-cycle fill and is the
comparison point, not a fifth lane.

## 4. Area: replicated board and height storage

`synth_ecp5 -nodsp`, `stream_wrapper`, pinned suite (`results/v2/lanes/synth_l1_l2_l4.json`;
synth records under `build/synth/<synth_key>/`):

| Lanes | LUT4 | FF | CCU2C | LUT4 ratio | FF ratio | FF added |
|---|---|---|---|---|---|---|
| 1 | 4,030 | 2,220 | 342 | 1.00 | 1.00 | — |
| 2 | 7,345 | 3,738 | 642 | 1.82 | 1.68 | +1,518 |
| 4 | 14,035 | 6,773 | 1,225 | 3.48 | 3.05 | +4,553 |

The FF growth is 1,518 per added lane (1 → 2 → 4: +1,518, +3,035 = 2 × 1,518, within one flop).
Reading `rtl/lane_player.sv` and `rtl/candidate_eval.sv` against that count: every lane latches
its own copy of the 200-bit board and the 50-bit height cache in `lane_player` (`board_q`,
`heights_q`) and again in its `candidate_eval` (`board_q`, `heights_q`), and its merge and clear
units hold the 200-bit merged and cleared boards — at least 900 of the 1,518 flip-flops per added
lane are replicated board/height storage; the rest are the candidate, feature, score, best and
counter registers of the lane. Only the *source* of the heights is shared (the core profiles the
latched board once and broadcasts fifty bits), which is why the FF ratio (3.05×) is a little below
the LUT ratio (3.48×) but nowhere near a shared-storage design: shared source heights do not make
the per-lane registers disappear, and the guide's caution is confirmed by the count rather than
assumed. LUT4s grow slightly faster than linearly (3.48× for four evaluators); the `REDUCE` mux
over four lanes and the wider `lane_done`/best selection are small, so most of the excess is
per-lane control plus four independent compactors and feature units.

## 5. Development route (seed 1, 50 MHz, nodsp)

`a1-cache-d1-p0-l4` on LFE5U-85F (CABGA381, speed 6), `nextpnr-ecp5 0.11.1`, `--freq 50`,
auto-allocated I/O, `route-record-v2` records under `results/v2/raw/routes/<route_key>.json`:

| Budget | Status | Placement estimate | Routed fmax | Wall | Record |
|---|---|---|---|---|---|
| 1,200 s | **`route_timeout`** — "declared route budget exhausted (a resource limit, not proof the design cannot route)" | 57.15 MHz (PASS at 50 MHz) | none (routing did not finish; no timing report) | 1,200.6 s, peak RSS 773 MB | `3137bdf7316a474f…json` |
| 3,600 s | running when this document was written; its record is added here when it lands | | | | |

Placement finished in 93 s with a 57.15 MHz estimate; `router1` was still at an overflow of
950–1,935 nets after 1,000 s (72,794 arcs), oscillating rather than converging. That is the same
symptom as the one non-converging two-lane seed in the v1 matrix (`results/implementation.csv`:
4/5 two-lane routes met 50 MHz). The likely cause is fan-out rather than utilisation (17 % of the
85F's LUT4s): the core broadcasts the 200-bit latched board and the 50-bit heights to four
evaluators, and each `REDUCE` input multiplexes four 44-bit best records. Nothing here is a timing
result: no routed report exists for four lanes yet, and the timed-out record is kept as the
outcome of this seed and budget. The multi-seed, multi-clock sweep is U17.

## 6. Public protocol and replays

`make test-protocol ARCH=1 BOARD_REPR=1 LANES=4`: 9/9 (`tb_protocol`: acceptance, input
scrambling, response stalls, preview independence, reset). Replays with the four-lane core
(`results/replays/a1-cache-d1-p0-l4_seed200{0,1,2}_cap100.jsonl`, cap 100 pieces): every move
checked against the literal reference.
