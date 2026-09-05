# Quality protocol v2: long-horizon games and censoring-aware statistics (U15/U16)

v1 measured game quality on 2,000-piece streams with a 2,000-piece cap (`benchmarks/config.json`,
`results/quality.csv`; frozen). Most good policies hit that cap, so v1 could only compare lines
within a fixed short horizon. v2 asks the longer question — how long does each policy survive and
how many lines does it clear before a 50,000-piece cap — on fresh streams, with statistics that treat
the cap as what it is: administrative censoring.

## 1. Protocol `quality-v2-bag50k` (`benchmarks/config_v2.json`)

| Field | Value |
|---|---|
| Rules | `drop-v1.1`, unchanged (`model/game.py` literal descent is the oracle for every move) |
| Streams | seven-bag (`model.streams.seven_bag`, the v1 generator) run to **50,001 pieces**, stored as one byte per piece (`benchmarks/streams_v2/stream_<seed>.bin.gz`) with content hashes in `benchmarks/streams_v2/manifest.json` (`stream-manifest-v2`); `python tools/streams_v2.py check` re-hashes and regenerates every entry, `decode` prints piece names |
| Development streams | seeds 10000–10019 (20) — disjoint from every v1 split (1000–1049, 2000–2019, 3000–3099; asserted at import) |
| Held-out streams | seeds 20000–20099 (100); 30000–30099 reserved for the optional i.i.d. suite (not generated) |
| Cap | 50,000 successfully locked pieces (`pilot` suite: 10,000) |
| Policies | depth-one `heuristic` P0, P1, P5, P6, P7 and `random_legal` (own RNG seeded from the stream seed; it never touches the piece generator) |
| Outcomes | restricted mean locked pieces `mean(min(T, C))`, mean lines by the cap, cap-hit fraction; survival curves; every policy paired against P0 |
| Intervals | paired bootstrap over stream ids (whole streams), 5,000 resamples, seed 20260905, 2.5/97.5 percentiles |
| Execution | software model (`python-fast`) whose decisions passed their own-reference RTL tests (`results/v2/raw/decisions/`), summary mode with checkpoints every 1,000 pieces |

Suites: `pilot` (development, cap 10,000, all six policies), `pilot50k` (development, cap 50,000,
P0 and the strongest pilot policy), `bag50k` (held-out, the primary study). A suite's `role` must
match its split; `bench-v2 MODE=pilot` refuses held-out suites, and a held-out run requires a freeze
record whose protocol hash and model closure match (`MODE=freeze`, schema `quality-freeze-v1`:
canonical protocol, every stream hash, model/source/toolchain identities, analysis definition,
freeze time — a reproducibility record, not proof that nobody looked at data). Held-out runs accept
no `--seeds`/`--cap` overrides.

## 2. Execution: summary mode, checkpoints, identities

`model/longrun.py::play_summary` keeps the board, the stream index, the totals, a chained
trajectory hash (`h_i = sha256(h_{i-1} | move)`) and the random policy's RNG state; it writes a
checkpoint (`quality-checkpoint-v1`, atomic replace, previous checkpoint retained as `.prev`) every
1,000 locked pieces and at completion, and resumes only from a checkpoint whose identity (quality
key, protocol hash, policy, stream hash, cap, model closure) matches exactly. Summary mode and the
per-move replay mode make the same decisions: the tests compare them on short games by trajectory
hash, totals and terminal reason for P0, P7 and the random policy, interrupt a game at a checkpoint
boundary and resume it to the identical result (RNG state included), and show that a changed
identity or a completed checkpoint is not resumed while a corrupt current checkpoint falls back to
its retained predecessor.

Each game is one atomic record `results/v2/raw/quality/<quality_key>.json` (`quality-record-v2`,
key from `tools/identity.py`: protocol content, policy, stream hash, cap, model closure, runtime)
with `duration`, `event_observed`, `trajectory_sha256`, wall time and process peak RSS. A crash is
recorded as `<key>.failed.json` and counted as a failed job — never as a top-out or a censoring —
and the analysis refuses to summarise while one exists. Progress prints at most every 60 s (jobs
done/total, active job, ETA). `bench-v2 MODE=dry-run` prints the workload per suite (games,
decision upper bound, complete records) without running anything.

