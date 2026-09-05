"""U02: complete job identities (guide §10.2).

Canonical serialization, transitive HDL closure, and the invalidation matrix: every input that
determines a result changes its key, a documentation-only edit changes nothing, and a parser
change re-analyses instead of re-routing."""
import json
from pathlib import Path

import pytest

from tools import identity as ident

TOOLS = {"yosys": "Yosys 0.68+182 (fake)", "nextpnr-ecp5": "nextpnr-0.11.1 (fake)", "verilator": "Verilator 5.051 (fake)"}
PARAMS = {"ARCH": 1, "BOARD_REPR": 1, "LANES": 1, "DEPTH": 1, "PRECISION": 0}


@pytest.fixture
def fake_root(tmp_path: Path) -> Path:
    (tmp_path / "rtl" / "generated").mkdir(parents=True)
    (tmp_path / "sim").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "rtl" / "top.sv").write_text('`include "params.svh"\nmodule top; sub u(); endmodule\n')
    (tmp_path / "rtl" / "sub.sv").write_text('`include "generated/shapes.svh"\nmodule sub; endmodule\n')
    (tmp_path / "rtl" / "params.svh").write_text("`define W 10\n")
    (tmp_path / "rtl" / "generated" / "shapes.svh").write_text("localparam SHAPES = 7;\n")
    (tmp_path / "rtl" / "files.f").write_text("# ordered\nrtl/sub.sv\nrtl/top.sv\n")
    (tmp_path / "rtl" / "files_core.f").write_text("rtl/sub.sv\nrtl/top.sv\n")
    (tmp_path / "sim" / "main.cpp").write_text("int main(){return 0;}\n")
    (tmp_path / "tools" / "build_native.py").write_text("# builder\n")
    (tmp_path / "docs" / "design.md").write_text("# design\n")
    return tmp_path


def synth(root, **kw):
    args = dict(cfg=PARAMS, top="top", files_f="rtl/files.f", root=root, tools=TOOLS)
    args.update(kw)
    return ident.synth_identity(**args)


# ---- canonical serialization -------------------------------------------------------------------

def test_canonical_is_order_independent_and_compact():
    a = {"b": [1, 2, {"z": 1, "a": 2}], "a": "é", "c": 1.5}
    b = {"c": 1.5, "a": "é", "b": [1, 2, {"a": 2, "z": 1}]}
    assert ident.canonical(a) == ident.canonical(b) == b'{"a":"\\u00e9","b":[1,2,{"a":2,"z":1}],"c":1.5}'
    assert ident.sha256_of(a) == ident.sha256_of(b)
    assert ident.sha256_of({"x": 1}) != ident.sha256_of({"x": "1"}), "types are part of the identity"
    with pytest.raises(ValueError):
        ident.canonical({"x": float("nan")})
    with pytest.raises(TypeError):
        ident.canonical({"p": Path("x")})


def test_file_record_uses_relative_path_length_and_bytes(fake_root):
    rec = ident.file_record(fake_root / "rtl" / "params.svh", fake_root)
    assert rec == {"path": "rtl/params.svh", "bytes": 13, "sha256": ident.sha256_bytes(b"`define W 10\n")}


# ---- closure ----------------------------------------------------------------------------------------

def test_closure_follows_includes_and_keeps_order(fake_root):
    c = ident.hdl_closure("rtl/files.f", root=fake_root)
    assert c["ordered"] == ["rtl/sub.sv", "rtl/top.sv"]
    assert [r["path"] for r in c["closure"]] == ["rtl/generated/shapes.svh", "rtl/params.svh", "rtl/sub.sv", "rtl/top.sv"]


def test_real_repository_closure_includes_generated_headers():
    c = ident.hdl_closure("rtl/files.f")
    paths = {r["path"] for r in c["closure"]}
    assert any(p.startswith("rtl/generated/") for p in paths), "generated includes must be in the closure"
    assert set(c["ordered"]) <= paths and len(c["closure"]) > len(c["ordered"])


# ---- synth invalidation matrix ------------------------------------------------------------------------

def test_synth_key_is_deterministic(fake_root):
    assert synth(fake_root)["synth_key"] == synth(fake_root)["synth_key"]


@pytest.mark.parametrize("edit", ["rtl/top.sv", "rtl/sub.sv", "rtl/params.svh", "rtl/generated/shapes.svh"])
def test_source_or_include_edit_changes_synth_key(fake_root, edit):
    before = synth(fake_root)["synth_key"]
    p = fake_root / edit
    p.write_text(p.read_text() + "// edit\n")
    assert synth(fake_root)["synth_key"] != before


def test_files_f_order_changes_synth_key(fake_root):
    before = synth(fake_root)["synth_key"]
    (fake_root / "rtl" / "files.f").write_text("rtl/top.sv\nrtl/sub.sv\n")
    assert synth(fake_root)["synth_key"] != before


def test_documentation_edit_does_not_change_synth_key(fake_root):
    before = synth(fake_root)["synth_key"]
    (fake_root / "docs" / "design.md").write_text("# design, revised\n")
    (fake_root / "README.md").write_text("new readme\n")
    assert synth(fake_root)["synth_key"] == before


