# v2 release notes and gate status (U20)

The release manifest is `benchmarks/release_v2.json`; `make check-release-v2` is its rather fussy
bouncer. The check does not generate evidence. It verifies frozen input hashes, required artifacts,
U00–U20 command records, measurement identities, exact result membership, report links, headline
claims, and the local shape of both CI workflows.

The last line is deliberately unambiguous: `OK — releasable`, `NOT RELEASABLE (blocked: …)`, or
`FAIL`. A blocked row is not a soft pass, and the `v2.0-a2` tag must not exist until the first verdict
is real.

## Platform ledger

| Family (`toolchains/oss_cad_suite.lock.json`) | Host | Status | What actually ran | Evidence |
|---|---|---|---|---|
| `linux-x64` | Linux x86_64 sandbox used for U00–U20 | **executed** | all 19 steps of `bash scripts/fresh_clone_check.sh` on a clean clone, including bootstrap, doctor, Python and RTL tests, the native A2 subset, trace/demo regeneration, and report checks | `results/evidence/U20/fresh_clone_linux-x64.json`, `results/host/Linux-x86_64.json` |
| `darwin-arm64` | the maintainer's Apple-silicon Mac (demonstration machine) | **executed** | `bash scripts/bootstrap.sh --enroll`, then `bash scripts/fresh_clone_check.sh` from a clean clone: bootstrap, doctor, tests, smoke, directed RTL, the native A2 subset, trace/demo regeneration, viewer and report checks; viewer and GIF inspected | `results/evidence/U20/fresh_clone_darwin-arm64.json`, `results/host/Darwin-arm64.json` |
| `darwin-x64`, `linux-arm64` | — | unenrolled | outside this release's support set; bootstrap refuses them with an enrollment hint | — |
| `remote-ci` (`.github/workflows/ci.yml`) | GitHub Actions at the release commit | **executed** | `fast` and `hdl` tiers passed at `4a68e3b79f87` (https://github.com/hareS1234/tetromino-circuit/actions/runs/34012898896) | `results/evidence/U20/remote_ci.json` |

## Readiness against guide §14

| Requirement | Status | Where |
|---|---|---|
| A2 accepts candidates on consecutive cycles and has fixed unstalled latency | satisfied: 4,096 back-to-back tokens at spacing 1, visible latency 22; `D(N) = N + 29` on 3,000 states | `docs/verification_a2.md` V06/V11, `results/v2/raw/intervals/` |
| Exact architectures agree on the declared corpora and RTL replays; reset, stalls, final-result handling, and signed ties are covered | satisfied | `docs/verification_a2.md` V07–V10 and V14, `results/traces/` |
| At least one complete A2 route meets target, with every planned attempt accounted for | satisfied | `docs/results.md` §1, `results/v2/summary/matrix_hardware-v2.json` |
| New precision profiles are versioned, tested independently, and reported honestly | satisfied: P5/P6/P7 change 1/25/87 of 981 development decisions; their held-out results, including the P6/P7 collapse, are published | `docs/precision_v2.md`, `docs/quality_v2.md` |
| The long-run study handles censoring and leaves the old study untouched | satisfied: restricted means, product-limit survival, and medians only where observed; `make check-v1-results` still passes | `docs/quality_v2.md`, frozen `results/quality.csv` |
| README, viewer, reports, manifests, and result links agree | satisfied by `make check-report-v2` | `docs/claims.json` |
| The maintainer's actual demo machine and remote CI have passed their stated checks | satisfied (see the platform table) | `results/evidence/U20/` |
| The author can explain the main design and measurement choices | an author exercise, not an automated gate | `docs/author_notes.md` |

## Why the full validator runs on Linux

Synthesis, route, and native identities include the tools' version strings. The Darwin build of the
same OSS CAD Suite release reports different strings, so a Mac quite correctly plans different keys
and cannot validate the recorded Linux routes. The manually dispatched `release-check` workflow runs
the full validator on linux-x64, where those identities match. The Mac has a different job: reproduce
the supported local path, inspect the demo, and leave a clean-clone record.

## How the two external checks were recorded

The small `scripts/release_unblock.py` helper only updates the release bookkeeping. It does not run
measurements, inspect a browser, or query GitHub.

1. On Apple silicon, from `tetromino-circuit/`, use Python 3.11 or 3.12 plus Xcode command-line tools,
   `make`, `git`, and `curl`:

   ```bash
   bash scripts/bootstrap.sh --enroll
   python3 scripts/release_unblock.py verify-lock
   git add toolchains/oss_cad_suite.lock.json docs/toolchain.md results/host/Darwin-arm64.json
   git commit -m "Enrol the darwin-arm64 toolchain asset"
   REUSE_ARCHIVE=1 bash scripts/fresh_clone_check.sh
   open viewer/demo.html assets/a2_pipeline.gif
   git add results/evidence/U20/fresh_clone_darwin-arm64.json
   git commit -m "Record the Mac fresh-clone reproduction"
   ```

   The commit before `fresh_clone_check.sh` matters: a clean clone cannot see an uncommitted lock.
   Enrollment and doctor have already passed on this Mac; the lock, host observation, and current
   writing changes still need to be reviewed and committed before this step.

2. Push the intended release commit and wait for both `checks` jobs (`fast` and `hdl`) to turn green.
   Open the run, confirm its checked-out SHA and job conclusions, then record what you inspected:

   ```bash
   python3 scripts/release_unblock.py ci-record https://github.com/<owner>/<repo>/actions/runs/<id> <commit-sha>
   git add results/evidence/U20/remote_ci.json
   git commit -m "Record the remote CI run"
   ```

   `ci-record` performs only basic string checks. A plausible-looking URL is not proof; the human
   inspection above is part of the gate.

3. Once both records are real, update the two rows and validate on Linux:

   ```bash
   python3 scripts/release_unblock.py mark-executed
   git add -A
   git commit -m "U20: Mac reproduction and remote CI recorded"
   git push
   ```

   Dispatch Actions → `release-check` → Run workflow on `upgrade/a2`. Tag only if its
   `make check-release-v2` step ends with `check-release-v2: OK — releasable`:

   ```bash
   git tag -a v2.0-a2 -m "A2 architecture study"
   git push origin v2.0-a2
   ```
