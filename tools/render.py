#!/usr/bin/env python3
"""Turn a replay into a GIF, showing each landed piece just before its clear takes effect."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.pieces import PIECE_NAMES, shape  # noqa: E402
from model.replay import read_replay  # noqa: E402

CELL = 24
BOARD_W, BOARD_H = 10 * CELL, 20 * CELL
SIDEBAR = 280
BG = (18, 18, 24)
GRID = (40, 40, 52)
BLOCK = (150, 160, 175)
PIECE_COLORS = {0: (80, 200, 230), 1: (240, 210, 70), 2: (170, 90, 210), 3: (90, 210, 110),
                4: (230, 80, 80), 5: (80, 110, 230), 6: (240, 150, 60)}
TEXT = (235, 235, 240)
DIM = (150, 150, 160)


def font(size=16):
    for name in ("DejaVuSansMono.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_board(draw, ox, oy, rows, cell=CELL, highlight=None, color=BLOCK):
    for y in range(20):
        for x in range(10):
            sx = ox + x * cell
            sy = oy + (19 - y) * cell
            occupied = (rows[y] >> x) & 1
            if highlight and (x, y) in highlight:
                fill = color
            elif occupied:
                fill = BLOCK
            else:
                fill = BG
            draw.rectangle([sx, sy, sx + cell - 1, sy + cell - 1], fill=fill, outline=GRID)


def landed_cells(rec):
    shp = shape(rec["piece_id"], rec["rotation"])
    return {(rec["x"] + dx, rec["y"] + dy) for dx, dy in shp.cells}


def frame_for(meta, rec, total_moves, big_font, small_font):
    img = Image.new("RGB", (BOARD_W + SIDEBAR + 30, BOARD_H + 20), BG)
    d = ImageDraw.Draw(img)
    draw_board(d, 10, 10, rec["rows_before"], highlight=landed_cells(rec), color=PIECE_COLORS[rec["piece_id"]])
    x0 = BOARD_W + 30
    lines = [
        (f"{meta.get('backend', '?')}", big_font, TEXT),
        (label_for(meta), small_font, DIM),
        ("", small_font, DIM),
        (f"move   {rec['move_index'] + 1}/{total_moves}", small_font, TEXT),
        (f"piece  {PIECE_NAMES[rec['piece_id']]}", small_font, TEXT),
        (f"place  rot {rec['rotation']} x {rec['x']} y {rec['y']}", small_font, TEXT),
        (f"lines  {rec['cumulative_lines']}  (+{rec['lines']})", small_font, TEXT),
        (f"score  {rec.get('score')}", small_font, TEXT),
    ]
    if "cycles" in rec:
        lines.append((f"cycles {rec['cycles']}  (RTL sim)", small_font, TEXT))
    f = rec.get("features") or {}
    lines.append((f"A {f.get('A')}  Q {f.get('Q')}  U {f.get('U')}", small_font, DIM))
    lines.append(("", small_font, DIM))
    lines.append((f"seed {meta.get('seed')}  spec {meta.get('spec')}", small_font, DIM))
    y = 14
    for text, fnt, col in lines:
        d.text((x0, y), text, font=fnt, fill=col)
        y += 24 if fnt is big_font else 20
    return img


def label_for(meta):
    parts = [meta.get("policy", "?")]
    if meta.get("arch") is not None:
        parts.append(f"A{meta['arch']}")
        parts.append("cache" if meta.get("board_repr") == 1 else "bitmap")
        parts.append(f"L{meta.get('lanes')}")
    parts.append(f"D{meta.get('depth')}")
    parts.append(f"P{meta.get('precision')} {meta.get('precision_name', '')}".strip())
    return " ".join(parts)


def render(replay_path: Path, out: Path, duration_ms: int = 120, max_frames: int | None = None, png: Path | None = None):
    meta, records, terminal = read_replay(replay_path)
    big_font, small_font = font(18), font(15)
    frames = []
    step = 1
    if max_frames and len(records) > max_frames:
        step = -(-len(records) // max_frames)
    for i, rec in enumerate(records):
        if i % step == 0 or i == len(records) - 1:
            frames.append(frame_for(meta, rec, len(records), big_font, small_font))
    if not frames:
        raise SystemExit("replay has no moves to render")
    # final frame: board after the last move with the terminal reason
    last = records[-1]
    img = Image.new("RGB", frames[0].size, BG)
    d = ImageDraw.Draw(img)
    draw_board(d, 10, 10, last["rows_after"])
    d.text((BOARD_W + 30, 14), f"{meta.get('backend')}", font=big_font, fill=TEXT)
    d.text((BOARD_W + 30, 40), label_for(meta), font=small_font, fill=DIM)
    d.text((BOARD_W + 30, 80), f"{terminal['reason']}", font=big_font, fill=(240, 120, 90))
    d.text((BOARD_W + 30, 110), f"{terminal['pieces_locked']} pieces, {terminal['lines']} lines", font=small_font, fill=TEXT)
    frames.append(img)
    out.parent.mkdir(parents=True, exist_ok=True)
    durations = [duration_ms] * (len(frames) - 1) + [duration_ms * 15]
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    if png:
        img.save(png)
    return len(frames), out.stat().st_size


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--png", default=None, help="also save the final frame as PNG")
    ap.add_argument("--duration", type=int, default=120, help="ms per frame")
    ap.add_argument("--max-frames", type=int, default=None)
    args = ap.parse_args()
    n, size = render(ROOT / args.replay if not Path(args.replay).is_absolute() else Path(args.replay),
                     ROOT / args.out if not Path(args.out).is_absolute() else Path(args.out),
                     args.duration, args.max_frames, Path(args.png) if args.png else None)
    print(f"rendered {n} frames, {size / 1e6:.2f} MB -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
