# Tetromino Circuit

How much faster does a tiny Tetris engine get if candidates move through a pipeline instead of
waiting their turn in one evaluator? This repo is a perhaps-overcommitted answer to that question:
a drop-only search engine in SystemVerilog, a deliberately independent Python oracle, and enough
saved build evidence to check the answer without taking my word for it.

![A real RTL trace: 34 candidates moving through the A2 pipeline](assets/a2_pipeline.gif)

The animation is one frame per clock edge from the actual RTL trace in
`results/traces/a2_normal_search.json`. All 34 candidates enter the 23-bank pipe one per cycle,
retire in order, and occasionally steal the lead from one another. The response turns up 63 cycles
after the request. Open [`viewer/demo.html`](viewer/demo.html) for the version you can pause and
poke at.

## The short version

- **The pipeline worked.** On the common 1,000-board corpus, A2 takes a median of 46 cycles per
  decision (`N + 29`) instead of 773 for the one-lane A1 evaluator. That is 17.1× fewer cycles in
  total, with the same move on every board. The routed A2 netlists report 72.40–75.63 MHz across
  three seeds at 50 MHz, using 6,104 LUT4s and 5,489 flip-flops. It costs 1.51× the LUT4s of one A1
  evaluator; four replicated A1 lanes cost rather more and only one of their three seeds routed.
- **Narrow coefficients were a mixed bag.** Over 100 held-out seven-bag streams capped at 50,000
  pieces, the powers-of-two profile P1 has a restricted mean of 22,675 pieces versus 11,846 for P0:
  +10,828 pieces, CI95 [7,082, 14,719]. P5, the 4-bit profile, behaves like P0 while shaving a little
  area. P6 and P7 fall apart. That failure is useful data, so it stays in the report.
- **The checks are intentionally fussy.** The exact architectures cover 8,250 v1 decisions plus
  1,000 per v2 configuration. The row compactor, reducer, and pipeline control have unbounded
  k-induction proofs (the compactor record says `unbounded`), and twelve planted RTL bugs are each
  caught by a named test. See [`docs/verification_a2.md`](docs/verification_a2.md).

These are RTL-simulation and FPGA device-model results, not measured on a board. The full
tables, including timeouts and failed timing runs, live in [`docs/results.md`](docs/results.md).

## A map of the rabbit hole

| If you want... | Start here |
|---|---|
| The exact game being implemented | [`docs/spec.md`](docs/spec.md) — the `drop-v1.1` contract and score `76L − 51A − 36Q − 18U` |
| The three hardware architectures | [`docs/design.md`](docs/design.md) for A0/A1, then [`docs/design_a2.md`](docs/design_a2.md) for the pipeline |
| The research argument | [`docs/research_report.md`](docs/research_report.md); the denser tables are in [`docs/results.md`](docs/results.md) |
| The quality and precision experiments | [`docs/quality_v2.md`](docs/quality_v2.md) and [`docs/precision_v2.md`](docs/precision_v2.md) |
| Why cached results are so picky | [`docs/identities.md`](docs/identities.md) |
| The cycle-by-cycle replay | [`docs/replay.md`](docs/replay.md) and `viewer/` |
| Tool versions and CI | [`docs/toolchain.md`](docs/toolchain.md) and [`docs/ci.md`](docs/ci.md) |
| Old v1 material | [`docs/history/`](docs/history/README.md); it is kept as evidence, not polished retroactively |

Raw v2 records are one JSON file per job under `results/v2/raw/`. Job logs and exit codes are under
`results/evidence/E00–E19` for v1 and `results/evidence/U00–U20` for v2. It is a lot of bookkeeping,
but it prevents a stale netlist from quietly becoming a current result.

## Try it

For the saved demo, no setup is needed: open [`viewer/demo.html`](viewer/demo.html). To load one of
the other traces, run `python3 -m http.server` inside `viewer/` and open `index.html`.

The software checks need Python 3.11 or 3.12 and take about a minute:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-deps -e .
bash scripts/env.sh python -m pytest tests/unit -q
bash scripts/env.sh python tools/check_claims.py
bash scripts/env.sh python tools/check_trace.py
```

For RTL work, install the pinned OSS CAD Suite through the bootstrap script. The archive is about
740 MB and expands to roughly 3 GB under `.tools/`.

```bash
bash scripts/bootstrap.sh
make doctor
make smoke
make test-core ARCH=2 BOARD_REPR=1 COUNT=50 DRIVER=native
```

The full study is resumable. Complete job identities include the relevant sources, parameters,
tool versions, and constraints, so rerunning a command reuses only a genuinely matching record.

```bash
make verify-a2-release
make measure-v2 MODE=run
make bench-v2 MODE=run SUITE=bag50k
make analyze-quality-v2
make plots-v2
make results-v2
make check-report-v2
```

The hardware matrix is 84 routes plus 6,000 decisions and took 4.4 h on two cores. The held-out
quality run is 600 games and took about 11 minutes in summary mode. Use
`make measure-v2 MODE=dry-run` or `make bench-v2 MODE=dry-run` when you only want to see the bill.
A changed quality protocol has to be frozen with `make bench-v2 MODE=freeze` before held-out games
will run.

`make help` has the rest. Hardware configurations use `ARCH`, `BOARD_REPR`, `LANES`, `DEPTH`, and
`PRECISION`; `python -m model.config --list` prints the fourteen combinations that are actually
supported. Unsupported combinations fail both in Python and during RTL elaboration.

## Sharp edges and honest limitations

- This is not full Tetris. Kicks, tucks, spins, hold, lock delay, gravity, hidden rows, combos,
  garbage, and multiplayer are deliberately excluded. Pieces pick a rotation and column, then fall
  straight down.
- Quality numbers come from the bit-exact Python policy model. The RTL is checked against that model,
  but the long games themselves are not hardware runs.
- Cycle counts come from RTL simulation. Timing comes from nextpnr on an ECP5 LFE5U-85F model with
  auto-allocated I/O. No board, no power measurement, no mystery lab equipment hiding off-camera.
- A route timeout means “not routed inside this budget,” not “physically impossible.” All such
  outcomes are kept.
- The heuristic coefficients come from Lee (2013) and were not tuned here. P1 beating P0 is an
  observation about two fixed policies, not a claim that a search found better weights.
- U20 still needs a clean Mac reproduction and a real GitHub Actions run. The exact state is tracked
  in [`docs/release_v2.md`](docs/release_v2.md); the release validator refuses to call it done early.

## References, licence, and credits

MIT; see [`LICENSE`](LICENSE). [`NOTICE.md`](NOTICE.md) credits the heuristic and toolchain.
[`docs/author_notes.md`](docs/author_notes.md) is a compact notebook of design choices, open
questions, and measurement boundaries.

The fixed four-feature heuristic comes from Yiyuan Lee, *Tetris AI – The (Near) Perfect Bot* (2013).
The hardware flow uses the YosysHQ OSS CAD Suite (Yosys, nextpnr-ecp5, Verilator, SymbiYosys, and
boolector), pinned to release 2026-09-04. The target device model is a Lattice ECP5 LFE5U-85F in a
CABGA381 package, speed grade 6.
