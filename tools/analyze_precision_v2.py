#!/usr/bin/env python3
"""Compare P5–P7 with exact P0 on the same boards.

This is a decision-sensitivity study, not a comparison of already-diverged games. It records ties,
score gaps, sacrificed P0 score, and the integer stability certificate. Development data stays
labelled as development data because it helped choose the ladder.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model.numeric import QUANTIZED_PRECISION_IDS, profile_metadata, to_baseline_units  # noqa: E402
from model.sensitivity import analyze_state, candidate_table, perturbation_summary, winner  # noqa: E402

OUT_ROOT = ROOT / "results" / "v2" / "precision"
FIXTURE = ROOT / "tests" / "fixtures" / "precision_v2_divergences.json"
SPLITS = {
    "development": {"label": "development (planning data: chose the ladder; not a final evaluation)",
                    "corpora": ["benchmarks/states/corpus_d1.jsonl", "benchmarks/states/corpus_d1_upgrade_dev.jsonl"]},
    "heldout": {"label": "held-out common-state corpus (frozen before use, U16)",
                "corpora": ["benchmarks/states/corpus_v2_heldout.jsonl"]},
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_corpus(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def quantiles(values):
    vals = sorted(values)
    if not vals:
        return None
    def q(f):
        return vals[min(len(vals) - 1, int(round(f * (len(vals) - 1))))]
    return {"n": len(vals), "min": vals[0], "p10": q(0.10), "p25": q(0.25), "median": q(0.5), "p75": q(0.75), "p90": q(0.90),
            "max": vals[-1], "mean": round(statistics.mean(vals), 2)}


def analyze_corpus(path: Path, precisions, out_dir: Path) -> dict:
    recs = load_corpus(path)
    name = path.stem
    per_profile = {}
    writers = {}
    for p in precisions:
        writers[p] = open(out_dir / f"states_{name}_p{p}.jsonl", "w")
    counts = {p: {"legal_states": 0, "multi_candidate_states": 0, "changed": 0, "certified": 0, "not_certified": 0,
                  "exact_ties": 0, "ties_introduced": 0, "ties_broken": 0, "changed_with_exact_tie": 0,
                  "gap_changed": [], "gap_unchanged": [], "loss_changed": [], "rank_changed": [], "certified_and_changed": 0,
                  "changed_ids": []} for p in precisions}
    no_move = 0
    for r in recs:
        rows, piece = tuple(r["rows"]), r["piece"]
        table = candidate_table(rows, piece, precisions)
        if not table:
            no_move += 1
            continue
        for p in precisions:
            a = analyze_state(rows, piece, p, table)
            a["state_id"] = r["id"]
            a["category"] = r.get("category")
            a["piece"] = piece
            writers[p].write(json.dumps(a) + "\n")
            c = counts[p]
            c["legal_states"] += 1
            c["multi_candidate_states"] += a["legal_candidates"] >= 2
            c["changed"] += a["changed"]
            c["certified"] += a["certified"]
            c["not_certified"] += not a["certified"]
            c["exact_ties"] += a["exact_tie_size"] > 1
            c["ties_introduced"] += a["tie_introduced"]
            c["ties_broken"] += a["tie_broken"]
            c["certified_and_changed"] += a["certified"] and a["changed"]
            if a["exact_gap"] is not None:
                (c["gap_changed"] if a["changed"] else c["gap_unchanged"]).append(a["exact_gap"])
            if a["changed"]:
                c["loss_changed"].append(a["exact_winner_score_loss_p0"])
                c["rank_changed"].append(a["exact_winner_quantized_rank"])
                c["changed_with_exact_tie"] += a["exact_tie_size"] > 1
                if len(c["changed_ids"]) < 200:
                    c["changed_ids"].append(r["id"])
    for w in writers.values():
        w.close()
    for p in precisions:
        c = counts[p]
        legal = c["legal_states"]
        per_profile[f"p{p}"] = {
            "precision": p, "legal_states": legal, "multi_candidate_states": c["multi_candidate_states"],
            "changed": c["changed"], "changed_rate": round(c["changed"] / legal, 4) if legal else None,
            "certified_unchanged": c["certified"], "not_certified": c["not_certified"],
            "not_certified_but_unchanged": c["not_certified"] - c["changed"],
            "certified_and_changed": c["certified_and_changed"],          # must be 0 (soundness)
            "exact_ties": c["exact_ties"], "changed_with_exact_tie": c["changed_with_exact_tie"],
            "ties_introduced": c["ties_introduced"], "ties_broken": c["ties_broken"],
            "exact_gap_changed": quantiles(c["gap_changed"]), "exact_gap_unchanged": quantiles(c["gap_unchanged"]),
            "p0_score_loss_changed": quantiles(c["loss_changed"]),
            "exact_winner_rank_changed": quantiles(c["rank_changed"]),
            "changed_state_ids": c["changed_ids"],
        }
        assert per_profile[f"p{p}"]["certified_and_changed"] == 0, "certificate soundness violated"
    return {"corpus": str(path.relative_to(ROOT)), "sha256": sha256_file(path), "states": len(recs), "no_move_states": no_move,
            "profiles": per_profile}


def explain_fixtures(out_path: Path) -> dict:
    fixtures = json.loads(FIXTURE.read_text())
    out = {"schema": "precision-divergence-explanations-v1", "fixture": str(FIXTURE.relative_to(ROOT)),
           "fixture_sha256": sha256_file(FIXTURE), "note": "candidate tables derived by model.policy (literal descent); "
           "raw P5-P7 scores are in their own units, baseline_units = 76*score/M", "states": []}
    for fx in fixtures:
        rows, piece = tuple(fx["rows"]), fx["piece"]
        table = candidate_table(rows, piece, QUANTIZED_PRECISION_IDS)
        claims = {int(k[1]): v for k, v in fx.items() if k.endswith("_candidate")}
        winners = {0: winner(table, "score_p0")["candidate_id"]}
        for p in QUANTIZED_PRECISION_IDS:
            winners[p] = winner(table, f"score_p{p}")["candidate_id"]
        for p, cid in claims.items():
            if winners[p] != cid:
                raise SystemExit(f"fixture state {fx['source_state_id']}: P{p} winner {winners[p]} != claimed {cid}")
        for row in table:
            for p in QUANTIZED_PRECISION_IDS:
                bu = to_baseline_units(row[f"score_p{p}"], p)
                row[f"score_p{p}_baseline_units"] = f"{bu.numerator}/{bu.denominator}" if bu.denominator != 1 else str(bu.numerator)
        analyses = {f"p{p}": analyze_state(rows, piece, p, table) for p in QUANTIZED_PRECISION_IDS}
        out["states"].append({"source_state_id": fx["source_state_id"], "rows": list(rows), "piece": piece, "claims": fx,
                              "winners": {f"p{k}": v for k, v in winners.items()}, "candidates": table, "analysis": analyses})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=1) + "\n")
    return out


def write_csv(summary: dict, path: Path):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["split", "corpus", "precision", "name", "legal_states", "changed", "changed_rate", "certified_unchanged",
                    "not_certified_but_unchanged", "exact_ties", "ties_introduced", "ties_broken", "median_exact_gap_changed",
                    "median_exact_gap_unchanged", "median_p0_loss_changed"])
        for c in summary["corpora"]:
            for key, pp in c["profiles"].items():
                w.writerow([summary["split"], c["corpus"], pp["precision"], profile_metadata(pp["precision"])["name"], pp["legal_states"],
                            pp["changed"], pp["changed_rate"], pp["certified_unchanged"], pp["not_certified_but_unchanged"],
                            pp["exact_ties"], pp["ties_introduced"], pp["ties_broken"],
                            (pp["exact_gap_changed"] or {}).get("median"), (pp["exact_gap_unchanged"] or {}).get("median"),
                            (pp["p0_score_loss_changed"] or {}).get("median")])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=sorted(SPLITS), default=None)
    ap.add_argument("--corpus", action="append", default=None, help="override the split's corpora (repeatable)")
    ap.add_argument("--profiles", default=",".join(str(p) for p in QUANTIZED_PRECISION_IDS))
    ap.add_argument("--explain", action="store_true", help="write the fixture explanations only")
    args = ap.parse_args()
    precisions = tuple(int(x) for x in args.profiles.split(","))
    if args.explain or args.split is None:
        doc = explain_fixtures(OUT_ROOT / "divergence_explanations.json")
        for s in doc["states"]:
            print(f"fixture state {s['source_state_id']} piece {s['piece']}: winners {s['winners']} ({len(s['candidates'])} legal candidates)")
        print(f"-> {OUT_ROOT.relative_to(ROOT) / 'divergence_explanations.json'}")
        if args.split is None:
            return 0
    split = SPLITS[args.split]
    corpora = [ROOT / c for c in (args.corpus or split["corpora"])]
    missing = [c for c in corpora if not c.is_file()]
    if missing:
        raise SystemExit(f"corpus missing for split {args.split}: {', '.join(str(m.relative_to(ROOT)) for m in missing)}")
    out_dir = OUT_ROOT / args.split
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {"schema": "precision-sensitivity-v1", "split": args.split, "label": split["label"],
               "recorded_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "profiles": {f"p{p}": {**profile_metadata(p), **perturbation_summary(p)} for p in precisions},
               "definitions": {
                   "changed": "quantized winner (highest raw score, ties to the lower id) differs from the exact winner",
                   "exact_gap": "exact best score minus exact runner-up score (P0 units; 0 = exact tie)",
                   "certified_unchanged": "M*(S(g)-S(c)) > E(g)+E(c) for every other legal c, E(c) = sum |delta_i| f_i(c)",
                   "not_certified": "the bound fails for at least one candidate; the decision may still be unchanged",
                   "p0_score_loss": "S(g) - S(h): exact score given up by the quantized choice h",
               },
               "corpora": [analyze_corpus(c, precisions, out_dir) for c in corpora]}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    write_csv(summary, out_dir / "disagreement.csv")
    for c in summary["corpora"]:
        print(f"{c['corpus']}: {c['states']} states, {c['no_move_states']} without a legal move")
        for key, pp in c["profiles"].items():
            print(f"  P{pp['precision']}: changed {pp['changed']}/{pp['legal_states']} ({100 * pp['changed_rate']:.2f}%), "
                  f"certified unchanged {pp['certified_unchanged']}, not certified but unchanged {pp['not_certified_but_unchanged']}, "
                  f"exact ties {pp['exact_ties']}, ties introduced {pp['ties_introduced']}, broken {pp['ties_broken']}; "
                  f"median exact gap changed/unchanged {(pp['exact_gap_changed'] or {}).get('median')}/{(pp['exact_gap_unchanged'] or {}).get('median')}")
    print(f"CHECK precision_sensitivity {sum(len(c['profiles']) for c in summary['corpora'])}/{sum(len(c['profiles']) for c in summary['corpora'])}")
    print(f"-> {out_dir.relative_to(ROOT) / 'summary.json'} [{split['label']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
