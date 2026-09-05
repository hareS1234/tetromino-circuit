"""U15: v2 long-horizon benchmark machinery — disjoint stream splits with content hashes, summary mode
identical to replay mode, checkpoints that resume only on an exact identity match, crashes recorded as
failed jobs, the held-out guard and the freeze record."""
import gzip
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from model import streams_v2  # noqa: E402
from model.longrun import CHECKPOINT_SCHEMA, SoftwarePolicy, load_checkpoint, play_summary, trajectory_hash_of_records  # noqa: E402
from model.replay import make_decider, play_game  # noqa: E402
from model.streams import SPLITS  # noqa: E402
from tools import bench  # noqa: E402

PROTO = ROOT / "benchmarks" / "config_v2.json"


# ---- streams ----------------------------------------------------------------------------------------------------

def test_v2_splits_are_disjoint_from_v1_and_streams_verify():
    v1 = {s for r in SPLITS.values() for s in r}
    v2 = {s for r in streams_v2.SPLITS_V2.values() for s in r}
    assert not (v1 & v2)
    assert streams_v2.SPLITS_V2["v2_development"] == range(10000, 10020) and streams_v2.SPLITS_V2["v2_heldout"] == range(20000, 20100)
    m = streams_v2.load_manifest(ROOT)
    assert m["schema"] == "stream-manifest-v2" and m["length"] == 50_001 and len(m["streams"]) >= 120
    doc = streams_v2.load_stream_v2(ROOT, 10000)
    assert doc["length"] == 50_001 and doc["split"] == "v2_development" and set(doc["pieces"]) <= set(range(7))
    # seven-bag structure: every aligned block of seven is a permutation
    for i in range(0, 49_000, 7):
        assert sorted(doc["pieces"][i:i + 7]) == list(range(7))
    # content hash is over the decoded bytes and reproduces from the generator
    assert doc["sha256"] == streams_v2.content_sha256(streams_v2.generate_pieces(10000))
    assert streams_v2.decode_names(doc["pieces"], 3).count(" ") == 2
    # the v1 manifest and streams are untouched by the v2 machinery
    v1m = json.loads((ROOT / "benchmarks" / "streams" / "manifest.json").read_text())
    assert v1m["length"] == 2001 and "10000" not in v1m["streams"]


def test_tampered_stream_is_rejected(tmp_path):
    root = tmp_path
    (root / "benchmarks" / "streams_v2").mkdir(parents=True)
    manifest = streams_v2.load_manifest(root)
    streams_v2.write_stream_v2(root, 10000, length=700, manifest=manifest)
    streams_v2.write_manifest(root, manifest)
    assert streams_v2.check_manifest(root) == [] or all("regeneration" in p for p in streams_v2.check_manifest(root))
    path = streams_v2.stream_file(root, 10000)
    data = bytearray(gzip.decompress(path.read_bytes()))
    data[5] = (data[5] + 1) % 7
    path.write_bytes(gzip.compress(bytes(data)))
    with pytest.raises(ValueError, match="hash"):
        streams_v2.load_stream_v2(root, 10000)
    with pytest.raises(FileNotFoundError):
        streams_v2.load_stream_v2(root, 10001)


# ---- protocol ----------------------------------------------------------------------------------------------------

def test_protocol_v2_checks_and_workloads():
    proto = bench.load_protocol(PROTO)
    assert bench.check_protocol(proto) == []
    assert proto["name"] == "quality-v2-bag50k" and proto["suites"]["bag50k"]["role"] == "held-out"
    assert proto["suites"]["bag50k"]["cap"] == 50_000 and proto["suites"]["bag50k"]["streams"]["seeds"] == [20000, 20099]
    assert proto["statistics"]["bootstrap_resamples"] == 5000
    w = bench.workload(proto, "bag50k")
    assert (w["games"], w["max_decisions"]) == (600, 30_000_000)
    assert bench.workload(proto, "pilot")["games"] == 120
    pols = {(p["policy"], p["precision"]) for p in proto["suites"]["bag50k"]["policies"]}
    assert pols == {("heuristic", 0), ("heuristic", 1), ("heuristic", 5), ("heuristic", 6), ("heuristic", 7), ("random_legal", 0)}
    # a held-out suite whose split/role disagree, or a seed outside its split, is rejected
    bad = json.loads(PROTO.read_text())
    bad["suites"]["bag50k"]["streams"]["seeds"] = [20000, 20100]
    bad["_path"], bad["_sha256"] = "x", "y"
    assert any("not in split" in p for p in bench.check_protocol(bad))
    bad = json.loads(PROTO.read_text())
    bad["suites"]["pilot"]["role"] = "held-out"
    bad["_path"], bad["_sha256"] = "x", "y"
    assert any("does not match split" in p for p in bench.check_protocol(bad))


