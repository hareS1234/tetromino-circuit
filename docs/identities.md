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

Derived artifacts under `results/v2/summary/` are rebuilt from the raw records on every run and
sorted by complete key: `routes_<matrix>.csv` (every attempt of every job of the manifest, with a
`current` column saying whether the record's identity is the one the present source and toolchain
resolve to), `matrix_<matrix>.json` (expected jobs, planned route keys, latest status per job,
counts), `quality.csv` and `quality_<suite>.json`.

## Runner (`tools/measure_matrix.py`)

Manifests (`hardware-matrix-v2`) list configurations × targets × seeds plus `extra_jobs`, one DSP
policy, the route timeout and an optional decision-corpus block; `benchmarks/smoke_v2.json` is the
development preset behind `make upgrade-smoke`, the release matrix is a separate explicit command
(`make measure-matrix MANIFEST=…`). `plan` is a dry run (jobs, keys, reuse/run/retry), `run`
resumes: a job whose latest record exists under its `route_key` is reused whatever its status —
a completed failure is a result — and `--retry REASON --only <job>` records a distinct attempt.
`results/v2/runner.lock` (pid, manifest, start) refuses a second orchestrator while the first is
alive and clears a stale lock; `results/v2/runner.heartbeat.json` and the console get a status
record at each job start/finish and a heartbeat at most 60 s apart (active job, elapsed, peak RSS,
completed/total, successes/failures/timeouts/errors, ETA range from completed comparable jobs).
A route runs in its own process group and is killed with its children when the budget expires.

## Summaries

`tools/bench.py::summarise(rows, suite, source=…, protocol_sha256=…)` selects the suite's cap,
requires every selected row to carry the one named source identity and the one protocol identity
(`SummaryConflict` otherwise — the pre-U02 version combined rows from different `model/` versions
silently), joins the exact expected stream ids (missing streams make a policy `incomplete` and list
them; streams outside the suite are ignored), rejects duplicate rows that disagree, and computes the
paired bootstrap against the suite baseline. The frozen v1 study is recomputed from
`results/quality.csv` with `--summarise-v1 precision|depth` and must equal
`results/quality_summary.json` (`make check-v1-results`, 8/8 policies).

v2 runs take `--config <protocol>` and `--out-root results/v2`; the frozen v1 protocol cannot be
re-run through the tool and `results/` is refused as an output root.

## Gates and release membership

`tools/gate.py` (v1 recorder) and `tools/ugate.py` (upgrade recorder) reject a gate with zero
commands (status `failed`); `ugate` additionally requires every named check to have a nonzero
count (`N passed`, `RTL tests: N total, 0 failed`, `native: all N decisions match`, `CHECK name ok/total`
with `ok == total > 0`) and records the git commit (tracked-file dirtiness only), the source closure
hash, the toolchain identity, commands with exit codes and logs, artifacts and limitations.

`tools/check_v1_results.py` names every expected v1 job from `benchmarks/config.json` — 640 quality
games, 45 routes, 9 decision files, E00–E19 — and requires exact membership (no missing, extra or
duplicate jobs), one source and one toolchain identity, a committed summary equal to the
recomputation, and evidence with nonempty commands and zero exit codes. `tools/check_release.py`
uses it instead of the former minimum row counts. The v2 release validator (U20) applies the same
membership rule to the U-jobs and the v2 manifests.

## Source closure exclusions (U20)

`tools/identity.py::SOURCE_EXCLUDE` removes `benchmarks/release_v2.json` from the source closure: the
release manifest describes the scope of the measurements after the fact (which platforms executed,
which are blocked) and is not an input to any of them, so flipping a row from blocked to executed must
not make the recorded closures look stale. Tool identities are version strings, so the same suite
release on another platform (the darwin build) yields different synthesis/route/native keys; validators
that re-plan keys run where the measurements were made (`docs/release_v2.md`).
