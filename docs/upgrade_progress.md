# Upgrade progress (U00–U20)

Branch `upgrade/a2` from `v1.0` (`c66ad9b`). Evidence per job in `results/evidence/Uxx/summary.json`
(schema `upgrade-evidence-v1`). Statuses: pending, running, passed, failed, blocked.

| Job | Status | Notes |
|---|---|---|
| U00 baseline inventory | passed | `docs/audit_response.md`, `results/evidence/U00/inventory.json` |
| U01 portable bootstrap | passed | `toolchains/oss_cad_suite.lock.json` (linux-x64 verified, three families unenrolled), `scripts/bootstrap.sh --enroll`, `results/host/Linux-x86_64.json`, `tools/doctor.py` v2 lock; gate: test-bootstrap 11 passed, bootstrap idempotent, doctor OK, test-python 316 passed, smoke 1/1 (`results/evidence/U01`, commit `ff19486`). Mac execution blocked → U20 |
| U02 identities / resume / summaries / gates | pending | |
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

* Last passing job: U01.
* Current job: U02.
* Active process/log: none.
* Next command: `make test-identities` (after U02's tests exist).
* Blockers: none for U02; remote CI and Mac execution are environment blockers for U03/U20.
