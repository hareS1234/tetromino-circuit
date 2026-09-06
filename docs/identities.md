# Result identities, resume and evidence (U02)

A stale netlist that happens to have the right filename is a particularly boring way to ruin an
experiment. v2 avoids that by hashing the complete recipe for every build and measurement as
canonical JSON (`tools/identity.py`: sorted keys, no whitespace, ASCII escapes, no NaN). File inputs
carry repository-relative paths, byte counts, and SHA-256 values. Modification times count for
nothing, and an RTL hash by itself is never enough.

| Key | Inputs | Where it is used |
|---|---|---|
| `synth_key` | ordered `rtl/files.f` list and its hash, every file in the transitive `` `include `` closure (including `rtl/generated/*.svh`), top module, elaboration parameters, Yosys identity string, DSP policy (`default` or `nodsp`), synthesis script version and command list | `build/synth/<synth_key>/` (`identity.json`, `synth.ys`, `yosys.log`, `netlist.json`, `summary.json` with `netlist_sha256`) |
| `route_key` | `synth_key`, netlist SHA-256, nextpnr identity, device/package/speed, target MHz, seed, I/O constraint policy, options, route timeout, route script version | `build/route/<route_key>/` and `results/v2/raw/routes/<route_key>.json` |
| `analysis_key` | `route_key`, log parser version | re-parsing a retained log (`tools/pnr.py reanalyze`) never re-routes |
| `native_key` | ordered `rtl/files_core.f` closure, parameters, `sim/main.cpp`, the builder, Verilator identity, flags | `build/native/<native_key>/` (alias symlink `build/native_<id>`) |
| `quality_key` | protocol file content, policy/profile, stream SHA-256, cap, model closure (`model/*.py`), Python runtime | `results/v2/raw/quality/<quality_key>.json` |

`tests/unit/test_identity.py` is the invalidation matrix: a source file, an include, a generated
header, the `.f` order, the tool identity, the DSP policy, the script version, the parameters, the
frequency, seed, device, timeout, options, netlist, profile, stream, cap and protocol each change
the appropriate key; a documentation-only edit changes nothing; a parser version changes
`analysis_key` only.

## Records

One atomic JSON per job (`.part` file, then rename); parallel workers never append to a shared CSV.

* `route-record-v2` (`results/v2/raw/routes/<route_key>.json`; a deliberate retry is
  `<route_key>.a<n>.json` and never replaces an earlier attempt). Separate fields for the process
  (`return_code`, `completed`, `timed_out`, `cancelled`, elapsed, peak RSS), the timing result
  (`met`, `reported_fmax_mhz`, `report_available`, `source`, worst path endpoints and logic/routing
  delay, the placement-stage estimate kept apart) and the area (LUT4, FF, carry, BRAM, DSP from
  synthesis; `TRELLIS_COMB`/`TRELLIS_FF` from nextpnr). Absent measurements are `null`, never zero.
  Statuses: `routed_timing_met`, `routed_timing_failed`, `route_timeout`, `tool_error`, `cancelled`,
  each with a `status_reason`. Timing is parsed only from the section after `Routing complete.`
  and from the `--report` JSON; return code zero alone is never the timing gate (a run without
  `--timing-allow-fail` exits 1 on a timing failure and is still a completed route). Parser fixtures
  from real logs: `tests/fixtures/pnr_logs/` (pass, timing failure, run killed during routing,
  completed log without a clock, log ending at routing complete).
* `decision-record-v2` (`results/v2/raw/decisions/<configuration>/<corpus_hash>.json` + `.csv`):
  native differential corpus keyed by `native_key` and the corpus content hash.
* `quality-record-v2`: one game; resume skips a key whose record is `complete`.
* `synth-record-v2` in `build/synth/<key>/summary.json`; reuse requires the recorded `synth_key`
  and a netlist that still hashes to `netlist_sha256`.

Derived artifacts under `results/v2/summary/` are rebuilt from raw records on every run. The
`routes_<matrix>.csv` file contains every attempt and marks the identity that matches the current
source and toolchain. `matrix_<matrix>.json` records expected jobs, planned keys, current status,
and counts. Quality summaries live in `quality.csv` and `quality_<suite>.json`.

## Runner (`tools/measure_matrix.py`)

Manifests (`hardware-matrix-v2`) list configurations × targets × seeds plus `extra_jobs`, one DSP
policy, the route timeout and an optional decision-corpus block; `benchmarks/smoke_v2.json` is the
development preset behind `make upgrade-smoke`, the release matrix is a separate explicit command
(`make measure-matrix MANIFEST=…`). `plan` is a dry run of jobs, keys, reuse, and retries. `run`
reuses any record with the current `route_key`, including a completed failure. The command
`--retry REASON --only <job>` records a distinct attempt.
`results/v2/runner.lock` (pid, manifest, start) refuses a second orchestrator while the first is
alive and clears a stale lock; `results/v2/runner.heartbeat.json` and the console get a status
record at each job start/finish and a heartbeat at most 60 s apart (active job, elapsed, peak RSS,
completed/total, successes/failures/timeouts/errors, ETA range from completed comparable jobs).
A route runs in its own process group and is killed with its children when the budget expires.

## Summaries

`tools/bench.py::summarise(rows, suite, source=…, protocol_sha256=…)` selects the suite's cap and
requires one source and protocol identity. A mismatch raises `SummaryConflict`. The function joins
the exact expected stream ids and marks policies with missing streams as `incomplete`. It ignores
streams outside the suite, rejects conflicting duplicates, and computes the paired bootstrap against
the suite baseline. The frozen v1 study is recomputed from
`results/quality.csv` with `--summarise-v1 precision|depth` and must equal
`results/quality_summary.json` (`make check-v1-results`, 8/8 policies).

v2 runs take `--config <protocol>` and `--out-root results/v2`; the frozen v1 protocol cannot be
re-run through the tool and `results/` is refused as an output root.

## Gates and release membership

`tools/gate.py` and `tools/ugate.py` reject a gate with zero commands. `ugate` also requires every
named check to have a nonzero count. Accepted forms include `N passed`, RTL totals, native decision
matches, and `CHECK name ok/total`. Each record stores the git commit, tracked-file state, source
closure, toolchain identity, commands, log digests, artifacts, and limitations. Command logs stay
local because build output can contain machine-specific paths. Their SHA-256 digests remain in the
tracked summaries, and a local log must match its digest when present.

`tools/check_v1_results.py` names every expected v1 job from `benchmarks/config.json`: 640 quality
games, 45 routes, 9 decision files, and E00–E19. It requires exact membership with no missing, extra, or
duplicate jobs), one source and one toolchain identity, a committed summary equal to the
recomputation, and evidence with nonempty commands and zero exit codes. `tools/check_release.py`
uses it instead of the former minimum row counts. The v2 release validator (U20) applies the same
membership rule to the U-jobs and the v2 manifests.

## Source closure exclusions (U20)

`tools/identity.py::SOURCE_EXCLUDE` removes `benchmarks/release_v2.json` from the source closure: the
release manifest describes the scope of the measurements after the fact (which platforms executed,
which are blocked) and is not an input to any of them, so flipping a row from blocked to executed must
not make the recorded closures look stale. Tool identities are version strings, so the same suite
release on another platform (the darwin build) yields different synthesis/route/native keys. Validators
that recalculate tool-bound keys run where the measurements were made (`docs/release_v2.md`).
