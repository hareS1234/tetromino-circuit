# Results

`tools/write_report_v2.py` generates this file from committed records. `make check-report-v2` compares a fresh copy. Cycles are RTL-simulation counts under the documented request/response protocol. Routed fmax is nextpnr-ecp5's reported value for the LFE5U-85F device model with auto-allocated I/O. It is a model result, never a board measurement. Projections use a clock constraint met by every seed. Host wall time belongs to the runner process. Restricted mean and survival follow `docs/quality_v2.md` §3. Every table names its raw source.

## 1. Hardware matrix v2 (`benchmarks/hardware_v2.json`, U17)

The target is an ECP5 LFE5U-85F CABGA381 speed 6. Yosys uses `synth_ecp5 -nodsp`, and nextpnr-ecp5 uses `--freq` with auto-allocated I/O. Toolchain: `oss-cad-suite-2026-09-04`. Each configuration is synthesized once and reused for every target and seed. The route budget is 600 s (a1-cache-d1-p0-l4 1200 s).

Each raw job is a `route-record-v2` under `results/v2/raw/routes/`. The derived CSV is `results/v2/summary/routes_hardware-v2.csv`. It includes every attempt; this report summarizes current attempts. A met job passes its constraint. A failed job routed below the constraint. A timeout exhausted its declared budget. Counts: {'completed': 84, 'reused': 0, 'successes': 44, 'failures': 32, 'timeouts': 8, 'errors': 0}.

### 1.1 Routing outcomes per configuration and clock constraint (seeds 11, 12, 13)

| Configuration | LUT4 | FF | CCU2C | 50 MHz | 60 MHz | 80 MHz | 100 MHz |
|---|---:|---:|---:|---|---|---|---|
| X0 A0 serial, bitmap (`a0-bitmap-d1-p0-l1`) | 3071 | 2416 | 224 | 3/3 met; fmax 64.7–66.1 | 3/3 met; fmax 64.7–66.1 | 0/3 met, 3 failed; fmax 64.7–66.1 | 0/3 met, 3 failed; fmax 64.7–66.1 |
| X1 A1 fast, bitmap (`a1-bitmap-d1-p0-l1`) | 4043 | 2121 | 342 | 3/3 met; fmax 67.1–67.9 | 3/3 met; fmax 67.1–67.9 | 0/3 met, 3 failed; fmax 67.1–67.9 | 0/3 met, 3 failed; fmax 67.1–67.9 |
| X2 A1 fast, height cache (`a1-cache-d1-p0-l1`) | 4030 | 2220 | 342 | 3/3 met; fmax 65.7–65.8 | 3/3 met; fmax 65.7–65.8 | 0/3 met, 3 failed; fmax 65.7–65.8 | 0/3 met, 3 failed; fmax 65.7–65.8 |
| X3 A1 cache, 2 lanes (`a1-cache-d1-p0-l2`) | 7345 | 3738 | 642 | 3/3 met; fmax 64.1–66.9 | 3/3 met; fmax 64.1–66.9 | 0/3 met, 3 failed; fmax 64.1–66.9 | 0/3 met, 3 failed; fmax 64.1–66.9 |
| X4 A1 cache, 4 lanes (`a1-cache-d1-p0-l4`) | 14035 | 6773 | 1225 | 1/3 met, 2 timeout; fmax 63.2 | 1/3 met, 2 timeout; fmax 63.2 | 0/3 met, 1 failed, 2 timeout; fmax 63.2 | 0/3 met, 1 failed, 2 timeout; fmax 63.2 |
| X5 A2 candidate pipeline (`a2-cache-d1-p0-l1`) | 6104 | 5489 | 418 | 3/3 met; fmax 72.4–75.6 | 3/3 met; fmax 72.4–75.6 | 0/3 met, 3 failed; fmax 72.4–75.6 | 0/3 met, 3 failed; fmax 72.4–75.6 |
| A1 cache, P1 powers_of_two (`a1-cache-d1-p1-l1`) | 3941 | 2130 | 324 | 3/3 met; fmax 66.0–66.6 | n/a | n/a | n/a |
| A1 cache, P5 coeff_u4 (`a1-cache-d1-p5-l1`) | 3909 | 2112 | 332 | 3/3 met; fmax 66.4–68.3 | n/a | n/a | n/a |
| A1 cache, P6 coeff_u3 (`a1-cache-d1-p6-l1`) | 3882 | 2100 | 329 | 3/3 met; fmax 65.1–65.6 | n/a | n/a | n/a |
| A1 cache, P7 coeff_u2 (`a1-cache-d1-p7-l1`) | 3883 | 2094 | 322 | 3/3 met; fmax 65.9–68.5 | n/a | n/a | n/a |

