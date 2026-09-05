# tetromino-circuit — every recipe runs through scripts/env.sh so fresh shells need no activation.
SHELL := /bin/bash
ENV := bash scripts/env.sh
PY := $(ENV) python
RUN_RTL := $(PY) tools/run_rtl.py

# Hardware/policy configuration (validated by model/config.py in every tool)
ARCH ?= 0
BOARD_REPR ?= 0
LANES ?= 1
DEPTH ?= 1
PRECISION ?= 0
SEED ?= 1
CAP ?= 250
COUNT ?= 50
DRIVER ?= native
CFG := --arch $(ARCH) --board-repr $(BOARD_REPR) --lanes $(LANES) --depth $(DEPTH) --precision $(PRECISION)
PARAMS := --param ARCH=$(ARCH) --param BOARD_REPR=$(BOARD_REPR) --param LANES=$(LANES) --param DEPTH=$(DEPTH) --param PRECISION=$(PRECISION)
CFG_ID := $(shell echo a$(ARCH)-$(if $(filter 1,$(BOARD_REPR)),cache,bitmap)-d$(DEPTH)-p$(PRECISION)-l$(LANES))

.PHONY: help doctor doctor-python gen check-gen smoke test-python test-geometry test-reference \
        demo-python tournament-python pilot-python streams \
        test-shapes test-score test-drop test-merge test-clear test-features test-candidate synth-candidate \
        test-core test-protocol native test-driver replay-suite demo-rtl test-wrapper synth pnr \
        test-fast test-cache test-precision measure-precision test-lookahead-reference test-lookahead-rtl \
        test-lanes test-rtl check-benchmark-config bench-pilot bench measure-matrix tournament plots \
        check-report check-release reproduce clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-28s %s\n", $$1, $$2}'

# ---------------------------------------------------------------- E00
doctor: ## full toolchain check (hardware gate)
	$(PY) tools/doctor.py --profile full
doctor-python: ## python-only check
	$(PY) tools/doctor.py --profile python
smoke: ## counter simulation, lint and synthesis smoke test
	$(RUN_RTL) --top counter --test tb_counter --source rtl/learning/counter.sv
	$(ENV) verilator --lint-only -Wall --top-module counter rtl/learning/counter.sv
	mkdir -p build/smoke && $(ENV) yosys -q -l build/smoke/counter_synth.log -p 'read_verilog -sv rtl/learning/counter.sv; synth_ecp5 -top counter; stat; check -assert' > /dev/null
	$(PY) tools/check_synth_log.py build/smoke/counter_synth.log --min-cells 4

# ---------------------------------------------------------------- E01–E03
gen: ## regenerate geometry tables and verify determinism
	$(PY) tools/gen_shapes.py
	$(PY) tools/gen_shapes.py --check
check-gen:
	$(PY) tools/gen_shapes.py --check
streams: ## regenerate the committed piece streams
	$(PY) tools/make_streams.py
	$(PY) tools/make_streams.py --check
test-geometry: ## E01 gate
	$(PY) -m pytest tests/unit/test_pieces.py tests/unit/test_board.py -q
test-reference: ## E02 gate: 40,500-case three-way differential and policy equivalence
	$(PY) -m pytest tests/unit/test_game.py tests/unit/test_reference.py tests/unit/test_policy.py -q
test-python: ## all pure-Python tests
	$(PY) -m pytest tests/unit -q
demo-python: ## software replay and GIF (seed 2000, 250 pieces)
	$(PY) tools/play.py --backend python --policy heuristic --seed 2000 --max-pieces 250 --out results/python_demo.jsonl
	$(PY) tools/play.py --backend python --policy random_legal --seed 2000 --max-pieces 250 --out results/random_demo.jsonl
	$(PY) tools/render.py --replay results/python_demo.jsonl --out assets/python_demo.gif --png assets/python_demo_final.png
tournament-python: demo-python ## two-policy software tournament
	$(PY) tools/render_tournament.py --replays results/python_demo.jsonl results/random_demo.jsonl --sync pieces --out assets/tournament_python.gif --max-frames 120
pilot-python: ## validation pilot, 20 seeds, cap 500
	$(PY) tools/pilot.py --split validation --cap 500 --out results/pilot_validation.csv

# ---------------------------------------------------------------- E04–E06 (module tests)
test-shapes: ## shape ROM vs Python, all 32 inputs
	$(RUN_RTL) --top shape_rom --test tb_shapes --files-f rtl/files_shapes.f
test-score: ## registered scorer vs Python (PRECISION=$(PRECISION))
	$(RUN_RTL) --top score --test tb_score --files-f rtl/files_score.f --param PRECISION=$(PRECISION)
test-drop:
	$(RUN_RTL) --top drop_unit --test tb_drop --files-f rtl/files_drop.f
test-merge:
	$(RUN_RTL) --top merge_unit --test tb_merge --files-f rtl/files_merge.f
test-clear:
	$(RUN_RTL) --top line_clear --test tb_clear --files-f rtl/files_clear.f
test-features:
	$(RUN_RTL) --top features --test tb_features --files-f rtl/files_features.f --param PRECISION=$(PRECISION)
