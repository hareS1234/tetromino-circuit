# CI without mystery meat (U03)

There are three jobs in `.github/workflows/ci.yml`. They all use the same bootstrap action, but they
are intentionally different sizes.

| Job | When | Job in plain English | Limit |
|---|---|---|---|
| `fast` | every push and pull request | Python tests, generated-file checks, frozen v1 results, v2 streams, reports, traces, viewer, links, headline claims, and a structural check of this workflow | 20 min |
| `hdl` | every push and pull request | pinned Linux CAD tools, bootstrap checks, directed RTL, native A1/A2 corpora, A2 specification/stream/protocol checks, a trace replay, identity/schema checks, and the small upgrade smoke route | 90 min |
| `heavy` | manual dispatch | the hardware manifest and quality suite named in the dispatch form; the defaults are tiny smoke inputs | 360 min |

The split keeps routine feedback quick. Routing 84 FPGA jobs requires a conscious click and an
explicit manifest.

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
The workflow uses reviewed major action tags: `actions/checkout@v5`, `actions/setup-python@v5`,
`actions/cache@v4`, and `actions/upload-artifact@v4`. The local validator rejects unexpected action
versions.

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

This mode skips GitHub-hosted actions. It expands composite shell steps and uses the default dispatch
inputs. The check catches local workflow mistakes. GitHub Actions still provides the remote result.

## Remote status

The pinned `fast` and `hdl` jobs passed at [`f4a8bf8d5fc5`](https://github.com/hareS1234/tetromino-circuit/actions/runs/34015987600). The original U03 blocked record remains historical; U20 carries the live remote-run evidence.

The separate `.github/workflows/release-check.yml` runs the full release validator on linux-x64. That platform choice matters because the published route identities include Linux tool version strings. Its full-history checkout is intentional too: the v1 validator checks tags.
