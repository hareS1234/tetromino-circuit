# Progress

| Job | Status | Evidence |
|---|---|---|
| E00 bootstrap and smoke | passed | `results/evidence/E00` — Verilator 5.051, Yosys 0.68, nextpnr 0.11.1; counter sim/lint/synth |
| E01 rules and geometry | passed | `results/evidence/E01` — 162 candidates, 200 one-hot positions, deterministic generation |
| E02 independent reference | passed | `results/evidence/E02` — 40,500-case three-way differential |
| E03 software player | passed | `results/evidence/E03` — replays, tournament GIF, 20-seed pilot |
| E04 ROM and scorer | passed | `results/evidence/E04` — 32 ROM inputs, 1,000 tuples per profile, mutation detected |
| E05 drop/merge/clear | passed | `results/evidence/E05` — 8,100 drop candidates incl. high-overhang regression |
| E06 A0 evaluator | passed | `results/evidence/E06` — 16,200 candidates, 277-cycle worst case, 2,703 LUT4 / 0 DSP |
| E07 A0 core | passed | `results/evidence/E07` — protocol suite; 1,000-request corpus |
| E08 native driver and release | passed | `results/evidence/E08` — drivers agree; seeds 2000–2002 × 250 pieces; tag `v0.2-rtl` |
| E09 implementation reports | passed | `results/evidence/E09` — wrapper tests; 66.5 MHz routed; tag `v0.3-implemented` |
| E10 A1 fast datapath | passed | `results/evidence/E10` — identical decisions; 790 vs 4,720 median cycles |
| E11 height cache | passed | `results/evidence/E11` — cache equals Python heights; 773 median cycles |
| E12 numerical profiles | passed | `results/evidence/E12` — own-reference tests P1–P4; validation pilot; divergence replay |
| E13 lookahead reference | passed | `results/evidence/E13` — 250 frozen cases, brute force agreement |
| E14 lookahead RTL | passed | `results/evidence/E14` — 250/250; worst 52,469 cycles; cap-100 replays |
| E15 two lanes | passed | `results/evidence/E15` — identical decisions; 1.87× speed-up |
| E16 freeze the study | passed | `results/evidence/E16` — `benchmarks/config.json`, pilot estimate |
| E17 run the study | passed | `results/quality.csv`, `results/implementation.csv`, `results/tournament_report.json` |
| E18 portfolio and report | passed | `assets/plots/`, `README.md`, `docs/design.md` |
| E19 fresh environment and CI | passed (remote CI unverified) | `.github/workflows/ci.yml`, fresh-clone check |

Last passing job, current job, next command and blockers are updated at the end of each session in
the section below.

## Session log

* Session 1 (2026-09-05): E00–E19 complete and recorded (`results/evidence/`). The E19 fresh-clone
  check performed a full bootstrap including the suite download. Remote CI is unverified because no
  repository push was authorised in this session; `.github/workflows/ci.yml` uses the same bootstrap
  as local development. Next command for a maintainer: push and watch the `checks` workflow, then
  `make reproduce` on a second machine. The only environment restriction observed was that the GitHub
  REST API is unreachable from the build container (release assets are reachable), which the bootstrap
  avoids by construction.
