"""Python side of the persistent native Verilator driver (one subprocess, one line per decision)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .board import board_words


class NativeCore:
    FIELDS = ("error", "no_move", "rotation", "x", "y", "score", "cycles", "interval")

    def __init__(self, exe: Path, max_cycles: int = 4_000_000):
        self.exe = Path(exe)
        if not self.exe.is_file():
            raise FileNotFoundError(self.exe)
        self.proc = subprocess.Popen([str(self.exe), f"+max_cycles={max_cycles}"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        self.requests = 0

    def request(self, rows, piece: int, next_piece: int = 0) -> dict:
        words = board_words(rows)
        line = f"{piece} {next_piece} " + " ".join(str(w) for w in words) + "\n"
        self.proc.stdin.write(line)
        self.proc.stdin.flush()
        out = self.proc.stdout.readline()
        if not out:
            err = self.proc.stderr.read()
            raise RuntimeError(f"native driver exited (code {self.proc.poll()}): {err.strip()}")
        parts = out.split()
        if len(parts) != len(self.FIELDS):
            raise RuntimeError(f"malformed native response: {out!r}")
        vals = [int(p) for p in parts]
        rec = dict(zip(self.FIELDS, vals))
        if rec["error"] not in (0, 1) or rec["no_move"] not in (0, 1) or not 0 <= rec["rotation"] <= 3 \
                or not 0 <= rec["x"] <= 9 or not 0 <= rec["y"] <= 19 or rec["cycles"] <= 0:
            raise RuntimeError(f"native response out of range: {rec}")
        self.requests += 1
        return rec

    def request_pair(self, rows1, piece1, next1, rows2, piece2, next2) -> tuple[dict, dict]:
        """Batch mode: the second request is offered while the first is in flight; the first response
        carries interval_measured = edges between the two real acceptance edges."""
        w1, w2 = board_words(rows1), board_words(rows2)
        line = f"P {piece1} {next1} " + " ".join(str(w) for w in w1) + f" {piece2} {next2} " + " ".join(str(w) for w in w2) + "\n"
        self.proc.stdin.write(line)
        self.proc.stdin.flush()
        out1 = self.proc.stdout.readline()
        out2 = self.proc.stdout.readline()
        if not out1 or not out2:
            err = self.proc.stderr.read()
            raise RuntimeError(f"native driver exited (code {self.proc.poll()}): {err.strip()}")
        v1 = [int(p) for p in out1.split()]
        v2 = [int(p) for p in out2.split()]
        if len(v1) != len(self.FIELDS) + 1 or len(v2) != len(self.FIELDS):
            raise RuntimeError(f"malformed pair response: {out1!r} {out2!r}")
        rec1 = dict(zip(self.FIELDS + ("interval_measured",), v1))
        rec2 = dict(zip(self.FIELDS, v2))
        self.requests += 2
        return rec1, rec2

    def close(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.wait(timeout=60)
        return self.proc.returncode

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
