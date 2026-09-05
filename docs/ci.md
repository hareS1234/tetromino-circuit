# Continuous integration (U03)

`.github/workflows/ci.yml` has three tiers; `.github/actions/bootstrap/action.yml` is the shared
bootstrap used by every job that needs tools.

| Job | Trigger | What it runs | Budget |
|---|---|---|---|
| `fast` | every push / pull request | Python-only: `make doctor-python`, generated-geometry and stream determinism, `make test-python` (JUnit XML), `make check-v1-results`, v2 stream determinism, both report checks, `make check-trace`, `make check-viewer`, `make check-links`, `make check-claims`, workflow validation (`tools/ci_local.py --validate`) | 20 min |
| `hdl` | every push / pull request | the Linux HDL gate: pinned OSS CAD Suite, `make doctor`, `make test-bootstrap`, `make smoke`, `make test-rtl`, `make test-core ARCH=1 BOARD_REPR=1 COUNT=200 DRIVER=native`, the A2 checks added in U20 (`make check-a2-spec`, `make test-a2-stream`, `make test-compactor-native MODE=random COUNT=20000`, `make test-core ARCH=2 BOARD_REPR=1 COUNT=200 DRIVER=native`, `make test-protocol ARCH=2 BOARD_REPR=1`, `make trace-a2-demo`, `make check-trace`), `make test-identities`, `make test-result-schemas`, `make upgrade-smoke` (one real route, 50-state native corpus, 12-game v2 quality smoke), `make matrix-status` | 90 min |
| `heavy` | manual (`workflow_dispatch`) with `manifest`, `quality_protocol`, `quality_suite` inputs (defaults are the smoke presets) | `make matrix-plan` + `make measure-matrix MANIFEST=…` + the named v2 quality suite | 360 min |

Artifacts are uploaded `if: always()`: JUnit XML (`build/junit/**`), cocotb `results.xml`, build
and tool logs, route records and logs, `results/v2/raw/**` and `results/v2/summary/**`, and the
host observation. Result files are never restored from a cache: only the toolchain archive is
cached, so an artifact is always produced by the run that uploaded it.

## Bootstrap action

`.github/actions/bootstrap` resolves the runner's `uname -s`/`uname -m` to the lock entry in
`toolchains/oss_cad_suite.lock.json`, restores the archive from a cache keyed by
`oss-cad-suite-<runner.os>-<runner.arch>-<release>-<sha256>`, and runs `scripts/bootstrap.sh`, which
verifies the restored (or freshly downloaded) archive against the platform entry before extracting
it. A cold cache downloads the release asset directly from the GitHub release URL (no API). With
`hdl: "false"` the action installs only the locked Python environment (`TETROMINO_SKIP_SUITE=1`).
Python 3.12 is the CI interpreter; 3.11 remains supported. Both were exercised locally on
2026-09-05 (`.venv` 3.11.15 and `.venv312` 3.12.3: `make test-python` 381 passed under each,
`make smoke`, `make test-identities` and a native corpus under 3.12).

Action references (major tags): `actions/checkout@v5`, `actions/setup-python@v5`,
`actions/cache@v4`, `actions/upload-artifact@v4`. They are to be pinned to commit SHAs in U20
after the first inspected remote run.

## Local validation

`bash scripts/env.sh python tools/ci_local.py --validate` checks the workflow structure, action
references, the existence of every `make` target and script the steps call, and every `${{ }}`
expression. `tools/ci_local.py --job fast|hdl|heavy [--event workflow_dispatch]` runs the job's
shell steps here in order (composite steps expanded, GitHub-runtime actions skipped, dispatch
inputs at their defaults, `$GITHUB_OUTPUT` emulated) and prints `CHECK ci_job_<name> ran/ran`.

## Remote status

No remote repository, GitHub credentials or `gh` are available in the environment that produced
this branch, so the workflow has not run on GitHub. U03's remote gate is recorded as **blocked**
in `results/evidence/U03/summary.json` (the local job executions are recorded there as supporting
evidence). U20 added the A2 checks to the `fast` and `hdl` tiers and validated the workflow locally
again, but the remote run itself remains **blocked** (`benchmarks/release_v2.json`, platform
`remote-ci`; `docs/release_v2.md`): whoever publishes the repository must push the release commit,
inspect the run, fix concrete failures, pin the action SHAs, and record the run URL, commit SHA and
conclusion in `results/evidence/U20/remote_ci.json` before `make check-release-v2` can report the
release as releasable. The first cold-cache run's observed duration is the budget reference; the
`timeout-minutes` values above are initial allowances, not measurements.
