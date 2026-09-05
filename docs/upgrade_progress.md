# Upgrade progress (U00–U20)

Branch `upgrade/a2` from `v1.0` (`c66ad9b`). Evidence per job in `results/evidence/Uxx/summary.json`
(schema `upgrade-evidence-v1`). Statuses: pending, running, passed, failed, blocked.

| Job | Status | Notes |
|---|---|---|
| U00 baseline inventory | passed | `docs/audit_response.md`, `results/evidence/U00/inventory.json` |
| U01 portable bootstrap | passed | `toolchains/oss_cad_suite.lock.json` (linux-x64 verified, three families unenrolled), `scripts/bootstrap.sh --enroll`, `results/host/Linux-x86_64.json`, `tools/doctor.py` v2 lock; gate: test-bootstrap 11 passed, bootstrap idempotent, doctor OK, test-python 316 passed, smoke 1/1 (`results/evidence/U01`, commit `ff19486`). Mac execution blocked → U20 |
| U02 identities / resume / summaries / gates | passed | `tools/identity.py` (synth/route/analysis/native/quality keys), identity-keyed `build/synth|route|native/<key>`, `results/v2/raw/{routes,decisions,quality}` one record per job, `measure_matrix.py plan/run/status` with lock+heartbeat+retry, `bench.py --config/--out-root` + strict `summarise`, empty gates rejected, `check_v1_results.py` exact membership. Gate: test-identities 35 passed, test-result-schemas 30 passed, check-v1-results 640/640 · 8/8 · 45/45 · 9/9 · 20/20, upgrade-smoke (1 real route routed_timing_met 66.49 MHz reused by identity, 50/50 native decisions, 12 v2 games) (`results/evidence/U02`, commit `0fb5379`). `docs/identities.md` |
| U03 GitHub workflow | **blocked** (remote) — local validation passed | `.github/workflows/ci.yml` fast/hdl/heavy on `.github/actions/bootstrap` (cache key OS/arch/release/hash, hash-verified before extraction, `hdl: false` software-only), `tools/ci_local.py` (`--validate` 3/3; local runs: fast 10/10 steps, hdl 11/11, heavy 6/6 with the smoke manifest), `docs/ci.md`; Python 3.12 (`.venv312`) passed test-python 381, smoke, identities, native corpus. No remote/credentials → remote run not executed (`results/evidence/U03`, commit `b6d8715`); U20 must push, inspect, pin action SHAs |
| U04 A2 specification | passed | `docs/design_a2.md`, `architecture/a2_stages.json` (23 banks), `model/config.py` verified/declared/unsupported with Makefile ids from `python -m model.config`, `model/a2_token_model.py`; gate `make check-a2-spec`: 14 spec tests, stages 39/39, widths 5/5, identity 13/13, latency 16/16, A2 elaboration rejected 2/2 (`results/evidence/U04`, commit `034e3b9`) |
| U05 compactor reference + formal | passed | `model/compaction.py`, `rtl/row_rank20.sv`, `rtl/line_clear_parallel.sv`, `sim/compactor_main.cpp`, `formal/{smoke,compactor}`; gate: test-prefix 15 passed, native exhaustive 1,048,576/1,048,576 masks, random 100,000/100,000 boards, formal smoke unbounded, miter **unbounded** (k-induction, boolector, 51 s), covers reached (`results/formal/*.json`, `results/evidence/U05`) |
| U06 pipelined compactor | passed | `rtl/line_clear_pipe.sv` (P4–P12, shared `advance_i`), `rtl/line_clear_pipe_harness.sv`, `sim/compactor_pipe_main.cpp`, `tb/tb_clear_pipe.py`, `tools/synth_module.py`; gate: cocotb 4/4, native stream continuous 4096 (spacing 1, transfer 9 edges), random 4096 (0 mismatch/stability/spurious), stalls 8/8, back-to-back 300, reset 22/22, micro-synthesis 3283 LUT4 / 3482 FF / 0 DSP / no latch with match+select modules live (`results/evidence/U06`) |
| U07 landing/merge front end | passed | `rtl/drop_merge_pipe.sv` (P0–P3), harness, `tb/tb_drop_merge_pipe.py`; gate: cocotb 5/5 (40,500 corpus tokens + fixtures, stalls/bubbles, reset at every occupancy), smoke synthesis 1019 LUT4 / 420 FF / 0 DSP / no latch (`results/evidence/U07`) |
| U08 feature/score pipes | passed | `rtl/features_pipe.sv` (P13–P19), `rtl/score_pipe.sv` (P20–P22), harnesses, `tb/tb_features_pipe.py` (200 one-hots, height-20 columns, checkerboards, 10,000 boards), `tb/tb_score_pipe.py` (bounds, 10,000 tuples, signed); gate cocotb 3/3 + 3/3, synthesis 824 LUT4/989 FF and 43 LUT4/219 FF, no DSP/latch (`results/evidence/U08`) |
| U09 candidate pipeline | passed | `rtl/candidate_pipe.sv` (P0–P22, one advance), `tools/a2_vectors.py` + `sim/candidate_pipe_main.cpp` native harness, `tb/tb_candidate_pipe.py`; gate: cocotb 4/4, stream 4,096 tokens (spacing 1, **visible 22, transfer 23** measured), oracle traffic 1,733/1,733 (12,240/12,240 in a larger run), metadata 201/201, reset 50/50, trace `results/traces/a2_stall_reset.vcd.gz`, synthesis 5128 LUT4 / 5114 FF / 0 DSP (`results/evidence/U09`) |
| U10 search + core integration | passed | `rtl/search_pipeline.sv`, `g_a2` in `rtl/tetris_core.sv`, A2 promoted to verified, `tools/make_corpus_v2.py` (2,000-state dev corpus, seeds 11000–11099), pair mode in `sim/main.cpp` + `tools/request_interval.py`; gate: core corpus 1000/1000 + dev 2000/2000 (min/median/max cycles 38/46/63 = N+29), tb_protocol 9/9, tb_wrapper 4/4, drivers agree 50/50, request interval 200/200 = N+31, check-a2-spec (`results/evidence/U10`) |
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

* Last passing job: U10 (U03 is blocked on the remote run only; its local validation passed).
* Current job: U11.
* Active process/log: none.
* Next command: `make verify-a2-release` (V01–V14 + A0/A1 regression), `make formal-a2-control` (control conservation + best reduction proofs), `make mutation-check-a2` (`tools/run_mutations.py`, twelve mutations), `make replay-suite ARCH=2 BOARD_REPR=1 CAP=250`, verification matrix.
* Blockers: remote CI (U03/U20) and Mac execution (U20) are environment blockers; A2 work is not blocked.
