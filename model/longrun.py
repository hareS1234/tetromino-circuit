"""Summary-mode game execution with checkpoints for long quality runs (U15, guide §9.5-9.6).

`play_game` (model/replay.py) keeps one record per move; a 50,000-piece game does not need
them.  `play_summary` keeps only the current board, the stream index, the totals, a chained
trajectory hash and — for the random policy — the RNG state, writes a checkpoint every
`checkpoint_every` locked pieces and at completion, and resumes from a checkpoint whose identity
matches exactly.  The decisions are the same ones `play_game` makes (same deciders), which the
unit tests check on short games move for move (identical trajectory hash, final board, totals and
terminal reason).

Event-time definitions (guide §9.5): duration T = successfully locked pieces before the first
top-out decision; `event_observed = True` when the top-out was seen (T = 0 for an immediate
top-out), `False` when the game was stopped by the cap C (duration C).  A crash is neither: the
caller records a failed job.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
from pathlib import Path

from . import fast, policy
from .board import EMPTY_BOARD, validate_board
from .game import drop_y, lock_and_clear

CHECKPOINT_SCHEMA = "quality-checkpoint-v1"
TERMINAL_TOP_OUT = "top_out"
TERMINAL_CAP = "cap_reached"


class SoftwarePolicy:
    """A depth-one software policy with an inspectable RNG (random_legal) for checkpointing."""

    def __init__(self, name: str, precision: int, stream_seed: int, engine: str = "fast"):
        if name not in ("heuristic", "random_legal", "lowest_stack"):
            raise ValueError(f"unknown policy {name}")
        self.name, self.precision, self.engine = name, precision, engine
        self.rng = random.Random(policy.random_seed_for_stream(stream_seed)) if name == "random_legal" else None

    def decide(self, rows, piece):
        if self.name == "heuristic":
            return fast.best_move_fast(rows, piece, self.precision) if self.engine == "fast" else policy.best_move(rows, piece, self.precision)
        if self.name == "random_legal":
            return fast.random_legal_fast(rows, piece, self.rng, self.precision) if self.engine == "fast" \
                else policy.random_legal(rows, piece, self.rng, self.precision)
        return fast.lowest_stack_fast(rows, piece, self.precision) if self.engine == "fast" else policy.lowest_stack(rows, piece, self.precision)

    def rng_state(self):
        if self.rng is None:
            return None
        version, state, gauss = self.rng.getstate()
        return {"version": version, "state": list(state), "gauss_next": gauss}

    def set_rng_state(self, doc):
        if self.rng is None or doc is None:
            return
        self.rng.setstate((doc["version"], tuple(doc["state"]), doc["gauss_next"]))


def chain_hash(previous: str, move_index: int, piece: int, candidate_id: int, y: int, lines: int) -> str:
    """Trajectory hash chained one move at a time (serialisable in a checkpoint)."""
    return hashlib.sha256(f"{previous}|{move_index}|{piece}|{candidate_id}|{y}|{lines}".encode()).hexdigest()


def trajectory_hash_of_records(records) -> str:
    h = "genesis"
    for r in records:
        h = chain_hash(h, r["move_index"], r["piece_id"], r["candidate_id"], r["y"], r["lines"])
    return h


def atomic_write_json(path: Path, doc: dict, keep_previous: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(doc, sort_keys=True) + "\n")
    if keep_previous and path.is_file():
        os.replace(path, path.with_suffix(path.suffix + ".prev"))
    os.replace(tmp, path)


def load_checkpoint(path: Path, identity: dict) -> dict | None:
    """The checkpoint at `path` (or its retained predecessor) whose identity matches exactly; else None."""
    for candidate in (path, path.with_suffix(path.suffix + ".prev")):
        if not candidate.is_file():
            continue
        try:
            doc = json.loads(candidate.read_text())
        except ValueError:
            continue                      # corrupt (interrupted write): try the retained predecessor
        if doc.get("schema") != CHECKPOINT_SCHEMA or doc.get("identity") != identity:
            return None                   # another job's checkpoint: never resume from it
        if doc.get("status") == "complete":
            return None                   # the game is over; its record is the result
        return doc
    return None


def play_summary(pol: SoftwarePolicy, pieces, cap: int, *, identity: dict | None = None, checkpoint_path: Path | None = None,
                 checkpoint_every: int = 1000, resume: bool = True, stop_after: int | None = None, on_progress=None) -> dict:
    """Run one depth-one game in summary mode.

    identity: dict written into every checkpoint; a checkpoint resumes only when its identity equals this one.
    stop_after: raise InterruptedError after that many locked pieces in this call (used by the resume tests).
    Returns {'pieces_locked', 'lines', 'reason', 'event_observed', 'duration', 'trajectory_sha256', 'resumed_from', 'checkpoints'}.
    """
    if cap + 1 > len(pieces):
        raise ValueError("stream too short for cap plus preview")
    identity = dict(identity or {})
    rows, start, lines, traj = EMPTY_BOARD, 0, 0, "genesis"
    resumed_from = None
    if checkpoint_path is not None and resume:
        ck = load_checkpoint(checkpoint_path, identity)
        if ck is not None:
            rows, start, lines, traj = tuple(ck["rows"]), ck["piece_index"], ck["lines"], ck["trajectory_sha256"]
            validate_board(rows, normalized=True)
            pol.set_rng_state(ck.get("rng_state"))
            resumed_from = start
    checkpoints = 0

    def write(index, rows_, lines_, traj_, status, terminal=None):
        nonlocal checkpoints
        if checkpoint_path is None:
            return
        doc = {"schema": CHECKPOINT_SCHEMA, "identity": identity, "status": status, "piece_index": index, "rows": list(rows_),
               "lines": lines_, "pieces_locked": index, "trajectory_sha256": traj_, "rng_state": pol.rng_state(), "cap": cap,
               "terminal": terminal}
        atomic_write_json(checkpoint_path, doc)
        checkpoints += 1

    locked_here = 0
    i = start
    while i < cap:
        piece = pieces[i]
        rec = pol.decide(rows, piece)
        if rec is None:
            terminal = {"pieces_locked": i, "lines": lines, "reason": TERMINAL_TOP_OUT, "event_observed": True, "duration": i,
                        "trajectory_sha256": traj, "resumed_from": resumed_from}
            write(i, rows, lines, traj, "complete", terminal)
            terminal["checkpoints"] = checkpoints
            return terminal
        rotation, x, y = rec["rotation"], rec["x"], rec["y"]
        expected_y = drop_y(rows, piece, rotation, x)
        if expected_y is None or expected_y != y:
            raise RuntimeError(f"move {i}: backend landing y={y} disagrees with oracle {expected_y}")
        new_rows, cleared = lock_and_clear(rows, piece, rotation, x, y)
        if "next_rows" in rec and tuple(rec["next_rows"]) != new_rows:
            raise RuntimeError(f"move {i}: backend post-clear board disagrees with oracle")
        lines += cleared
        traj = chain_hash(traj, i, piece, 10 * rotation + x, y, cleared)
        rows = new_rows
        i += 1
        locked_here += 1
        if checkpoint_every and i % checkpoint_every == 0 and i < cap:
            write(i, rows, lines, traj, "running")
            if on_progress:
                on_progress(i, lines)
        if stop_after is not None and locked_here >= stop_after and i < cap:
            raise InterruptedError(f"stopped after {locked_here} locked pieces at index {i}")
    terminal = {"pieces_locked": cap, "lines": lines, "reason": TERMINAL_CAP, "event_observed": False, "duration": cap,
                "trajectory_sha256": traj, "resumed_from": resumed_from}
    write(cap, rows, lines, traj, "complete", terminal)
    terminal["checkpoints"] = checkpoints
    return terminal
