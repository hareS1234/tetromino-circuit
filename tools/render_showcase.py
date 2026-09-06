#!/usr/bin/env python3
"""Cut a couple of loud, arcade-sized GIFs from the saved RTL games."""
from __future__ import annotations

import argparse
import bisect
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.pieces import PIECE_NAMES, shape  # noqa: E402
from model.replay import read_replay  # noqa: E402

INK = (235, 246, 255)
MUTED = (114, 139, 164)
VOID = (5, 8, 20)
PANEL = (9, 16, 35)
CYAN = (48, 235, 255)
MAGENTA = (255, 61, 181)
LIME = (149, 255, 85)
PIECE_COLORS = {
    0: (36, 220, 255),   # I
    1: (255, 220, 54),   # O
    2: (183, 83, 255),   # T
    3: (80, 235, 115),   # S
    4: (255, 76, 100),   # Z
    5: (72, 116, 255),   # J
    6: (255, 148, 45),   # L
}


def face(size: int, bold: bool = False):
    names = ("DejaVuSansMono-Bold.ttf", "DejaVuSans-Bold.ttf") if bold else ("DejaVuSansMono.ttf", "DejaVuSans.ttf")
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def dim(color, amount=0.42):
    return tuple(round(c * amount) for c in color)


def arcade_backdrop(width: int, height: int, seed: int) -> Image.Image:
    img = Image.new("RGB", (width, height), VOID)
    d = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(1, height - 1)
        d.line((0, y, width, y), fill=(5 + round(7 * t), 8 + round(6 * t), 20 + round(18 * t)))
    rng = random.Random(seed)
    for _ in range(28):
        x = rng.randrange(0, width)
        y = rng.randrange(45, height)
        color = (12, rng.randrange(35, 65), rng.randrange(65, 105))
        length = rng.randrange(25, 110)
        d.line((x, y, min(width, x + length), y), fill=color, width=1)
        d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)
    for y in range(0, height, 4):
        d.line((0, y, width, y), fill=(8, 12, 26))
    return img


def occupancy(grid):
    return [sum((1 << x) for x, value in enumerate(row) if value >= 0) for row in grid]


def replay_states(records):
    """Rebuild piece colours; the replay itself stores the leaner occupied/not-occupied board."""
    grid = [[-1] * 10 for _ in range(20)]
    out = []
    for rec in records:
        if occupancy(grid) != rec["rows_before"]:
            raise ValueError(f"move {rec['move_index']}: coloured board drifted from the replay")
        before = [row[:] for row in grid]
        landed = [row[:] for row in grid]
        for dx, dy in shape(rec["piece_id"], rec["rotation"]).cells:
            landed[rec["y"] + dy][rec["x"] + dx] = rec["piece_id"]
        full = [y for y, row in enumerate(landed) if all(value >= 0 for value in row)]
        after = [row[:] for y, row in enumerate(landed) if y not in full]
        after += [[-1] * 10 for _ in full]
        if occupancy(after) != rec["rows_after"]:
            raise ValueError(f"move {rec['move_index']}: line-clear reconstruction disagrees with the replay")
        out.append({"before": before, "landed": landed, "after": after, "full": full})
        grid = after
    return out


def cell_box(bx, by, cell, x, y, inset=2):
    left = bx + x * cell + inset
    top = by + (19 - y) * cell + inset
    return (left, top, left + cell - 2 * inset - 1, top + cell - 2 * inset - 1)


def neon_cell(draw, box, color, hot=False):
    draw.rounded_rectangle(box, radius=3, fill=dim(color, 0.82), outline=color, width=1)
    x0, y0, x1, y1 = box
    draw.line((x0 + 3, y0 + 2, x1 - 3, y0 + 2), fill=INK if hot else tuple(min(255, c + 45) for c in color), width=1)
    draw.line((x0 + 2, y0 + 3, x0 + 2, y1 - 3), fill=tuple(min(255, c + 25) for c in color), width=1)


