#!/usr/bin/env python3
"""Generate, check and decode the v2 long piece streams (U15).

    python tools/streams_v2.py generate --split v2_development     # seeds 10000-10019, 50,001 pieces each
    python tools/streams_v2.py generate --split v2_heldout         # seeds 20000-20099
    python tools/streams_v2.py check                               # every manifest entry re-hashed and regenerated
    python tools/streams_v2.py decode 10000 --head 30              # readable piece names

Files: benchmarks/streams_v2/stream_<seed>.bin.gz (one byte per piece, gzip) and manifest.json
(schema stream-manifest-v2, content hashes over the decoded bytes).  The v1 streams and manifest
are not touched.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.streams_v2 import (SPLITS_V2, STREAM_LENGTH_V2, check_manifest, decode_names, load_manifest,  # noqa: E402
                              load_stream_v2, write_manifest, write_stream_v2)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    g = sub.add_parser("generate")
    g.add_argument("--split", choices=list(SPLITS_V2), required=True)
    g.add_argument("--length", type=int, default=STREAM_LENGTH_V2)
    g.add_argument("--force", action="store_true", help="rewrite existing entries (content must be identical anyway)")
    sub.add_parser("check")
    d = sub.add_parser("decode")
    d.add_argument("seed", type=int)
    d.add_argument("--head", type=int, default=40)
    args = ap.parse_args()
    if args.cmd == "generate":
        manifest = load_manifest(ROOT)
        written = kept = 0
        for seed in SPLITS_V2[args.split]:
            if str(seed) in manifest["streams"] and not args.force:
                kept += 1
                continue
            old = manifest["streams"].get(str(seed))
            entry = write_stream_v2(ROOT, seed, args.length, manifest)
            if old and old["sha256"] != entry["sha256"]:
                raise SystemExit(f"stream {seed}: regenerated content differs from the committed hash; refusing to overwrite the manifest")
            written += 1
        write_manifest(ROOT, manifest)
        print(f"streams_v2 {args.split}: {written} written, {kept} already present ({len(manifest['streams'])} entries in the manifest)")
        return 0
    if args.cmd == "check":
        problems = check_manifest(ROOT)
        m = load_manifest(ROOT)
        n = len(m["streams"])
        print(f"CHECK streams_v2 {n - len(problems)}/{n}")
        for p in problems:
            print("  -", p)
        return 1 if problems else 0
    if args.cmd == "decode":
        doc = load_stream_v2(ROOT, args.seed)
        print(f"seed {doc['seed']} split {doc['split']} length {doc['length']} sha256 {doc['sha256'][:16]}… generator {doc['generator']}")
        print(decode_names(doc["pieces"], args.head))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