# ---- summary mode, checkpoints, resume ---------------------------------------------------------------------------

@pytest.mark.parametrize("policy,precision,cap", [("heuristic", 0, 600), ("heuristic", 7, 1500), ("random_legal", 0, 300)])
def test_summary_mode_matches_replay_mode(policy, precision, cap):
    stream = streams_v2.load_stream_v2(ROOT, 10001)
    records, terminal = play_game(make_decider(policy, 1, precision, 10001, "fast"), stream, cap)
    sp = SoftwarePolicy(policy, precision, 10001)
    term = play_summary(sp, stream["pieces"], cap, checkpoint_every=100)
    assert (term["pieces_locked"], term["lines"], term["reason"]) == (terminal["pieces_locked"], terminal["lines"], terminal["reason"])
    assert term["trajectory_sha256"] == trajectory_hash_of_records(records)
    assert term["event_observed"] == (terminal["reason"] == "top_out") and term["duration"] == terminal["pieces_locked"]
    if records:
        # the final board of the replay is the board the summary run ended on (via the identical trajectory)
        assert records[-1]["cumulative_lines"] == term["lines"]


def test_interrupted_game_resumes_from_checkpoint_to_the_same_result(tmp_path):
    stream = streams_v2.load_stream_v2(ROOT, 10002)
    cap = 900
    ident = {"quality_key": "k1", "protocol_sha256": "p", "policy": {"policy": "random_legal", "depth": 1, "precision": 0},
             "stream_sha256": stream["sha256"], "cap": cap, "model_closure": "m"}
    ck = tmp_path / "ck.json"
    # uninterrupted reference
    ref = play_summary(SoftwarePolicy("random_legal", 0, 10002), stream["pieces"], cap, checkpoint_every=100)
    # random_legal on 900 pieces tops out early; use a heuristic game for a long interrupted run too
    ident_h = {**ident, "policy": {"policy": "heuristic", "depth": 1, "precision": 0}, "quality_key": "k2"}
    ck_h = tmp_path / "ck_h.json"
    ref_h = play_summary(SoftwarePolicy("heuristic", 0, 10002), stream["pieces"], cap, checkpoint_every=100)
    with pytest.raises(InterruptedError):
        play_summary(SoftwarePolicy("heuristic", 0, 10002), stream["pieces"], cap, identity=ident_h, checkpoint_path=ck_h,
                     checkpoint_every=100, stop_after=450)
    saved = json.loads(ck_h.read_text())
    assert saved["schema"] == CHECKPOINT_SCHEMA and saved["status"] == "running" and saved["piece_index"] == 400 and saved["identity"] == ident_h
    resumed = play_summary(SoftwarePolicy("heuristic", 0, 10002), stream["pieces"], cap, identity=ident_h, checkpoint_path=ck_h, checkpoint_every=100)
    assert resumed["resumed_from"] == 400
    assert (resumed["pieces_locked"], resumed["lines"], resumed["reason"], resumed["trajectory_sha256"]) == \
        (ref_h["pieces_locked"], ref_h["lines"], ref_h["reason"], ref_h["trajectory_sha256"])
    final = json.loads(ck_h.read_text())
    assert final["status"] == "complete" and final["terminal"]["lines"] == ref_h["lines"] and ck_h.with_suffix(".json.prev").is_file()
    # random policy: RNG state travels through the checkpoint (stop mid-game at a checkpoint boundary)
    rnd_stream = streams_v2.load_stream_v2(ROOT, 10003)
    long_ref = play_summary(SoftwarePolicy("random_legal", 0, 10003), rnd_stream["pieces"], 2000, checkpoint_every=10)
    if long_ref["pieces_locked"] > 20:
        with pytest.raises(InterruptedError):
            play_summary(SoftwarePolicy("random_legal", 0, 10003), rnd_stream["pieces"], 2000, identity=ident, checkpoint_path=ck,
                         checkpoint_every=10, stop_after=15)
        res = play_summary(SoftwarePolicy("random_legal", 0, 10003), rnd_stream["pieces"], 2000, identity=ident, checkpoint_path=ck, checkpoint_every=10)
        assert res["resumed_from"] == 10 and res["trajectory_sha256"] == long_ref["trajectory_sha256"] and res["lines"] == long_ref["lines"]
    # a fresh SoftwarePolicy without the checkpoint's RNG state would diverge: the checkpoint stores the state
    assert ref["reason"] in ("top_out", "cap_reached")


