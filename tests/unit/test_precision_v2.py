"""Quantized coefficients, their known divergences, and the integer stability bound."""
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from model import fast, policy  # noqa: E402
from model.config import SUPPORTED_IDS, V1_SUPPORTED_IDS, Config, status, validate  # noqa: E402
from model.numeric import (EXACT_COEFFICIENTS, PROFILES, QUANTIZED_PRECISION_IDS, V1_PRECISION_IDS, coefficient_perturbations,  # noqa: E402
                           error_bound, profile, profile_metadata, quantize_magnitudes, score_bounds, score_profile,
                           sufficient_score_width, to_baseline_units)
from model.pieces import candidate_ids, decode_candidate, shape  # noqa: E402
from model.sensitivity import analyze_state, candidate_table, certify, gap, winner  # noqa: E402
from reference_grid import cells_from_rows, ref_features, ref_landing, ref_lock_and_clear  # noqa: E402

FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "precision_v2_divergences.json").read_text())
CORPUS = [json.loads(l) for l in (ROOT / "benchmarks" / "states" / "corpus_d1.jsonl").read_text().splitlines() if l.strip()]


# Profiles

def test_quantized_magnitudes_are_generated_exactly_as_specified():
    assert quantize_magnitudes(4) == (15, 10, 7, 4)
    assert quantize_magnitudes(3) == (7, 5, 3, 2)
    assert quantize_magnitudes(2) == (3, 2, 1, 1)
    # nearest rounding with positive half-ties upward, checked against exact rationals
    for bits in (2, 3, 4):
        m = (1 << bits) - 1
        for q, w in zip(quantize_magnitudes(bits), EXACT_COEFFICIENTS):
            exact = Fraction(w * m, 76)
            assert q == (exact.numerator * 2 + exact.denominator) // (2 * exact.denominator)
    with pytest.raises(AssertionError):
        quantize_magnitudes(5)


def test_profiles_0_to_4_are_unchanged_and_5_to_7_carry_metadata():
    assert {p: PROFILES[p].coefficients for p in V1_PRECISION_IDS} == {
        0: (76, 51, 36, 18), 1: (64, 64, 32, 16), 2: (80, 48, 36, 18), 3: (76, 51, 36, 18), 4: (76, 51, 36, 0)}
    assert all(PROFILES[p].coeff_bits is None and PROFILES[p].score_width == 32 for p in V1_PRECISION_IDS)
    assert PROFILES[3].q_cap == 15 and not PROFILES[4].use_u
    expected = {5: ("coeff_u4", (15, 10, 7, 4), 4, 15, (-4120, 60), 14),
                6: ("coeff_u3", (7, 5, 3, 2), 3, 7, (-1960, 28), 12),
                7: ("coeff_u2", (3, 2, 1, 1), 2, 3, (-780, 12), 11)}
    for p, (name, coeffs, bits, levels, rng, width) in expected.items():
        pr = profile(p)
        assert (pr.name, pr.coefficients, pr.coeff_bits, pr.levels, pr.score_width) == (name, coeffs, bits, levels, width)
        assert pr.q_cap is None and pr.use_u, "quantized profiles keep exact features"
        assert score_bounds(p) == rng
        assert sufficient_score_width(coeffs) == width
        meta = profile_metadata(p)
        assert meta["coefficients"] == list(coeffs) and meta["score_range"] == list(rng) and "raw" in meta["units"]
    assert QUANTIZED_PRECISION_IDS == (5, 6, 7) and sorted(PROFILES) == list(range(8))
    assert sufficient_score_width(EXACT_COEFFICIENTS) == 16 and profile_metadata(0)["units"] == "baseline"


def test_configurations_and_guards():
    for p in QUANTIZED_PRECISION_IDS:
        c = Config(1, 1, 1, 1, p)
        assert c.id == f"a1-cache-d1-p{p}-l1" and status(c) == "verified" and c.id in SUPPORTED_IDS and c.id not in V1_SUPPORTED_IDS
        for bad in (Config(1, 0, 1, 1, p), Config(1, 1, 2, 1, p), Config(1, 1, 4, 1, p), Config(1, 1, 1, 2, p), Config(2, 1, 1, 1, p),
                    Config(0, 0, 1, 1, p)):
            assert status(bad) == "unsupported"
            with pytest.raises(ValueError):
                validate(bad)
    assert status(Config(1, 1, 1, 1, 8)) == "unsupported"
    with pytest.raises(ValueError, match="unknown PRECISION"):
        profile(8)
    src = (ROOT / "rtl" / "tetris_core.sv").read_text()
    assert "LANES == 1 && DEPTH == 1 && PRECISION >= 0 && PRECISION <= 7" in src


def test_raw_scores_are_not_baseline_units():
    # the scale 76/M is dropped in hardware; conversion is exact rational, never a float comparison
    assert to_baseline_units(-4120, 5) == Fraction(76 * -4120, 15)
    assert to_baseline_units(60, 5) == Fraction(76 * 60, 15) == 304
    assert to_baseline_units(-77, 0) == -77
    assert score_profile((200, 200, 180), 0, 5) == -4120 and score_profile((0, 0, 0), 4, 7) == 12


