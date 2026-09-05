# Tetromino Circuit

A drop-only Tetris search engine in SystemVerilog. It compares a serial evaluator, replicated
evaluators, and a pipeline that overlaps candidate boards, with an independent software reference
and reproducible FPGA implementation experiments.

![Real RTL pipeline trace: the A2 candidate pipeline evaluating a 34-candidate board](assets/a2_pipeline.gif)

*One frame per clock edge of the actual RTL (`results/traces/a2_normal_search.json`): 34 candidates
enter the 23-bank pipeline one per cycle, retire in order, and the running best settles on the winner;
the public response arrives 63 cycles after the request. `viewer/demo.html` replays the same trace
interactively (`docs/replay.md`).*

**Three measured facts** (RTL simulation and device-model implementation; not measured on a board):

1. **Decision latency.** On the common 1,000-state corpus the pipelined evaluator (`a2-cache-d1-p0-l1`)
   needs a median of 46 cycles per decision (`N + 29` for N candidates) against 773 for the one-lane
   fast evaluator — 17.1× fewer cycles in total — while returning the identical move on every state.
   In the 84-route release matrix (six configurations × {50, 60, 80, 100} MHz × three seeds plus the
   precision cores; 4.4 h wall) its three 50 MHz routes on the ECP5 LFE5U-85F all meet timing at
   72.40–75.63 MHz reported, at 6,104 LUT4 / 5,489 flip-flops — 1.51× the LUT4s of the one-lane
   evaluator; every configuration fails 80 and 100 MHz ([`docs/results.md`](docs/results.md)).
2. **Playing strength at a long horizon.** On 100 fresh held-out seven-bag streams with a 50,000-piece
   cap, the powers-of-two coefficient profile P1 survives a restricted mean of 22,675 locked pieces
   against 11,846 for the exact baseline P0 — a paired difference of +10,828 pieces
   (CI95 [7,082, 14,719]) — while the 4-bit quantized profile P5 is indistinguishable from P0
   ([`docs/quality_v2.md`](docs/quality_v2.md)).
3. **Verification.** Every hardware configuration matches the literal-descent Python reference on the
   common corpus (8,250 v1 decisions plus 1,000 per v2 configuration); the parallel row compactor,
   the best reducer and the pipeline control discipline have unbounded k-induction proofs
   (`results/formal/`, compactor status `unbounded`), and twelve deliberate mutations are each killed
   by a named check ([`docs/verification_a2.md`](docs/verification_a2.md)).

## What is here

| | |
|---|---|
| Game contract | [`docs/spec.md`](docs/spec.md) — `drop-v1.1`: 10×20 board, drop-only placement, exact scoring `76·L − 51·A − 36·Q − 18·U`, ties to the lower candidate id, numerical profiles P0–P7 |
| Architectures | [`docs/design.md`](docs/design.md) (A0 serial, A1 fast evaluator, height cache, two lanes, depth two — v1), [`docs/design_a2.md`](docs/design_a2.md) (A2 candidate pipeline), [`docs/lanes.md`](docs/lanes.md) (four lanes) |
| Report | [`docs/research_report.md`](docs/research_report.md) — the six-part technical report with five figures; dense tables in [`docs/results.md`](docs/results.md) |
| Experiments | [`docs/quality_v2.md`](docs/quality_v2.md) (long-horizon quality study), [`docs/precision_v2.md`](docs/precision_v2.md) (quantization ladder), [`docs/timing_journal.md`](docs/timing_journal.md) (A2 timing), [`docs/hardware_v2.md`](docs/hardware_v2.md) (the 84-route release matrix, `benchmarks/hardware_v2.json`) |
| Evidence | `results/evidence/E00–E19` (v1) and `U00–U20` (v2): every job's commands, exit codes and counts; raw records under `results/v2/raw/`, one file per job, keyed by complete identities ([`docs/identities.md`](docs/identities.md)) |
| Replay | [`docs/replay.md`](docs/replay.md), `viewer/`, `assets/a2_pipeline.gif`, `assets/diagrams/*.svg` |
| Toolchain and CI | [`docs/toolchain.md`](docs/toolchain.md) (pinned OSS CAD Suite, per-platform lock), [`docs/ci.md`](docs/ci.md) |
| History | [`docs/history/`](docs/history/README.md) — the v1 manual, audits and job log; upgrade log [`docs/upgrade_progress.md`](docs/upgrade_progress.md) |