### 1.2 Seed-level results at 50 MHz and worst-path categories

| Configuration | seed 11 | seed 12 | seed 13 | worst-path categories (all routed records of the configuration) |
|---|---|---|---|---|
| `a0-bitmap-d1-p0-l1` | 66.09 MHz met (26 s) | 64.70 MHz met (36 s) | 65.69 MHz met (29 s) | landing (A1 closed-form drop / A0 descent) ×12 |
| `a1-bitmap-d1-p0-l1` | 67.11 MHz met (35 s) | 67.20 MHz met (48 s) | 67.90 MHz met (92 s) | landing (A1 closed-form drop / A0 descent) ×8, compactor (ranks/select) ×4 |
| `a1-cache-d1-p0-l1` | 65.67 MHz met (40 s) | 65.75 MHz met (40 s) | 65.69 MHz met (43 s) | landing (A1 closed-form drop / A0 descent) ×12 |
| `a1-cache-d1-p0-l2` | 64.08 MHz met (86 s) | 66.87 MHz met (90 s) | 65.46 MHz met (88 s) | landing (A1 closed-form drop / A0 descent) ×8, lane control ×4 |
| `a1-cache-d1-p0-l4` | timeout (1201 s) | 63.24 MHz met (408 s) | timeout (1201 s) | landing (A1 closed-form drop / A0 descent) ×4 |
| `a2-cache-d1-p0-l1` | 72.40 MHz met (99 s) | 73.37 MHz met (99 s) | 75.63 MHz met (125 s) | A2 enumeration / reducer ×12 |
| `a1-cache-d1-p1-l1` | 66.59 MHz met (41 s) | 65.98 MHz met (42 s) | 66.39 MHz met (41 s) | landing (A1 closed-form drop / A0 descent) ×2, lane control ×1 |
| `a1-cache-d1-p5-l1` | 66.44 MHz met (38 s) | 67.76 MHz met (43 s) | 68.29 MHz met (39 s) | landing (A1 closed-form drop / A0 descent) ×2, compactor (ranks/select) ×1 |
| `a1-cache-d1-p6-l1` | 65.57 MHz met (36 s) | 65.27 MHz met (209 s) | 65.12 MHz met (41 s) | landing (A1 closed-form drop / A0 descent) ×3 |
| `a1-cache-d1-p7-l1` | 67.82 MHz met (38 s) | 68.50 MHz met (41 s) | 65.91 MHz met (42 s) | landing (A1 closed-form drop / A0 descent) ×3 |

### 1.3 Decision cycles on the common 1,000-state corpus and the 50 MHz projection

