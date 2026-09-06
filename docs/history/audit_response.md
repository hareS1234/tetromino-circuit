# Response to the A2 upgrade guide's audit (U00)

Baseline inspected: branch `upgrade/a2` created from `master` at `c66ad9b` (tag `v1.0`); no
remote configured; the delivered archive `tetromino-circuit.tar.gz` has SHA-256
`48a4f256…ca50` as the guide records. The live checkout tracks 409 files; the archive omits the
twelve `results/inspection/*.png` frames (committed at `dcc2131`): an export discrepancy, the
files are present and unchanged here. Recount from the saved files: 45 unique (configuration, seed)
routing attempts, 44 `routed` with timing met, one `killed_no_convergence` (A1/cache/two lanes,
seed 3, 1,313.6 s); 640 unique held-out quality jobs from one source hash `66a5deeeb0c72b61`
plus 40 pilot rows; P2 disagreement 0 of 981 legal corpus states; nine decision files
(1,000 rows for depth-one configurations, 250 for depth two); E00–E19 evidence all `passed`.
Full numbers: `results/evidence/U00/inventory.json`.

## Disposition of each audit item

| Item (guide §2) | Disposition | Where |
|---|---|---|
| cocotb import path | already fixed in v1 (`tools/run_rtl.py` extends `sys.path`); regression with an out-of-tree working directory added in U01's test suite | `tests/unit/test_bootstrap.py` |
| DSP inference | already fixed for v1 (shift-add); v2 makes the DSP policy an explicit identity field (`dsp_policy`) and the controlled study uses `-nodsp` | U02 `tools/identity.py`, U17 |
| One-stage landing timing failure | preserved (`results/history/implementation_dev_history*.csv`, `docs/history/bugs.md` #5); consolidated by identity in U19 | n/a |
| A1 serial per candidate | newly actionable: A2 candidate pipeline | U04–U12 |
| P2 changed no decisions | wording corrected below; P2 preserved; P5–P7 added | U14 |
| Capped quality study | newly actionable: protocol `quality-v2-bag50k` | U15–U16 |
| Four lanes unsupported | newly actionable | U13 |
| Remote CI never ran | unverified; recorded as blocked in this environment (no remote, no credentials) | U03/U20 |
| Mac bootstrap compares against the Linux checksum | confirmed in `scripts/bootstrap.sh` (single `archive_sha256`, lock overwritten by observations); fixed | U01 |
| Route resume keyed on RTL hash only | confirmed in `tools/measure_matrix.py`; replaced by full synth/route identities | U02 |
| Mixed-source quality summaries | confirmed in `tools/bench.py::summarise`; replaced by single-identity summaries | U02 |
| Native build reuse by mtime | confirmed in `tools/build_native.py`; replaced by content identity | U02 |
| Empty gate passes | confirmed in `tools/gate.py` (`all([])`); rejected in both recorders | U02 |
| Release check counts rows | confirmed in `tools/check_release.py`; replaced by expected-job membership | U02 |
| Global warning suppression | confirmed (`-Wno-WIDTHTRUNC` etc. in both builders); new A2 files are built with those suppressions removed and legacy waivers scoped per file | U07–U09 |
| Heavy CI job without cache | confirmed; shared bootstrap/cache step | U03 |

## Wording corrections accepted

* **P2.** The v1 problems report said P2 "chose the same move as the exact profile on 0 of 981
  corpus states"; the data say it *differed* on 0 of 981. `docs/history/PROBLEMS_FOUND.md` is corrected
  in U19's history move; the statement is empirical agreement on a finite corpus and on the 100
  v1 held-out games, not universal equivalence.
* **Multiplication.** The v1 rule "no `*` in the datapath" is restated as a mapping policy: shift-add
  in LUT-oriented datapaths, `-nodsp` for the controlled study, DSP-backed scorer kept as a labelled
  microbenchmark; compile-time `*` on genvars is elaboration arithmetic and is fine.
* **`pip freeze`.** The v1 note's explanation for Python 3.12 was inaccurate; U01 pins the build
  backend deliberately and tests the declared Python version rather than relying on freeze defaults.
* **`cell` keyword.** Preventive naming guidance, not a defect of the original specification.
* **Native `interval`.** It measures the earliest eligible acceptance edge, not a second real
  acceptance; U10 adds a batch harness with two actual acceptance edges.
* **"Passes 50 MHz".** Feasibility at the constraint only; U17 adds the constraint sweep and path
  categories, and the report avoids calling any figure a physical maximum.
* **Depth-two bound.** The report's displayed expression `34·(44+1+34·44)` = 52,394 omits
  controller/cache/finalization edges and sits below the observed 52,469; the repository's actual
  timeout (120,000 in `tb/tb_lookahead.py`) is the guard, and the FSM-derived bound is restated in
  U19 with the overhead included.

## Unverified in this environment

Real-Mac execution and remote CI cannot be run here (Linux container, no macOS host, no GitHub
remote or token). Both stay `blocked` in the evidence until executed by the maintainer.