# Known divergences, checked against the grid oracle

def independent_candidates(rows, piece):
    """Literal set-of-cells descent (tests/reference_grid.py): (candidate_id, lines, A, Q, U) per legal candidate."""
    occupied = cells_from_rows(rows)
    out = []
    for cid in candidate_ids(piece):
        rotation, x = decode_candidate(cid)
        shp = shape(piece, rotation)
        y, legal = ref_landing(occupied, shp.cells, shp.width, x)
        if not legal:
            continue
        after, lines = ref_lock_and_clear(occupied, shp.cells, x, y)
        a, q, u = ref_features(after)
        out.append((cid, lines, a, q, u))
    return out


def test_divergence_fixtures_reproduce_with_reference_and_fast_models():
    for fx in FIXTURE:
        rows, piece = tuple(fx["rows"]), fx["piece"]
        claims = {int(k[1]): v for k, v in fx.items() if k.endswith("_candidate")}
        assert 0 in claims and len(claims) >= 2
        for p, cid in claims.items():
            assert policy.best_move(rows, piece, p)["candidate_id"] == cid, (fx["source_state_id"], p)
            assert fast.best_move_fast(rows, piece, p)["candidate_id"] == cid, (fx["source_state_id"], p)
        # the state is the corpus state it names
        rec = next(r for r in CORPUS if r["id"] == fx["source_state_id"])
        assert tuple(rec["rows"]) == rows and rec["piece"] == piece
    # first fixture: piece O, rotation 0 at x = 8 (exact) versus x = 4 (P6, P7)
    assert FIXTURE[0]["piece"] == 1 and decode_candidate(8) == (0, 8) and decode_candidate(4) == (0, 4)


def test_every_candidate_score_matches_the_independent_reference_for_each_quantized_profile():
    for fx in FIXTURE:
        rows, piece = tuple(fx["rows"]), fx["piece"]
        table = {r["candidate_id"]: r for r in candidate_table(rows, piece, QUANTIZED_PRECISION_IDS)}
        ref = independent_candidates(rows, piece)
        assert sorted(table) == sorted(cid for cid, *_ in ref)
        for cid, lines, a, q, u in ref:
            row = table[cid]
            assert (row["lines"], row["A"], row["Q"], row["U"]) == (lines, a, q, u)
            assert row["score_p0"] == 76 * lines - 51 * a - 36 * q - 18 * u
            for p in QUANTIZED_PRECISION_IDS:
                wl, wa, wq, wu = profile(p).coefficients
                assert row[f"score_p{p}"] == wl * lines - wa * a - wq * q - wu * u
                assert row[f"E_p{p}"] == sum(abs(d) * f for d, f in zip(coefficient_perturbations(p), (lines, a, q, u)))


# Stability certificate

def test_perturbations_and_error_bound():
    assert coefficient_perturbations(5) == (0, -5, -8, 34)
    assert coefficient_perturbations(6) == (0, 23, -24, 26)
    assert coefficient_perturbations(7) == (0, -1, -32, 22)
    for p in QUANTIZED_PRECISION_IDS:
        m = profile(p).levels
        for feats in ((0, 0, 0, 0), (4, 200, 200, 180), (1, 37, 2, 11)):
            l, a, q, u = feats
            exact = 76 * l - 51 * a - 36 * q - 18 * u
            raw = score_profile((a, q, u), l, p)
            assert abs(76 * raw - m * exact) <= error_bound(feats, p), (p, feats)
    with pytest.raises(ValueError):
        coefficient_perturbations(0)


def synthetic(rows_of):
    """Build a candidate table from (candidate_id, L, A, Q, U) tuples for all quantized profiles."""
    table = []
    for cid, l, a, q, u in rows_of:
        row = {"candidate_id": cid, "rotation": cid // 10, "x": cid % 10, "y": 0, "lines": l, "A": a, "Q": q, "U": u,
               "score_p0": 76 * l - 51 * a - 36 * q - 18 * u}
        for p in QUANTIZED_PRECISION_IDS:
            row[f"score_p{p}"] = score_profile((a, q, u), l, p)
            row[f"E_p{p}"] = error_bound((l, a, q, u), p)
        table.append(row)
    return table


