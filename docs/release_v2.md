# v2 release: scope, platform support and blocked gates (U20)

The v2 release is described by `benchmarks/release_v2.json` (schema `release-manifest-v2`) and validated by
`make check-release-v2` (`tools/check_release_v2.py`). The validator creates nothing: it checks that the
frozen inputs still hash as declared, that every listed artifact exists, that every evidence record
U00–U20 carries real commands with exit code 0 and nonzero counts, that the expensive measurements
correspond to the checked-out sources through their identities (route and native keys re-planned from
the RTL, the quality protocol hash and model closure, the trace harness keys), and it re-runs the
exact-membership validators (`check-release` for v1, `check-hardware-v2`, `check-quality-v2`,
`check-trace`, `check-viewer`, `check-report-v2`, `check-links`, `check-claims`, `ci_local --validate`).
Its last line is one of `OK — releasable`, `NOT RELEASABLE (blocked: …)` or `FAIL`; a blocked item is
never counted as satisfied, and the tag `v2.0-a2` must not exist while anything is blocked.

## Platform support table

| Family (`toolchains/oss_cad_suite.lock.json`) | Host | Status | What ran | Evidence |
|---|---|---|---|---|
| `linux-x64` | Linux x86_64 sandbox that executed U00–U20 | **executed** | `bash scripts/fresh_clone_check.sh` on a clean clone of the release commit: bootstrap from the committed lock, doctor, Python tests, smoke, directed RTL, the native A2 core subset, trace/demo regeneration, viewer and report checks | `results/evidence/U20/fresh_clone_linux-x64.json`, `results/host/Linux-x86_64.json` |
| `darwin-arm64` | the maintainer's Apple-silicon Mac (demonstration machine) | **blocked** | nothing yet: the lock entry is unenrolled; bootstrap (`--enroll`), doctor, tests, smoke, the A2 native subset, the demo regeneration and the viewer/GIF inspection must be run *on that Mac* and recorded | to be written by `bash scripts/fresh_clone_check.sh` there (`results/evidence/U20/fresh_clone_darwin-arm64.json`) |
| `darwin-x64`, `linux-arm64` | — | unenrolled | not part of the release scope; the bootstrap refuses them until enrolled | — |
| `remote-ci` (`.github/workflows/ci.yml`) | GitHub Actions at the release commit | **blocked** | the workflow validates locally (`tools/ci_local.py --validate`) and its `fast` tier ran locally; no remote run exists because no remote repository was available to the session | a successful run URL and SHA, to be recorded in `results/evidence/U20/remote_ci.json` |

## Release readiness (guide §14) — actual status

| Requirement | Status | Where |
|---|---|---|
| A2 overlaps candidates, accepts consecutive tokens in consecutive cycles, fixed documented latency under no stalls | satisfied: 4,096 back-to-back tokens with spacing 1, visible latency 22, `D(N) = N + 29` measured on 3,000 states | `docs/verification_a2.md` V06/V11, `results/v2/raw/intervals/` |
| Exact architectures agree on the declared corpora and RTL replays; reset, stalls, last result, signed ties have explicit evidence | satisfied | `docs/verification_a2.md` V07–V10, V14; `results/traces/` |
| At least one complete A2 implementation meets the claimed target; every planned route attempt accounted for with its real status | satisfied by the release matrix (`make check-hardware-v2`) | `docs/results.md` §1, `results/v2/summary/matrix_hardware-v2.json` |
| New profiles versioned, change some development decisions, own-reference tests, honest quality results | satisfied: P5/P6/P7 change 1/25/87 of 981 development decisions; held-out P6/P7 collapse is reported | `docs/precision_v2.md`, `docs/quality_v2.md` |
| Long-horizon study handles censoring and preserves the old experiment | satisfied: restricted means at the cap, product-limit survival, medians only where reached; `make check-v1-results` unchanged | `docs/quality_v2.md`, `results/quality.csv` (frozen) |
| README, viewer, report, manifests and raw result links agree | satisfied by `make check-report-v2` (links, claims, generated tables) | `docs/claims.json` |
| The maintainer's actual demo machine and remote CI have passed their stated checks | **blocked** (see the platform table) | `results/evidence/U20/` |
| The author can explain the twelve questions of guide §12.5 | to be done by the author (`docs/author_notes.md`) | — |

## Where the validator can run

The v2 identities that relate the expensive measurements to the sources (synthesis, route and native
keys; `docs/identities.md`) include the pinned tools' *version strings*. The darwin build of the same OSS
CAD Suite release prints different strings, so on the Mac `make check-hardware-v2` re-plans different
keys and reports the Linux route records as missing — that is the identity system doing its job, not a
defect in the records. `make check-release-v2` is therefore run on linux-x64 with the pinned suite: the
`release-check` workflow (`.github/workflows/release-check.yml`, manual dispatch, full-history checkout
for the v1 tag check) does exactly that on a hosted runner and uploads `build/release_v2_check.json`.
The Mac's job is the reproduction record (`scripts/fresh_clone_check.sh`), the demo inspection and the
lock enrolment.

## Executing the blocked items

1. **On the Mac** (Apple silicon), in `tetromino-circuit/` with Python 3.11 or 3.12 on `PATH` (or
   `PYTHON=/path/to/python3.12`), Xcode command-line tools, `make`, `git`, `curl`:

   ```bash
   PYTHON=python3.12 bash scripts/bootstrap.sh --enroll      # downloads the darwin-arm64 asset, records its sha256 in the lock
   python3 - <<'EOF2'
   import json, pathlib
   p = pathlib.Path("toolchains/oss_cad_suite.lock.json"); d = json.loads(p.read_text())
   d["assets"]["darwin-arm64"]["status"] = "verified"        # after comparing the recorded hash with the release page
   p.write_text(json.dumps(d, indent=1) + "\n")
   EOF2
   git add toolchains/oss_cad_suite.lock.json results/host/Darwin-arm64.json && git commit -m "Enrol the darwin-arm64 toolchain asset"
   REUSE_ARCHIVE=1 PYTHON=python3.12 bash scripts/fresh_clone_check.sh    # writes results/evidence/U20/fresh_clone_darwin-arm64.json
   open viewer/demo.html                                    # inspect the replay; assets/a2_pipeline.gif is the GIF
   ```

   Commit the record. The fresh clone must see the *committed* lock, hence the commit before the check.
2. **Remote CI**: push the branch to the GitHub repository; the `checks` workflow (`fast` + `hdl`) runs on
   push. Record the successful run in `results/evidence/U20/remote_ci.json`:

   ```json
   {"schema": "remote-ci-run-v1", "url": "https://github.com/<owner>/<repo>/actions/runs/<id>", "sha": "<commit>", "ok": true, "jobs": ["fast", "hdl"]}
   ```
3. **Mark both executed** in `benchmarks/release_v2.json` (platform rows `darwin-arm64` and `remote-ci`,
   gate rows `mac-reproduction` and `remote-ci-run`: `"status": "executed"` plus the `evidence` path), update
   the two rows of the platform table above, commit, push, and dispatch the `release-check` workflow at that
   commit. Only when it prints `check-release-v2: OK — releasable` is `git tag v2.0-a2` permitted.
