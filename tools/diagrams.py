#!/usr/bin/env python3
"""Generate the static SVG diagrams of docs/design.md and docs/design_a2.md (U18 step 5, guide §12.3).

    python tools/diagrams.py            # writes assets/diagrams/*.svg

Diagrams (plain SVG, neutral palette, text labels — no measurement is invented: residency numbers come
from results/stage_cycles_*.json, latencies from architecture/a2_stages.json):
  architecture.svg   request → latch/cache → search (A0 serial | A1 lanes | A2 pipeline) → reduction → response
  fsm_a0_a1.svg      the candidate evaluator FSM (shared by A0 and A1) with measured state residency per candidate
  a2_pipeline.svg    the 23 banks in six groups, the immutable context beside the per-token payload
  compaction.svg     a compaction example with non-adjacent full rows: keep bits, inclusive ranks, preserved order
  lanes.svg          four-lane dense-index ownership (N = 17 → [5,4,4,4]) and the deterministic REDUCE order
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "assets" / "diagrams"
INK, MUTED, LINE, PANEL, ACC, BEST = "#222", "#666", "#999", "#f2f2f2", "#d95f02", "#1b9e77"


def svg(w, h, body, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="t">\n'
            f'<title id="t">{title}</title>\n<style>text{{font-family:system-ui,Segoe UI,Roboto,sans-serif;font-size:12px;fill:{INK}}}'
            f'.m{{fill:{MUTED};font-size:11px}}.s{{font-size:10px}}.b{{font-weight:bold}}.mono{{font-family:ui-monospace,Menlo,monospace}}</style>\n'
            f'<rect width="{w}" height="{h}" fill="white"/>\n{body}</svg>\n')


def box(x, y, w, h, label, sub=None, fill=PANEL, stroke=LINE, dash=None, cls=""):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    s = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{fill}" stroke="{stroke}"{d}/>\n'
    s += f'<text x="{x + w / 2}" y="{y + (h / 2 - 2 if sub else h / 2 + 4)}" text-anchor="middle" class="b {cls}">{label}</text>\n'
    if sub:
        s += f'<text x="{x + w / 2}" y="{y + h / 2 + 12}" text-anchor="middle" class="m">{sub}</text>\n'
    return s


def arrow(x1, y1, x2, y2, label=None, cls="m"):
    s = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{INK}" stroke-width="1.2" marker-end="url(#a)"/>\n'
    if label:
        s += f'<text x="{(x1 + x2) / 2}" y="{min(y1, y2) - 4}" text-anchor="middle" class="{cls}">{label}</text>\n'
    return s


MARKER = f'<defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="{INK}"/></marker></defs>\n'


def architecture():
    b = MARKER
    b += f'<text x="20" y="26" class="b">tetris_core: request → cache → search → deterministic reduction → response</text>\n'
    b += f'<text x="20" y="44" class="m">The context (board, heights, piece) is latched once per request and is immutable during the search; every architecture uses the same reduction rule and protocol.</text>\n'
    ym = 170                     # centre line
    b += box(20, ym - 30, 110, 60, "request", "board, piece, next")
    b += f'<text x="150" y="{ym - 36}" text-anchor="middle" class="s m">req_valid / req_ready</text>\n'
    b += arrow(130, ym, 170, ym)
    b += box(170, ym - 30, 140, 60, "latch + cache", "board_q, heights_q (1 cycle)")
    b += f'<text x="340" y="{ym - 36}" text-anchor="middle" class="s m">search_start</text>\n'
    b += arrow(310, ym, 370, ym)
    b += box(370, 70, 260, 56, "A0 / A1: candidate_eval lanes", "one candidate at a time; lane k owns ids[k::LANES]", dash="4,3")
    b += box(370, ym - 28, 260, 56, "A2: search_pipeline", "dense enumeration → 23-bank candidate_pipe (II = 1)")
    b += box(370, 270, 260, 56, "A1 depth two: search_depth2", "root × next-piece leaves (v1, historical)", dash="4,3")
    b += f'<line x1="330" y1="98" x2="330" y2="298" stroke="{LINE}" stroke-dasharray="3,3"/>\n'
    b += arrow(330, 98, 370, 98); b += arrow(330, 298, 370, 298)
    b += arrow(630, 98, 680, ym - 8); b += arrow(630, ym, 680, ym); b += arrow(630, 298, 680, ym + 8)
    b += box(680, ym - 30, 130, 60, "reduction", "highest score, lower id on ties")
    b += f'<text x="830" y="{ym - 36}" text-anchor="middle" class="s m">rsp_valid / rsp_ready</text>\n'
    b += arrow(810, ym, 850, ym)
    b += box(850, ym - 30, 110, 60, "response", "rot, x, y, score, cycles")
    b += f'<text x="20" y="360" class="m">A2: best_reducer folds retired tokens in acceptance order and the core’s REDUCE state reads lane slot 0. A1 with L lanes: REDUCE visits one lane per cycle (L cycles).</text>\n'
    b += f'<text x="20" y="376" class="m">Solid = the architecture measured in v2 (a2-cache-d1-p0-l1); dashed = the v1 architectures kept as exact comparison points (X0–X4) and the historical depth-two study.</text>\n'
    return svg(980, 390, b, "tetris_core architecture: request, cache, search alternatives, reduction, response")


def fsm():
    a0 = json.loads((ROOT / "results" / "stage_cycles_a0_repr0_p0.json").read_text())["profiles"]["legal_no_clear"]
    a1 = json.loads((ROOT / "results" / "stage_cycles_a1_repr1_p0.json").read_text())["profiles"]["legal_no_clear"]
    states = [("DECODE", "shape ROM"), ("DROP", "landing"), ("MERGE", "lock cells"), ("CLEAR", "compactor"), ("FEAT", "A, Q, U"), ("SCORE", "76L−51A−36Q−18U"), ("FINISH", "local best")]
    keys = {"DECODE": ["DECODE"], "DROP": ["DROP_START", "DROP_WAIT"], "MERGE": ["MERGE_START", "MERGE_WAIT"], "CLEAR": ["CLEAR_START", "CLEAR_WAIT"],
            "FEAT": ["FEAT_START", "FEAT_WAIT"], "SCORE": ["SCORE_START", "SCORE_WAIT"], "FINISH": ["FINISH"]}
    b = MARKER
    b += f'<text x="20" y="26" class="b">Candidate evaluator FSM (candidate_eval, shared by A0 and A1) — measured cycles per legal candidate without a line clear</text>\n'
    b += f'<text x="20" y="44" class="m">Residency from results/stage_cycles_a0_repr0_p0.json (A0 bitmap) and results/stage_cycles_a1_repr1_p0.json (A1 cache), profile legal_no_clear: totals {a0["total"]} and {a1["total"]} cycles.</text>\n'
    x = 20
    for i, (name, sub) in enumerate(states):
        c0 = sum(a0.get(k, 0) for k in keys[name]); c1 = sum(a1.get(k, 0) for k in keys[name])
        w = 112
        b += box(x, 70, w, 54, name, sub)
        b += f'<text x="{x + w / 2}" y="145" text-anchor="middle" class="mono s">A0 {c0} cyc</text>\n'
        b += f'<text x="{x + w / 2}" y="160" text-anchor="middle" class="mono s">A1 {c1} cyc</text>\n'
        # residency bars (A0 scale)
        b += f'<rect x="{x}" y="170" width="{max(2, w * c0 / a0["total"])}" height="8" fill="{MUTED}"/>\n'
        b += f'<rect x="{x}" y="181" width="{max(2, w * c1 / a1["total"])}" height="8" fill="{ACC}"/>\n'
        if i < len(states) - 1:
            b += arrow(x + w, 97, x + w + 18, 97)
        x += w + 18
    b += f'<text x="20" y="210" class="m">Bars: each state’s share of the candidate’s cycles (grey A0, orange A1; a full-width bar would be 100 % of that architecture’s total).</text>\n'
    b += f'<text x="20" y="226" class="m">A0 spends {a0["FEAT_WAIT"]} of {a0["total"]} cycles scanning features cell by cell and {a0["DROP_WAIT"]} dropping; A1 keeps the {a1["CLEAR_WAIT"]}-cycle compactor as {round(100 * a1["CLEAR_WAIT"] / a1["total"])} % of its {a1["total"]}.</text>\n'
    b += f'<text x="20" y="242" class="m">A2 removes the FSM: every state becomes one or more pipeline banks and a new candidate enters every cycle (docs/design_a2.md).</text>\n'
    return svg(940, 258, b, "A0/A1 candidate evaluator FSM with measured state residency")


def a2_pipeline():
    m = json.loads((ROOT / "architecture" / "a2_stages.json").read_text())
    groups = [("landing", 0, 1), ("merge", 2, 3), ("ranks", 4, 9), ("select", 10, 12), ("features", 13, 19), ("score", 20, 22)]
    b = MARKER
    b += f'<text x="20" y="26" class="b">A2 candidate pipeline: {m["banks"]} banks, one global advance, visible latency {m["latency"]["visible_edges"]}, transfer {m["latency"]["transfer_edges"]}, II {m["latency"]["candidate_ii"]}</text>\n'
    b += f'<rect x="20" y="60" width="150" height="120" rx="4" fill="#e8f0ff" stroke="#557"/>\n'
    b += f'<text x="95" y="80" text-anchor="middle" class="b">immutable context</text>\n'
    b += f'<text x="95" y="104" text-anchor="middle" class="s mono">board_i [200]</text><text x="95" y="120" text-anchor="middle" class="s mono">heights_i [50]</text><text x="95" y="136" text-anchor="middle" class="s mono">piece_i [3]</text>\n'
    b += f'<text x="95" y="158" text-anchor="middle" class="m s">owned by the core</text><text x="95" y="171" text-anchor="middle" class="m s">for the whole search</text>\n'
    x = 200
    for gi, (name, lo, hi) in enumerate(groups):
        n = hi - lo + 1
        w = 26 * n + 8
        b += f'<rect x="{x}" y="60" width="{w}" height="120" rx="4" fill="{PANEL}" stroke="{LINE}"/>\n'
        b += f'<text x="{x + w / 2}" y="{52 if gi % 2 == 0 else 40}" text-anchor="middle" class="m">{name} P{lo}–P{hi}</text>\n'
        for i in range(lo, hi + 1):
            bx = x + 4 + 26 * (i - lo)
            b += f'<rect x="{bx}" y="70" width="22" height="70" fill="white" stroke="{INK}"/>\n'
            b += f'<text x="{bx + 11}" y="110" text-anchor="middle" class="s mono">P{i}</text>\n'
            bits = m["stages"][i]["out_bits"]
            b += f'<text x="{bx + 11}" y="155" text-anchor="middle" class="s m">{bits}b</text>\n'
        x += w + 10
    b += arrow(170, 120, 200, 120)
    notes = ["Each bank register holds one candidate’s private payload (merged board, keep bits, ranks, cleared board, features, score — bit widths under the banks)",
             "plus the metadata legal / y / id / tag / last. advance = !rst && (!valid[22] || m_ready): every bank moves together or none does; s_ready = advance;",
             "a reset clears every valid bit at one edge. search_pipeline issues dense candidates j = 0..N−1 (tag = j), best_reducer folds retirements in order; D(N) = N + 29."]
    for i, t in enumerate(notes):
        b += f'<text x="20" y="{200 + 16 * i}" class="m">{t.replace("&", "&amp;")}</text>\n'
    return svg(max(980, x + 20), 250, b, "A2 grouped pipeline with the immutable context and per-token payload")


def compaction():
    from model import compaction as cp
    rows = [0x3FF, 0x2AB, 0x3FF, 0x155, 0x3FF, 0x0F3, 0x001] + [0] * 13   # full rows 0, 2, 4 (non-adjacent)
    keep = cp.keep_mask(rows)
    ranks = cp.inclusive_prefix(keep)
    out, _cleared = cp.compact_filter(rows)
    b = MARKER
    b += f'<text x="20" y="26" class="b">Stable compaction by inclusive prefix ranks (line_clear_parallel / line_clear_pipe P4–P12)</text>\n'
    b += f'<text x="20" y="44" class="m">Example: rows 0, 2 and 4 are full (non-adjacent). keep[s] = row s is not full; rank[s] = kept rows at or below s (inclusive prefix);</text>\n'
    b += f'<text x="20" y="58" class="m">a kept row s lands in output row rank[s]−1, so survivors keep their order and the top rows are zero-filled.</text>\n'
    cols = ["row s", "content", "keep", "rank", "→ output row"]
    xs = [20, 90, 330, 400, 470]
    for cx, c in zip(xs, cols):
        b += f'<text x="{cx}" y="78" class="b s">{c}</text>\n'
    for s in range(8):
        y = 98 + 22 * s
        r = rows[s]
        cells = "".join(f'<rect x="{90 + 11 * x}" y="{y - 12}" width="10" height="16" fill="{INK if (r >> x) & 1 else "white"}" stroke="{LINE}"/>' for x in range(10))
        full = r == cp.FULL
        b += f'<text x="20" y="{y}" class="mono s">{s}</text>{cells}\n'
        b += f'<text x="{xs[2]}" y="{y}" class="mono s">{int(keep[s])}</text><text x="{xs[3]}" y="{y}" class="mono s">{ranks[s]}</text>\n'
        b += f'<text x="{xs[4]}" y="{y}" class="mono s">{"removed (full)" if full else f"{ranks[s] - 1}"}</text>\n'
    b += f'<text x="20" y="275" class="m">Output rows 0..{sum(keep) - 1} keep the survivors’ order (rows 1, 3, 5, 6, 7 → 0, 1, 2, 3, 4); the top {20 - sum(keep)} rows are zero.</text>\n'
    b += f'<text x="20" y="291" class="m">Selection: match[d][s] = keep[s] ∧ rank[s] = d+1 (one-hot per output row). Reference model/compaction.py; proof formal/compactor (unbounded k-induction).</text>\n'
    # output board picture
    for s in range(8):
        y = 98 + 22 * s
        r = out[s]
        b += "".join(f'<rect x="{620 + 11 * x}" y="{y - 12}" width="10" height="16" fill="{INK if (r >> x) & 1 else "white"}" stroke="{LINE}"/>' for x in range(10)) + "\n"
        b += f'<text x="{740}" y="{y}" class="mono s">out {s}</text>\n'
    b += f'<text x="620" y="78" class="b s">compacted board</text>\n'
    return svg(900, 305, b, "compaction example with non-adjacent full rows, keep bits and inclusive ranks")


def lanes():
    from model.pieces import candidate_ids
    ids = list(candidate_ids(0))   # I piece: 17 dense candidates
    b = MARKER
    b += f'<text x="20" y="26" class="b">Four-lane dense-index ownership and deterministic reduction (a1-cache-d1-p0-l4)</text>\n'
    b += f'<text x="20" y="44" class="m">Piece I, N = 17 dense candidates (ids below). Lane k owns ids[k::4]: sizes [5, 4, 4, 4]. Each lane keeps a local best; REDUCE visits lanes 0..3 in order, one per cycle, with the global tie-break (lower id).</text>\n'
    for k in range(4):
        y = 70 + 40 * k
        owned = ids[k::4]
        b += box(20, y, 90, 30, f"lane {k}", f"{len(owned)} owned", fill=PANEL)
        for j, cid in enumerate(ids):
            x = 130 + 40 * j
            mine = (j % 4) == k
            b += f'<rect x="{x}" y="{y + 4}" width="34" height="22" rx="3" fill="{ACC if mine else "white"}" stroke="{INK if mine else LINE}"/>\n'
            b += f'<text x="{x + 17}" y="{y + 19}" text-anchor="middle" class="s mono" fill="{"white" if mine else MUTED}">{cid}</text>\n'
    b += f'<text x="130" y="240" class="m">dense index j:</text>\n'
    for j in range(len(ids)):
        b += f'<text x="{130 + 40 * j + 17}" y="255" text-anchor="middle" class="s mono m">{j}</text>\n'
    b += box(20, 275, 780, 40, "REDUCE: for rk in 0..3: take lane rk’s best if valid and (score higher, or equal with lower id) — then FINALIZE", None, fill="white", stroke=BEST, dash="6,3")
    b += f'<text x="20" y="335" class="m">Measured: cycles = 45·⌈N/L⌉ + 7 + L when every candidate is legal (docs/lanes.md); the winning lane finished strictly last in 95 of 293 corpus cases, never changing the decision.</text>\n'
    return svg(830, 350, b, "four-lane dense-index assignment and the deterministic reduction order")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in (("architecture", architecture), ("fsm_a0_a1", fsm), ("a2_pipeline", a2_pipeline), ("compaction", compaction), ("lanes", lanes)):
        (OUT / f"{name}.svg").write_text(fn())
        print(f"assets/diagrams/{name}.svg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
