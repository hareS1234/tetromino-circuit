#!/usr/bin/env python3
"""Generate the committed seven-bag piece streams and their hash manifest."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.streams import SPLITS, STREAM_LENGTH, load_stream, seven_bag, write_stream  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="verify committed streams match the generator")
    args = ap.parse_args()
    manifest = {"spec": "drop-v1.1", "length": STREAM_LENGTH, "splits": {}, "streams": {}}
    bad = 0
    for split, seeds in SPLITS.items():
        manifest["splits"][split] = [seeds.start, seeds.stop - 1]
        for seed in seeds:
            if args.check:
                try:
                    doc = load_stream(ROOT, seed)
                except (FileNotFoundError, ValueError) as exc:
                    print(f"seed {seed}: {exc}")
                    bad += 1
                    continue
                if doc["pieces"] != seven_bag(seed):
                    print(f"seed {seed}: committed pieces differ from the generator")
                    bad += 1
            else:
                doc = write_stream(ROOT, seed)
            manifest["streams"][str(seed)] = doc["sha256"]
    path = ROOT / "benchmarks" / "streams" / "manifest.json"
    if args.check:
        old = json.loads(path.read_text()) if path.is_file() else {}
        if old != manifest:
            print("manifest differs from committed streams")
            bad += 1
        print("checked", len(manifest["streams"]), "streams;", bad, "problems")
        return 1 if bad else 0
    path.write_text(json.dumps(manifest, indent=1) + "\n")
    print("wrote", len(manifest["streams"]), "streams and manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
