"""U19: the report checkers reject numbers the sources do not produce, placeholders and broken links."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools import check_claims, check_links  # noqa: E402


def write(root: Path, rel: str, content) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(content) if isinstance(content, (dict, list)) else content)
    return p


def claims(*items) -> dict:
    return {"schema": "claims-v1", "claims": list(items)}


def test_claim_value_must_appear_verbatim_and_sources_must_exist(tmp_path):
    write(tmp_path, "results/q.json", {"policies": {"p1": {"mean": {"value": 22674.97}}}, "n": 100})
    write(tmp_path, "results/dec.csv", "state_id,core_cycles\n1,40\n2,46\n3,63\n")
    write(tmp_path, "results/dec_b.csv", "state_id,core_cycles\n4,10\n")
    write(tmp_path, "README.md", "P1 survives 22,675 pieces on 100 streams; median 46 cycles; 4 decisions; ratio 1.2×.\n")
    write(tmp_path, "docs/claims.json", claims(
        {"id": "p1", "source": "results/q.json", "path": "policies.p1.mean.value", "format": "{:,.0f}", "documents": ["README.md"]},
        {"id": "n", "source": "results/q.json", "path": "n", "format": "{}", "documents": ["README.md"]},
        {"id": "med", "csv": {"file": "results/dec.csv", "column": "core_cycles", "agg": "median"}, "format": "{:.0f}", "documents": ["README.md"]},
        {"id": "count", "csv": {"files": ["results/dec.csv", "results/dec_b.csv"], "agg": "count"}, "format": "{}", "documents": ["README.md"]},
        {"id": "sum_a", "csv": {"file": "results/dec.csv", "column": "core_cycles", "agg": "sum"}, "format": "{:.0f}", "documents": []},
        {"id": "ratio", "csv": {"file": "results/dec.csv", "column": "core_cycles", "agg": "max"}, "divide_by": "med", "scale": 0.875,
         "format": "{:.1f}×", "documents": ["README.md"]},
    ))
    problems, shown, n = check_claims.check(tmp_path)
    assert n == 6 and problems == []
    assert shown == {"p1": "22,675", "n": "100", "med": "46", "count": "4", "sum_a": "149", "ratio": "1.2×"}
    # a document that states another number fails; a missing source fails; a missing document fails
    write(tmp_path, "README.md", "P1 survives 22,676 pieces on 100 streams; median 46 cycles; 4 decisions; ratio 1.2×.\n")
    problems, _, _ = check_claims.check(tmp_path)
    assert problems == ["p1: '22,675' not found in README.md"]
    (tmp_path / "results/q.json").unlink()
    problems, _, _ = check_claims.check(tmp_path)
    assert any(p.startswith("p1: cannot compute (FileNotFoundError") for p in problems)
    assert any(p.startswith("n: cannot compute") for p in problems)


def test_csv_filter_and_empty_values_and_placeholders(tmp_path):
    write(tmp_path, "results/routes.csv", "configuration_id,current,status,reported_fmax_mhz,timing_met\n"
                                          "a2,True,routed_timing_met,76.36,True\na2,True,route_timeout,,False\na1,True,routed_timing_met,65.0,True\n")
    write(tmp_path, "README.md", "A2 reports 76.4 MHz; met 1 of its routes; 1 timeout. Results are TBD.\n")
    write(tmp_path, "docs/claims.json", claims(
        {"id": "fmax", "csv": {"file": "results/routes.csv", "column": "reported_fmax_mhz", "agg": "max", "filter": {"configuration_id": "a2", "current": "True"}},
         "format": "{:.1f}", "documents": ["README.md"]},
        {"id": "met", "csv": {"file": "results/routes.csv", "column": "timing_met", "agg": "count_true", "filter": {"configuration_id": "a2"}}, "format": "{}", "documents": ["README.md"]},
        {"id": "timeouts", "csv": {"file": "results/routes.csv", "agg": "count", "filter": {"configuration_id": "a2", "status": "route_timeout"}}, "format": "{}", "documents": ["README.md"]},
        {"id": "none", "csv": {"file": "results/routes.csv", "column": "reported_fmax_mhz", "agg": "min", "filter": {"configuration_id": "zzz"}}, "format": "{}", "documents": []},
    ))
    problems, shown, _ = check_claims.check(tmp_path)
    assert shown["fmax"] == "76.4" and shown["met"] == "1" and shown["timeouts"] == "1"
    assert "none: cannot compute (ValueError: no values for column reported_fmax_mhz)" in problems
    assert "README.md: placeholder markers ['TBD']" in problems


def test_links_and_anchors(tmp_path):
    write(tmp_path, "docs/a.md", "# Title\n\n## Second heading\n\nSee [b](b.md#part-two), [img](../assets/x.png), [self](#second-heading), [bad](#nope), [gone](c.md), [ext](https://example.org/).\n")
    write(tmp_path, "docs/b.md", "# B\n\n## Part two\n")
    write(tmp_path, "assets/x.png", "png")
    write(tmp_path, "README.md", "[docs](docs/a.md) ![fig](assets/x.png) [anchor](docs/b.md#missing)\n")
    problems, checked, external, n_docs = check_links.check(tmp_path)
    assert n_docs == 3 and external == 1 and checked == 8
    assert sorted(problems) == ["README.md: anchor #missing not in docs/b.md", "docs/a.md: anchor #nope not found", "docs/a.md: broken link c.md"]
    assert check_links.slug("## `code` and *emphasis* — dash") == "code-and-emphasis--dash" or check_links.slug("`code` and *emphasis*") == "code-and-emphasis"


def test_real_claims_file_is_well_formed():
    spec = json.loads((ROOT / "docs" / "claims.json").read_text())
    ids = [c["id"] for c in spec["claims"]]
    assert len(ids) == len(set(ids)), "duplicate claim ids"
    for c in spec["claims"]:
        assert ("source" in c and "path" in c) or "csv" in c, c["id"]
        assert "format" in c and "documents" in c, c["id"]
        for d in c["documents"]:
            assert d in check_claims.READER_FACING, f"{c['id']}: {d} is not a reader-facing document"
        if "divide_by" in c:
            assert ids.index(c["divide_by"]) < ids.index(c["id"]), f"{c['id']}: divide_by must be computed first"
