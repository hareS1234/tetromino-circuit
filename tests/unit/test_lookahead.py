"""Depth-two reference (E13): the frozen 250-case corpus covers root/leaf ties, all-terminal
fallback, no current move, differing previews, and late winning roots.  Verifies that S2 uses
leaf-board penalties exactly once, that the accelerated model agrees, and that the committed
expectations are current."""
import json
from pathlib import Path

import pytest

from model import fast, lookahead
from model.features import features
from model.game import legal_actions, lock_and_clear
from model.numeric import score_profile
from model.pieces import candidate_ids

ROOT = Path(__file__).resolve().parents[2]
CORPUS = [json.loads(l) for l in (ROOT / "benchmarks" / "states" / "corpus_d2.jsonl").read_text().splitlines() if l.strip()]


def brute_force(rows, piece, nxt):
    """Independent restatement: enumerate (root, leaf) pairs with explicit S2 arithmetic."""
    best_surv = None
    best_fb = None
    for r1, x1, y1 in legal_actions(rows, piece):
        b1, l1 = lock_and_clear(rows, piece, r1, x1, y1)
        a1, q1, u1 = features(b1)
        s1 = 76 * l1 - 51 * a1 - 36 * q1 - 18 * u1
        rid = 10 * r1 + x1
        leaf_best = None
        for r2, x2, y2 in legal_actions(b1, nxt):
            b2, l2 = lock_and_clear(b1, nxt, r2, x2, y2)
            a2, q2, u2 = features(b2)
            s2 = 76 * (l1 + l2) - 51 * a2 - 36 * q2 - 18 * u2   # penalties on the leaf board only
            if leaf_best is None or s2 > leaf_best:
                leaf_best = s2
        if leaf_best is not None and (best_surv is None or leaf_best > best_surv[0]):
            best_surv = (leaf_best, rid, r1, x1, y1)
        if best_fb is None or s1 > best_fb[0]:
            best_fb = (s1, rid, r1, x1, y1)
    if best_surv:
        return {"score": best_surv[0], "candidate_id": best_surv[1], "rotation": best_surv[2], "x": best_surv[3], "y": best_surv[4], "surviving": True}
    if best_fb:
        return {"score": best_fb[0], "candidate_id": best_fb[1], "rotation": best_fb[2], "x": best_fb[3], "y": best_fb[4], "surviving": False}
    return None


def test_corpus_size_and_categories():
    cats = {}
    for r in CORPUS:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    assert len(CORPUS) == 250
    for need in ("root_ties", "all_terminal_fallback", "no_current_move", "differing_previews", "late_root_winner"):
        assert cats.get(need, 0) > 0, f"corpus lacks {need}"


@pytest.mark.parametrize("rec", CORPUS, ids=[f"{r['id']}-{r['category']}" for r in CORPUS])
def test_reference_matches_brute_force_and_fast_model(rec):
    rows, piece, nxt = tuple(rec["rows"]), rec["piece"], rec["next_piece"]
    ref = lookahead.best_move_depth2(rows, piece, nxt)
    bf = brute_force(rows, piece, nxt)
    fm = fast.best_move_depth2_fast(rows, piece, nxt)
    exp = rec["expected"]
    if bf is None:
        assert ref is None and fm is None and exp["no_move"]
        return
    for got in (ref, fm):
        assert got is not None
        assert (got["rotation"], got["x"], got["y"], got["score"], got["surviving"]) == \
            (bf["rotation"], bf["x"], bf["y"], bf["score"], bf["surviving"])
    assert (exp["rotation"], exp["x"], exp["y"], exp["score"], exp["surviving"]) == \
        (bf["rotation"], bf["x"], bf["y"], bf["score"], bf["surviving"]), "committed expectation stale"


def test_surviving_preferred_over_fallback_and_score_convention():
    surv = [r for r in CORPUS if r["expected"].get("surviving")]
    fb = [r for r in CORPUS if not r["expected"]["no_move"] and not r["expected"]["surviving"]]
    assert surv and fb
    for r in fb:
        rec = lookahead.best_move_depth2(tuple(r["rows"]), r["piece"], r["next_piece"])
        assert rec["score"] == rec["score_s1"]          # fallback returns S1
        assert rec["leaf_count"] == 0
    for r in surv[:20]:
        rec = lookahead.best_move_depth2(tuple(r["rows"]), r["piece"], r["next_piece"])
        assert rec["leaf_count"] > 0
        assert rec["score"] == rec["leaf"]["lines"] * 76 + rec["lines"] * 76 - 51 * rec["leaf"]["A"] - 36 * rec["leaf"]["Q"] - 18 * rec["leaf"]["U"]


def test_late_root_winner_cases_are_last_dense_index():
    for r in [r for r in CORPUS if r["category"] == "late_root_winner"]:
        assert r["expected"]["candidate_id"] == candidate_ids(r["piece"])[-1]


def test_differing_previews_change_decisions():
    groups = {}
    for r in [r for r in CORPUS if r["category"] == "differing_previews"]:
        groups.setdefault(tuple(r["rows"]), set()).add((r["expected"]["rotation"], r["expected"]["x"]))
    assert any(len(v) > 1 for v in groups.values()), "no board where the preview changes the root choice"


def test_score_bound_two_moves():
    assert max(r["expected"]["score"] for r in CORPUS if not r["expected"]["no_move"]) <= 608
