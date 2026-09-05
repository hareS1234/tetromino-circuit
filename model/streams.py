"""Seven-bag piece streams, committed as JSON so results never depend on the
random library's future behaviour."""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

SPEC_ID = "drop-v1.1"
STREAM_LENGTH = 2001  # 2,000 decisions plus one preview for a depth-two decision at move 2,000

SPLITS = {
    "training": range(1000, 1050),
    "validation": range(2000, 2020),
    "test": range(3000, 3100),
}


def seven_bag(seed: int, length: int = STREAM_LENGTH):
    rng = random.Random(seed)
    pieces = []
    while len(pieces) < length:
        bag = [0, 1, 2, 3, 4, 5, 6]
        rng.shuffle(bag)
        pieces.extend(bag)
    return pieces[:length]


def stream_sha256(pieces) -> str:
    return hashlib.sha256(json.dumps(list(pieces), separators=(",", ":")).encode()).hexdigest()


def split_of(seed: int) -> str:
    for name, rng in SPLITS.items():
        if seed in rng:
            return name
    return "adhoc"


def stream_path(root: Path, seed: int) -> Path:
    return root / "benchmarks" / "streams" / f"stream_{seed}.json"


def write_stream(root: Path, seed: int, length: int = STREAM_LENGTH) -> dict:
    pieces = seven_bag(seed, length)
    doc = {"spec": SPEC_ID, "seed": seed, "split": split_of(seed), "length": len(pieces),
           "generator": "python-random-seven-bag", "sha256": stream_sha256(pieces), "pieces": pieces}
    path = stream_path(root, seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    return doc


def load_stream(root: Path, seed: int) -> dict:
    path = stream_path(root, seed)
    if not path.is_file():
        raise FileNotFoundError(f"stream for seed {seed} not generated: {path}")
    doc = json.loads(path.read_text())
    if doc["sha256"] != stream_sha256(doc["pieces"]):
        raise ValueError(f"stream {seed} hash mismatch")
    return doc
