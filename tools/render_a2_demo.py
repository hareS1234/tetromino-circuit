#!/usr/bin/env python3
"""Render an a2-trace-v1 file into a GitHub-viewable GIF plus first/middle/last PNG frames (U18 step 5-6).

    python tools/render_a2_demo.py --trace results/traces/a2_normal_search.json --gif assets/a2_pipeline.gif
    python tools/render_a2_demo.py --trace results/traces/a2_stall_reset.json --gif assets/a2_stall_reset.gif

Every frame is one clock edge of the real RTL trace: the board with the token currently retiring (or the
newest accepted token) drawn on it, the 23 banks grouped into six functional blocks with the tag of
each occupied bank, the token's reference explanation (full rows, keep bits, inclusive ranks, cleared
board, A/Q/U/L, score), the running best from the RTL (`best` registers) and a timeline with the
handshakes, advance and reset.  State is readable from labels and outlines, not colour alone.  Frames
are not synthetic: the pipeline occupancy, handshakes and best come from the trace records.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GROUPS = [("landing", 0, 1), ("merge", 2, 3), ("ranks", 4, 9), ("select", 10, 12), ("features", 13, 19), ("score", 20, 22)]
ACCENT = "#d95f02"       # selected token
BEST = "#1b9e77"         # current best (double outline)
NEUTRAL = "#4d4d4d"
LIGHT = "#e6e6e6"
PIECE_NAMES = ("I", "O", "T", "S", "Z", "J", "L")


def draw_board(ax, rows, piece_cells=None, full_rows=(), title="", cleared=False):
    ax.set_xlim(-0.2, 10.2)
    ax.set_ylim(-0.2, 20.2)
    ax.set_aspect("equal")
    ax.axis("off")
    for y in range(20):
        for x in range(10):
            filled = (rows[y] >> x) & 1
            ax.add_patch(__import__("matplotlib.patches", fromlist=["Rectangle"]).Rectangle(
                (x, y), 1, 1, facecolor=(NEUTRAL if filled else "white"), edgecolor="#bbbbbb", linewidth=0.4))
    if piece_cells:
        for (x, y) in piece_cells:
            ax.add_patch(__import__("matplotlib.patches", fromlist=["Rectangle"]).Rectangle(
                (x, y), 1, 1, facecolor=ACCENT, edgecolor="black", linewidth=0.8, hatch="//"))
    for r in full_rows:
        ax.add_patch(__import__("matplotlib.patches", fromlist=["Rectangle"]).Rectangle(
            (0, r), 10, 1, facecolor="none", edgecolor="black", linewidth=2.0, linestyle="--"))
    ax.set_title(title, fontsize=8)


def piece_cells_of(payload, piece):
    from model.pieces import shape
    if not payload or not payload["legal"]:
        return None
    shp = shape(piece, payload["rotation"])
    return [(payload["x"] + dx, payload["y"] + dy) for dx, dy in shp.cells]


def render_frame(doc, idx, payload_by_tag, fig, axes):
    import matplotlib.patches as mp
    c = doc["cycles"][idx]
    req = doc["requests"][0]
    rows, piece = req["rows"], req["piece"]
    ax_board, ax_pipe, ax_expl, ax_time = axes
    for ax in axes:
        ax.clear()
    # ---- selected token: the one in P22 after this edge (it retires on the next edge), else the newest
    # token in flight, else none.  Banks are post-edge registers; `m` is the pre-edge retirement of this edge.
    sel_tag = None
    sel_why = ""
    best = c.get("best") or {"valid": 0, "score": 0, "id": -1, "y": 0}      # the standalone pipe harness has no reducer
    if c["banks"][22] is not None:
        sel_tag = c["banks"][22]["tag"]
        sel_why = "in P22, retires next edge"
    else:
        occupied = [b["tag"] for b in c["banks"] if b]
        if occupied:
            sel_tag = max(occupied)
            sel_why = "newest token in flight"
        elif c.get("m"):
            sel_tag = c["m"]["tag"]
            sel_why = "retired on this edge"
        elif best["valid"] and any(cc.get("m") for cc in doc["cycles"][:idx + 1]):
            bp = next((p for p in payload_by_tag.values() if p["candidate_id"] == best["id"]), None)
            if bp is not None:
                sel_tag = bp["tag"]
                sel_why = "search complete: final best (winner)"
    pl = payload_by_tag.get(sel_tag) if sel_tag is not None else None
    cells = piece_cells_of(pl, piece)
    title = "original board (immutable context)"
    if pl is not None:
        title = f"id {pl['candidate_id']} tag {pl['tag']}: rot {pl['rotation']} x {pl['x']} " + (f"y {pl['y']} legal" if pl["legal"] else "ILLEGAL") + f"\n{sel_why}"
    draw_board(ax_board, rows, cells, pl["full_rows"] if pl and pl["legal"] else (), title)
    # ---- pipeline: six groups ----
    ax_pipe.set_xlim(0, 23.5)
    ax_pipe.set_ylim(-1.6, 3.4)
    ax_pipe.axis("off")
    frozen = (not c["advance"]) and not c["rst"]
    for gi, (gname, lo, hi) in enumerate(GROUPS):
        ax_pipe.add_patch(mp.Rectangle((lo, 0.2), hi - lo + 1, 1.6, facecolor=LIGHT, edgecolor="#999999", linewidth=0.6))
        ax_pipe.text(lo + (hi - lo + 1) / 2, 2.05 + (0.5 if gi % 2 else 0.0), f"{gname} P{lo}–P{hi}", ha="center", va="bottom", fontsize=6.5, color=NEUTRAL)
    for i, b in enumerate(c["banks"]):
        if b is None:
            continue
        is_sel = sel_tag is not None and b["tag"] == sel_tag
        is_best = best["valid"] and payload_by_tag.get(b["tag"], {}).get("candidate_id") == best["id"]
        face = ACCENT if is_sel else "white"
        ax_pipe.add_patch(mp.Rectangle((i + 0.1, 0.4), 0.8, 1.2, facecolor=face, edgecolor="black", linewidth=1.8 if is_sel else 0.8))
        if is_best:
            ax_pipe.add_patch(mp.Rectangle((i + 0.02, 0.32), 0.96, 1.36, facecolor="none", edgecolor=BEST, linewidth=1.6, linestyle="--"))
        ax_pipe.text(i + 0.5, 1.0, str(b["tag"]), ha="center", va="center", fontsize=7, color="white" if is_sel else "black")
        if b["last"]:
            ax_pipe.text(i + 0.5, 0.15, "last", ha="center", va="top", fontsize=6, color=NEUTRAL)
    for i in range(23):
        ax_pipe.text(i + 0.5, -0.35, f"P{i}", ha="center", va="top", fontsize=5.5, color="#888888")
    state = "RESET: all banks cleared" if c["rst"] else ("STALL: advance = 0, tokens frozen (output blocked)" if frozen else "advance = 1")
    ax_pipe.text(0, -1.1, state, fontsize=8, color="black" if not frozen else ACCENT, weight="bold" if (frozen or c["rst"]) else "normal")
    occ = sum(1 for b in c["banks"] if b)
    ax_pipe.text(23.4, -1.1, f"occupancy {occ}/23", ha="right", fontsize=8, color=NEUTRAL)
    ax_pipe.set_title(f"candidate pipeline — 23 banks, one global advance ({doc['scenario']})", fontsize=9)
    # ---- explanation ----
    ax_expl.axis("off")
    ax_expl.set_xlim(0, 10)
    ax_expl.set_ylim(0, 10)
    lines = []
    if pl is not None and pl["legal"]:
        keep = "".join("k" if k else "·" for k in pl["keep"])
        ranks = pl["ranks"]
        lines += [f"token {pl['tag']} (id {pl['candidate_id']}) — reference explanation",
                  f"full rows: {pl['full_rows'] if pl['full_rows'] else 'none'}   L = {pl['lines']}",
                  f"keep (row 0..19): {keep}",
                  "ranks 0..9 : " + " ".join(f"{r:2d}" for r in ranks[:10]),
                  "ranks 10..19: " + " ".join(f"{r:2d}" for r in ranks[10:]),
                  f"after clear: A {pl['A']}  Q {pl['Q']}  U {pl['U']}",
                  f"score = 76·{pl['lines']} − 51·{pl['A']} − 36·{pl['Q']}",
                  f"        − 18·{pl['U']} = {pl['score']}"]
    rtl = c.get("m")
    if rtl:
        rp = payload_by_tag.get(rtl["tag"])
        okm = rp is not None and ((not rp["legal"] and rtl["legal"] == 0) or (rp["legal"] and rtl["score"] == rp["score"] and rtl["y"] == rp["y"]))
        lines.append(f"retired this edge: tag {rtl['tag']} legal {rtl['legal']} y {rtl['y']} score {rtl['score']} " + ("✓ = reference" if okm else "✗ MISMATCH"))
    if pl is not None and pl["legal"]:
        pass
    elif pl is not None:
        lines += [f"token {pl['tag']} (id {pl['candidate_id']}): illegal placement — canonical legal 0, y 0, score 0"]
    else:
        lines += ["no token selected"]
    if "best" not in c:
        lines.append("standalone candidate_pipe harness: no reducer (verification scenario)")
        if c.get("phase"):
            lines.append(f"story phase: {c['phase']}" + ("  — m_ready = 0 (output blocked)" if c.get("m_ready") == 0 else ""))
    elif best["valid"]:
        bp = next((p for p in payload_by_tag.values() if p["candidate_id"] == best["id"]), None)
        lines.append(f"running best (RTL): id {best['id']} score {best['score']} y {best['y']}" + (f"  (tag {bp['tag']})" if bp else ""))
    else:
        lines.append("running best (RTL): none yet")
    if c.get("best_changed"):
        lines.append("▶ best updated on this edge")
    if req.get("response") and any(cc.get("rsp_valid") for cc in doc["cycles"][:idx + 1]):
        r = req["response"]
        lines.append(f"public response: rot {r['rotation']} x {r['x']} y {r['y']} score {r['score']} ({r['cycles']} cycles = N + 29)")
    for k, t in enumerate(lines):
        ax_expl.text(0.05, 9.7 - 0.62 * k, t, fontsize=6.6, family="monospace", va="top",
                     color=(BEST if t.startswith("running best") or t.startswith("▶") else "black"))
    # cleared board thumbnail (reference) for the selected token
    if pl is not None and pl["legal"]:
        inset = ax_expl.inset_axes([0.02, 0.0, 0.30, 0.27])
        draw_board(inset, pl["cleared_rows"], None, (), f"cleared board, tag {pl['tag']} (L={pl['lines']})")
    # ---- timeline ----
    ax_time.axis("off")
    n = len(doc["cycles"])
    ax_time.set_xlim(0, n + 1)
    ax_time.set_ylim(0, 4)
    for j, cc in enumerate(doc["cycles"]):
        x = j + 1
        if cc.get("s"):
            ax_time.plot([x], [3], marker="^", color=NEUTRAL, markersize=3)
        if cc.get("m") and cc["m"].get("consumed", 1):
            ax_time.plot([x], [2], marker="v", color=NEUTRAL, markersize=3)
        if not cc["advance"] and not cc["rst"]:
            ax_time.plot([x], [1], marker="s", color=ACCENT, markersize=3)
        if cc["rst"]:
            ax_time.plot([x], [1], marker="x", color="black", markersize=4)
    ax_time.axvline(idx + 1, color=ACCENT, linewidth=1.2)
    ax_time.text(0, 3, "accept ▲", fontsize=6.5, va="center", ha="right")
    ax_time.text(0, 2, "retire ▼", fontsize=6.5, va="center", ha="right")
    ax_time.text(0, 1, "stall ■ / reset ✕", fontsize=6.5, va="center", ha="right")
    ax_time.text(n + 1, 0.2, f"cycle {c['cycle']} of {n}", fontsize=8, ha="right")
    fig.suptitle(f"A2 candidate pipeline, real RTL trace — {doc['scenario']} ({doc.get('scenario_kind', '')}); piece {PIECE_NAMES[piece]}, "
                 f"{req['candidate_count']} candidates", fontsize=10)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", default="results/traces/a2_normal_search.json")
    ap.add_argument("--gif", default="assets/a2_pipeline.gif")
    ap.add_argument("--frames-dir", default=None, help="directory for first/middle/last PNG frames (default results/traces/frames/<scenario>)")
    ap.add_argument("--fps", type=float, default=3.0)
    ap.add_argument("--scale", type=float, default=1.0)
    args = ap.parse_args()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    doc = json.loads((ROOT / args.trace).read_text())
    payload_by_tag = {p["tag"]: p for p in doc["requests"][0]["candidates"]}
    fig = plt.figure(figsize=(12.5 * args.scale, 7.2 * args.scale), dpi=80)
    gs = fig.add_gridspec(2, 3, height_ratios=[5, 1], width_ratios=[1.0, 2.6, 1.9], hspace=0.25, wspace=0.08)
    ax_board = fig.add_subplot(gs[0, 0])
    ax_pipe = fig.add_subplot(gs[0, 1])
    ax_expl = fig.add_subplot(gs[0, 2])
    ax_time = fig.add_subplot(gs[1, :])
    axes = (ax_board, ax_pipe, ax_expl, ax_time)
    frames = []
    n = len(doc["cycles"])
    frames_dir = ROOT / (args.frames_dir or f"results/traces/frames/{Path(args.trace).stem}")
    frames_dir.mkdir(parents=True, exist_ok=True)
    keep = {0: "first", n // 2: "middle", n - 1: "last"}
    for i in range(n):
        render_frame(doc, i, payload_by_tag, fig, axes)
        fig.canvas.draw()
        img = Image.frombuffer("RGBA", fig.canvas.get_width_height(), fig.canvas.buffer_rgba(), "raw", "RGBA", 0, 1).convert("P", palette=Image.ADAPTIVE, colors=128)
        frames.append(img)
        if i in keep:
            fig.savefig(frames_dir / f"{keep[i]}_cycle{doc['cycles'][i]['cycle']}.png", dpi=80)
    out = ROOT / args.gif
    out.parent.mkdir(parents=True, exist_ok=True)
    duration = int(1000 / args.fps)
    durations = [duration] * len(frames)
    durations[-1] = duration * 4          # hold the final frame
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    size = out.stat().st_size
    print(f"{args.trace}: {n} frames -> {out.relative_to(ROOT)} ({size / 1024:.0f} KB), stills in {frames_dir.relative_to(ROOT)}")
    meta = {"schema": "a2-render-v1", "trace": args.trace, "gif": str(out.relative_to(ROOT)), "frames": n, "fps": args.fps,
            "trace_source_sha256": doc["source_sha256"], "scenario": doc["scenario"], "stills": sorted(p.name for p in frames_dir.glob("*.png"))}
    (frames_dir / "render.json").write_text(json.dumps(meta, indent=1) + "\n")
    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
