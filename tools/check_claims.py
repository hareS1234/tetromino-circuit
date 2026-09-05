#!/usr/bin/env python3
"""Every headline number in the reader-facing documents resolves to a result file (U19 gate `make check-claims`).

    python tools/check_claims.py            # verify docs/claims.json against the documents
    python tools/check_claims.py --print    # print every claim's current value (to write the documents)

docs/claims.json lists claims: an id, a source (JSON file + dotted path, or a CSV aggregate over one file or a
pooled list of `files`), an optional arithmetic (`divide_by` another claim, `scale`, `abs`), a `format` (Python
format spec) and the documents that must contain the formatted value verbatim.  The checker recomputes each
value from the source, formats it and searches the documents; a document that states a number the sources do
not produce fails the check, and so does a claim whose source cannot be computed.  It also rejects
TODO/TBD/placeholder markers in the reader-facing summaries.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAIMS = "docs/claims.json"
READER_FACING = ["README.md", "docs/results.md", "docs/research_report.md"]
PLACEHOLDER = re.compile(r"\b(TODO|TBD|XXX|placeholder|lorem ipsum)\b", re.I)


def lookup(doc, path: str):
    cur = doc
    for part in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = cur[part]
    return cur


def csv_value(spec: dict, root: Path):
    rows = []
    for rel in spec.get("files") or [spec["file"]]:          # `files`: several CSVs pooled (e.g. every v1 decision corpus)
        with open(root / rel) as fh:
            rows += list(csv.DictReader(fh))
    if "filter" in spec:
        rows = [r for r in rows if all(r.get(k) == v for k, v in spec["filter"].items())]
    if spec.get("agg") == "count":
        return len(rows)
    agg = spec.get("agg", "median")
    if agg == "count_true":
        return sum(1 for r in rows if r[spec["column"]] in ("True", "true", "1"))
    vals = [float(r[spec["column"]]) for r in rows if r.get(spec["column"]) not in ("", None, "None")]
    if not vals:
        raise ValueError(f"no values for column {spec['column']}")
    if agg == "median":
        return statistics.median(vals)
    if agg == "mean":
        return statistics.mean(vals)
    if agg == "sum":
        return sum(vals)
    if agg == "min":
        return min(vals)
    if agg == "max":
        return max(vals)
    raise ValueError(f"unknown agg {agg}")


def value_of(claim: dict, values: dict, root: Path):
    if "csv" in claim:
        v = csv_value(claim["csv"], root)
    else:
        doc = json.loads((root / claim["source"]).read_text())
        v = lookup(doc, claim["path"])
    if "divide_by" in claim:
        v = v / values[claim["divide_by"]]
    if "scale" in claim:
        v = v * claim["scale"]
    if claim.get("abs"):
        v = abs(v)
    return v


def check(root: Path, claims_rel: str = CLAIMS, print_values: bool = False) -> tuple[list[str], dict, int]:
    """Return (problems, {claim id: formatted value}, number of claims)."""
    spec = json.loads((root / claims_rel).read_text())
    values, shown_by_id, problems, texts = {}, {}, [], {}
    for c in spec["claims"]:
        try:
            v = value_of(c, values, root)
        except (KeyError, FileNotFoundError, IndexError, ValueError, TypeError, ZeroDivisionError) as exc:
            problems.append(f"{c['id']}: cannot compute ({exc.__class__.__name__}: {exc})")
            continue
        values[c["id"]] = v
        shown = c["format"].format(v) if "format" in c else str(v)
        shown_by_id[c["id"]] = shown
        if print_values:
            src = c.get("source") or c.get("csv", {}).get("file") or f"{len(c.get('csv', {}).get('files', []))} files"
            print(f"{c['id']:45s} {shown:>14s}   ({src})")
            continue
        for d in c.get("documents", []):
            if d not in texts:
                p = root / d
                texts[d] = p.read_text() if p.is_file() else None
            if texts[d] is None:
                problems.append(f"{c['id']}: document {d} missing")
            elif shown not in texts[d]:
                problems.append(f"{c['id']}: '{shown}' not found in {d}")
    if not print_values:
        for d in READER_FACING:
            p = root / d
            if p.is_file():
                hits = PLACEHOLDER.findall(p.read_text())
                if hits:
                    problems.append(f"{d}: placeholder markers {sorted(set(h.upper() for h in hits))}")
    return problems, shown_by_id, len(spec["claims"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true")
    args = ap.parse_args()
    problems, _, n = check(ROOT, print_values=args.print)
    if args.print:
        return 0
    failed_claims = {p.split(":")[0] for p in problems if not p.startswith(tuple(READER_FACING))}
    print(f"CHECK claims {n - len(failed_claims)}/{n}")
    for p in problems:
        print("  -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
