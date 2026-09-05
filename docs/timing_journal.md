# A2 timing journal (U12)

Target: ECP5 LFE5U-85F, CABGA381, speed 6, nextpnr-ecp5 0.11.1 (pinned suite 2026-09-04),
`--freq` as the default clock constraint, I/O auto-allocated (`--lpf-allow-unconstrained`),
synthesis with `synth_ecp5 -nodsp` (controlled DSP policy; the v2 identity records it). Every
route below is a raw record under `results/v2/raw/routes/<route_key>.json` with its log under
`build/route/<route_key>/`. One development seed (1) is used here; the multi-seed, multi-clock
study is U17. "Meets timing" means the routed timing report's `PASS` at the requested constraint,
not a physical maximum.

## Route 1 — as assembled in U09/U10 (before)

| Item | Value |
|---|---|
| Source | commit `1bdb517` (`features_pipe.sv` with the comparator maximum tree in P14) |
| Synthesis | 13,498 cells: LUT4 6,235, FF 5,489, CCU2C 493, BRAM 0, DSP 0, no latch; hierarchy contains no `line_clear`, `candidate_eval`, `lane_player` or `drop_fast` instance (A2 path only) |
| Route (50 MHz, seed 1) | `routed_timing_met`, reported fmax 71.77 MHz, 93 s, peak RSS 585 MB; TRELLIS_COMB 7,823, TRELLIS_FF 5,489 |
| Worst path | `u_features.code13_TRELLIS_FF_Q_86.Q` → `u_features.heights14_TRELLIS_FF_Q_20` : 13.93 ns = 5.34 ns logic + 8.59 ns routing, through `g_h[3].m4321` — the P14 height select's 5-bit comparator/maximum tree (three CCU2C comparators in series plus muxes) |
| Category | feature logic (P14 encoders), as anticipated in `docs/design_a2.md` §6 |
| Record | `results/v2/raw/routes/89d1c15de8112bfa…json` |

## Change — one logic grouping in P14

The highest nonempty 4-bit group of a column was selected by a maximum tree over the encoded
values `4g + code_g` (`(v4 > v3) ? v4 : v3`, …, three levels of 5-bit magnitude comparators). The
same function is a priority select on the five one-bit "group nonempty" flags: `sel[g] = ne[g] &&
!ne[g+1..4]` (one-hot), `height = OR_g (v[g] & {5{sel[g]}})`. No register boundary moved, no bank
was added: the stage manifest, the latency constants (visible 22, transfer 23, `D(N) = N + 29`) and
every cycle equation are unchanged. The block test (`make test-features-pipe`: 200 one-hots,
height-20 columns, 10,000 boards), the whole-pipeline streams (`tools/a2_native.py --phase all`)
and the 1,000-state core corpus were re-run on the revised source before routing.

## Route 2 — after the change

| Item | Value |
|---|---|
| Synthesis | 13,271 cells: LUT4 6,104 (−131), FF 5,489 (=), CCU2C 418 (−75), DSP 0, no latch |
| Route (50 MHz, seed 1) | `routed_timing_met`, reported fmax **76.36 MHz** (+4.6 MHz), 91 s |
| Worst path | `u_search.j_TRELLIS_FF_Q_5.Q` → `u_front.hsel0[1]_TRELLIS_FF_Q_2` : 13.10 ns = 4.89 ns logic + 8.21 ns routing — dense index `j` → `cand_rom` → candidate decode → `shape_rom` → P0 height selection mux |
| Category | height select (P0) fed by the enumeration ROM chain (`docs/design_a2.md` §6 lists P0's height mux as a candidate) |
| Record | `results/v2/raw/routes/8b0b4756e36fd3a3…json` |

## Pilots at additional targets (seed 1, same source)

| Target | Status | Reported fmax | Record |
|---|---|---|---|
| 60 MHz | `routed_timing_met` | 76.36 MHz | `02580bd7544d5767…json` |
| 80 MHz | `routed_timing_failed` (return code 1, report present) | 76.36 MHz | `6a5af1f0758a8cd3…json` |

Timing-driven placement produced the same netlist result at all three constraints for this seed,
so 76 MHz is the observed ceiling of this source with one seed; 80 MHz would need the
`j → cand_rom → shape_rom → hsel` chain shortened (registering the decoded candidate before P0 adds
a bank and changes the schedule — a separate revision with manifest/equation updates, not made
here). The v1 A1/cache configuration reported 62–69 MHz at 50 MHz in `results/implementation.csv`
(different identity: default DSP policy, v1 toolchain lock), so the pipelined evaluator is not
slower per cycle while evaluating one candidate per cycle instead of one per 39–40 cycles.

## Status of the U12 gate

At least one complete A2 route meets 50 MHz (routes 1 and 2, seed 1) and the exact source of
route 2 passes U11's functional gates (re-run on the revised `features_pipe.sv`). Multi-seed
robustness and the clock sweep are U17; no figure here is a physical maximum or a board result.
