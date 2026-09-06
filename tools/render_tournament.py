#!/usr/bin/env python3
"""Render up to four replays together, synchronized by pieces or recorded RTL cycles."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.pieces import PIECE_NAMES  # noqa: E402
from model.replay import read_replay  # noqa: E402
from tools.render import BG, DIM, PIECE_COLORS, TEXT, draw_board, font, landed_cells  # noqa: E402

CELL = 16
PANEL_W = 10 * CELL + 250
PANEL_H = 20 * CELL + 70


def load_manifest(path: Path | None):
    rows = []
    if path and path.is_file():
        with open(path) as fh:
            rows = list(csv.DictReader(fh))
    return rows


def hardware_label(meta, manifest):
    if meta.get("arch") is None:
        return "software model (no hardware)"
    rows = []
    for row in manifest:
        try:
            same = (int(row["arch"]) == meta["arch"] and int(row["board_repr"]) == meta["board_repr"]
                    and int(row["lanes"]) == meta["lanes"] and int(row["depth"]) == meta["depth"]
                    and int(row["precision"]) == meta["precision"])
        except (KeyError, ValueError):
            continue
        if same and row.get("lut4"):
            rows.append(row)
    if not rows:
        return "LUT4/FF: not measured"
    met = sum(1 for r in rows if r.get("timing_met") == "True")
    return f"LUT4 {rows[0]['lut4']} FF {rows[0]['ff']} (synth); timing met {met}/{len(rows)} seeds @ {rows[0].get('target_mhz')} MHz"


def panel_title(meta):
    if meta.get("arch") is None:
        return f"{meta.get('backend')} {meta.get('policy')}"
    return f"A{meta['arch']} {'cache' if meta['board_repr'] else 'bitmap'} L{meta['lanes']} D{meta['depth']} P{meta['precision']}"


def render(replays, out: Path, manifest_path: Path | None, sync: str, duration_ms: int, max_frames: int | None):
    loaded = [read_replay(p) for p in replays]
    if not 1 <= len(loaded) <= 4:
        raise SystemExit("between one and four replays are required")
    metas = [m for m, _, _ in loaded]
    for m in metas[1:]:
        if m["spec"] != metas[0]["spec"] or m["stream_sha256"] != metas[0]["stream_sha256"] or m["seed"] != metas[0]["seed"]:
            raise SystemExit("replays must share spec, seed and stream hash")
    manifest = load_manifest(manifest_path)
    big, small = font(15), font(13)
    if sync == "cycles":
        for m, recs, _ in loaded:
            if any("cycles" not in r for r in recs):
                raise SystemExit("--sync cycles requires RTL cycle counts on every move")
        totals = []
        for _, recs, _ in loaded:
            acc = 0
            cum = []
            for r in recs:
                acc += r["cycles"]
                cum.append(acc)
            totals.append(cum)
        horizon = max(t[-1] for t in totals)
        n_frames = max_frames or 120
        ticks = [round(horizon * (i + 1) / n_frames) for i in range(n_frames)]
    else:
        longest = max(len(recs) for _, recs, _ in loaded)
        step = 1
        if max_frames and longest > max_frames:
            step = -(-longest // max_frames)
        ticks = list(range(0, longest + 1, step))
        if ticks[-1] != longest:
            ticks.append(longest)

    cols = 2 if len(loaded) > 1 else 1
    rows_n = 2 if len(loaded) > 2 else 1
    frames = []
    for tick in ticks:
        img = Image.new("RGB", (cols * PANEL_W + 10, rows_n * PANEL_H + 40), BG)
        d = ImageDraw.Draw(img)
        mode_label = "piece-synchronised (same n pieces on every board)" if sync == "pieces" else \
            "cycle-synchronised (boards advance by simulated RTL cycles)"
        d.text((10, 8), f"seed {metas[0]['seed']}  {metas[0]['spec']}  {mode_label}", font=small, fill=DIM)
        for k, (meta, recs, term) in enumerate(loaded):
            px = 10 + (k % 2) * PANEL_W
            py = 40 + (k // 2) * PANEL_H
            if sync == "pieces":
                n = min(tick, len(recs))
            else:
                cum = totals[k]
                n = sum(1 for c in cum if c <= tick)
            if n == 0:
                board = [0] * 20
                highlight = None
                color = None
                last = None
            else:
                last = recs[n - 1]
                board = last["rows_after"]
                highlight = landed_cells(last) if last["lines"] == 0 else None
                color = PIECE_COLORS[last["piece_id"]]
            draw_board(d, px, py + 22, board, cell=CELL, highlight=highlight, color=color or TEXT)
            d.text((px, py), panel_title(meta), font=big, fill=TEXT)
            tx = px + 10 * CELL + 10
            ty = py + 22
            info = [(meta.get("policy", "?") + ("" if meta.get("arch") is None else "  RTL simulation"), DIM)]
            lines_so_far = last["cumulative_lines"] if last else 0
            info.append((f"pieces {n}", TEXT))
            info.append((f"lines  {lines_so_far}", TEXT))
            if last and "cycles" in last:
                info.append((f"cycles {last['cycles']} (last decision)", TEXT))
            elif meta.get("arch") is not None:
                info.append(("cycles: n/a", DIM))
            info.append((hardware_label(meta, manifest), DIM))
            if n >= len(recs) and (sync == "pieces" or tick >= totals[k][-1]):
                info.append((term["reason"].upper().replace("_", " "), (240, 120, 90)))
            for text, col in info:
                for chunk in wrap(text, 30):
                    d.text((tx, ty), chunk, font=small, fill=col)
                    ty += 17
        frames.append(img)
    out.parent.mkdir(parents=True, exist_ok=True)
    durations = [duration_ms] * (len(frames) - 1) + [duration_ms * 15]
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    return len(frames), out.stat().st_size


def wrap(text, width):
    words = text.split(" ")
    out, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    out.append(cur)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replays", nargs="+", required=True)
    ap.add_argument("--implementation", default=None, help="results/implementation.csv")
    ap.add_argument("--sync", default="pieces", choices=["pieces", "cycles"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--duration", type=int, default=150)
    ap.add_argument("--max-frames", type=int, default=None)
    args = ap.parse_args()
    n, size = render([ROOT / p for p in args.replays], ROOT / args.out,
                     ROOT / args.implementation if args.implementation else None,
                     args.sync, args.duration, args.max_frames)
    print(f"rendered {n} frames, {size / 1e6:.2f} MB -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
