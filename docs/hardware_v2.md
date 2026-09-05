# v2 hardware matrix: serial reuse, replication and pipelining across clock constraints (U17)

The release matrix is `benchmarks/hardware_v2.json` (schema `hardware-matrix-v2`), executed by
`make measure-v2 MODE=run` (one sequential runner, resumable by full route identity, heartbeat
≤ 60 s) and accounted for by `make check-hardware-v2`. The generated tables are in
[`docs/results.md`](results.md) §1; the figures in `results/v2/figures/` carry per-point job keys
(`*.points.json`). This document records the protocol, the outcomes and the worst-path categories.

## 1. Protocol

| Item | Value |
|---|---|
| Device / tools | ECP5 LFE5U-85F CABGA381 speed 6; Yosys `synth_ecp5 -nodsp`; nextpnr-ecp5 with `--freq <target>` as the only constraint, I/O auto-allocated (`--lpf-allow-unconstrained`); pinned suite `oss-cad-suite-2026-09-04` |
| Top | `stream_wrapper` (the 32-bit streaming wrapper around `tetris_core`, as in v1) |
| Exact configurations (X0–X5) | `a0-bitmap-d1-p0-l1`, `a1-bitmap-d1-p0-l1`, `a1-cache-d1-p0-l1`, `a1-cache-d1-p0-l2`, `a1-cache-d1-p0-l4`, `a2-cache-d1-p0-l1` |
| Targets × seeds | {50, 60, 80, 100} MHz × seeds {11, 12, 13} — 72 jobs |
| Precision cores | `a1-cache-d1-p{1,5,6,7}-l1` at 50 MHz × seeds {11, 12, 13} — 12 jobs (P0 is X2) |
| Synthesis | one per configuration (synth key), reused for every target and seed; the record stores the netlist hash |
| Route budget | 600 s per job; 1,200 s for four lanes (after the U13 pilots: seed 1 did not converge in 3,600 s, seed 2 routed in 214 s) |
| Statuses | `routed_timing_met` (report PASS at the constraint), `routed_timing_failed` (routed, report below the constraint), `route_timeout` (budget exhausted: an observed resource limit under that budget, never proof that the netlist cannot route). Tool errors and cancelled jobs are *not* outcomes and are reported by `check-hardware-v2` as incomplete work |
| Decisions | the six exact configurations on the 1,000-state v1 corpus with the native driver (`decision-record-v2`, matched against the literal reference) |
| Identity | `route_key = H(synth_key, netlist sha256, target, seed, device, nextpnr identity, budget)`; a record is reused only under an identical key (`docs/identities.md`) |

Every job is one file `results/v2/raw/routes/<route_key>.json`; the derived
`results/v2/summary/routes_hardware-v2.csv` lists every attempt with a `current` flag, and
`results/v2/summary/matrix_hardware-v2.json` records the manifest hash, toolchain, source closure and
the status of each expected job.

## 2. Outcomes

`make check-hardware-v2`: 84/84 jobs have an outcome record under their planned identity, 6/6 decision
corpora matched, 84/84 current rows in the derived CSV. Outcomes: **44 met, 32 failed timing, 8
timeouts, 0 errors**; wall time 15,890 s (4.4 h) on two cores, peak RSS 831 MB (four lanes). Log:
`results/evidence/U17/matrix_run.log`; first-run summary: `results/evidence/U17/matrix_hardware-v2.run.json`.

| Configuration | LUT4 / FF / CCU2C (routed) | 50 MHz | 60 MHz | 80 MHz | 100 MHz | reported fmax over the routed seeds |
|---|---|---|---|---|---|---|
| X0 `a0-bitmap-d1-p0-l1` | 3,071 / 2,416 / 224 | 3/3 met | 3/3 met | 0/3 | 0/3 | 64.70–66.09 MHz |
| X1 `a1-bitmap-d1-p0-l1` | 4,043 / 2,121 / 342 | 3/3 met | 3/3 met | 0/3 | 0/3 | 67.11–67.90 MHz |
| X2 `a1-cache-d1-p0-l1` | 4,030 / 2,220 / 342 | 3/3 met | 3/3 met | 0/3 | 0/3 | 65.67–65.75 MHz |
| X3 `a1-cache-d1-p0-l2` | 7,345 / 3,738 / 642 | 3/3 met | 3/3 met | 0/3 | 0/3 | 64.08–66.87 MHz |
| X4 `a1-cache-d1-p0-l4` | 14,035 / 6,773 / 1,225 | 1 met, 2 timeout | 1 met, 2 timeout | 1 failed, 2 timeout | 1 failed, 2 timeout | 63.24 MHz (seed 12 only) |
| X5 `a2-cache-d1-p0-l1` | 6,104 / 5,489 / 418 | 3/3 met | 3/3 met | 0/3 | 0/3 | 72.40–75.63 MHz |
| P1 `a1-cache-d1-p1-l1` | 3,941 / 2,130 / 324 | 3/3 met | — | — | — | 65.98–66.59 MHz |
| P5 `a1-cache-d1-p5-l1` | 3,909 / 2,112 / 332 | 3/3 met | — | — | — | 66.44–68.29 MHz |
| P6 `a1-cache-d1-p6-l1` | 3,882 / 2,100 / 329 | 3/3 met | — | — | — | 65.12–65.57 MHz |
| P7 `a1-cache-d1-p7-l1` | 3,883 / 2,094 / 322 | 3/3 met | — | — | — | 65.91–68.50 MHz |