def playfield(img, grid, bx, by, cell, active=(), ghost=(), flash_rows=(), border=CYAN):
    width, height = 10 * cell, 20 * cell
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.rounded_rectangle((bx - 7, by - 7, bx + width + 6, by + height + 6), radius=9, outline=(*border, 185), width=5)
    for x, y, color in active:
        if 0 <= x < 10 and 0 <= y < 20:
            gd.rectangle(cell_box(bx, by, cell, x, y, 0), fill=(*color, 170))
    glow = glow.filter(ImageFilter.GaussianBlur(8))
    img.paste(glow, (0, 0), glow)

    d = ImageDraw.Draw(img)
    d.rounded_rectangle((bx - 5, by - 5, bx + width + 4, by + height + 4), radius=8, fill=(4, 8, 19), outline=border, width=2)
    for y in range(20):
        for x in range(10):
            box = cell_box(bx, by, cell, x, y, 1)
            d.rectangle(box, fill=(8, 14, 29), outline=(19, 34, 54))
            if grid[y][x] >= 0:
                neon_cell(d, cell_box(bx, by, cell, x, y), PIECE_COLORS[grid[y][x]])
    for x, y in ghost:
        if 0 <= x < 10 and 0 <= y < 20 and grid[y][x] < 0:
            d.rounded_rectangle(cell_box(bx, by, cell, x, y, 4), radius=2, outline=(105, 132, 155), width=1)
    for x, y, color in active:
        if 0 <= x < 10 and 0 <= y < 20:
            neon_cell(d, cell_box(bx, by, cell, x, y), color, hot=True)
    for y in flash_rows:
        top = by + (19 - y) * cell
        d.rectangle((bx, top, bx + width - 1, top + cell - 1), fill=INK)
        d.line((bx, top + cell // 2, bx + width, top + cell // 2), fill=MAGENTA, width=3)


def text(draw, xy, value, font, fill=INK, anchor=None):
    draw.text(xy, value, font=font, fill=fill, anchor=anchor)


def led_strip(draw, x, y, active, width=23):
    for i in range(width):
        color = CYAN if i == active else ((35, 89, 105) if i < active else (25, 37, 53))
        draw.rounded_rectangle((x + i * 12, y, x + i * 12 + 7, y + 7), radius=2, fill=color)


def preview_piece(draw, piece, x, y, cell=14):
    cells = shape(piece, 0).cells
    min_x = min(dx for dx, _ in cells)
    min_y = min(dy for _, dy in cells)
    for dx, dy in cells:
        box = (x + (dx - min_x) * cell, y + (2 - (dy - min_y)) * cell,
               x + (dx - min_x + 1) * cell - 3, y + (3 - (dy - min_y)) * cell - 3)
        neon_cell(draw, box, PIECE_COLORS[piece])


def single_frame(base, state, rec, falling_y, phase, frame_no, source_name):
    img = base.copy()
    d = ImageDraw.Draw(img)
    bx, by, cell = 34, 71, 25
    piece_cells = shape(rec["piece_id"], rec["rotation"]).cells
    ghost = [(rec["x"] + dx, rec["y"] + dy) for dx, dy in piece_cells]
    active = [(rec["x"] + dx, falling_y + dy, PIECE_COLORS[rec["piece_id"]]) for dx, dy in piece_cells]
    grid = state["landed"] if phase == "flash" else state["before"]
    if phase == "settled":
        grid, active, ghost = state["after"], [], []
    playfield(img, grid, bx, by, cell, active, ghost, state["full"] if phase == "flash" else ())

    text(d, (34, 19), "TETROMINO CIRCUIT", face(25, True), CYAN)
    text(d, (350, 28), "RTL ARCADE FEED", face(14, True), MAGENTA)
    text(d, (350, 52), "A2 // 23-STAGE PIPELINE", face(20, True))
    text(d, (350, 83), "LIVE REPLAY", face(11, True), VOID)
    d.rounded_rectangle((465, 80, 567, 99), radius=8, fill=LIME)
    text(d, (516, 90), "VERIFIED", face(11, True), VOID, "mm")

    move = rec["move_index"] + 1
    lines = rec["cumulative_lines"] if phase == "settled" else rec["cumulative_lines"] - rec["lines"]
    labels = [
        ("MOVE", f"{move:03d} / 250", CYAN),
        ("LINES", f"{lines:03d}", LIME),
        ("DECISION", f"{rec.get('cycles', 0):02d} clocks", MAGENTA),
        ("SCORE", f"{rec.get('score', 0):+d}", INK),
    ]
    y = 126
    for label, value, color in labels:
        text(d, (350, y), label, face(11, True), MUTED)
        text(d, (350, y + 16), value, face(22, True), color)
        y += 59

    text(d, (350, 377), "NOW", face(10, True), MUTED)
    text(d, (350, 395), PIECE_NAMES[rec["piece_id"]], face(25, True), PIECE_COLORS[rec["piece_id"]])
    text(d, (475, 377), "NEXT", face(10, True), MUTED)
    preview_piece(d, rec["next_piece_id"], 476, 398)

    event = "HARD DROP"
    event_color = CYAN
    if phase == "flash":
        event = ("TRIPLE LINE!" if rec["lines"] == 3 else f"{rec['lines']} LINE COMBO!")
        event_color = MAGENTA
    elif phase == "settled" and rec["lines"]:
        event = f"+{rec['lines']} // BOARD COMPACTED"
        event_color = LIME
    d.rounded_rectangle((339, 466, 688, 514), radius=10, fill=(12, 24, 48), outline=dim(event_color, 0.8), width=2)
    text(d, (514, 490), event, face(18, True), event_color, "mm")

    text(d, (350, 538), "PIPE OCCUPANCY", face(10, True), MUTED)
    led_strip(d, 350, 559, frame_no % 23)
    text(d, (34, 590), f"seed 2000  //  moves 66–93  //  {source_name}", face(10), MUTED)
    return img


def save_gif(frames, durations, out, comment):
    out.parent.mkdir(parents=True, exist_ok=True)
    paletted = [frame.quantize(colors=112, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for frame in frames]
    paletted[0].save(out, save_all=True, append_images=paletted[1:], duration=durations,
                     loop=0, optimize=True, disposal=2, comment=comment.encode())


def render_single(replay_path: Path, out: Path, start=65, stop=93):
    meta, records, _ = read_replay(replay_path)
    if meta.get("backend") != "rtl-native" or meta.get("arch") != 2:
        raise ValueError("the single-board reel expects an A2 RTL replay")
    states = replay_states(records)
    base = arcade_backdrop(720, 620, 7)
    frames, durations = [], []
    first = records[start]
    intro = single_frame(base, states[start], first, 20, "settled", 0, replay_path.name)
    d = ImageDraw.Draw(intro)
    d.rounded_rectangle((57, 250, 260, 345), radius=12, fill=(5, 10, 24), outline=MAGENTA, width=2)
    text(d, (158, 277), "HIGHLIGHT REEL", face(16, True), MAGENTA, "mm")
    text(d, (158, 310), "TRIPLE INCOMING", face(14, True), INK, "mm")
    text(d, (158, 332), "REAL RTL MOVES", face(10, True), MUTED, "mm")
    frames.append(intro)
    durations.append(850)

    frame_no = 1
    for index in range(start, min(stop, len(records))):
        rec, state = records[index], states[index]
        piece_cells = shape(rec["piece_id"], rec["rotation"]).cells
        spawn = 20 - max(dy for _, dy in piece_cells)
        for progress in (0.18, 0.46, 0.74, 1.0):
            eased = 1 - (1 - progress) ** 2
            falling_y = round(spawn + (rec["y"] - spawn) * eased)
            frames.append(single_frame(base, state, rec, falling_y, "drop", frame_no, replay_path.name))
            durations.append(48 if progress < 1 else 68)
            frame_no += 1
        if rec["lines"]:
            for _ in range(2):
                frames.append(single_frame(base, state, rec, rec["y"], "flash", frame_no, replay_path.name))
                durations.append(86)
                frame_no += 1
            frames.append(single_frame(base, state, rec, rec["y"], "settled", frame_no, replay_path.name))
            durations.append(105)
            frame_no += 1
    frames.append(single_frame(base, states[stop - 1], records[stop - 1], records[stop - 1]["y"], "settled", frame_no, replay_path.name))
    durations.append(900)
    save_gif(frames, durations, out, f"source={replay_path.relative_to(ROOT)}; renderer=tools/render_showcase.py")
    return len(frames), out.stat().st_size


def race_frame(base, loaded, states, cumulative, tick, previous_counts, horizon):
    img = base.copy()
    d = ImageDraw.Draw(img)
    text(d, (26, 18), "ONE CLOCK BUDGET. THREE ENGINES.", face(25, True), CYAN)
    text(d, (894, 25), f"{tick:06,d} / {horizon:,} CYCLES", face(16, True), MAGENTA, "ra")
    d.rounded_rectangle((26, 57, 894, 68), radius=5, fill=(18, 31, 52))
    d.rounded_rectangle((26, 57, 26 + round(868 * tick / horizon), 68), radius=5, fill=CYAN)

    titles = (("A0", "SERIAL FSM", MAGENTA), ("A1", "CACHED BOARD", (255, 181, 54)), ("A2", "PIPELINE", LIME))
    counts = []
    for k, ((meta, records, _), state_list, times) in enumerate(zip(loaded, states, cumulative)):
        n = bisect.bisect_right(times, tick)
        counts.append(n)
        panel_x = 20 + k * 300
        color = titles[k][2]
        d.rounded_rectangle((panel_x, 84, panel_x + 280, 456), radius=12, fill=(7, 13, 29), outline=dim(color, 0.7), width=2)
        text(d, (panel_x + 14, 97), titles[k][0], face(25, True), color)
        text(d, (panel_x + 62, 104), titles[k][1], face(12, True), INK)
        grid = state_list[n - 1]["after"] if n else [[-1] * 10 for _ in range(20)]
        gained = 0
        if n:
            old_lines = records[previous_counts[k] - 1]["cumulative_lines"] if previous_counts[k] else 0
            gained = records[n - 1]["cumulative_lines"] - old_lines
        border = INK if gained else color
        playfield(img, grid, panel_x + 13, 137, 14, border=border)

        stats_x = panel_x + 169
        current_lines = records[n - 1]["cumulative_lines"] if n else 0
        median = sorted(r["cycles"] for r in records)[len(records) // 2]
        text(d, (stats_x, 144), "PIECES", face(9, True), MUTED)
        text(d, (stats_x, 158), f"{n:03d}", face(25, True), color)
        text(d, (stats_x, 199), "LINES", face(9, True), MUTED)
        text(d, (stats_x, 213), f"{current_lines:03d}", face(25, True), INK)
        text(d, (stats_x, 254), "MEDIAN", face(9, True), MUTED)
        text(d, (stats_x, 269), f"{median:,}", face(17, True), color)
        text(d, (stats_x, 291), "clocks/move", face(8), MUTED)
        d.rounded_rectangle((stats_x, 330, panel_x + 264, 340), radius=4, fill=(20, 33, 51))
        d.rounded_rectangle((stats_x, 330, stats_x + round(95 * n / len(records)), 340), radius=4, fill=color)
        if gained:
            text(d, (stats_x, 362), f"+{gained} LINE{'S' if gained != 1 else ''}", face(11, True), INK)
        if n == len(records):
            d.rounded_rectangle((stats_x - 4, 391, panel_x + 267, 423), radius=7, fill=color)
            text(d, (panel_x + 216, 407), "CAP HIT", face(11, True), VOID, "mm")
        else:
            text(d, (stats_x, 399), "RUNNING", face(10, True), color)

    text(d, (460, 480), "same seed  //  same exact P0 policy  //  real RTL decision counts", face(12, True), INK, "mm")
    text(d, (460, 505), f"At {horizon:,} clocks: A0 {counts[0]} pieces  •  A1 {counts[1]}  •  A2 {counts[2]}", face(13, True), MAGENTA, "mm")
    return img, counts


def render_race(replay_paths, out: Path, frame_count=120):
    loaded = [read_replay(path) for path in replay_paths]
    if len(loaded) != 3 or [m.get("arch") for m, _, _ in loaded] != [0, 1, 2]:
        raise ValueError("the race expects A0, A1, and A2 replays, in that order")
    first_meta = loaded[0][0]
    for meta, records, _ in loaded[1:]:
        if (meta["seed"], meta["stream_sha256"], meta["precision"], len(records)) != (
                first_meta["seed"], first_meta["stream_sha256"], first_meta["precision"], len(loaded[0][1])):
            raise ValueError("race replays must use the same stream, precision, and piece cap")
    states = [replay_states(records) for _, records, _ in loaded]
    cumulative = []
    for _, records, _ in loaded:
        total, times = 0, []
        for rec in records:
            total += rec["cycles"]
            times.append(total)
        cumulative.append(times)
    horizon = cumulative[2][-1]
    base = arcade_backdrop(920, 530, 19)
    frames, durations, previous = [], [], [0, 0, 0]
    for i in range(frame_count + 1):
        tick = round(horizon * i / frame_count)
        frame, previous = race_frame(base, loaded, states, cumulative, tick, previous, horizon)
        frames.append(frame)
        durations.append(52)
    durations[0] = 700
    durations[-1] = 1200
    sources = ",".join(str(path.relative_to(ROOT)) for path in replay_paths)
    save_gif(frames, durations, out, f"sources={sources}; renderer=tools/render_showcase.py")
    return len(frames), out.stat().st_size


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--single-replay", default="results/replays/a2-cache-d1-p0-l1_seed2000_cap250.jsonl")
    ap.add_argument("--race-replays", nargs=3, default=[
        "results/replays/a0-bitmap-d1-p0-l1_seed2000_cap250.jsonl",
        "results/replays/a1-cache-d1-p0-l1_seed2000_cap250.jsonl",
        "results/replays/a2-cache-d1-p0-l1_seed2000_cap250.jsonl",
    ])
    ap.add_argument("--single-out", default="assets/showcase_neon.gif")
    ap.add_argument("--race-out", default="assets/showcase_race.gif")
    args = ap.parse_args()

    n, size = render_single(ROOT / args.single_replay, ROOT / args.single_out)
    print(f"showcase: neon reel {n} frames, {size / 1e6:.2f} MB -> {args.single_out}")
    n, size = render_race([ROOT / path for path in args.race_replays], ROOT / args.race_out)
    print(f"showcase: architecture race {n} frames, {size / 1e6:.2f} MB -> {args.race_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
