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

## Executing the blocked items

On the Mac, from a clean clone of the release commit:

```bash
bash scripts/bootstrap.sh --enroll          # records the darwin-arm64 asset hash in the lock for review
bash scripts/fresh_clone_check.sh           # writes results/evidence/U20/fresh_clone_darwin-arm64.json
open viewer/demo.html                       # inspect the replay; open assets/a2_pipeline.gif
```

Commit the enrolled lock entry, `results/host/darwin-arm64.json` and the evidence record, set the
`darwin-arm64` row of `benchmarks/release_v2.json` to `executed` with that evidence path, and re-run
`make check-release-v2`. For CI: push the release commit to the remote repository, let the `fast` and
`hdl` tiers run, and record the successful run URL and SHA in `results/evidence/U20/remote_ci.json`
(`{"schema": "remote-ci-run-v1", "url": …, "sha": …, "jobs": …}`), then set the `remote-ci` row to
`executed`. Only when the validator prints `OK — releasable` is `git tag v2.0-a2` permitted.