## Quickstart

**1. Watch the saved demo** (no tools): open [`viewer/demo.html`](viewer/demo.html) in a browser — the
bundled replay of `results/traces/a2_normal_search.json` with play/pause, step, jump-to-candidate and
the exact bank registers on selection; `assets/a2_pipeline.gif` is the same trace as a GIF. To load
the other traces, `cd viewer && python3 -m http.server` and open `index.html` (`docs/replay.md`).

**2. Run a small correctness check** (Python 3.11/3.12; about a minute):

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.lock && .venv/bin/pip install --no-deps -e .
.venv/bin/python -m pytest tests/unit -q                       # 450+ tests incl. the 40,500-case differential
.venv/bin/python tools/check_claims.py && .venv/bin/python tools/check_trace.py   # numbers ↔ result files; traces
```

With the pinned HDL toolchain (downloads the OSS CAD Suite, about 740 MB, extracted 3 GB, into `.tools/`;
`docs/toolchain.md`):

```bash
bash scripts/bootstrap.sh              # idempotent: pinned suite, venv, per-platform lock check
make doctor && make smoke              # toolchain check; counter simulation + lint + synth_ecp5
make test-core ARCH=2 BOARD_REPR=1 COUNT=50 DRIVER=native      # the A2 core against the reference (≈2 min incl. the Verilator build)
```

**3. Reproduce the full study** (resumable; every job keyed by its complete identity, so a repeated
command re-runs nothing that already has a record):

```bash
make verify-a2-release                 # the A2 verification matrix: cocotb, native corpora, streams, regression (≈10 min)
make measure-v2 MODE=run               # 84 routes + 6,000 decisions: 4.4 h wall on two cores (8 four-lane timeouts of 1,200 s), ≈1 GB under build/
make bench-v2 MODE=run SUITE=bag50k    # 600 held-out games under the committed freeze record (≈11 min, 23 MB RSS)
make analyze-quality-v2 && make plots-v2 && make results-v2 && make check-report-v2
```

The pilots that sized these runs are in `docs/quality_v2.md` §4 and `docs/hardware_v2.md`; `make
measure-v2 MODE=dry-run` and `make bench-v2 MODE=dry-run` list the jobs and budgets without running them.
A changed quality protocol must be frozen again (`make bench-v2 MODE=freeze`) before its held-out suite will run.

`make help` lists every target. Configurations are selected with `ARCH` (0 serial, 1 fast, 2 pipelined),
`BOARD_REPR` (0 bitmap, 1 bitmap + height cache), `LANES` (1, 2, 4), `DEPTH` (1, 2) and `PRECISION`
(0–7); only the fourteen verified combinations are accepted (`python -m model.config --list`;
`model/config.py`, `tetris_core.sv`).

## Limitations

* The game is a simplification: no rotation system or wall kicks, tucks, spins, hold, lock delay,
  soft/hard-drop timing, gravity levels, hidden rows, level or bonus scoring, back-to-back, combos,
  garbage or multiplayer (`docs/spec.md`). Scores are not comparable to workers playing other rules.
* Playing-strength numbers come from the Python bit-exact policy model whose decisions passed their
  own-reference RTL tests; they are labelled as such wherever they appear.
* Cycle counts are RTL-simulation counts under the documented protocol; latency projections divide
  them by a *routed* clock constraint on a device model with auto-allocated I/O. The design was not measured
  on a board, and no power figure is given. A route that exhausts its budget is a recorded outcome
  under that budget, not proof that the design cannot route.
* The heuristic coefficients are an attributed baseline (Lee, 2013), not tuned; the P1 result above is
  an observation about two fixed policies, not a tuning result.
* The remote CI run and the Mac reproduction of U20 are recorded as blocked in
  [`docs/release_v2.md`](docs/release_v2.md) and `docs/upgrade_progress.md` until they are executed;
  `make check-release-v2` reports the release as not releasable while they are.

## Licence and attribution

MIT (`LICENSE`); third-party notices and the heuristic attribution in `NOTICE.md`. The build manual and
upgrade guide were written with planning notes and the implementation jobs executed with Contributor; the author's
notes are in [`docs/author_notes.md`](docs/author_notes.md).
