#!/usr/bin/env python3
"""Validate the A2 specification triple: stage manifest, configuration identity, cycle contract (U04).

    python tools/check_a2_spec.py [--rtl]      # --rtl also checks that A2 elaboration is rejected

Checks (each printed as CHECK name ok/total):
  stages      — 23 banks, contiguous indices, unique names, delay 1, field widths add up, metadata
                carried on every bank from P2, group boundaries match the manifest
  widths      — the input/output port widths of docs/design_a2.md §4 equal the manifest's fields
  identity    — Config(2,1,1,1,0).id == "a2-cache-d1-p0-l1", declared not verified, neighbours rejected,
                Makefile ids come from model.config
  latency     — abstract token model: visible 22, transfer 23, II 1, D(N) = N + 29 for N in 9/17/34,
                R(N) = D(N) + 2, order preserved with bubbles and stalls
  elaboration — (--rtl) tetris_core with ARCH=2 fails to elaborate until U10 (V01)
  lane_guards — (--rtl) the four-lane A1 elaborates (U13); four lanes with bitmap/depth two/approximate
                profile and three lanes are rejected in RTL and in Python
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import a2_token_model as tm  # noqa: E402
from model.config import DECLARED_IDS, SUPPORTED_IDS, Config, status, validate  # noqa: E402

MANIFEST = ROOT / "architecture" / "a2_stages.json"
META_FROM_P2 = {"legal": 1, "y": 5, "candidate_id": 6, "tag": 16, "last": 1}


def check_stages(m: dict, problems: list) -> tuple[int, int]:
    total = ok = 0
    stages = m["stages"]

    def chk(cond, msg):
        nonlocal total, ok
        total += 1
        if cond:
            ok += 1
        else:
            problems.append(msg)

    chk(m["banks"] == 23 and len(stages) == 23, f"expected 23 banks, manifest has {m['banks']}/{len(stages)}")
    chk([s["index"] for s in stages] == list(range(len(stages))), "bank indices are not contiguous from 0")
    chk(len({s["name"] for s in stages}) == len(stages), "bank names are not unique")
    chk(all(s["delay_edges"] == 1 for s in stages), "every bank must have delay_edges 1")
    chk(all(sum(f["bits"] for f in s["out_fields"]) == s["out_bits"] for s in stages), "out_bits does not equal the sum of out_fields")
    chk(sum(s["delay_edges"] for s in stages) == m["latency"]["transfer_edges"], "sum of delays must equal transfer_edges")
    chk(m["latency"]["visible_edges"] == m["latency"]["transfer_edges"] - 1, "visible = transfer - 1")
    for s in stages[2:]:
        fields = {f["name"]: f["bits"] for f in s["out_fields"]}
        chk(all(fields.get(k) == v for k, v in META_FROM_P2.items()), f"{s['name']}: metadata {META_FROM_P2} not carried")
    for s in stages[:2]:
        fields = {f["name"]: f["bits"] for f in s["out_fields"]}
        chk(all(fields.get(k) == v for k, v in (("candidate_id", 6), ("tag", 16), ("last", 1))), f"{s['name']}: id/tag/last not carried")
    groups = m["stage_groups"]
    chk(groups["drop_merge_pipe"] == [0, 3] and groups["line_clear_pipe"] == [4, 12] and groups["features_pipe"] == [13, 19]
        and groups["score_pipe"] == [20, 22], "stage groups must tile P0-P22 as 0-3, 4-12, 13-19, 20-22")
    out12 = {f["name"] for f in stages[12]["out_fields"]}
    chk("board" in out12 and "cleared" in out12, "P12 must output the compacted board and clear count")
    chk({f["name"] for f in stages[3]["out_fields"]} >= {"board"}, "P3 must output the merged board")
    chk(stages[9]["out_fields"][3]["name"] == "survivors" and stages[9]["out_fields"][4]["name"] == "cleared", "P9 must form survivor and clear counts")
    chk({f["name"] for f in stages[10]["out_fields"]} >= {"match", "board"}, "P10 must register 400 match bits and the delayed board")
    match_bits = next(f["bits"] for f in stages[10]["out_fields"] if f["name"] == "match")
    chk(match_bits == 400, f"match bits {match_bits} != 20x20")
    chk(next(f["bits"] for f in stages[11]["out_fields"] if f["name"] == "partial_rows") == 1000, "P11 must carry 20x5x10 partial-row bits")
    chk({f["name"] for f in stages[19]["out_fields"]} >= {"A", "Q", "U", "L"}, "P19 must output A, Q, U, L")
    chk(stages[22]["out_fields"][0] == {"name": "score", "bits": 32}, "P22 must output a 32-bit score")
    return ok, total


def check_widths(m: dict, problems: list) -> tuple[int, int]:
    total = ok = 0
    expected_in = {"rotation": 2, "x": 4, "candidate_id": 6, "tag": 16, "last": 1}
    expected_out = {"legal": 1, "last": 1, "candidate_id": 6, "tag": 16, "y": 5, "score": 32}
    expected_ctx = {"ctx_board_i": 200, "ctx_heights_i": 50, "ctx_piece_i": 3}
    for name, exp, got in (("input", expected_in, m["input_fields"]), ("output", expected_out, m["output_fields"]),
                           ("context", expected_ctx, m["context_fields"])):
        total += 1
        if {f["name"]: f["bits"] for f in got} == exp:
            ok += 1
        else:
            problems.append(f"{name} fields {got} != {exp}")
    total += 1
    if m["input_bits"] == sum(expected_in.values()):
        ok += 1
    else:
        problems.append("input_bits mismatch")
    total += 1
    last = {f["name"]: f["bits"] for f in m["stages"][-1]["out_fields"]}
    if all(last.get(k) == v for k, v in expected_out.items()):
        ok += 1
    else:
        problems.append(f"P22 fields {last} do not provide the output ports {expected_out}")
    return ok, total


def check_identity(problems: list) -> tuple[int, int]:
    total = ok = 0

    def chk(cond, msg):
        nonlocal total, ok
        total += 1
        if cond:
            ok += 1
        else:
            problems.append(msg)

    a2 = Config(2, 1, 1, 1, 0)
    chk(a2.id == "a2-cache-d1-p0-l1", f"A2 id {a2.id}")
    st = status(a2)
    sources = [ROOT / "rtl" / f for f in ("candidate_pipe.sv", "search_pipeline.sv")]
    in_lists = all(f.name in (ROOT / "rtl" / lst).read_text() for f in sources for lst in ("files.f", "files_core.f"))
    if st == "declared":
        chk(a2.id in DECLARED_IDS and a2.id not in SUPPORTED_IDS, "declared A2 must not be verified")
        chk(not all(f.is_file() for f in sources), "A2 sources exist but the configuration is still declared: promote or remove")
        try:
            validate(a2)
            chk(False, "validate accepted the declared A2 configuration")
        except ValueError as exc:
            chk("declared" in str(exc) and "not implemented/verified" in str(exc), f"unexpected message: {exc}")
    else:
        chk(st == "verified" and a2.id in SUPPORTED_IDS, f"A2 status {st}")
        chk(all(f.is_file() for f in sources) and in_lists, "verified A2 requires its sources in rtl/files.f and rtl/files_core.f")
        chk(validate(a2) is a2, "validate must accept the verified A2 configuration")
        chk("ARCH == 2 && BOARD_REPR == 1 && LANES == 1 && DEPTH == 1 && PRECISION == 0" in (ROOT / "rtl" / "tetris_core.sv").read_text(),
            "tetris_core CFG_OK must admit exactly the A2 configuration")
    for bad in (Config(2, 0, 1, 1, 0), Config(2, 1, 2, 1, 0), Config(2, 1, 4, 1, 0), Config(2, 1, 1, 2, 0), Config(2, 1, 1, 1, 1),
                Config(2, 1, 1, 1, 5)):
        try:
            validate(bad)
            chk(False, f"validate accepted {bad.id}")
        except ValueError as exc:
            chk(status(bad) == "unsupported" and "not supported" in str(exc), f"{bad.id}: {exc}")
    from model.config import V1_SUPPORTED_IDS
    chk(len(V1_SUPPORTED_IDS) == 9 and V1_SUPPORTED_IDS <= set(SUPPORTED_IDS), "the nine v1 configurations must stay verified")
    out = subprocess.run([sys.executable, "-m", "model.config", "2", "1", "1", "1", "0"], cwd=ROOT, capture_output=True, text=True)
    chk(out.stdout.strip() == "a2-cache-d1-p0-l1", "python -m model.config does not print the id")
    mk = (ROOT / "Makefile").read_text()
    chk("model.config" in mk and "$(shell echo a$(ARCH)" not in mk, "Makefile must derive CFG_ID from model.config, not text")
    mk_out = subprocess.run(["make", "-s", "--no-print-directory", "print-cfg-id", "ARCH=2", "BOARD_REPR=1"], cwd=ROOT,
                            capture_output=True, text=True, env={**os.environ, "MAKEFLAGS": ""})
    lines = [l for l in mk_out.stdout.splitlines() if l.strip() and "directory" not in l]
    chk(lines[-1:] == ["a2-cache-d1-p0-l1"], f"make print-cfg-id gave {mk_out.stdout.strip()!r}")
    return ok, total


def check_latency(m: dict, problems: list) -> tuple[int, int]:
    total = ok = 0

    def chk(cond, msg):
        nonlocal total, ok
        total += 1
        if cond:
            ok += 1
        else:
            problems.append(msg)

    banks = m["banks"]
    s = tm.stream(4096, banks)
    chk(set(s["visible_latency"].values()) == {m["latency"]["visible_edges"]}, f"visible latency {set(s['visible_latency'].values())}")
    chk(set(s["transfer_latency"].values()) == {m["latency"]["transfer_edges"]}, f"transfer latency {set(s['transfer_latency'].values())}")
    chk(set(s["accept_spacings"]) == {m["latency"]["candidate_ii"]} and len(s["accept_spacings"]) == 4095, "acceptance spacing != 1")
    chk(s["order_preserved"], "order not preserved")
    import random
    rng = random.Random(7)
    stall = {e for e in range(6000) if rng.random() < 0.3}
    bubble = {e for e in range(6000) if rng.random() < 0.2}
    s2 = tm.stream(500, banks, ready=lambda e: e not in stall, bubbles=lambda e: e in bubble)
    chk(s2["order_preserved"] and len(s2["transfer_latency"]) == 500, "order/count under bubbles and stalls")
    chk(all(v >= m["latency"]["transfer_edges"] for v in s2["transfer_latency"].values()), "stalled transfer latency below the minimum")
    for n, expected in ((9, 38), (17, 46), (34, 63)):
        d = tm.decision_latency(n, banks)
        sim = tm.simulate_search(n, banks)
        chk(d["decision_cycles"] == expected == tm.formula(n, banks) == sim["rsp_valid_edge"], f"D({n}) = {d['decision_cycles']}/{sim['rsp_valid_edge']} != {expected}")
        chk(sim["issued"] == sim["retired"] == n, f"N={n}: issued {sim['issued']} retired {sim['retired']}")
        chk(tm.request_interval(n, banks) == expected + 2, f"R({n}) != D + 2")
    chk("N + 29" in m["latency"]["decision_formula"], "manifest formula text")
    return ok, total


def check_elaboration(problems: list) -> tuple[int, int]:
    """V01: direct elaboration of tetris_core with ARCH=2 fails while A2 is declared and succeeds once verified;
    the nearby unsupported A2 combinations must always fail."""
    files = [str(ROOT / s) for s in (ROOT / "rtl" / "files_core.f").read_text().split() if s.endswith(".sv")]
    from tools.build_native import WARNING_WAIVERS
    # no -Wno-fatal: it would demote the $error guard (v1 lesson); legacy warning waivers as in the native build
    cmd = ["bash", str(ROOT / "scripts" / "env.sh"), "verilator", "--lint-only", *WARNING_WAIVERS, "--top-module", "tetris_core",
           f"-I{ROOT / 'rtl'}", "-GARCH=2", "-GBOARD_REPR=1", "-GLANES=1", "-GDEPTH=1", "-GPRECISION=0", *files]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    text = out.stdout + out.stderr
    ok = total = 0
    if status(Config(2, 1, 1, 1, 0)) == "declared":
        total += 1
        if out.returncode != 0 and "unsupported parameter combination" in text:
            ok += 1
        else:
            problems.append(f"A2 elaboration was not rejected (exit {out.returncode})")
    else:
        total += 1
        if out.returncode == 0:
            ok += 1
        else:
            problems.append(f"verified A2 does not elaborate (exit {out.returncode}): {text[-400:]}")
    # nearby unsupported combinations must fail in elaboration
    base = cmd[:-len(files)]
    for override in (["-GBOARD_REPR=0"], ["-GLANES=2"], ["-GDEPTH=2"], ["-GPRECISION=1"]):
        total += 1
        bad = subprocess.run(base + override + files, cwd=ROOT, capture_output=True, text=True)
        if bad.returncode != 0 and "unsupported parameter combination" in bad.stdout + bad.stderr:
            ok += 1
        else:
            problems.append(f"A2 with {override} was not rejected in elaboration")
    total += 1
    good = subprocess.run(base + ["-GARCH=1"] + files, cwd=ROOT, capture_output=True, text=True)
    if "unsupported parameter combination" not in (good.stdout + good.stderr):
        ok += 1
    else:
        problems.append("ARCH=1 elaboration reported the configuration error")
    return ok, total


def check_lane_guards(problems: list) -> tuple[int, int]:
    """U13: the four-lane A1 (cache, depth one, exact) elaborates; four lanes with the bitmap, depth two, an
    approximate profile, or three lanes, are rejected by CFG_OK, and the Python validator agrees."""
    files = [str(ROOT / s) for s in (ROOT / "rtl" / "files_core.f").read_text().split() if s.endswith(".sv")]
    from tools.build_native import WARNING_WAIVERS
    base = ["bash", str(ROOT / "scripts" / "env.sh"), "verilator", "--lint-only", *WARNING_WAIVERS, "--top-module", "tetris_core",
            f"-I{ROOT / 'rtl'}", "-GARCH=1", "-GBOARD_REPR=1", "-GLANES=4", "-GDEPTH=1", "-GPRECISION=0"]
    ok = total = 0
    total += 1
    l4 = Config(1, 1, 4, 1, 0)
    good = subprocess.run(base + files, cwd=ROOT, capture_output=True, text=True)
    if good.returncode == 0 and status(l4) == "verified" and l4.id == "a1-cache-d1-p0-l4":
        ok += 1
    else:
        problems.append(f"four-lane A1 does not elaborate or is not verified (exit {good.returncode}, status {status(l4)})")
    for override, bad_cfg in ((["-GBOARD_REPR=0"], Config(1, 0, 4, 1, 0)), (["-GDEPTH=2"], Config(1, 1, 4, 2, 0)),
                              (["-GPRECISION=1"], Config(1, 1, 4, 1, 1)), (["-GLANES=3"], Config(1, 1, 3, 1, 0))):
        total += 1
        bad = subprocess.run(base + override + files, cwd=ROOT, capture_output=True, text=True)
        rejected_rtl = bad.returncode != 0 and "unsupported parameter combination" in bad.stdout + bad.stderr
        try:
            validate(bad_cfg)
            rejected_py = False
        except ValueError:
            rejected_py = status(bad_cfg) == "unsupported"
        if rejected_rtl and rejected_py:
            ok += 1
        else:
            problems.append(f"{bad_cfg.id} ({override}) not rejected: rtl {rejected_rtl}, python {rejected_py}")
    return ok, total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rtl", action="store_true", help="also check that A2 elaboration is rejected (needs Verilator)")
    args = ap.parse_args()
    m = json.loads(MANIFEST.read_text())
    problems = []
    results = {"stages": check_stages(m, problems), "widths": check_widths(m, problems), "identity": check_identity(problems),
               "latency": check_latency(m, problems)}
    if args.rtl:
        results["elaboration"] = check_elaboration(problems)
        results["lane_guards"] = check_lane_guards(problems)
    for name, (ok, total) in results.items():
        print(f"CHECK a2_{name} {ok}/{total}")
    if problems:
        print("check-a2-spec: FAIL")
        for p in problems:
            print("  -", p)
        return 1
    print(f"check-a2-spec: OK (A2 {status(Config(2, 1, 1, 1, 0))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