| Configuration | decisions matched | min | median | mean | max | cycles by N = 9 / 17 / 34 (median) | projection at 50 MHz |
|---|---|---:|---:|---:|---:|---|---|
| `a0-bitmap-d1-p0-l1` | matched 1000/1000 | 125 | 4719 | 5147.4 | 9596 | 2472 / 4686 / 9375 | 94.4 µs (median cycles ÷ 50 MHz; 3/3 seeds met) |
| `a1-bitmap-d1-p0-l1` | matched 1000/1000 | 116 | 790 | 910.4 | 1572 | 422 / 790 / 1572 | 15.8 µs (median cycles ÷ 50 MHz; 3/3 seeds met) |
| `a1-cache-d1-p0-l1` | matched 1000/1000 | 107 | 773 | 887.5 | 1538 | 413 / 773 / 1538 | 15.5 µs (median cycles ÷ 50 MHz; 3/3 seeds met) |
| `a1-cache-d1-p0-l2` | matched 1000/1000 | 64 | 414 | 463.6 | 774 | 234 / 414 / 774 | 8.3 µs (median cycles ÷ 50 MHz; 3/3 seeds met) |
| `a1-cache-d1-p0-l4` | matched 1000/1000 | 44 | 236 | 264.1 | 416 | 146 / 236 / 416 | withheld (1/3 seeds met 50 MHz) |
| `a2-cache-d1-p0-l1` | matched 1000/1000 | 38 | 46 | 51.9 | 63 | 38 / 46 / 63 | 0.9 µs (median cycles ÷ 50 MHz; 3/3 seeds met) |

The projection divides RTL-simulation cycles by a routed clock constraint on a device model. It is withheld when any seed misses 50 MHz. Timing failures and timeouts remain valid outcomes. `make check-hardware-v2` reports missing or corrupt jobs.

The standalone A2 harness sends 4096 consecutive tokens. Acceptance spacing is [1, 1], retirement spacing is [1, 1], and visible latency is [22, 22]. Transfer latency is [23, 23]; occupancy reaches 23 with a mean of 22.866. With 20% bubbles and 30% stalls, acceptance spacing is [1, 41] and mean occupancy is 11.538. All 200/200 request pairs satisfy R(N) = N + 31.


## 2. Evaluator replication (U13; `docs/lanes.md`)

| Counter (`results/v2/lanes/lanes{L}_stats.json`) | LANES = 4 | LANES = 2 |
|---|---:|---:|
| cases with a move | 293 | 293 |
| cross-lane ties | 74 | 58 |
| winner lane finished strictly last | 95 | 134 |
| winner lane finished last or tied | 156 | 230 |
| invalid local bests | 62 | 17 |
| unequal finish cases | 300 | 202 |
| ownership (N = 9 / 17 / 34) | [3, 2, 2, 2] / [5, 4, 4, 4] / [9, 9, 8, 8] | [5, 4] / [9, 8] / [17, 17] |

| Lanes (`results/v2/lanes/synth_l1_l2_l4.json`, `synth_ecp5 -nodsp`) | LUT4 | FF | CCU2C | FF added |
|---|---:|---:|---:|---:|
| 1 (`a1-cache-d1-p0-l1`) | 4,030 | 2,220 | 342 | n/a |
| 2 (`a1-cache-d1-p0-l2`) | 7,345 | 3,738 | 642 | +1,518 |
| 4 (`a1-cache-d1-p0-l4`) | 14,035 | 6,773 | 1,225 | +4,553 |

The common corpus follows `45·⌈N/L⌉ + 7 + L` when every candidate is legal. Each illegal candidate costs 11 cycles. Two lanes give a 1.91× total speed-up, and four lanes give 3.36×. In development routing, four-lane seed 1 timed out at 1,200 s and 3,600 s. Seed 2 met 50 MHz at 65.96 MHz (`docs/lanes.md` §5).

## 3. Coefficient quantization ladder (U14; `docs/precision_v2.md`)

Common-state sensitivity, development split (`benchmarks/states/corpus_d1.jsonl`, 1000 states; `benchmarks/states/corpus_d1_upgrade_dev.jsonl`, 2000 states). These are planning data:

