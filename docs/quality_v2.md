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

## 5. What U16 does

Freeze (`MODE=freeze`), run `bag50k` (600 games, summary mode, resumable), `check-quality-v2`
(every expected record present and consistent with the freeze), `analyze-quality-v2` (restricted
means, lines, cap hits, survival curves with "not reached" medians, paired intervals). Results are
published as `results/v2/summary/quality.json` and `results/v2/figures/survival_bag50k.png`; see
`docs/results.md` once U16 has run.
