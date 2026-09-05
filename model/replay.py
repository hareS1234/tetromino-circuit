"""Game orchestration and the replay JSONL schema shared by every backend."""
from __future__ import annotations

import json
import random
import subprocess
import time
from pathlib import Path

from . import fast, lookahead, policy
from .board import EMPTY_BOARD, validate_board
from .game import drop_y, lock_and_clear
from .numeric import profile
from .streams import SPEC_ID

TERMINAL_TOP_OUT = "top_out"
TERMINAL_CAP = "cap_reached"


def git_commit(root: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
        if out.returncode == 0:
            commit = out.stdout.strip()
            dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
            return commit + ("-dirty" if dirty else "")
    except OSError:
        pass
    return "unknown"


def make_decider(policy_name: str, depth: int, precision: int, stream_seed: int, engine: str = "fast"):
    """Return decide(rows, piece, next_piece) -> record|None for a software policy."""
    prof = profile(precision)
    if policy_name == "heuristic":
        if depth == 1:
            if engine == "fast":
                return lambda rows, piece, nxt: fast.best_move_fast(rows, piece, precision)
            return lambda rows, piece, nxt: policy.best_move(rows, piece, precision)
        if depth == 2:
            if engine == "fast":
                return lambda rows, piece, nxt: fast.best_move_depth2_fast(rows, piece, nxt, precision)
            return lambda rows, piece, nxt: lookahead.best_move_depth2(rows, piece, nxt, precision)
        raise ValueError("depth must be 1 or 2")
    if depth != 1:
        raise ValueError(f"policy {policy_name} supports depth 1 only")
    if policy_name == "random_legal":
        rng = random.Random(policy.random_seed_for_stream(stream_seed))
        if engine == "fast":
            return lambda rows, piece, nxt: fast.random_legal_fast(rows, piece, rng, precision)
        return lambda rows, piece, nxt: policy.random_legal(rows, piece, rng, precision)
    if policy_name == "lowest_stack":
        if engine == "fast":
            return lambda rows, piece, nxt: fast.lowest_stack_fast(rows, piece, precision)
        return lambda rows, piece, nxt: policy.lowest_stack(rows, piece, precision)
    raise ValueError(f"unknown policy {policy_name}")


def metadata(*, backend, policy_name, seed, stream_doc, max_pieces, depth=1, precision=0,
             arch=None, board_repr=None, lanes=None, root: Path | None = None, extra=None):
    prof = profile(precision)
    meta = {
        "type": "meta", "spec": SPEC_ID, "backend": backend, "policy": policy_name,
        "arch": arch, "board_repr": board_repr, "lanes": lanes, "depth": depth,
        "precision": precision, "precision_name": prof.name, "coefficients": list(prof.coefficients),
        "seed": seed, "stream_sha256": stream_doc["sha256"], "max_pieces": max_pieces,
        "commit": git_commit(root) if root else "unknown", "implementation_manifest": None,
        "created_unix": int(time.time()),
    }
    if extra:
        meta.update(extra)
    return meta


def play_game(decide, stream_doc: dict, max_pieces: int, *, depth: int = 1, on_move=None):
    """Run a game.  decide(rows, piece, next_piece) returns a record with rotation/x/y (and
    optional 'cycles').  Returns (records, terminal_record)."""
    pieces = stream_doc["pieces"]
    if max_pieces + 1 > len(pieces):
        raise ValueError("stream too short for cap plus preview")
    rows = EMPTY_BOARD
    records = []
    total_lines = 0
    for i in range(max_pieces):
        piece = pieces[i]
        nxt = pieces[i + 1] if depth == 2 else None
        rec = decide(rows, piece, nxt)
        if rec is None:
            terminal = {"type": "terminal", "reason": TERMINAL_TOP_OUT, "pieces_locked": i, "lines": total_lines}
            return records, terminal
        rotation, x, y = rec["rotation"], rec["x"], rec["y"]
        expected_y = drop_y(rows, piece, rotation, x)
        if expected_y is None or expected_y != y:
            raise RuntimeError(f"move {i}: backend landing y={y} disagrees with oracle {expected_y}")
        new_rows, lines = lock_and_clear(rows, piece, rotation, x, y)
        if "next_rows" in rec and tuple(rec["next_rows"]) != new_rows:
            raise RuntimeError(f"move {i}: backend post-clear board disagrees with oracle")
        validate_board(new_rows, normalized=True)
        total_lines += lines
        out = {
            "type": "move", "move_index": i, "piece_id": piece, "next_piece_id": pieces[i + 1],
            "rows_before": list(rows), "rotation": rotation, "x": x, "y": y,
            "candidate_id": 10 * rotation + x, "rows_after": list(new_rows), "lines": lines,
            "cumulative_lines": total_lines, "score": rec.get("score"),
            "features": {"A": rec.get("A"), "Q": rec.get("Q"), "U": rec.get("U")},
        }
        for key in ("cycles", "surviving"):
            if key in rec:
                out[key] = rec[key]
        records.append(out)
        if on_move:
            on_move(out)
        rows = new_rows
    terminal = {"type": "terminal", "reason": TERMINAL_CAP, "pieces_locked": max_pieces, "lines": total_lines}
    return records, terminal


def write_replay(path: Path, meta: dict, records, terminal) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(json.dumps(meta) + "\n")
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
        fh.write(json.dumps(terminal) + "\n")


def read_replay(path: Path):
    meta = None
    records = []
    terminal = None
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            doc = json.loads(line)
            if doc.get("type") == "meta":
                meta = doc
            elif doc.get("type") == "terminal":
                terminal = doc
            else:
                records.append(doc)
    if meta is None or terminal is None:
        raise ValueError(f"incomplete replay {path}")
    return meta, records, terminal


def replay_decisions(records):
    """Volatile-free view of a replay used for determinism comparisons."""
    return [(r["move_index"], r["piece_id"], r["rotation"], r["x"], r["y"], r["lines"]) for r in records]
