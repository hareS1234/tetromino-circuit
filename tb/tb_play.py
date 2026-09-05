"""cocotb backend for a complete game: the host submits board/piece, checks the RTL answer
against the Python reference, applies it, and repeats inside one simulation."""
import os

import cocotb

from common import ROOT, param, reset
from core_driver import idle_inputs, request
from model import lookahead, policy
from model.replay import metadata, play_game, write_replay
from model.streams import load_stream

SEED = int(os.environ["TETROMINO_SEED"])
CAP = int(os.environ["TETROMINO_CAP"])
OUT = os.environ["TETROMINO_REPLAY"]
DEPTH = param("DEPTH", 1)
PREC = param("PRECISION", 0)
ARCH = param("ARCH", 0)
TIMEOUT = 4_000_000 if DEPTH == 2 else 60_000


@cocotb.test()
async def play_full_game(dut):
    idle_inputs(dut)
    await reset(dut)
    stream = load_stream(ROOT, SEED)

    async def decide(rows, piece, nxt):
        fields, edges, _ = await request(dut, rows, piece, next_piece=nxt if nxt is not None else (piece + 3) % 7, timeout=TIMEOUT)
        exp = lookahead.best_move_depth2(rows, piece, nxt, PREC) if DEPTH == 2 else policy.best_move(rows, piece, PREC)
        assert fields["error"] == 0
        if fields["no_move"]:
            assert exp is None, "RTL reported no move but the reference found one"
            return None
        assert exp is not None
        assert (fields["rotation"], fields["x"], fields["y"], fields["score"]) == (exp["rotation"], exp["x"], exp["y"], exp["score"])
        assert fields["cycles"] == edges
        rec = dict(exp)
        rec["cycles"] = edges
        return rec

    # play_game is synchronous; drive it with an explicit loop instead
    from model.board import EMPTY_BOARD, validate_board
    from model.game import drop_y, lock_and_clear
    pieces = stream["pieces"]
    rows = EMPTY_BOARD
    records = []
    total = 0
    terminal = None
    for i in range(CAP):
        piece = pieces[i]
        nxt = pieces[i + 1] if DEPTH == 2 else None
        rec = await decide(rows, piece, nxt)
        if rec is None:
            terminal = {"type": "terminal", "reason": "top_out", "pieces_locked": i, "lines": total}
            break
        y = drop_y(rows, piece, rec["rotation"], rec["x"])
        assert y == rec["y"]
        new_rows, lines = lock_and_clear(rows, piece, rec["rotation"], rec["x"], y)
        validate_board(new_rows)
        total += lines
        records.append({"type": "move", "move_index": i, "piece_id": piece, "next_piece_id": pieces[i + 1],
                        "rows_before": list(rows), "rotation": rec["rotation"], "x": rec["x"], "y": rec["y"],
                        "candidate_id": 10 * rec["rotation"] + rec["x"], "rows_after": list(new_rows), "lines": lines,
                        "cumulative_lines": total, "score": rec["score"],
                        "features": {"A": rec["A"], "Q": rec["Q"], "U": rec["U"]}, "cycles": rec["cycles"]})
        rows = new_rows
    if terminal is None:
        terminal = {"type": "terminal", "reason": "cap_reached", "pieces_locked": CAP, "lines": total}
    meta = metadata(backend="rtl-cocotb", policy_name="heuristic", seed=SEED, stream_doc=stream, max_pieces=CAP,
                    depth=DEPTH, precision=PREC, arch=ARCH, board_repr=param("BOARD_REPR", 0), lanes=param("LANES", 1),
                    root=ROOT, extra={"driver": "cocotb"})
    write_replay(ROOT / OUT if not os.path.isabs(OUT) else OUT, meta, records, terminal)
    dut._log.info(f"game: {terminal}")