| Profile | coefficients | changed (corpus_d1) | changed (dev 2,000) | certified unchanged | not certified but unchanged | exact ties | ties introduced / broken | median exact gap changed / unchanged |
|---|---|---|---|---:|---:|---:|---|---|
| P5 `coeff_u4` | (15, 10, 7, 4) | 1 / 981 (0.10 %) | 6 / 1963 (0.31 %) | 237 | 743 | 192 | 0 / 0 | 2 / 36 |
| P6 `coeff_u3` | (7, 5, 3, 2) | 25 / 981 (2.55 %) | 76 / 1963 (3.87 %) | 128 | 828 | 192 | 40 / 0 | 15 / 36 |
| P7 `coeff_u2` | (3, 2, 1, 1) | 87 / 981 (8.87 %) | 221 / 1963 (11.26 %) | 141 | 753 | 192 | 35 / 15 | 15 / 36 |

Scorer microbenchmarks and complete A1/cache cores (`results/v2/precision/scorer_study.json`, `synth_ecp5 -nodsp`; scorer-only savings are not core savings):

| Profile | scorer LUT4 | scorer FF | scorer CCU2C | core LUT4 | core FF | core CCU2C | Δ core LUT4 vs P0 |
|---|---:|---:|---:|---:|---:|---:|---:|
| P0 `exact` | 97 | 20 | 26 | 4,030 | 2,220 | 342 | +0 |
| P1 `powers_of_two` | 17 | 18 | 13 | 3,941 | 2,130 | 324 | -89 |
| P2 `two_terms` | 53 | 18 | 26 | 4,041 | 2,220 | 342 | +11 |
| P3 `cap_holes` | 97 | 20 | 26 | 4,058 | 2,216 | 363 | +28 |
| P4 `no_bumpiness` | 72 | 19 | 20 | 3,908 | 2,167 | 272 | -122 |
| P5 `coeff_u4` | 79 | 15 | 21 | 3,909 | 2,112 | 332 | -121 |
| P6 `coeff_u3` | 63 | 13 | 18 | 3,882 | 2,100 | 329 | -148 |
| P7 `coeff_u2` | 28 | 12 | 11 | 3,883 | 2,094 | 322 | -147 |
| P0 with constant multiplies, DSP allowed (reference only) | 25 | 18 | 17 | n/a | n/a | n/a | DSP 4 |


## 4. Quality study v2 (U16; `docs/quality_v2.md`)

Protocol `quality-v2-bag50k` (`benchmarks/config_v2.json`, hash `12e05937e613…`, frozen 2026-09-05T18:23:11Z), suite `bag50k` (held-out): streams 20000–20099 (100 paired seven-bag streams), cap 50,000 locked pieces, 5,000 paired bootstrap resamples (seed 20260905). Raw: one `quality-record-v2` per game under `results/v2/raw/quality/`; analysis `results/v2/summary/quality.json`; figure `results/v2/figures/survival_bag50k.png`.

| Policy | restricted mean pieces (to C) | mean lines | median lines [IQR] | cap hit | top-outs | median survival | duration quartiles |
|---|---:|---:|---|---:|---:|---|---|
| `heuristic-d1-p0` (exact) | 11,846.5 | 4,721.8 | 3,191.5 [1,612.5, 6,390.2] | 2/100 | 98 | 7880 pieces | [4,075, 8,022, 16,018] |
| `heuristic-d1-p1` (powers_of_two) | 22,675.0 | 9,054.7 | 8,619.5 [2,186.2, 14,808.8] | 13/100 | 87 | 21563 pieces | [5,508, 21,590, 37,066] |
| `heuristic-d1-p5` (coeff_u4) | 11,084.5 | 4,416.9 | 2,991.5 [1,513.5, 5,459.8] | 2/100 | 98 | 7337 pieces | [3,826, 7,522, 13,692] |
| `heuristic-d1-p6` (coeff_u3) | 2,225.7 | 873.1 | 722.5 [357.8, 1,139.8] | 0/100 | 100 | 1843 pieces | [938, 1,849, 2,892] |
| `heuristic-d1-p7` (coeff_u2) | 680.0 | 254.9 | 224.5 [143.0, 354.2] | 0/100 | 100 | 601 pieces | [400, 604, 928] |
| `random_legal-d1-p0` | 25.6 | 0.1 | 0.0 [0.0, 0.0] | 0/100 | 100 | 26 pieces | [24, 26, 27] |