def test_tool_params_policy_script_change_synth_key(fake_root):
    base = synth(fake_root)["synth_key"]
    assert synth(fake_root, tools={**TOOLS, "yosys": "Yosys 0.69 (fake)"})["synth_key"] != base
    assert synth(fake_root, cfg={**PARAMS, "PRECISION": 1})["synth_key"] != base
    assert synth(fake_root, dsp_policy="nodsp")["synth_key"] != base
    assert synth(fake_root, script_version="synth-v3")["synth_key"] != base
    assert synth(fake_root, top="sub")["synth_key"] != base
    with pytest.raises(ValueError):
        synth(fake_root, dsp_policy="maybe")


# ---- route / analysis ------------------------------------------------------------------------------------

def route(**kw):
    args = dict(synth_key="s" * 64, netlist_sha256="n" * 64, freq_mhz=50, seed=1, timeout_s=600, tools=TOOLS)
    args.update(kw)
    return ident.route_identity(**args)


@pytest.mark.parametrize("change", [
    {"freq_mhz": 60}, {"seed": 2}, {"netlist_sha256": "m" * 64}, {"synth_key": "t" * 64}, {"timeout_s": 1800},
    {"device": {**ident.DEVICE_ECP5_85F, "speed": "8"}}, {"device": {**ident.DEVICE_ECP5_85F, "package": "CABGA554"}},
    {"options": ["--lpf-allow-unconstrained", "--timing-allow-fail"]}, {"script_version": "route-v3"},
    {"tools": {**TOOLS, "nextpnr-ecp5": "nextpnr-0.12 (fake)"}},
])
def test_route_inputs_change_route_key(change):
    assert route(**change)["route_key"] != route()["route_key"]


def test_route_key_is_deterministic_and_freq_is_float():
    a, b = route(), route(freq_mhz=50.0)
    assert a["route_key"] == b["route_key"] and a["target_mhz"] == 50.0


def test_parser_version_changes_analysis_not_route():
    rk = route()["route_key"]
    a1 = ident.analysis_identity(rk, "pnr-parser-v2")
    a2 = ident.analysis_identity(rk, "pnr-parser-v3")
    assert a1["route_key"] == a2["route_key"] == rk
    assert a1["analysis_key"] != a2["analysis_key"]


# ---- native --------------------------------------------------------------------------------------------------

def test_native_key_covers_sources_driver_and_flags(fake_root):
    base = ident.native_identity(PARAMS, root=fake_root, tools=TOOLS)["native_key"]
    (fake_root / "sim" / "main.cpp").write_text("int main(){return 1;}\n")
    assert ident.native_identity(PARAMS, root=fake_root, tools=TOOLS)["native_key"] != base
    (fake_root / "sim" / "main.cpp").write_text("int main(){return 0;}\n")
    assert ident.native_identity(PARAMS, root=fake_root, tools=TOOLS)["native_key"] == base
    assert ident.native_identity(PARAMS, root=fake_root, tools=TOOLS, flags=["--cc"])["native_key"] != base
    assert ident.native_identity(PARAMS, root=fake_root, tools={**TOOLS, "verilator": "Verilator 5.052"})["native_key"] != base
    (fake_root / "rtl" / "generated" / "shapes.svh").write_text("localparam SHAPES = 8;\n")
    assert ident.native_identity(PARAMS, root=fake_root, tools=TOOLS)["native_key"] != base


# ---- quality ---------------------------------------------------------------------------------------------------

def quality(**kw):
    args = dict(protocol={"name": "quality-v2-bag50k", "cap": 50000}, policy={"policy": "heuristic", "depth": 1, "precision": 0},
                stream_sha256="a" * 64, cap=50000, protocol_path="benchmarks/config_v2.json", model_closure="m" * 64,
                runtime={"python": "3.11.15"})
    args.update(kw)
    return ident.quality_identity(**args)


@pytest.mark.parametrize("change", [
    {"policy": {"policy": "heuristic", "depth": 1, "precision": 5}}, {"policy": {"policy": "heuristic", "depth": 2, "precision": 0}},
    {"stream_sha256": "b" * 64}, {"cap": 2000}, {"protocol": {"name": "quality-v2-bag50k", "cap": 50001}},
    {"model_closure": "n" * 64}, {"protocol_path": "benchmarks/config.json"},
])
def test_quality_inputs_change_quality_key(change):
    assert quality(**change)["quality_key"] != quality()["quality_key"]


def test_quality_runtime_is_part_of_identity():
    assert quality(runtime={"python": "3.12.3"})["quality_key"] != quality()["quality_key"]


# ---- repository-level ---------------------------------------------------------------------------------------------

def test_real_synth_identity_matches_documented_layout():
    doc = ident.synth_identity("a1-cache-d1-p0-l1", tools=TOOLS)
    assert doc["params"] == PARAMS and doc["top"] == "stream_wrapper" and len(doc["synth_key"]) == 64
    assert json.loads(ident.canonical(doc))["hdl"]["files_f"] == "rtl/files.f"


def test_source_closure_covers_manifests_and_scripts():
    assert len(ident.source_closure_sha256()) == 64
    assert "benchmarks/*.json" in ident.SOURCE_PATTERNS and "scripts/*.sh" in ident.SOURCE_PATTERNS
