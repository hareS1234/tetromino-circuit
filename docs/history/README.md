# History

The v1 phase of this repository (tags `v0.1-python` … `v1.0`, jobs E00–E19) was audited before the
v2 upgrade (jobs U00–U20). The useful engineering records from that phase live here:

| Document | What it is |
|---|---|
| `progress.md` | the v1 job log (last passing job, evidence pointers) |
| `bugs.md`, `PROBLEMS_FOUND.md` | defects found and fixed during v1, and the audit of the first manual |
| `audit_response.md` | the U00 baseline inventory and audit response that started the v2 upgrade |
| `understanding.md` | the v1 author's working notes |

Development-history routing rows (attempts made while the v1 timing problems were fixed, including
failed-timing rows) live in `results/history/`: the two original CSVs and
`implementation_dev_history_consolidated.csv`, which merges them by identity and attempt
(`implementation_dev_history_consolidated.json` records the merge: sources, rows in/out, duplicates
merged, failed rows kept). The frozen v1 experiment itself is `results/implementation.csv`,
`results/quality.csv`, `results/decisions/` and `results/evidence/E00–E19`, validated by
`make check-v1-results`.

Former result-history CSVs were consolidated here; the older job notes were moved here from the
top-level `docs/` folder.
