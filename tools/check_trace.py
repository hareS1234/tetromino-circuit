#!/usr/bin/env python3
"""Validate a2-trace-v1 files against their own consistency rules and the reference payloads (U18).

    python tools/check_trace.py [results/traces/a2_*.json]

Checks per trace: header (schema, manifest hash, source hash reported), token conservation (every
accepted tag retires exactly once unless a reset flushed it while in flight), ordering (tags retire in
acceptance order), movement (a token in bank i under advance is in bank i+1 next cycle), stall
stability (no bank changes while advance is low), reset flush (no valid bank after a reset edge),
retired values (legal, y, score, id) against the literal-descent payload of the same tag, the
compactor's RTL keep bits / inclusive ranks / cleared board against the payload where sampled, the
running best against the reference running best, the final best against the oracle decision and the
public response (production traces), and the response cycle count against the trace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.identity import source_closure_sha256  # noqa: E402

MANIFEST = ROOT / "architecture" / "a2_stages.json"


def check_trace(path: Path) -> tuple[int, int, list[str]]:
    doc = json.loads(path.read_text())
    problems = []
    ok = total = 0

    def chk(cond, msg):
        nonlocal ok, total
        total += 1
        if cond:
            ok += 1
        else:
            problems.append(msg)

    chk(doc.get("schema") == "a2-trace-v1", "schema")
    chk(doc.get("stage_manifest_sha256") == hashlib.sha256(MANIFEST.read_bytes()).hexdigest(), "stage manifest hash differs from architecture/a2_stages.json")
    chk(len(doc.get("bank_names", [])) == 23 and doc.get("sampling") == "handshakes pre-edge; registers post-edge", "bank names / sampling statement")
    if doc.get("source_sha256") != source_closure_sha256():
        print(f"  note: {path.name} was exported from source {doc.get('source_sha256', '')[:12]} (current {source_closure_sha256()[:12]})")
    cycles = doc["cycles"]
    req = doc["requests"][0]
    payload = {p["tag"]: p for p in req["candidates"]}
    production = doc.get("top") == "tetris_core"
    accepted, retired = [], []
    flushed = set()
    prev = None
    best_seen = []
    for c in cycles:
        banks = c["banks"]
        chk(len(banks) == 23, f"cycle {c['cycle']}: {len(banks)} banks")
        if c["rst"]:
            chk(all(b is None for b in banks), f"cycle {c['cycle']}: reset edge left valid banks")
            if prev is not None:
                flushed.update(b["tag"] for b in prev["banks"] if b)
        if c["s"]:
            accepted.append(c["s"]["tag"])
            chk(c["s"]["tag"] in payload and payload[c["s"]["tag"]]["candidate_id"] == c["s"]["id"], f"cycle {c['cycle']}: accepted tag/id not in the payloads")
            chk(c["s"]["last"] == int(c["s"]["tag"] == len(payload) - 1) or not production, f"cycle {c['cycle']}: last flag on tag {c['s']['tag']}")
        m = c["m"]
        if m and m.get("consumed", 1):
            retired.append(m["tag"])
            p = payload.get(m["tag"])
            chk(p is not None, f"cycle {c['cycle']}: retired unknown tag {m['tag']}")
            if p:
                chk(m["legal"] == int(p["legal"]) and m["id"] == p["candidate_id"], f"cycle {c['cycle']}: tag {m['tag']} legal/id {m['legal']}/{m['id']} vs payload")
                if p["legal"]:
                    chk(m["y"] == p["y"] and m["score"] == p["score"], f"cycle {c['cycle']}: tag {m['tag']} y/score {m['y']}/{m['score']} vs payload {p['y']}/{p['score']}")
                else:
                    chk(m["y"] == 0 and m["score"] == 0, f"cycle {c['cycle']}: illegal tag {m['tag']} carries non-canonical y/score")
        if prev is not None and not c["rst"]:
            if not prev_advance_of(prev, c):
                chk(banks == prev["banks"], f"cycle {c['cycle']}: banks changed while advance was low")
            else:
                for i in range(22):
                    if prev["banks"][i] is not None:
                        chk(banks[i + 1] is not None and banks[i + 1]["tag"] == prev["banks"][i]["tag"],
                            f"cycle {c['cycle']}: token {prev['banks'][i]['tag']} did not move from bank {i} to {i + 1}")
                if prev["banks"][22] is not None:
                    # the token sitting in P22 after the previous edge is the one visible (pre-edge) and consumed on this edge
                    chk(bool(m) and m["tag"] == prev["banks"][22]["tag"] and m.get("consumed", 1),
                        f"cycle {c['cycle']}: token in P22 did not retire on the advance")
        # compactor samples against the payload
        if c.get("p9") and c["p9"]["tag"] in payload and payload[c["p9"]["tag"]]["legal"]:
            p = payload[c["p9"]["tag"]]
            keep_bits = sum(k << i for i, k in enumerate(p["keep"]))
            chk(c["p9"]["keep"] == keep_bits and c["p9"]["ranks"] == p["ranks"], f"cycle {c['cycle']}: P9 keep/ranks of tag {c['p9']['tag']} differ from the reference")
        if c.get("p12") and c["p12"]["tag"] in payload and payload[c["p12"]["tag"]]["legal"]:
            p = payload[c["p12"]["tag"]]
            board = int(c["p12"]["board"], 16)
            rows = [(board >> (10 * r)) & 0x3FF for r in range(20)]
            chk(rows == p["cleared_rows"], f"cycle {c['cycle']}: P12 cleared board of tag {c['p12']['tag']} differs from the reference")
        if production and c.get("best_changed") and c["best"]["valid"] and retired:
            b = payload[retired[-1]]["best_after"]
            chk(b is not None and (c["best"]["score"], c["best"]["id"], c["best"]["y"]) == (b["score"], b["candidate_id"], b["y"]),
                f"cycle {c['cycle']}: running best {c['best']} differs from the reference running best {b}")
            best_seen.append(c["best"])
        prev = c
    # conservation and order
    if production:
        chk(accepted == list(range(len(payload))), f"accepted tags {accepted[:5]}… are not the dense order 0..N-1")
        chk(retired == accepted, "retired tags differ from accepted tags (conservation/order)")
    else:
        chk(sorted(set(retired) | flushed) == sorted(accepted) and len(retired) == len(set(retired)),
            f"conservation: accepted {len(accepted)}, retired {len(retired)}, flushed {len(flushed)}")
        chk(retired == sorted(retired), "retired tags out of order")
        chk(any(not c["advance"] and not c["rst"] and c.get("m") for c in cycles), "no frozen stall cycle with an unconsumed output")
        chk(any(c["rst"] for c in cycles[3:]), "no reset with occupied stages")
    if production:
        oracle, resp = req["oracle"], req["response"]
        final = [c["best"] for c in cycles if c.get("m")][-1] if any(c.get("m") for c in cycles) else None
        chk(final is not None and final["valid"] == 1 and final["id"] == oracle["candidate_id"] and final["score"] == oracle["score"], "final best differs from the oracle decision")
        chk((resp["rotation"], resp["x"], resp["y"], resp["score"], resp["no_move"]) == (oracle["rotation"], oracle["x"], oracle["y"], oracle["score"], 0),
            "public response differs from the oracle decision")
        acc = [c["cycle"] for c in cycles if c.get("req_accept")]
        rsp = [c["cycle"] for c in cycles if c.get("rsp_valid_pre") == 0 and c.get("rsp_valid") == 1]
        chk(len(acc) == 1 and rsp and rsp[0] - acc[0] == resp["cycles"], f"response cycles {resp['cycles']} vs trace {rsp[0] - acc[0] if rsp and acc else None}")
        chk(len(best_seen) >= 1, "no running-best update recorded")
        n = len(payload)
        chk(resp["cycles"] == n + 29, f"D(N) = {resp['cycles']} != N + 29 = {n + 29}")
    return ok, total, problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("traces", nargs="*", default=[str(p) for p in sorted((ROOT / "results" / "traces").glob("a2_*.json"))])
    args = ap.parse_args()
    bad = 0
    for t in args.traces:
        path = ROOT / t if not Path(t).is_absolute() else Path(t)
        ok, total, problems = check_trace(path)
        print(f"CHECK trace_{path.stem} {ok}/{total}")
        for p in problems[:12]:
            print("  -", p)
        bad += bool(problems)
    return 1 if bad else 0


def prev_advance_of(prev: dict, cur: dict) -> bool:
    """The advance that produced `cur`'s registers is the one sampled pre-edge in `cur` itself."""
    return bool(cur["advance"])


if __name__ == "__main__":
    raise SystemExit(main())
