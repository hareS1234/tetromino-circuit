#!/usr/bin/env python3
"""Pack the CSS, JavaScript, and one hashed trace into the offline viewer demo."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", default="results/traces/a2_normal_search.json")
    ap.add_argument("--out", default="viewer/demo.html")
    args = ap.parse_args()
    trace_path = ROOT / args.trace
    raw = trace_path.read_bytes()
    doc = json.loads(raw)
    css = (ROOT / "viewer" / "style.css").read_text()
    js = (ROOT / "viewer" / "app.js").read_text()
    index = (ROOT / "viewer" / "index.html").read_text()
    body_start = index.index("<body>") + len("<body>")
    body_end = index.index('<script src="app.js"></script>')
    body = index[body_start:body_end]
    embedded = json.dumps(doc, separators=(",", ":")).replace("</", "<\\/")
    stages = json.dumps(json.loads((ROOT / "architecture" / "a2_stages.json").read_text())["stages"], separators=(",", ":"))
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>A2 pipeline replay — embedded demo ({doc['scenario']})</title>
<style>
{css}
</style>
</head>
<body data-trace-sha256="{hashlib.sha256(raw).hexdigest()}" data-trace-path="{args.trace}" data-scenario="{doc['scenario']}">
{body}
<script>window.A2_EMBEDDED_TRACE = {embedded};window.A2_EMBEDDED_STAGES = {stages};</script>
<script>
{js}
</script>
</body>
</html>
"""
    out = ROOT / args.out
    out.write_text(html)
    print(f"{out.relative_to(ROOT)}: {out.stat().st_size / 1024:.0f} KB with {args.trace} embedded ({doc['scenario']}, {len(doc['cycles'])} cycles)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
