# Bug and decision journal

Format: intended behaviour, observed behaviour, evidence, fix. Entries are in the order they
happened during the build.

## 1. Spawn-under-overhang (specification)

*Intended:* a piece entering from above stops at the first obstruction. *Observed:* the original
`drop-v1` rule initialised the piece inside the board at `y = 20 − height`, so a J in rotation 3
could appear beneath a block in its short column (rows 15 and 18 = 4, x = 2 → accepted at y = 16).
*Evidence:* 806 disagreements in 570,000 random candidate cases between the old rule and literal
descent from y = 20 (audit); the corrected corpus in `tests/unit/test_reference.py` still contains
cases that distinguish the rules. *Fix:* `drop-v1.1` entry from above; regression fixture
`spawn_under_overhang_J`; three-way differential (set-of-cells oracle, bitmap descent, closed form).

## 2. cocotb runner ignores `PYTHONPATH` (tooling)

*Intended:* `tools/run_rtl.py` makes `tb/` and `model/` importable inside the simulator.
*Observed:* `ModuleNotFoundError: tb_counter`: cocotb 2.0.1's runner exports `PYTHONPATH` from the
parent's `sys.path`, not from the environment variable the manual's Appendix A sets.
*Fix:* insert the directories into `sys.path` before `runner.test()`.

## 3. Latch inferred in the descent collision check (synthesis)

*Intended:* a purely combinational four-cell collision test. *Observed:* Yosys `ERROR: Latch
inferred for signal idx` because the index was assigned only inside one branch of an `always_comb`.
*Fix:* compute every index unconditionally and gate only its use.

## 4. Constant multipliers mapped to DSP slices (synthesis)

*Intended:* LUT-only designs so profiles are comparable. *Observed:* the exact scorer written with
`*` used 12 `MULT18X18D` blocks, and `y*10 + x` index arithmetic in the drop, merge, feature and
compactor units used more (standalone scorer: 4 DSP + 25 LUT4 with `*`, 0 DSP + 97 LUT4 + 26 CCU2C
with shift-add). *Fix:* explicit shift-add for the exact coefficients (76 = 64+8+4, 51 = 32+16+2+1,
36 = 32+4, 18 = 16+2), `(y<<3)+(y<<1)` for indices, and a compactor that shifts rows instead of
indexing them (`line_clear.sv`), which removed the last DSP and 300 LUT4s. The multiply form is kept
behind `USE_MULT` for the measurement.

## 5. Single-stage closed-form drop fails timing (implementation)

*Intended:* one registered cycle for the landing formula. *Observed:* `a1-bitmap` routed at 43.5 MHz
and `a1-cache` at 43.0 MHz against the 50 MHz constraint; the critical path ran from the latched `x`
through the height-select mux, four signed subtractions, the maximum and the in-board compare
(`results/implementation_dev_history.csv`, rows 2–3). *Fix:* two registered stages
(select/subtract, then max/clamp/check); +1 cycle per candidate; routed 64–69 MHz on every profile.

## 6. Verilator `-Wno-fatal` would have hidden the parameter guard (tooling)

*Intended:* an unsupported `ARCH/BOARD_REPR/LANES/DEPTH/PRECISION` combination fails elaboration
via `$error` in a generate block. *Observed:* the runner's blanket `-Wno-fatal` demotes that
`USERERROR` to a warning. *Fix:* suppress only the specific benign width/pin warnings so the guard
stays fatal; `model/config.py` is the single validator on the Python side.

## 7. `cell` is a reserved word (RTL)

A signal named `cell` in `features.sv` produced "syntax error, unexpected cell" in Verilator.
Renamed to `cell_bit`.

## Decisions worth knowing

* The exact scorer is shift-add in production; DSP inference is reported as a measured alternative.
* The compactor shifts rows (no variable indexing): the same 22-cycle latency, smaller and DSP-free.
* `BOARD_REPR=0` re-profiles the latched board in a dedicated PROFILE cycle per candidate so the
  bitmap-versus-cache comparison is one cycle per candidate against one cycle per request, and the
  profile logic is inside each lane rather than shared.
* The study kept the manual's declared 2,000-piece cap even though the validation pilot predicted
  saturation for the exact policies; cap-hit fraction and lines-at-cap are reported as the primary
  statistics rather than silently changing the protocol after seeing results.

## 8. A killed route reported a placement-stage Fmax as a routed result (tooling)

*Intended:* only a completed nextpnr run can report `timing_met`. *Observed:* seed 3 of the two-lane
configuration did not converge (about 305 overused wires after 88,000 router iterations and 22 minutes,
against 74–90 s for the other four seeds). When it stopped, `tools/pnr.py` parsed the last
"Max frequency" line in its log, which was a *placement-stage* estimate. It then recorded
`timing_met=True`.
*Fix:* an incomplete run now records no frequency and `timing_met=False`; a 30-minute route budget
records `route_timeout`; the affected row was corrected to `killed_no_convergence` in
`results/implementation.csv` and `results/implementation_manifest.json` (44 of 45 attempts met timing).
