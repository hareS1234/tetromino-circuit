#!/usr/bin/env python3
"""Export the three cycle-by-cycle A2 stories from Verilated RTL.

The normal and last-winner stories use the production core. The stall/reset story is clearly marked
as a standalone verification setup because production never blocks its candidate output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import compaction, policy  # noqa: E402
from model.board import board_words, pack_rows  # noqa: E402
from model.config import Config, validate  # noqa: E402
from model.features import column_heights, features  # noqa: E402
from model.game import drop_y, lock_and_clear  # noqa: E402
from model.pieces import candidate_ids, decode_candidate, shape  # noqa: E402
from tools.build_native import WARNING_WAIVERS, build_harness  # noqa: E402
from tools.identity import native_identity, source_closure_sha256, toolchain_identity  # noqa: E402

TRACES = ROOT / "results" / "traces"
MANIFEST = ROOT / "architecture" / "a2_stages.json"
CORPUS = ROOT / "benchmarks" / "states" / "corpus_d1.jsonl"
A2 = validate(Config(2, 1, 1, 1, 0))
PUBLIC = ["--public-flat-rw"]


def merged_rows(rows, piece, rotation, x, y):
    shp = shape(piece, rotation)
    out = list(rows)
    for dx, dy in shp.cells:
        out[y + dy] |= 1 << (x + dx)
    return tuple(out)


def candidate_payloads(rows, piece) -> list[dict]:
    """One payload per dense candidate (tag = dense index), with the running best after it."""
    best = None
    out = []
    for j, cid in enumerate(candidate_ids(piece)):
        rotation, x = decode_candidate(cid)
        y = drop_y(rows, piece, rotation, x)
        p = {"tag": j, "candidate_id": cid, "rotation": rotation, "x": x, "legal": y is not None, "y": y if y is not None else 0}
        if y is not None:
            merged = merged_rows(rows, piece, rotation, x, y)
            keep = compaction.keep_mask(merged)
            ranks = compaction.inclusive_prefix(keep)
            cleared, lines = lock_and_clear(rows, piece, rotation, x, y)
            a, q, u = features(cleared)
            sc = policy.score_profile((a, q, u), lines, 0)
            p.update({"merged_rows": list(merged), "full_rows": [r for r in range(20) if merged[r] == compaction.FULL],
                      "keep": [int(k) for k in keep], "ranks": ranks, "cleared_rows": list(cleared), "lines": lines,
                      "A": a, "Q": q, "U": u, "score": sc})
            if best is None or sc > best["score"] or (sc == best["score"] and cid < best["candidate_id"]):
                best = {"candidate_id": cid, "score": sc, "y": y, "tag": j}
        else:
            p.update({"merged_rows": None, "full_rows": [], "keep": None, "ranks": None, "cleared_rows": None, "lines": 0,
                      "A": None, "Q": None, "U": None, "score": 0})
        p["best_after"] = dict(best) if best else None
        out.append(p)
    return out


def corpus():
    return [json.loads(l) for l in CORPUS.read_text().splitlines() if l.strip()]


def pick_normal_search():
    for rec in corpus():
        rows, piece = tuple(rec["rows"]), rec["piece"]
        if len(candidate_ids(piece)) != 34:
            continue
        pay = candidate_payloads(rows, piece)
        legal = [p for p in pay if p["legal"]]
        if len(legal) < 30 or not any(p["lines"] >= 1 for p in legal):
            continue
        changes = sum(1 for i, p in enumerate(pay) if p["best_after"] and (i == 0 or pay[i - 1]["best_after"] != p["best_after"]))
        scores = sorted((p["score"] for p in legal), reverse=True)
        if changes >= 3 and scores[0] > scores[1]:
            return rec, pay, {"rule": "first corpus_d1 state in id order with N = 34, >= 30 legal candidates, a line-clearing candidate, "
                                     ">= 3 running-best updates and a unique winner", "best_updates": changes}
    raise SystemExit("no normal-search fixture found")


def pick_last_candidate_wins():
    for rec in corpus():
        if rec.get("category") != "last_candidate_winner":
            continue
        rows, piece = tuple(rec["rows"]), rec["piece"]
        pay = candidate_payloads(rows, piece)
        legal = [p for p in pay if p["legal"]]
        if not legal or not pay[-1]["legal"]:
            continue
        scores = sorted((p["score"] for p in legal), reverse=True)
        if pay[-1]["best_after"]["candidate_id"] == pay[-1]["candidate_id"] and scores[0] > scores[1]:
            return rec, pay, {"rule": "first corpus_d1 state of category last_candidate_winner whose unique winner is the final dense candidate"}
    raise SystemExit("no last-candidate-wins fixture found")


def header(scenario: str, backend_top: str, native_key: str, fixture: dict, extra: dict) -> dict:
    return {"schema": "a2-trace-v1", "backend": "verilator-native", "top": backend_top, "native_key": native_key,
            "source_sha256": source_closure_sha256(), "toolchain_id": toolchain_identity(), "configuration_id": A2.id,
            "stage_manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(), "scenario": scenario,
            "sampling": "handshakes pre-edge; registers post-edge", "timing_projection": None, "fixture": fixture,
            "bank_names": [s["name"] for s in json.loads(MANIFEST.read_text())["stages"]],
            "stage_groups": json.loads(MANIFEST.read_text())["stage_groups"], **extra}


def run_core_story(scenario: str, rec: dict, pay: list[dict], selection: dict, out_path: Path, jobs: int) -> dict:
    exe = build_harness("tetris_core", "rtl/files_core.f", "sim/trace_main.cpp", params=A2.params(), jobs=jobs, quiet=True,
                        waivers=WARNING_WAIVERS, extra_flags=PUBLIC)
    nkey = native_identity(A2.params(), "rtl/files_core.f", driver="sim/trace_main.cpp", top="tetris_core",
                           flags=__import__("tools.build_native", fromlist=["NATIVE_FLAGS"]).NATIVE_FLAGS + PUBLIC)["native_key"]
    rows, piece = tuple(rec["rows"]), rec["piece"]
    work = ROOT / "build" / "traces"
    work.mkdir(parents=True, exist_ok=True)
    req = work / f"{scenario}.req"
    req.write_text(f"{piece} 0 " + " ".join(str(w) for w in board_words(rows)) + "\n")
    raw = work / f"{scenario}.jsonl"
    proc = subprocess.run([str(exe), f"+requests={req}", f"+out={raw}"], cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout, proc.stderr)
        raise SystemExit(f"trace harness failed for {scenario}")
    cycles = [json.loads(l) for l in raw.read_text().splitlines() if l.strip()]
    resp_line = [l for l in proc.stdout.splitlines() if l.startswith("request 0:")][0].split()
    response = {"error": int(resp_line[3]), "no_move": int(resp_line[5]), "rotation": int(resp_line[7]), "x": int(resp_line[9]),
                "y": int(resp_line[11]), "score": int(resp_line[13]), "cycles": int(resp_line[15])}
    oracle = policy.best_move(rows, piece, 0)
    doc = header(scenario, "tetris_core", nkey, {"corpus": str(CORPUS.relative_to(ROOT)), "state_id": rec["id"], "category": rec.get("category"),
                                                 "selection": selection, "label": "demonstration fixture from the development corpus, not a held-out sample"},
                 {"scenario_kind": "production search (m_ready constant 1; the pipeline never stalls)"})
    doc["requests"] = [{"request": 0, "rows": list(rows), "piece": piece, "heights": column_heights(rows), "candidate_count": len(pay),
                        "oracle": {"rotation": oracle["rotation"], "x": oracle["x"], "y": oracle["y"], "score": oracle["score"],
                                   "candidate_id": oracle["candidate_id"], "no_move": False} if oracle else {"no_move": True},
                        "response": response, "candidates": pay}]
    doc["cycles"] = cycles
    doc["events"] = events_of(cycles)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    return doc


def events_of(cycles: list[dict]) -> list[dict]:
    ev = []
    for c in cycles:
        if c.get("req_accept"):
            ev.append({"cycle": c["cycle"], "kind": "request_accepted"})
        if c.get("s"):
            ev.append({"cycle": c["cycle"], "kind": "candidate_accepted", "tag": c["s"]["tag"], "id": c["s"]["id"], "last": c["s"]["last"]})
        if c.get("m") and (c["m"].get("consumed", 1)):
            ev.append({"cycle": c["cycle"], "kind": "candidate_retired", "tag": c["m"]["tag"], "id": c["m"]["id"], "legal": c["m"]["legal"],
                       "score": c["m"]["score"], "last": c["m"]["last"]})
        if c.get("best_changed"):
            ev.append({"cycle": c["cycle"], "kind": "best_changed", "best": c["best"]})
        if c.get("rst"):
            ev.append({"cycle": c["cycle"], "kind": "reset"})
        if c.get("m_ready") == 0:
            ev.append({"cycle": c["cycle"], "kind": "output_blocked"})
        if c.get("rsp_valid_pre"):
            ev.append({"cycle": c["cycle"], "kind": "response_consumed"})
    return ev


def run_stall_reset(out_path: Path, jobs: int) -> dict:
    from tools.a2_vectors import write_vectors
    vec = ROOT / "build" / "a2_vectors" / "trace_ctx7_seed2024.txt"
    write_vectors(vec, 7, 2024, 0)          # contexts 0..6 = pieces I O T S Z J L on one mixed board; context 2 (T) has 34 candidates
    context = 2
    exe = build_harness("candidate_pipe", "rtl/files_candidate_pipe.f", "sim/pipe_trace_main.cpp", jobs=jobs, quiet=True,
                        waivers=["-Wall"], extra_flags=PUBLIC)
    from tools.build_native import NATIVE_FLAGS
    nkey = native_identity({}, "rtl/files_candidate_pipe.f", driver="sim/pipe_trace_main.cpp", top="candidate_pipe", flags=NATIVE_FLAGS + PUBLIC)["native_key"]
    raw = ROOT / "build" / "traces" / "stall-reset.jsonl"
    raw.parent.mkdir(parents=True, exist_ok=True)
    args = [str(exe), f"+vectors={vec}", f"+out={raw}", f"+context={context}", "+stall_at=8", "+stall_len=9", "+reset_at=6"]
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout, proc.stderr)
        raise SystemExit("stall/reset trace harness failed")
    # the context: first C line of the vector file
    ctx_line = [l for l in vec.read_text().splitlines() if l.startswith("C ")][context].split()
    board = int(ctx_line[1], 16)
    rows = tuple((board >> (10 * r)) & 0x3FF for r in range(20))
    piece = int(ctx_line[3])
    pay = candidate_payloads(rows, piece)
    cycles = [json.loads(l) for l in raw.read_text().splitlines() if l.strip()]
    doc = header("stall-reset", "candidate_pipe", nkey,
                 {"vectors": str(vec.relative_to(ROOT)), "context": context, "label": "verification scenario on the standalone candidate interface "
                  "(a blocked m_ready and a reset with occupied stages); the production search never blocks its output"},
                 {"scenario_kind": "verification (standalone candidate_pipe harness)", "story": {"stall_at": 8, "stall_len": 9, "reset_at": 6, "note": "after stall_at acceptances m_ready drops; the elastic pipeline keeps advancing until P22 holds a token, then freezes for stall_len edges; the output is released for reset_at edges and reset is pulsed with stages occupied; a few more candidates follow and drain"}})
    doc["requests"] = [{"request": 0, "rows": list(rows), "piece": piece, "heights": column_heights(rows), "candidate_count": len(pay),
                        "oracle": None, "response": None, "candidates": pay}]
    doc["cycles"] = cycles
    doc["events"] = events_of(cycles)
    out_path.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", choices=["normal-search", "last-candidate-wins", "stall-reset", "all"], default="all")
    ap.add_argument("--jobs", type=int, default=2)
    args = ap.parse_args()
    TRACES.mkdir(parents=True, exist_ok=True)
    stories = ["normal-search", "last-candidate-wins", "stall-reset"] if args.story == "all" else [args.story]
    for s in stories:
        out = TRACES / f"a2_{s.replace('-', '_')}.json"
        if s == "normal-search":
            rec, pay, sel = pick_normal_search()
            doc = run_core_story(s, rec, pay, sel, out, args.jobs)
        elif s == "last-candidate-wins":
            rec, pay, sel = pick_last_candidate_wins()
            doc = run_core_story(s, rec, pay, sel, out, args.jobs)
        else:
            doc = run_stall_reset(out, args.jobs)
        n_ev = {}
        for e in doc["events"]:
            n_ev[e["kind"]] = n_ev.get(e["kind"], 0) + 1
        fx = doc["fixture"]
        print(f"{s}: {len(doc['cycles'])} cycles, {doc['requests'][0]['candidate_count']} candidates, events {n_ev}"
              + (f", state {fx['state_id']} ({fx.get('category')})" if "state_id" in fx else "")
              + (f", response {doc['requests'][0]['response']}" if doc["requests"][0]["response"] else "") + f" -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