| Policy vs `heuristic-d1-p0` | Δ restricted mean pieces [CI95] | Δ mean lines [CI95] | Δ cap-hit fraction [CI95] | streams won / lost / tied (pieces) |
|---|---|---|---|---|
| `heuristic-d1-p1` | +10,828.5 [7,082.4, 14,718.9] | +4,332.9 [2,784.3, 5,878.9] | +0.11 [0.05, 0.18] | 64 / 35 / 1 |
| `heuristic-d1-p5` | -762.0 [-3,255.0, 1,855.6] | -304.9 [-1,278.2, 779.4] | +0.00 [-0.04, 0.04] | 31 / 39 / 30 |
| `heuristic-d1-p6` | -9,620.8 [-11,792.5, -7,538.4] | -3,848.7 [-4,729.2, -2,970.5] | -0.02 [-0.05, 0.00] | 12 / 88 / 0 |
| `heuristic-d1-p7` | -11,166.5 [-13,297.2, -9,091.4] | -4,466.9 [-5,330.4, -3,619.5] | -0.02 [-0.05, 0.00] | 1 / 99 / 0 |
| `random_legal-d1-p0` | -11,820.9 [-13,969.0, -9,746.2] | -4,721.7 [-5,573.6, -3,887.7] | -0.02 [-0.05, 0.00] | 0 / 100 / 0 |

Every median is reached within the horizon. Restricted means stop at the cap and do not estimate unbounded survival. The development pilot used seeds 10000–10019 only to size the study. `docs/quality_v2.md` §4 records it.


## 5. A2 verification and timing evidence (U05–U12, U18)

Formal (`results/formal/*.json`): `compactor` unbounded (smtbmc boolector, depth 2); `reducer` unbounded (smtbmc boolector, depth 4); `control` unbounded (smtbmc boolector, depth 8). Mutations (`results/evidence/U11/mutations.json`): 12/12 killed.

| Check | Count | Where |
|---|---|---|
| U05 compactor exhaustive masks + random boards (passed) | pytest_passed 15; compactor_exhaustive 1048576/1048576; compactor_random 100000/100000; formal_smoke 1/1; formal_compactor 1/1; formal_compactor_cover 1/1 | `results/evidence/U05/summary.json` |
| U09 candidate pipeline streams (passed) | rtl_total 4; a2_stream 4096/4096; a2_traffic 1733/1733; a2_metadata 201/201; a2_reset 50/50; synth_candidate_pipe 3/3 | `results/evidence/U09/summary.json` |
| U10 A2 core corpus (passed) | native_decisions 50; rtl_total 1; request_interval_matches_inferred 200/200; a2_latency_equation 200/200; pytest_passed 14 | `results/evidence/U10/summary.json` |
| U11 verification release gate (passed) | pytest_passed 1529; rtl_total 77; native_decisions 3450; compactor_exhaustive 1048576/1048576; compactor_random 100000/100000; compactor_stream_continuous 4096/4096; compactor_stream_random 4096/4096; compactor_stream_stalls 8/8 | `results/evidence/U11/summary.json` |
| U12 A2 routes (passed) | synth_stream_wrapper 4/4; rtl_total 3; synth_features_pipe 3/3; a2_stream 4096/4096; a2_traffic 1733/1733; a2_metadata 201/201; a2_reset 50/50; native_decisions 1000 | `results/evidence/U12/summary.json` |
| U13 four-lane gate (passed) | pytest_passed 14; rtl_total 9; native_decisions 1000 | `results/evidence/U13/summary.json` |
| U14 quantization gate (passed) | pytest_passed 10; rtl_total 24; native_decisions 3000; precision_sensitivity 6/6; scorer_study 16/16; quality_jobs 640/640; quality_summary_recomputed 8/8; route_jobs 45/45 | `results/evidence/U14/summary.json` |
| U15 benchmark machinery (passed) | streams_v2 120/120; pytest_passed 6; quality_v2_pilot_records 120/120; quality_v2_pilot_paired 1/1; quality_v2_pilot_analysis 6/6; quality_v2_pilot50k_records 40/40; quality_v2_pilot50k_paired 1/1; quality_v2_pilot50k_analysis 2/2 | `results/evidence/U15/summary.json` |
| U16 held-out study (passed) | quality_v2_bag50k_records 600/600; quality_v2_bag50k_paired 1/1; quality_v2_bag50k_analysis 6/6; pytest_passed 6 | `results/evidence/U16/summary.json` |
| U18 replay traces (passed) | trace_a2_last_candidate_wins 580/580; trace_a2_normal_search 1108/1108; trace_a2_stall_reset 698/698; viewer 37/37; pytest_passed 439 | `results/evidence/U18/summary.json` |