Per seed the reported fmax is *identical at every target* (`results/v2/figures/fmax_by_seed.png`,
`docs/results.md` §1.2): nextpnr's timing-driven placement produced the same critical path whether
the constraint was 50 or 100 MHz, so "failed at 80 MHz" and "met at 60 MHz" are one number per seed
compared against four thresholds, not four different implementations. The eight four-lane timeouts
are seeds 11 and 13 at every target; seed 12 routed in 385–433 s each time. The U13 pilot seeds (1
and 2, `docs/lanes.md` §5) are separate records with their own budgets and are not part of this
matrix.

Decisions (`decision-record-v2`, native driver, 1,000 v1 corpus states each): all six exact
configurations match the literal reference on every state; median cycles A0 4,719, A1 bitmap 790, A1
cache 773, two lanes 414, four lanes 236, A2 46 (Σ over the corpus 5,147,432 / 910,412 / 887,469 /
463,569 / 264,092 / 51,943). The A2 stream statistics (`make a2-stream-stats`): 4,096 back-to-back
tokens with acceptance and retirement spacing 1, visible latency 22, transfer 23, occupancy max 23
(mean 22.87); under 20 % input bubbles and 30 % output stalls the mean occupancy is 11.54; 200/200
request pairs measure `R(N) = N + 31`.

## 3. Worst-path categories

Categories follow `tools/write_report_v2.py::PATH_CATEGORIES` applied to the worst path's start
register (`docs/results.md` §1.2 lists them per configuration):

| Family | Routed records | Worst-path category | Where exactly |
|---|---|---|---|
| A0 | 12 | descent (12) | `u_drop.y_q`/`x_q` — the row-by-row landing counter and its compare against the board |
| A1 (one lane, two lanes, four lanes, P1, P5–P7) | 52 | landing arithmetic (42), compactor output (5), lane control (5) | `u_drop.d_q[*]` → `y_o` (the closed-form landing: signed height differences → maximum); `u_clear.board_o` → `u_feat.colh` (the compactor's registered board feeding the column-height encoders; A1 bitmap seed 13, P5 seed 12); `u_lane.j` → drop/merge decode (the lane's dense-index counter through the candidate ROMs; two lanes seed 13, P1 seed 11) |
| A2 | 12 | enumeration chain (12) | `u_search.j` → `cand_rom` → candidate decode → `shape_rom` → `u_front.hsel` — the P0 height-select mux fed by the dense index, the same path as development route 2 (`docs/timing_journal.md`) |

Two things follow. The A1 family is bounded by one arithmetic path (the closed-form landing) at about
15 ns, which no amount of replication changes — the two- and four-lane cores report the same 63–67 MHz
as one lane. The A2 pipeline's limit is not a datapath stage but the *un-pipelined enumeration* in
front of it; registering the decoded candidate before P0 (one more bank, `D(N) = N + 30`) is the
identified next revision and was deliberately not made inside this experiment.

## 4. What the matrix says

* **Replication does not raise the clock and does not scale linearly.** Four lanes cost 3.48× the LUT4s
  and 3.05× the flip-flops of one lane for 3.36× fewer cycles (Σ), report a *lower* fmax (63.24 vs
  65.7 MHz) and routed on one seed in three within 1,200 s. The 50 MHz projection is withheld for four
  lanes because two of its three seeds have no routed report.
* **Pipelining is the change that paid.** A2 needs 17.1× fewer cycles than one lane (46 vs 773 median),
  meets 50 and 60 MHz on all three seeds at the highest reported fmax of the study (72.40–75.63 MHz) and
  costs 1.51× the LUT4s (6,104 vs 4,030) and 2.47× the flip-flops (5,489 vs 2,220) — the price of 23
  register banks carrying a private 200-bit board per candidate.
* **The clock sweep is a threshold test.** Since every seed's netlist result is target-independent
  here, the useful numbers are the per-seed fmax values and their spread (≤ 3.3 MHz within a
  configuration); the "met/failed" outcomes are those values compared against 50/60/80/100.
* **Nothing here is a board measurement.** Reported fmax comes from nextpnr's timing analysis on the
  device model with auto-allocated I/O; utilisation of the 85F is low (A2 uses about 7 % of its LUT4s),
  so the four-lane routing difficulty is congestion around the broadcast board/height nets and the
  four-way reduction, not device capacity. Timeouts remain recorded outcomes of a seed and a budget.
* **Precision cores are not a hardware story.** P1 and P5–P7 differ from the exact core by at most
  148 LUT4 (3.7 %) and route at the same clock; their effect is on the policy (`docs/quality_v2.md`).

## 5. Evidence

`results/evidence/U17/summary.json`: `make measure-v2 MODE=run` (the runner log with every job's
start/outcome line), `make check-hardware-v2`, `make a2-stream-stats`, `make plots-v2`,
`make results-v2`, `make check-report-v2`.