def test_checkpoint_resumes_only_on_exact_identity(tmp_path):
    stream = streams_v2.load_stream_v2(ROOT, 10004)
    ident = {"quality_key": "k", "protocol_sha256": "p", "policy": {"policy": "heuristic", "depth": 1, "precision": 0},
             "stream_sha256": stream["sha256"], "cap": 500, "model_closure": "m"}
    ck = tmp_path / "ck.json"
    with pytest.raises(InterruptedError):
        play_summary(SoftwarePolicy("heuristic", 0, 10004), stream["pieces"], 500, identity=ident, checkpoint_path=ck,
                     checkpoint_every=100, stop_after=250)
    assert load_checkpoint(ck, ident)["piece_index"] == 200
    for changed in ({**ident, "cap": 600}, {**ident, "model_closure": "other"}, {**ident, "stream_sha256": "x"},
                    {**ident, "policy": {"policy": "heuristic", "depth": 1, "precision": 5}}):
        assert load_checkpoint(ck, changed) is None
        fresh = play_summary(SoftwarePolicy("heuristic", 0, 10004), stream["pieces"], 500, identity=changed, checkpoint_path=tmp_path / "other.json",
                             checkpoint_every=100)
        assert fresh["resumed_from"] is None
    # a corrupt current checkpoint falls back to the retained previous one
    good = json.loads(ck.read_text())
    ck.write_text("{not json")
    prev = ck.with_suffix(".json.prev")
    assert prev.is_file() and load_checkpoint(ck, ident)["piece_index"] == 100
    ck.write_text(json.dumps(good))
    # a completed checkpoint is not resumed (the game is over; the record is the result)
    done = play_summary(SoftwarePolicy("heuristic", 0, 10004), stream["pieces"], 500, identity=ident, checkpoint_path=ck, checkpoint_every=100)
    assert done["resumed_from"] == 200 and load_checkpoint(ck, ident) is None


# ---- runner: records, failures, guards ---------------------------------------------------------------------------------

def test_run_suite_summary_mode_records_and_crash_is_a_failed_job(tmp_path, monkeypatch):
    proto = bench.load_protocol(PROTO)
    out = tmp_path / "v2"
    r = bench.run_suite_v2(proto, "pilot", out, seeds=[10000, 10001], cap=300, mode="summary", checkpoint_every=100, quiet=True)
    assert (r["run"], r["reused"], r["failed"]) == (12, 0, 0) and set(r["per_policy"]) == {bench.policy_key(p) for p in proto["suites"]["pilot"]["policies"]}
    recs = bench.v2_records(out)
    assert len(recs) == 12
    for d in recs.values():
        assert d["mode"] == "summary" and d["status"] == "complete" and d["cap"] == 300
        assert d["duration"] == d["pieces_locked"] and d["event_observed"] == (d["terminal_reason"] == "top_out")
        assert len(d["trajectory_sha256"]) == 64 and d["checkpoints_written"] >= 1 and d["peak_rss_mb_process"] > 0
        assert (ROOT / d["checkpoint"]).is_file() if d["checkpoint"] and not d["checkpoint"].startswith("/") else True
    # identical re-run reuses every record; the same jobs in replay mode give the same trajectories
    again = bench.run_suite_v2(proto, "pilot", out, seeds=[10000, 10001], cap=300, mode="summary", quiet=True)
    assert (again["run"], again["reused"]) == (0, 12)
    out2 = tmp_path / "v2b"
    bench.run_suite_v2(proto, "pilot", out2, seeds=[10000, 10001], cap=300, mode="replay", quiet=True)
    by_key = {k: d["trajectory_sha256"] for k, d in bench.v2_records(out2).items()}
    assert by_key == {k: d["trajectory_sha256"] for k, d in recs.items()}
    # a crash inside a game is a failed job: a .failed.json record, no outcome, nonzero failed count
    def boom(self, rows, piece):
        raise RuntimeError("simulated crash")
    monkeypatch.setattr(bench.SoftwarePolicy, "decide", boom)
    out3 = tmp_path / "v2c"
    r3 = bench.run_suite_v2(proto, "pilot", out3, seeds=[10000], cap=50, mode="summary", quiet=True)
    assert r3["failed"] == 6 and r3["run"] == 0 and bench.v2_records(out3) == {}
    failed = list((out3 / "raw" / "quality").glob("*.failed.json"))
    assert len(failed) == 6 and all(json.loads(f.read_text())["status"] == "failed" for f in failed)
    assert all("simulated crash" in json.loads(f.read_text())["error"] for f in failed)


