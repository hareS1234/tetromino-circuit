#!/usr/bin/env python3
"""Catch broken local Markdown links, images, and heading anchors."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^#{1,6}\s+(.*)$", re.M)


def slug(text: str) -> str:
    text = re.sub(r"[`*_]", "", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return re.sub(r"\s+", "-", text)


def anchors_of(path: Path) -> set[str]:
    out = set()
    seen = {}
    for h in HEADING.findall(path.read_text()):
        s = slug(h)
        if s in seen:
            seen[s] += 1
            out.add(f"{s}-{seen[s]}")
        else:
            seen[s] = 0
            out.add(s)
    return out


def check(root: Path) -> tuple[list[str], int, int, int]:
    """Return (problems, links checked, external links, documents scanned) for the Markdown under root."""
    docs = [root / "README.md", root / "NOTICE.md", root / "PROJECT_NOTES.md", root / "PROJECT_NOTES.md"] + sorted((root / "docs").rglob("*.md"))
    problems, external, checked, n_docs = [], 0, 0, 0
    for doc in docs:
        if not doc.is_file():
            continue
        n_docs += 1
        text = doc.read_text()
        for m in LINK.finditer(text):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                external += 1
                continue
            if target.startswith("#"):
                checked += 1
                if target[1:] not in anchors_of(doc):
                    problems.append(f"{doc.relative_to(root)}: anchor {target} not found")
                continue
            path_part, _, anchor = target.partition("#")
            dest = (doc.parent / path_part).resolve()
            checked += 1
            if not dest.exists():
                problems.append(f"{doc.relative_to(root)}: broken link {target}")
                continue
            if anchor and dest.suffix == ".md" and anchor not in anchors_of(dest):
                problems.append(f"{doc.relative_to(root)}: anchor #{anchor} not in {path_part}")
    return problems, checked, external, n_docs


def main() -> int:
    problems, checked, external, n_docs = check(ROOT)
    print(f"CHECK links {checked - len(problems)}/{checked} ({n_docs} documents, {external} external links not fetched)")
    for p in problems:
        print("  -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