## 3. Statistics (`model/survival.py`, `tools/analyze_quality_v2.py`)

Event time `T` = locked pieces before the first top-out decision (an immediate top-out has
`T = 0`); a game stopped at the cap reports duration `C` with `event_observed = false`. With a common
cap and no other missing observations `mean(min(T, C))` is the mean of the reported durations and
equals `Σ_{t<C} S(t)` of the product-limit survival `S(t) = P(T > t)` — the analysis asserts the
identity (exact rationals) for every policy, and `tests/unit/test_statistics_v2.py` checks it on
synthetic data with events at zero and later, all-censored observations, ties and mixed rows, along
with the general product-limit estimate when censoring happens before the cap (where the identity
no longer holds). The median is reported only if `S` reaches 1/2 within the horizon, otherwise
"not reached by C". Comparisons join rows by stream id and bootstrap paired differences of
restricted mean pieces, lines and cap-hit fraction; the summary rejects incomplete pairings,
conflicting duplicates and foreign identities (`check_paired`). Figures:
`results/v2/figures/survival_<suite>.png` (cap and censoring marked).

## 4. Development pilot (seeds 10000–10019; not a final evaluation)

`make bench-v2 MODE=pilot SUITE=pilot` (cap 10,000, 120 games, 70 s wall, process peak RSS 22 MB):

| Policy | restricted mean pieces | mean lines | cap hit | median survival | wall s (20 games) |
|---|---|---|---|---|---|
| P0 exact | 7,517.5 | 2,995.3 | 0.40 | 8,415 | 19.7 |
| P1 powers_of_two | 8,238.9 | 3,287.9 | 0.70 | not reached by 10,000 | 21.2 |
| P5 coeff_u4 | 7,634.9 | 3,044.1 | 0.55 | not reached by 10,000 | 20.3 |
| P6 coeff_u3 | 2,268.2 | 890.1 | 0.00 | 1,036 | 6.2 |
| P7 coeff_u2 | 688.8 | 258.4 | 0.00 | 533 | 2.0 |
| random_legal | 25.9 | 0.0 | 0.00 | 26 | 0.1 |

Paired against P0 (20 streams, 5,000 resamples): P1 +721 pieces (CI95 [−1,320, 2,780]) and
+293 lines ([−521, 1,099]); P5 +118 pieces ([−1,060, 1,208]); P6 −5,249 ([−6,921, −3,568]);
P7 −6,829 ([−8,041, −5,421]). Twenty streams do not separate P0, P1 and P5; the held-out study has
100.

`make bench-v2 MODE=pilot SUITE=pilot50k` (P0 and P1 — the strongest pilot policy by cap-hit —
to the full cap; 40 games, 107 s): P0 restricted mean 10,462 pieces, cap hit 0/20 (every game
topped out, median survival 8,415 pieces, median 3,366 lines); P1 27,819 pieces, cap hit 6/20,
median survival 24,992 pieces, mean lines 11,114 — paired against P0: +17,357 pieces (CI95
[9,855, 24,689]) and +6,947 lines ([3,977, 9,807]), P1 ahead on 16 of 20 streams. About 8,000–10,000 decisions per second per policy; a 50,000-piece game
takes 5–6 s, so the 600-game held-out suite is roughly a quarter of an hour of wall time. The
50,000 cap still censors 30 % of P1's development games, so the fixed-horizon interpretation is
retained rather than raising the cap (a larger cap does not guarantee observable medians).

Development-time protocol adjustment (recorded before the freeze): the `pilot50k` suite was
pointed at P1 after the `pilot` suite identified it as the strongest development policy; the
held-out suite itself was not changed. Every record carries the protocol hash of the file it was
run under; the earlier development records were removed rather than mixed.

## 5. Held-out study `bag50k` (U16) — 100 paired streams, cap 50,000

Frozen 2026-09-05T18:23:11Z at commit `b9200a5` (protocol `12e05937e613…`, model closure
`ea02300144a0…`, 120 stream hashes; `results/v2/protocol/freeze_quality-v2-bag50k.json`), then
`make bench-v2 MODE=run SUITE=bag50k`: 600 games in summary mode, 622 s wall, process peak RSS
23 MB, 0 failed jobs, every record under its identity; `make check-quality-v2 SUITE=bag50k`
600/600 records, paired set complete and consistent with the freeze. Analysis:
`results/v2/summary/quality.json` (= `analysis_bag50k.json`), figure
`results/v2/figures/survival_bag50k.png`.

