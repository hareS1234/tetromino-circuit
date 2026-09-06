# CI without mystery meat (U03)

There are three jobs in `.github/workflows/ci.yml`. They all use the same bootstrap action, but they
are intentionally different sizes.

| Job | When | Job in plain English | Limit |
|---|---|---|---|
| `fast` | every push and pull request | Python tests, generated-file checks, frozen v1 results, v2 streams, reports, traces, viewer, links, headline claims, and a structural check of this workflow | 20 min |
| `hdl` | every push and pull request | pinned Linux CAD tools, bootstrap checks, directed RTL, native A1/A2 corpora, A2 specification/stream/protocol checks, a trace replay, identity/schema checks, and the small upgrade smoke route | 90 min |
| `heavy` | manual dispatch | the hardware manifest and quality suite named in the dispatch form; the defaults are tiny smoke inputs | 360 min |

The split is mostly about blast radius. A typo should get a quick answer; routing 84 FPGA jobs should
require a conscious click and an explicit manifest.

Each job uploads useful scraps even on failure: JUnit XML, cocotb results, build logs, route records,
v2 raw/summary files, and the host observation. Only the CAD archive is cached. Results are never
restored from cache, so an uploaded record belongs to the run that uploaded it.

## Bootstrap action

`.github/actions/bootstrap` maps the runner's real `uname -s` and `uname -m` to
`toolchains/oss_cad_suite.lock.json`. Its cache key includes OS, architecture, release, and SHA-256.
Whether the archive came from cache or GitHub, `scripts/bootstrap.sh` checks the hash before
extracting it. The `fast` job passes `hdl: "false"`, which skips the CAD bundle and creates only the
locked Python environment.

CI uses Python 3.12; Python 3.11 is supported too. Both versions were exercised locally during U03.
The workflow currently uses major action tags (`actions/checkout@v5`, `actions/setup-python@v5`,
`actions/cache@v4`, and `actions/upload-artifact@v4`). Pin those to inspected commit SHAs after the
first real remote run.

## Kicking the tyres locally

```bash
bash scripts/env.sh python tools/ci_local.py --validate
bash scripts/env.sh python tools/ci_local.py --workflow .github/workflows/release-check.yml --validate
```

The validator checks expressions, action references, called scripts, and Make targets. To run one
job's shell commands in order, use:

```bash
bash scripts/env.sh python tools/ci_local.py --job fast
bash scripts/env.sh python tools/ci_local.py --job hdl
bash scripts/env.sh python tools/ci_local.py --job heavy --event workflow_dispatch
```

GitHub-hosted actions are skipped in this mode; composite shell steps are expanded and dispatch
inputs use their defaults. This catches a surprising amount, but it is not a substitute for GitHub
actually running the workflow.

## Remote status

This checkout has no Git remote, so there is no honest run URL or SHA to record. U03's original
remote gate and U20's `remote-ci` row therefore remain blocked. Before release, the maintainer must
push the intended commit, inspect both `fast` and `hdl`, pin the action revisions, and record the
successful run as described in `docs/release_v2.md`.

The separate `.github/workflows/release-check.yml` runs the full release validator on linux-x64.
That platform choice matters: the published route identities include Linux tool version strings.
Its full-history checkout is also intentional because the v1 validator checks tags.