test-candidate: ## A0/A1 candidate evaluator with intermediate-value checks
	$(RUN_RTL) --top candidate_eval --test tb_candidate --files-f rtl/files_candidate$(if $(filter 0,$(ARCH)),_a0,).f --param ARCH=$(ARCH) --param BOARD_REPR=$(BOARD_REPR) --param PRECISION=$(PRECISION)
synth-candidate:
	$(PY) tools/synth.py --top candidate_eval --arch $(ARCH) --board-repr $(BOARD_REPR) --precision $(PRECISION) --out build/synth_candidate_a$(ARCH)

# ---------------------------------------------------------------- E07–E09 (core)
test-core: ## differential core tests, COUNT requests, DRIVER=cocotb|native
	$(PY) tools/test_core.py $(CFG) --count $(COUNT) --driver $(DRIVER)
test-protocol: ## ready/valid, stalls, resets, invalid piece
	$(RUN_RTL) --top tetris_core --test tb_protocol --files-f rtl/files.f $(PARAMS)
native: ## build the persistent C++ Verilator driver for the configuration
	$(PY) tools/build_native.py $(CFG) --out build/native_$(CFG_ID)
test-driver: ## native vs cocotb equivalence on COUNT requests
	$(PY) tools/test_core.py $(CFG) --count $(COUNT) --driver both
replay-suite: ## seeds 2000-2002 with the RTL core, checked against Python at every move
	$(PY) tools/play_rtl.py $(CFG) --driver native --seed 2000 --max-pieces $(CAP) --out results/replays/$(CFG_ID)_seed2000_cap$(CAP).jsonl
	$(PY) tools/play_rtl.py $(CFG) --driver native --seed 2001 --max-pieces $(CAP) --out results/replays/$(CFG_ID)_seed2001_cap$(CAP).jsonl
	$(PY) tools/play_rtl.py $(CFG) --driver native --seed 2002 --max-pieces $(CAP) --out results/replays/$(CFG_ID)_seed2002_cap$(CAP).jsonl
demo-rtl: ## default RTL replay GIF (A0, seed 2000)
	$(PY) tools/play_rtl.py $(CFG) --driver native --seed 2000 --max-pieces $(CAP) --out results/rtl_demo.jsonl
	$(PY) tools/render.py --replay results/rtl_demo.jsonl --out assets/rtl_demo.gif --png assets/rtl_demo_final.png
test-wrapper: ## streaming wrapper framing, stalls, reset, back-to-back
	$(RUN_RTL) --top stream_wrapper --test tb_wrapper --files-f rtl/files.f $(PARAMS)
synth: ## Yosys synth_ecp5 of stream_wrapper for the configuration
	$(PY) tools/synth.py --top stream_wrapper $(CFG) --out build/synth_$(CFG_ID)
pnr: ## nextpnr-ecp5 85k CABGA381 speed 6 at the recorded target
	$(PY) tools/pnr.py $(CFG) --seed $(SEED) --json build/synth_$(CFG_ID)/netlist.json --out build/pnr_$(CFG_ID)_s$(SEED)

# ---------------------------------------------------------------- E10–E15
test-fast: ## A1 datapath modules vs oracle
	$(RUN_RTL) --top fast_tb --test tb_fast --files-f rtl/files_fast.f
test-cache:
	$(RUN_RTL) --top tetris_core --test tb_cache --files-f rtl/files.f --param ARCH=1 --param BOARD_REPR=1
test-precision: ## every profile against its own reference (scorer tuples + full requests)
	$(PY) tools/test_precision.py
measure-precision:
	$(PY) tools/measure_precision.py --split validation
test-lookahead-reference:
	$(PY) -m pytest tests/unit/test_lookahead.py -q
test-lookahead-rtl:
	$(RUN_RTL) --top tetris_core --test tb_lookahead --files-f rtl/files.f --param ARCH=1 --param BOARD_REPR=1 --param DEPTH=2
	$(RUN_RTL) --top tetris_core --test tb_lookahead --files-f rtl/files.f --param ARCH=1 --param BOARD_REPR=1 --param DEPTH=1 --build-tag d1preview
test-lanes:
	$(RUN_RTL) --top tetris_core --test tb_lanes --files-f rtl/files.f --param ARCH=1 --param BOARD_REPR=1 --param LANES=2
test-rtl: test-shapes test-score test-drop test-merge test-clear test-features test-candidate test-protocol ## directed RTL tests plus a differential subset
	$(PY) tools/test_core.py --arch 0 --board-repr 0 --count 100 --driver native

# ---------------------------------------------------------------- E16–E19
check-benchmark-config:
	$(PY) tools/bench.py --check-config
bench-pilot:
	$(PY) tools/bench.py --suite pilot
bench: ## frozen software study, SUITE=precision|depth
	$(PY) tools/bench.py --suite $(SUITE)
measure-matrix: ## synth + route seeds 1-5 for the nine configurations, plus decision corpus
	$(PY) tools/measure_matrix.py
tournament: ## real RTL tournament replays and GIF
	$(PY) tools/tournament.py
plots:
	$(PY) tools/plots.py
check-report:
	$(PY) tools/check_report.py
check-release:
	$(PY) tools/check_release.py
reproduce: ## resumable orchestrator of the documented release pipeline
	$(PY) tools/reproduce.py
clean:
	rm -rf build/*