def test_certificate_synthetic_cases():
    # a clear winner far ahead: certified for every profile, and unchanged
    far = synthetic([(0, 4, 10, 0, 0), (1, 0, 150, 40, 60), (2, 0, 120, 20, 30)])
    for p in QUANTIZED_PRECISION_IDS:
        c = certify(far, p)
        assert c["certified"] and c["margin_min"] > 0
        assert winner(far, f"score_p{p}")["candidate_id"] == 0
    # intentionally failing bound: exact gap 15 against error bounds in the hundreds -> not certified
    close = synthetic([(3, 0, 40, 5, 10), (5, 0, 39, 7, 8)])       # exact: -2400 vs -2385, winner 5
    assert close[1]["score_p0"] - close[0]["score_p0"] == 15 and winner(close, "score_p0")["candidate_id"] == 5
    for p in QUANTIZED_PRECISION_IDS:
        c = certify(close, p)
        assert not c["certified"] and c["blocking_candidate"] == 3 and c["margin_min"] <= 0
    # bound fails but the decision is unchanged: "not certified" is not "changed" (large U, delta_U = 34 for P5)
    near = synthetic([(0, 0, 20, 4, 60), (1, 0, 21, 4, 60)])       # exact gap 51; E(0)+E(1) = 4349 > 15*51
    a5 = analyze_state(None, None, 5, near)
    assert a5["exact_winner"] == 0 and not a5["changed"] and not a5["certified"] and a5["certificate_margin_min"] < 0
    # the fixture's mechanism, isolated: candidates 8 (28,2,8) and 4 (29,3,4) of state 7 -- exact winner 8 by 15,
    # P6 scores tie at -162 and the lower id 4 wins: changed, tie introduced, not certified
    fx = synthetic([(4, 0, 29, 3, 4), (8, 0, 28, 2, 8)])
    a6 = analyze_state(None, None, 6, fx)
    assert a6["exact_winner"] == 8 and a6["quantized_winner"] == 4 and a6["changed"] and a6["tie_introduced"] and not a6["certified"]
    assert a6["exact_gap"] == 15 and a6["quantized_gap_raw"] == 0 and a6["exact_winner_score_loss_p0"] == 15
    # exact tie: never certified; the quantized profile may break it toward the higher id -> changed
    tie = synthetic([(0, 0, 36, 0, 0), (1, 0, 0, 51, 0)])           # both -1836 exactly
    assert gap(tie, "score_p0") == 0
    for p in QUANTIZED_PRECISION_IDS:
        assert not certify(tie, p)["certified"]
    a7 = analyze_state(None, None, 7, tie)                          # P7: -72 vs -51 -> candidate 1 wins
    assert a7["exact_tie_size"] == 2 and a7["tie_broken"] and a7["changed"] and a7["quantized_winner"] == 1
    # a single legal candidate is trivially certified
    single = synthetic([(4, 1, 30, 2, 5)])
    assert certify(single, 6)["certified"] and certify(single, 6)["reason"] == "single legal candidate"
    assert certify([], 6)["certified"] is False


def test_certificate_soundness_on_the_development_corpus():
    """Certified => unchanged for every state and profile (the tool asserts this too); the guide's planning
    counts are reproduced: 1 / 25 / 87 changed decisions of 981 legal states."""
    changed = {p: 0 for p in QUANTIZED_PRECISION_IDS}
    legal = 0
    certified = {p: 0 for p in QUANTIZED_PRECISION_IDS}
    for rec in CORPUS:
        rows, piece = tuple(rec["rows"]), rec["piece"]
        table = candidate_table(rows, piece, QUANTIZED_PRECISION_IDS)
        if not table:
            continue
        legal += 1
        for p in QUANTIZED_PRECISION_IDS:
            a = analyze_state(rows, piece, p, table)
            assert not (a["certified"] and a["changed"])
            if a["changed"]:
                # the fast model (used by the benchmarks) agrees with the literal reference on the quantized winner
                assert fast.best_move_fast(rows, piece, p)["candidate_id"] == a["quantized_winner"]
            changed[p] += a["changed"]
            certified[p] += a["certified"]
    assert legal == 981
    assert (changed[5], changed[6], changed[7]) == (1, 25, 87)
    assert all(certified[p] > 0 for p in QUANTIZED_PRECISION_IDS)


def test_analysis_tool_summary_schema():
    out = subprocess.run(["bash", str(ROOT / "scripts" / "env.sh"), "python", "tools/analyze_precision_v2.py", "--explain"],
                         cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    doc = json.loads((ROOT / "results" / "v2" / "precision" / "divergence_explanations.json").read_text())
    assert doc["schema"] == "precision-divergence-explanations-v1" and len(doc["states"]) == 2
    s7 = next(s for s in doc["states"] if s["source_state_id"] == 7)
    assert s7["winners"] == {"p0": 8, "p5": 8, "p6": 4, "p7": 4} and len(s7["candidates"]) == 9
    assert all("score_p6_baseline_units" in c for c in s7["candidates"])
    summary = ROOT / "results" / "v2" / "precision" / "development" / "summary.json"
    if summary.is_file():
        d = json.loads(summary.read_text())
        assert d["schema"] == "precision-sensitivity-v1" and d["split"] == "development" and "planning" in d["label"]
        for c in d["corpora"]:
            for pp in c["profiles"].values():
                assert pp["certified_and_changed"] == 0
                assert pp["certified_unchanged"] + pp["not_certified"] == pp["legal_states"]
                assert pp["not_certified_but_unchanged"] + pp["changed"] == pp["not_certified"]