def test_analysis_rejects_incomplete_sets_and_reports_when_complete(tmp_path):
    proto = bench.load_protocol(PROTO)
    out = tmp_path / "v2"
    # build a tiny complete paired set by running the pilot suite on two streams at a small cap and
    # analysing a copy of the protocol whose pilot suite is exactly that
    small = json.loads(PROTO.read_text())
    small["suites"] = {"pilot": {**small["suites"]["pilot"], "streams": {"split": "v2_development", "seeds": [10005, 10006]}, "cap": 200}}
    small["statistics"]["bootstrap_resamples"] = 200
    spath = tmp_path / "small.json"
    spath.write_text(json.dumps(small))
    sproto = bench.load_protocol(spath)
    r = bench.run_suite_v2(sproto, "pilot", out, mode="summary", quiet=True)
    assert r["failed"] == 0
    from tools import analyze_quality_v2 as aq
    rows, problems = aq.collect(sproto, "pilot", out)
    assert problems == [] and all(len(v) == 2 for v in rows.values())
    doc = aq.analyse(sproto, "pilot", rows, None)
    assert doc["schema"] == "quality-analysis-v2" and set(doc["policies"]) == {bench.policy_key(p) for p in small["suites"]["pilot"]["policies"]}
    p0 = doc["policies"]["heuristic-d1-p0"]
    assert p0["restricted_mean_pieces"]["value"] <= 200 and 0 <= p0["cap_hit_fraction"]["value"] <= 1
    assert p0["median_statement"].startswith("not reached") or isinstance(p0["median_survival"], int)
    rnd = doc["policies"]["random_legal-d1-p0"]
    assert rnd["top_outs_observed"] == 2 and isinstance(rnd["median_survival"], int)           # random tops out within 200 pieces
    assert doc["comparisons"]["random_legal-d1-p0"]["restricted_mean_pieces"]["mean_diff"] < 0
    aq.plot_survival(doc, tmp_path / "s.png")
    assert (tmp_path / "s.png").stat().st_size > 1000
    # remove one record: incomplete pairing is refused
    key = rows["heuristic-d1-p0"][0]["quality_key"]
    (out / "raw" / "quality" / f"{key}.json").unlink()
    rows2, problems2 = aq.collect(sproto, "pilot", out)
    assert any("missing" in p for p in problems2)


def test_cli_guards_dry_run_pilot_freeze(tmp_path):
    env_root = tmp_path / "out"
    def run(*args):
        return subprocess.run(["bash", str(ROOT / "scripts" / "env.sh"), "python", "tools/bench.py", "--config", "benchmarks/config_v2.json",
                               "--out-root", str(env_root.relative_to(ROOT)) if env_root.is_relative_to(ROOT) else str(env_root), *args],
                              cwd=ROOT, capture_output=True, text=True)
    r = run("--mode", "dry-run")
    assert r.returncode == 0 and "600 games" in r.stdout and "30,000,000 decisions" in r.stdout and "freeze record: absent" in r.stdout
    # pilot never opens held-out outcomes
    r = run("--mode", "pilot", "--suite", "bag50k")
    assert r.returncode != 0 and "never opens held-out" in r.stdout + r.stderr
    # the held-out suite needs a freeze record first
    r = run("--mode", "run", "--suite", "bag50k")
    assert r.returncode != 0 and "freeze" in r.stdout + r.stderr
    r = run("--mode", "freeze")
    assert r.returncode == 0, r.stdout + r.stderr
    fz = json.loads((env_root / "protocol" / "freeze_quality-v2-bag50k.json").read_text())
    assert fz["schema"] == "quality-freeze-v1" and len(fz["streams"]) == 120 and len(fz["model_closure"]) == 64 and fz["analysis"]["statistics"]["bootstrap_resamples"] == 5000
    # a held-out run refuses overrides even after freezing
    r = run("--mode", "run", "--suite", "bag50k", "--cap", "10")
    assert r.returncode != 0 and "exactly as frozen" in r.stdout + r.stderr
