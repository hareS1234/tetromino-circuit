# A2 verification matrix (U11)

Each property of docs/design_a2.md maps to a test, proof or log. Counts are per check; several
checks reuse the same inputs (the 1,000-state v1 corpus feeds V11, V13 and the request-interval
measurement, the 250 mixed boards feed V04 twice) and are not independent unique states. Logs:
`results/evidence/U05`–`U11/cmd*.log`; formal results: `results/formal/*.json`; mutations:
`results/evidence/U11/mutations.json`.

| ID | Property | Evidence | Where |
|---|---|---|---|
| V01 | configuration rejection | Python `validate` accepts exactly `a2-cache-d1-p0-l1`; six neighbouring A2 combinations rejected in Python; elaboration of `tetris_core` with A2+bitmap, +2 lanes, +depth 2, +profile 1 fails on `CFG_OK` while A2 itself elaborates (6/6) | `make check-a2-spec`, `tests/unit/test_a2_spec.py` |
| V02 | rank control | all 2^20 keep masks with tagged rows on the actual HDL (1,048,576/1,048,576); ranks, survivors, keep and board compared with an independent C++ filter | `make test-compactor-native MODE=exhaustive` |
| V03 | row payload | 100,000 arbitrary 200-bit boards (random full-row density) exact board/count/order/padding; 12,000 boards + 20,000 masks in Python | `make test-compactor-native MODE=random COUNT=100000`, `make test-prefix` |
| — | compactor equivalence proof | **unbounded** k-induction (boolector, depth 2, ~51 s) of `line_clear_parallel` against an independent running-index filter plus rank order/uniqueness, keep, count and zero-padding properties; extreme cases covered | `make formal-compactor`, `results/formal/compactor.json` |
| V04 | geometry/merge | all 162 geometric candidates on 250 mixed boards (40,500 tokens) against literal descent and independent locking; spawn-under-overhang regression; anchor height 20; negative differences; four cells in one row | `make test-drop-merge-pipe` |
| V05 | features | empty board, all 200 one-hot positions, height-20 columns, checkerboards, holes, 10,000 arbitrary boards against direct hole counting; scorer at every bound and 10,000 tuples | `make test-features-pipe`, `make test-score-pipe` |
| V06 | continuous streaming | 4,096 accepted tokens under one context: every acceptance spacing 1, every retirement spacing 1, visible latency 22, transfer latency 23, all tags retire once | `make test-a2-stream` (`CHECK a2_stream`) |
| V07 | bubbles and stalls | oracle traffic with 20 % input bubbles and 30 % output stalls over 60 contexts (1,733 tokens; 12,240 over 420 contexts in a larger run), stability monitor; compactor stalls of 1/3/17/100 cycles at first and last outputs; cocotb stall schedules for every block | `make test-a2-stream` (`CHECK a2_traffic`), `make test-compactor-native MODE=stream`, block cocotb tests |
| V08 | reset flush | reset at each of the 24 occupancies of the 23-bank pipeline, stalled and unstalled, at last-token issue and just before retirement; no pre-reset token emerges (50/50); per-block equivalents | `make test-a2-reset`, block cocotb tests |
| V09 | metadata alignment | 64 identical candidates with distinct tags; rotation/x alternating every cycle (128 tokens); last carried by an illegal token; tag = dense index order asserted in `search_pipeline` | `make test-a2-metadata`, `rtl/search_pipeline.sv` assertions |
| V10 | winner hazards | reducer unit test: all illegal, one legal, last wins, exact ties with the highest id first, signed negatives, clear, 200 random sequences vs a shadow model; corpus coverage of 37 no-move and 302 last-candidate-winner decisions (dev), 19 and 141 (v1 corpus) | `make test-reducer`, `make test-a2-core-extra` |
| — | best-reduction proof | **unbounded** k-induction: dominance over an arbitrary witness token, provenance (best only changes to the accepted token), monotonicity, clear; covers reached | `make formal-a2-control`, `results/formal/reducer.json` |
| — | control conservation proof | **unbounded** k-induction on the abstract 5-bank pipeline with the production advance discipline: in-flight count equals set valid bits (≤ banks), output serial equals the next to retire (no spontaneous or duplicate retirement), stability under stalls, flush on reset; fill and drain covered | `results/formal/control.json`, `results/formal/control_cover.json` |
| V11 | whole-core equivalence | 1,000 v1 corpus states + 2,000 development states (`corpus_d1_upgrade_dev.jsonl`, seeds 11000–11099) match literal descent; cycles 38/46/63 = N + 29 | `make test-core ARCH=2 … COUNT=1000`, `make test-a2-core-extra` |
| V12 | public protocol | `tb_protocol` (9) and `tb_wrapper` (4) with A2: input scrambling after acceptance, response stalls, preview independence, reset | `make test-protocol/test-wrapper ARCH=2 BOARD_REPR=1` |
| V13 | driver consistency | native and cocotb agree on all fields and cycle counts for 50 directed requests; 200 request pairs with two real acceptance edges: measured interval = inferred = N + 31 | `make test-driver ARCH=2 …`, `make test-request-interval ARCH=2 …` |
| V14 | full RTL replays | seeds 2000–2002, cap 250, every move checked against the literal reference (95/90/96 lines; move-for-move identical to the v1 A0 replays) | `make replay-suite ARCH=2 BOARD_REPR=1 CAP=250`, `results/replays/a2-*.jsonl` |
| — | A0/A1 regression | directed RTL tests, A0 100-state corpus, two-lane A1 200 states, depth-two A1 100 states, cache, lanes and lookahead tests after the top-level change | `make regress-a0-a1` |
| §8.4 | mutations | twelve deliberate mutations, each killed by a named behavioural check (killing line recorded), sources restored | `make mutation-check-a2` |

Formal scope statement: the three proofs are unbounded k-induction results from the pinned
SBY/boolector; they cover the combinational compactor, the reducer and the abstract control
discipline, not the full core. No proof assumes `m_ready` is always high (the control proof lets
it vary freely); no eventual-completion property is claimed under permanent stalls. Bounded
covers show the extreme cases are reachable. Full-core equivalence rests on simulation (V11–V14).
