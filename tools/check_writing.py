#!/usr/bin/env python3
"""Check the repository's public writing rules."""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEXT_SUFFIXES = {
    ".css", ".html", ".js", ".md", ".py", ".sh", ".svg", ".toml", ".yaml", ".yml"
}
SKIP_PARTS = {".git", ".tools", ".venv", "build", "results"}

# These bytes identify published model and hardware measurements. Their older comments stay frozen.
IDENTITY_BOUND = {"model", "rtl"}

HEADING_QUESTION = re.compile(r"^#{1,6}\s+.*\b(?:what|why|how)\b", re.IGNORECASE)
WORD = re.compile(r"\b[\w'`./+%=-]+\b")


def repository_files() -> list[Path]:
    files = []
    for directory, names, filenames in os.walk(ROOT):
        names[:] = [name for name in names if name not in SKIP_PARTS]
        files.extend(Path(directory) / name for name in filenames)
    return sorted(files)


def public_text_files(files: list[Path]) -> list[Path]:
    return [
        path for path in files
        if path.suffix.lower() in TEXT_SUFFIXES
        and path.relative_to(ROOT).parts[0] not in IDENTITY_BOUND
    ]


def long_markdown_sentences(path: Path) -> list[tuple[int, int]]:
    """Return line and word counts for prose sentences longer than 65 words."""
    chunks: list[tuple[int, str]] = []
    lines: list[str] = []
    start = 1
    in_code = False
    for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        if line.startswith("```"):
            in_code = not in_code
            continue
        ignored = in_code or line.startswith(("#", "|", "- ", "* ")) or re.match(r"\s*\d+\. ", line)
        if ignored or not line.strip():
            if lines:
                chunks.append((start, " ".join(lines)))
                lines = []
            continue
        if not lines:
            start = lineno
        lines.append(line.strip())
    if lines:
        chunks.append((start, " ".join(lines)))

    found = []
    for lineno, paragraph in chunks:
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            count = len(WORD.findall(sentence))
            if count > 65:
                found.append((lineno, count))
    return found


def main() -> int:
    problems: list[str] = []
    files = repository_files()

    public_files = public_text_files(files)
    for path in public_files:
        rel = path.relative_to(ROOT)
        text = path.read_text(errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "\N{EM DASH}" in line:
                problems.append(f"{rel}:{lineno}: replace the em dash")
            if re.search(r"\bgenuinely\b", line, re.IGNORECASE):
                problems.append(f"{rel}:{lineno}: replace the banned filler word")
            if path.suffix.lower() == ".md" and HEADING_QUESTION.search(line):
                problems.append(f"{rel}:{lineno}: use a direct heading")
        if path.suffix.lower() == ".md":
            for lineno, count in long_markdown_sentences(path):
                problems.append(f"{rel}:{lineno}: split the {count}-word sentence")

    if problems:
        print("check-writing: FAIL")
        for problem in problems:
            print(f"- {problem}")
        return 1

    print(f"check-writing: OK. Checked {len(public_files)} public text files.")
    print("check-writing: model/ and rtl/ prose remains frozen with its measurement identity.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