The A2 timing journal records the worst paths around the P14 regrouping. Seed 1 improved from 71.77 to 76.36 MHz at the 50 MHz constraint (`docs/timing_journal.md`). `tools/check_trace.py` validates the replay traces described in `docs/replay.md`.

## 6. Frozen v1 experiment (E00–E19)

Generated by `tools/write_report.py` from `results/implementation.csv`, `results/decisions/`, `results/quality.csv` and `results/quality_summary.json` (v1 toolchain lock and default DSP policy: a different identity from the v2 matrix above; validated by `make check-v1-results`).

<!-- results:start -->

### Three measured facts

**Verification.** 8,250 complete-core decisions across 9 hardware configurations match the Python literal-descent reference (`results/decisions/*.csv`). Three 250-piece RTL games per depth-one configuration also match Python at every move (`results/replays/`).

**Resources.** The fast exact engine with a height cache (`a1-cache-d1-p0-l1`) synthesizes to 4027 LUT4 and 2220 flip-flops on the ECP5 LFE5U-85F (Yosys `synth_ecp5`), with routed timing 5/5 met 50 MHz; Fmax 64.5–69.0 MHz (`results/implementation.csv`).

**Latency.** The corpus median is 773 core cycles per decision (A0 serial: 4719). The routed projection is 15.5 µs per decision at the timing-supported 50 MHz constraint. It divides simulated cycles by a clock constraint and is not a board measurement.

### Measured results (generated by `tools/write_report.py`; do not edit by hand)

Sources: `results/implementation.csv` contains 45 routing attempts, with 44 meeting timing. The target is an ECP5 LFE5U-85F CABGA381 speed 6 at 50 MHz across seeds 1–5. Decisions come from `results/decisions/`, and policy results come from `results/quality_summary.json`. RTL hash `ae34d12e7803250b`; toolchain `oss-cad-suite-2026-09-04-8fb2384c2f88`.

