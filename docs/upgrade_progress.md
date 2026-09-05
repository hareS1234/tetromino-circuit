# Upgrade progress (U00–U20)

Branch `upgrade/a2` from `v1.0` (`c66ad9b`). Evidence per job in `results/evidence/Uxx/summary.json`
(schema `upgrade-evidence-v1`). Statuses: pending, running, passed, failed, blocked.

| Job | Status | Notes |
|---|---|---|
| U00 baseline inventory | passed | `docs/audit_response.md`, `results/evidence/U00/inventory.json` |
| U01 portable bootstrap | passed | `toolchains/oss_cad_suite.lock.json` (linux-x64 verified, three families unenrolled), `scripts/bootstrap.sh --enroll`, `results/host/Linux-x86_64.json`, `tools/doctor.py` v2 lock; gate: test-bootstrap 11 passed, bootstrap idempotent, doctor OK, test-python 316 passed, smoke 1/1 (`results/evidence/U01`, commit `ff19486`). Mac execution blocked → U20 |
| U02 identities / resume / summaries / gates | passed | `tools/identity.py` (synth/route/analysis/native/quality keys), identity-keyed `build/synth|route|native/<key>`, `results/v2/raw/{routes,decisions,quality}` one record per job, `measure_matrix.py plan/run/status` with lock+heartbeat+retry, `bench.py --config/--out-root` + strict `summarise`, empty gates rejected, `check_v1_results.py` exact membership. Gate: test-identities 35 passed, test-result-schemas 30 passed, check-v1-results 640/640 · 8/8 · 45/45 · 9/9 · 20/20, upgrade-smoke (1 real route routed_timing_met 66.49 MHz reused by identity, 50/50 native decisions, 12 v2 games) (`results/evidence/U02`, commit `0fb5379`). `docs/identities.md` |
| U03 GitHub workflow | pending (remote run will be blocked: no remote) | |
| U04 A2 specification | pending | |
| U05 compactor reference + formal | pending | |
| U06 pipelined compactor | pending | |
| U07 landing/merge front end | pending | |
| U08 feature/score pipes | pending | |
| U09 candidate pipeline | pending | |
| U10 search + core integration | pending | |
| U11 verification + mutations | pending | |
| U12 route A2 | pending | |
| U13 four-lane A1 | pending | |
| U14 quantization ladder | pending | |
| U15 v2 benchmarks/statistics | pending | |
| U16 v2 quality study | pending | |
| U17 v2 hardware matrix | pending | |
| U18 pipeline replay | pending | |
| U19 report/repository | pending | |
| U20 Mac + remote release | pending (Mac and CI blocked here) | |

## Current

* Last passing job: U02.
* Current job: U03.
* Active process/log: none.
* Next command: restructure `.github/workflows/ci.yml` (fast / HDL smoke / manual heavy, shared cached bootstrap), validate locally, record the remote gate as blocked (no remote, no credentials).
* Blockers: remote CI and Mac execution are environment blockers for U03/U20; A2 work (U04+) is not blocked.
