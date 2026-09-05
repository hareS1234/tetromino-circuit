#!/usr/bin/env python3
"""Static checks of the replay viewer and its bundled demo (U18: accessibility and trace validation).

    python tools/check_viewer.py

Checks: the viewer files exist and reference each other; every control has an accessible name (aria-label,
title or visible label text); canvases carry role="img" with labels; live regions exist; the bundled demo
embeds the committed trace byte-for-byte (sha256 attribute), its embedded JSON is valid a2-trace-v1 and
its cycle count matches; app.js parses (node --check when Node is available); the GIFs exist and are
GitHub-sized (< 5 MB); the render metadata points at traces that exist.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT / "viewer"


def main() -> int:
    ok = total = 0
    problems = []

    def chk(cond, msg):
        nonlocal ok, total
        total += 1
        if cond:
            ok += 1
        else:
            problems.append(msg)

    index = (VIEWER / "index.html").read_text() if (VIEWER / "index.html").is_file() else ""
    chk(bool(index) and (VIEWER / "app.js").is_file() and (VIEWER / "style.css").is_file(), "viewer files missing")
    chk('src="app.js"' in index and 'href="style.css"' in index, "index.html does not reference app.js/style.css")
    chk('lang="en"' in index and "<main" in index and "<header" in index, "landmarks/language missing")
    # controls: every button/select/input has an accessible name
    for m in re.finditer(r"<(button|select|input)([^>]*)>", index):
        attrs = m.group(2)
        named = 'aria-label="' in attrs or 'title="' in attrs or re.search(r'id="([^"]+)"', attrs) and re.search(r'for="' + re.escape(re.search(r'id="([^"]+)"', attrs).group(1)) + '"', index)
        text_child = m.group(1) == "button" and re.search(re.escape(m.group(0)) + r"\s*[^<\s]", index)
        inside_label = m.group(1) in ("input", "select") and re.search(r"<label>[^<]*" + re.escape(m.group(0)), index)
        chk(bool(named or text_child or inside_label), f"control without an accessible name: {m.group(0)[:60]}")
    for m in re.finditer(r"<canvas([^>]*)>", index):
        chk('role="img"' in m.group(1) and 'aria-label="' in m.group(1), f"canvas without role/label: {m.group(0)[:60]}")
    chk(index.count('aria-live="polite"') >= 3, "live regions for status/explanation/best missing")
    chk("color alone" in (VIEWER / "app.js").read_text() or "outline" in (VIEWER / "style.css").read_text(), "selected/best states must use outline/label, not colour alone")
    # app.js syntax
    node = shutil.which("node")
    if node:
        r = subprocess.run([node, "--check", str(VIEWER / "app.js")], capture_output=True, text=True)
        chk(r.returncode == 0, f"app.js does not parse: {r.stderr[:200]}")
    else:
        print("  note: node not available, app.js syntax not checked")
    # bundled demo
    demo = VIEWER / "demo.html"
    chk(demo.is_file(), "viewer/demo.html missing (make render-a2-demo)")
    if demo.is_file():
        html = demo.read_text()
        m = re.search(r'data-trace-sha256="([0-9a-f]{64})" data-trace-path="([^"]+)"', html)
        chk(bool(m), "demo.html lacks the trace hash attributes")
        if m:
            tp = ROOT / m.group(2)
            chk(tp.is_file() and hashlib.sha256(tp.read_bytes()).hexdigest() == m.group(1), "demo.html embeds a trace that differs from the committed file")
            em = re.search(r"window\.A2_EMBEDDED_TRACE = (\{.*?\});window\.A2_EMBEDDED_STAGES", html, re.S)
            chk(bool(em), "embedded trace object missing")
            if em and tp.is_file():
                try:
                    doc = json.loads(em.group(1).replace("<\\/", "</"))
                    ref = json.loads(tp.read_text())
                    chk(doc.get("schema") == "a2-trace-v1" and len(doc["cycles"]) == len(ref["cycles"]) and doc["source_sha256"] == ref["source_sha256"],
                        "embedded trace is not the committed a2-trace-v1 content")
                except ValueError as exc:
                    chk(False, f"embedded trace is not valid JSON: {exc}")
    # gifs and render metadata
    for gif in ("assets/a2_pipeline.gif", "assets/a2_stall_reset.gif", "assets/a2_last_candidate_wins.gif"):
        p = ROOT / gif
        chk(p.is_file() and 0 < p.stat().st_size < 5 * 1024 * 1024, f"{gif} missing or larger than 5 MB")
    for meta in (ROOT / "results" / "traces" / "frames").glob("*/render.json"):
        d = json.loads(meta.read_text())
        chk((ROOT / d["trace"]).is_file() and (ROOT / d["gif"]).is_file() and len(d["stills"]) == 3, f"{meta.relative_to(ROOT)}: trace/gif/stills inconsistent")
        chk(json.loads((ROOT / d["trace"]).read_text())["source_sha256"] == d["trace_source_sha256"], f"{meta.relative_to(ROOT)}: rendered from a different trace version")
    print(f"CHECK viewer {ok}/{total}")
    for p in problems:
        print("  -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