| Policy | restricted mean pieces (to C = 50,000) | mean lines | median lines [IQR] | cap hit | median survival | duration quartiles |
|---|---|---|---|---|---|---|
| P0 exact | **11,846** | **4,722** | 3,192 [1,613, 6,390] | 2/100 | 7,880 | [4,075, 8,022, 16,018] |
| P1 powers_of_two | **22,675** | **9,055** | 8,620 [2,186, 14,809] | 13/100 | 21,563 | [5,509, 21,591, 37,066] |
| P5 coeff_u4 | 11,085 | 4,417 | 2,992 [1,514, 5,460] | 2/100 | 7,337 | [3,826, 7,522, 13,692] |
| P6 coeff_u3 | 2,226 | 873 | 723 [358, 1,140] | 0/100 | 1,843 | [938, 1,849, 2,893] |
| P7 coeff_u2 | 680 | 255 | 225 [143, 354] | 0/100 | 601 | [400, 604, 928] |
| random_legal | 25.6 | 0.09 | 0 | 0/100 | 26 | [24, 26, 27] |

Every median is reached within the horizon (the cap censors 2 % of P0/P5 games and 13 % of P1
games, so the restricted means are means to 50,000, not unbounded expectations). Paired against
P0 (stream-level bootstrap, 5,000 resamples, seed 20260905):

| Policy vs P0 | Δ restricted mean pieces [CI95] | Δ mean lines [CI95] | Δ cap-hit fraction [CI95] | streams won / lost / tied (pieces) |
|---|---|---|---|---|
| P1 powers_of_two | **+10,829 [7,082, 14,719]** | **+4,333 [2,784, 5,879]** | +0.11 [0.05, 0.18] | 64 / 35 / 1 |
| P5 coeff_u4 | −762 [−3,255, 1,856] | −305 [−1,278, 779] | 0.00 [−0.04, 0.04] | 31 / 39 / 30 |
| P6 coeff_u3 | −9,621 [−11,793, −7,538] | −3,849 [−4,729, −2,971] | −0.02 [−0.05, 0.00] | 12 / 88 / 0 |
| P7 coeff_u2 | −11,167 [−13,297, −9,091] | −4,467 [−5,330, −3,620] | −0.02 [−0.05, 0.00] | 1 / 99 / 0 |
| random_legal | −11,821 [−13,969, −9,746] | −4,722 [−5,574, −3,888] | −0.02 [−0.05, 0.00] | 0 / 100 / 0 |

What the study shows, and what it does not:

* **P1 (64, 64, 32, 16) plays about twice as long as the exact baseline (76, 51, 36, 18)** on these
  streams — a large, well-separated paired effect (interval far from zero, 64 of 100 streams). The
  "exact" coefficients are the attributed baseline the repository never tuned; the powers-of-two
  profile weights the aggregate height more heavily relative to line clears (A/L = 1.0 against
  0.67; holes and bumpiness keep almost the same relative weight, 0.50/0.25 against 0.47/0.24),
  and over a 50,000-piece horizon keeping the stack low survives longer. v1's 2,000-piece study could not see this
  (most games hit its cap). This is an observation about these two fixed policies on seven-bag
  streams; it is not a tuning result and no coefficient search was done.
* **P5 (four-bit magnitudes) is indistinguishable from P0**: 30 of 100 games are move-for-move
  identical (equal outcomes), and the paired interval on pieces spans −3,255 to +1,856. The 0.1 %
  common-state disagreement rate of U14 translates into no measurable outcome difference here —
  an inconclusive comparison, kept as such.
* **P6 and P7 collapse**: three-bit magnitudes lose 81 % of the restricted mean pieces, two-bit
  92 %. The common-state rates (2.5 %, 8.9 % changed decisions) understate the trajectory effect
  because the changed decisions (small exact gaps, holes tolerated) compound.
* Depth two is not part of this study (the v1 depth results remain historical, `docs/design.md`).
  No i.i.d. suite was run. The held-out streams were never used for any development decision; the
  development pilot (§4) is reported separately and was used only to size the study and choose the
  `pilot50k` policy.