| Configuration | LUT4 | FF | Routed timing (5 seeds) | Median cycles/decision | Max | Decisions checked |
|---|---:|---:|---|---:|---:|---|
| A0 serial, bitmap (`a0-bitmap-d1-p0-l1`) | 3070 | 2416 | 5/5 met 50 MHz; Fmax 62.6–68.5 MHz | 4719 | 9596 | 1000/1000 match |
| A1 fast, bitmap (`a1-bitmap-d1-p0-l1`) | 4108 | 2121 | 5/5 met 50 MHz; Fmax 65.6–68.6 MHz | 790 | 1572 | 1000/1000 match |
| A1 fast, height cache (`a1-cache-d1-p0-l1`) | 4027 | 2220 | 5/5 met 50 MHz; Fmax 64.5–69.0 MHz | 773 | 1538 | 1000/1000 match |
| A1 cache, P1 powers_of_two (`a1-cache-d1-p1-l1`) | 3966 | 2130 | 5/5 met 50 MHz; Fmax 66.2–69.3 MHz | 773 | 1538 | 1000/1000 match |
| A1 cache, P2 two_terms (`a1-cache-d1-p2-l1`) | 3999 | 2220 | 5/5 met 50 MHz; Fmax 66.5–68.3 MHz | 773 | 1538 | 1000/1000 match |
| A1 cache, P3 cap_holes (`a1-cache-d1-p3-l1`) | 4004 | 2216 | 5/5 met 50 MHz; Fmax 66.8–68.2 MHz | 773 | 1538 | 1000/1000 match |
| A1 cache, P4 no_bumpiness (`a1-cache-d1-p4-l1`) | 3942 | 2167 | 5/5 met 50 MHz; Fmax 65.8–67.2 MHz | 773 | 1538 | 1000/1000 match |
| A1 cache, depth 2 (`a1-cache-d2-p0-l1`) | 4865 | 2849 | 5/5 met 50 MHz; Fmax 64.5–67.2 MHz | 13522 | 52469 | 250/250 match |
| A1 cache, 2 lanes (`a1-cache-d1-p0-l2`) | 7453 | 3738 | 4/5 met 50 MHz; 1 did not converge; Fmax 63.8–66.0 MHz | 414 | 774 | 1000/1000 match |

Projected decision latency uses median cycles ÷ 50 MHz. It is model-based and is not a board measurement. A0 serial, bitmap: 4719 cycles = 94.4 µs at a timing-supported 50 MHz. A1 fast, height cache: 773 cycles = 15.5 µs at a timing-supported 50 MHz. A1 cache, 2 lanes: 414 cycles; projection withheld because not every route seed completed with timing met.

Held-out playing strength, precision study (`results/quality.csv`, experiment `precision`): streams 3000–3099, cap 2000 pieces, Python bit-exact policies backed by the RTL differential corpora above.

| Policy | Mean lines | Median | IQR | Cap-hit | Top-out | Mean pieces | Mean diff vs exact (95% paired bootstrap CI) | Corpus disagreement with exact |
|---|---:|---:|---|---:|---:|---:|---|---:|
| heuristic-d1-p0 | 752.6 | 796 | 792–797 | 87% | 13% | 1897 | baseline |  |
| heuristic-d1-p1 | 756.6 | 797 | 795–798 | 91% | 9% | 1904 | +4.04 [-37.20, +42.55] | 4.2% |
| heuristic-d1-p2 | 752.6 | 796 | 792–797 | 87% | 13% | 1897 | +0.00 [+0.00, +0.00] | 0.0% |
| heuristic-d1-p3 | 730.3 | 796 | 792–797 | 80% | 20% | 1842 | -22.33 [-52.04, +6.66] | 5.9% |
| heuristic-d1-p4 | 16.1 | 14 | 8–21 | 0% | 100% | 79 | -736.47 [-760.99, -707.82] | 43.6% |
| random_legal-d1-p0 | 0.1 | 0 | 0–0 | 0% | 100% | 26 | -752.51 [-777.25, -723.70] |  |

Depth study (`results/quality.csv`, experiment `depth`; predeclared smaller workload): streams 3000–3019, cap 500 pieces, exact profile, compare only within this table.

| Policy | Mean lines | Median | IQR | Cap-hit | Mean diff vs depth 1 (95% CI) | Median RTL cycles/decision |
|---|---:|---:|---|---:|---|---:|
| heuristic-d1-p0 | 195.3 | 196 | 194–199 | 95% | baseline | 773 |
| heuristic-d2-p0 | 198.5 | 199 | 198–199 | 100% | +3.15 [+1.40, +5.70] | 13522 |

Tournament (`results/tournament_report.json`): seed 2000, cap 100, actual RTL replays. Lines: A0 serial, bitmap 33, A1 fast, height cache 33, A1 cache, P1 powers_of_two 37, A1 cache, depth 2 37. First move differing from A0: A0 serial, bitmap never, A1 fast, height cache never, A1 cache, P1 powers_of_two 40, A1 cache, depth 2 2.

<!-- results:end -->
