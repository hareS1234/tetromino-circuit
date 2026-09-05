# Problems found in the build manual (revision 3) during end-to-end implementation

Everything in the manual was implemented and executed (E00–E19). This lists where the manual was
wrong, incomplete, or misleading, what actually happened, and what was changed in this repository.
Items are ordered by how much they would have cost someone following the manual literally.

## Defects (the manual's instruction fails as written)

**1. Appendix A runner: `PYTHONPATH` is ignored by cocotb 2.0.1.** The manual's `tools/run_rtl.py`
sets `os.environ["PYTHONPATH"]` so the simulator can import `tb/` and `model/`. cocotb 2.0.1's
runner overwrites `PYTHONPATH` with the *parent process's `sys.path`*, so that assignment has no
effect; the only reason the manual's counter example would have worked is that it sets
`test_dir=root/"tb"` and the embedded interpreter happens to see the working directory. With any other
`test_dir` the first test dies with `ModuleNotFoundError: tb_counter`. Fix: insert the directories
into `sys.path` before `runner.test()` (`tools/run_rtl.py`). The manual's choice of `test_dir=tb/`
also drops `results.xml` into the source tree; the build directory is used instead.

**2. "Multiplication by compile-time constants is a reasonable first implementation."** With
Yosys `synth_ecp5` it is not: the exact scorer written with `*` mapped to 4 `MULT18X18D` blocks, and
`10*y + x` index arithmetic in the drop, merge, feature and compactor units mapped to 8 more. That
would have made the precision study meaningless — P0 would have hidden its arithmetic in DSP slices
while the shift-based profiles paid in LUTs. Fix: shift-add for the exact coefficients
(76 = 64+8+4, 51 = 32+16+2+1, 36 = 32+4, 18 = 16+2), `(y<<3)+(y<<1)` for indices, and a compactor
that shifts rows instead of indexing them. The multiply form is kept behind `USE_MULT` and measured:
scorer alone, 4 DSP + 25 LUT4 with `*` versus 0 DSP + 97 LUT4 + 26 CCU2C with shift-add. The manual
should tell the reader to forbid `*` in the datapath and to check the DSP column of the first
synthesis report.

**3. Latch guidance is incomplete.** Section 1.4 says to initialise every ROM output before the
case statement. The same rule applies to loop-local temporaries in `always_comb`: the descent
collision check assigned its bit index only inside one branch and Yosys refused with
`Latch inferred for signal idx`. Fix: compute every index unconditionally, gate only its use
(`rtl/drop_unit.sv`). The manual's "no unexplained latches" gate would catch it, but the guidance
should name the pattern.

**4. The native driver protocol cannot report the manual's own "request interval" quantity.**
Section 6.6 requires "Request interval: spacing between accepted requests", but the 5.6a protocol
(`error no_move rotation x y signed_score cycles`) has no field for it. Fix: an eighth field,
`interval`, measured in the C++ harness as the minimum acceptance-to-acceptance spacing with immediate
consumption (`sim/main.cpp`, `model/native.py`).

**5. `-Wno-fatal` would silently disable the parameter guard.** The manual asks for unsupported
parameter combinations to be "rejected explicitly" and its E-jobs table says build tools "must
reject combinations". A `$error` in a generate block is Verilator warning class `USERERROR`; any
runner that passes `-Wno-fatal` (a common way to survive width warnings) turns it into a warning and
builds the unsupported design anyway. Fix: suppress only specific benign warnings; keep `$error`
fatal; `model/config.py` is the single Python-side validator.

**6. Bootstrap must not use the GitHub API.** Section E00 step 3 says to "resolve the official dated
OSS CAD Suite asset". In the build environment the GitHub REST API was blocked while the release
*asset* URL was reachable; a bootstrap that resolves assets through the API fails for no good reason.
`scripts/bootstrap.sh` constructs the asset URL from the pinned date and platform and never queries
the API.

## Design targets the manual flagged as uncertain — measured outcomes

**7. One-cycle closed-form landing fails timing on ECP5-6 at 50 MHz.** Section 7A.3 called the
single registered stage "a design target, contingent on timing". It routed at 43.5 MHz (bitmap) and
43.0 MHz (cache): the path from the latched `x` through the height-select multiplexer, four signed
subtractions, the maximum and the in-board compare is about 23 ns with half of it routing. Two
registered stages (select/subtract, then max/clamp/check) route at 64–69 MHz for one extra cycle per
candidate. The failed reports are kept in `results/implementation_dev_history.csv`.

**8. The precision variants barely change area.** Section 7B.2's warning ("claim savings only if
measured") was correct: LUT4 counts across P0–P4 span 3,942–4,027, about 2%, because the scorer is a
tiny fraction of a design dominated by board registers, the compactor and the merge mask. The
manual's premise that precision is a resource lever should be reframed: it is a *decision* lever
whose resource effect is negligible at this scale.

**9. Profile P2 (two_terms, 80/48/36/18) is not a useful experimental point.** It chose the same
move as the exact profile on 0 of 981 corpus states and on every decision of all 100 held-out games.
The manual should replace it with a coarser quantisation (or keep it as a demonstration that the
argmax is insensitive to small coefficient perturbations, which is the finding here).

**10. The 2,000-piece cap censors the exact policies.** The validation pilot showed exact play
reaching the 500-piece cap on 20/20 streams; on the held-out study 87% of exact games and 91% of
powers-of-two games reached 2,000 pieces. The manual's "do not silently reduce the promised final
dataset" rule was followed and cap-hit fraction was declared the primary statistic before the test
split was opened, but a future revision should either raise the cap substantially (the Python model
plays about 6,000 decisions per second) or choose a harder variant, otherwise the strength axis
mostly measures survival to an arbitrary horizon.

**11. Depth two helps, a little.** Section 7C.4 said lookahead "is not guaranteed to improve
finite-stream results". On the paired 20-stream, 500-piece study depth two adds a small, statistically
positive number of lines, mostly by avoiding early top-outs; the effect size is bounded by the cap.

**12. The 700,000-cycle depth-two guard is 13× too loose for A1.** It was derived from the A0
per-candidate guard. The FSM bound for A1/cache is about 52,700 cycles (34 roots × (44 + 1 + 34 × 44)),
and the corpus worst case is 52,469. The manual asked for the exact bound to be derived, which was done;
the initial number is only misleading if someone reads it as a latency estimate.

## Gaps and smaller corrections

**13. No per-stage cycle attribution was specified for A0.** Section 7A.7 asks to "save per-stage
cycle counts to show where the speedup came from"; the manual did not say how. A cocotb trace of the
evaluator FSM (`stage_cycle_profile` in `tb/tb_candidate.py`) records cycles per state and produced the
277-cycle breakdown (213 in the feature scan) that explains the A0→A1 speed-up.

**14. CI re-downloads 740 MB every run.** Appendix B's workflow calls `bootstrap.sh` unconditionally.
An `actions/cache` step keyed on the pinned archive name was added.

**15. The manual's Verilator command line in Section 3.5 implies a free-running clock is optional;**
with a manually stepped clock the cocotb throughput here was about 24,000 cycles/s versus 1–4.5
million cycles/s for the native driver. The manual's decision to put the native driver in Phase 5 is
right; it should say plainly that cocotb full-game replays of the serial core are impractical beyond
a few dozen pieces.

**16. `cell` is a reserved word in SystemVerilog** (configuration blocks); Section 4.4's suggested
"one cell each cycle" naming leads naturally to a signal called `cell`, which Verilator rejects with an
unhelpful "unexpected cell" error.

**17. The E-jobs table's `make test-candidate` target names a wrapper (`candidate_eval_tb`) that
the design does not need:** `candidate_eval` already exposes the merged board, cleared board,
features and physical landing as ports, so tests drive it directly; the public core does not expose
them.

**18. development workflow-specific text** (cloud environment settings, PROJECT_NOTES.md, resume instructions) is harmless but
irrelevant to any other worker or to a human; the `PROJECT_NOTES.md` template was kept verbatim (a `PROJECT_NOTES.md`
copy points to it) and the evidence/progress contracts were implemented as specified.

## Not problems (checked and confirmed)

The seven numerical fixtures, the J high-overhang regression, the orientation table, the score bounds,
the empty-board winners and the O no-move board are all correct; cocotb 2.0.1 does require Verilator
5.036+ (the suite ships 5.051); Yosys `hierarchy -chparam` and nextpnr `--lpf-allow-unconstrained`
work as described; the streaming-wrapper word layout and the 25,000-cycle serial timeout are adequate
(worst corpus decision 9,596 cycles).
