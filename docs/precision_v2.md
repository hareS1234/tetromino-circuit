# Coefficient quantization ladder P5–P7 and decision sensitivity (U14)

v1 measured four structural approximations of the scorer (P1–P4: powers of two, two terms per
magnitude, capped holes, no bumpiness). U14 adds a *ladder* of coefficient-magnitude budgets that
keeps every feature exact and only shrinks the coefficient magnitudes. The study measures the useful
arithmetic width across several data points. P0–P4 are untouched (ids, names, coefficients, tests,
results).

## 1. Profiles

| PRECISION | name | `(wL, wA, wQ, wU)` | bits | M | raw score range (L ≤ 4) | sufficient signed width |
|---|---|---|---|---|---|---|
| 5 | `coeff_u4` | (15, 10, 7, 4) | 4 | 15 | [−4120, 60] | 14 |
| 6 | `coeff_u3` | (7, 5, 3, 2) | 3 | 7 | [−1960, 28] | 12 |
| 7 | `coeff_u2` | (3, 2, 1, 1) | 2 | 3 | [−780, 12] | 11 |

The magnitudes are generated, not chosen: `model.numeric.quantize_magnitudes(bits)` computes
`q_i = round_half_up(w_i · M / 76)` with `M = 2^bits − 1` in integer arithmetic
(`(2·w·M + 76) // 152`), and the module asserts the table above at import. A raw P5–P7 score is in
its own units. The common positive scale 76/M is dropped because it does not change the argmax. Raw
scores are never compared with P0 scores; `to_baseline_units` converts exactly (rational),
and the fixture explanations carry both. `coeff_bits`, `levels`, `score_width` and `score_range`
are analysis metadata on the `Profile` (`profile_metadata(p)`); the configuration identity stays
`PRECISION`. The new profiles are supported on A1/cache/depth-one/one-lane only
(`a1-cache-d1-p5-l1` … `p7`; `model/config.py` `UPGRADE_SUPPORTED`, `tetris_core` `CFG_OK`
`PRECISION <= 7` on that branch); every other combination is rejected in Python and in
elaboration.

## 2. Hardware

`rtl/score.sv` gains one generate branch (`g_quant`) for P5–P7. The features are zero-extended into
signed operands of sufficient width: 14, 12, or 11 bits. The feature bounds are A ≤ 200, Q ≤ 200,
U ≤ 180, and L ≤ 4. Simulation assertions check those bounds. Each profile forms its shift-add sum
at the selected width. The result is sign-extended onto the unchanged 32-bit score port. Landing, merge,
clearing, features and the tie-break are the exact ones; there are no coefficient registers
(elaboration constants).

`make test-precision-v2` checks each scorer at the range limits and on 1,000 random tuples. The A1
evaluator receives 16,200 candidate cases per profile with intermediate-value checks. Complete-core
runs compare 1,000 common states with the matching literal-descent reference. One 100-piece RTL
replay per profile is checked move by move. Evidence lives under `results/evidence/U14`. The unit tests
(`tests/unit/test_precision_v2.py`) check the generated magnitudes against exact rationals, the
metadata, the configuration guards, and every candidate score of the fixture states against the
independent set-of-cells reference (`tests/reference_grid.py`).

## 3. Decision sensitivity on common states (development data)

`tools/analyze_precision_v2.py --split development` evaluates P0 and each quantized profile on the
identical board and piece for every state of the supplied planning corpora
(`benchmarks/states/corpus_d1.jsonl`, 1,000 states, 981 with a legal move; and the 2,000-state
`corpus_d1_upgrade_dev.jsonl`, 1,963 legal). This is the corpus that chose the ladder, so the
numbers are development evidence, not a final evaluation; the fresh common-state corpus of U16
repeats the analysis untouched (`--split heldout`). A difference in a free-running game after
the boards have diverged is a different quantity and is not measured here.

| Profile | changed decisions (corpus_d1) | rate | changed (dev 2,000) | rate | certified unchanged (corpus_d1) | not certified but unchanged | exact ties | ties introduced / broken |
|---|---|---|---|---|---|---|---|---|
| P5 `coeff_u4` | 1 / 981 | 0.10 % | 6 / 1,963 | 0.31 % | 237 | 743 | 192 | 0 / 0 |
| P6 `coeff_u3` | 25 / 981 | 2.55 % | 76 / 1,963 | 3.87 % | 128 | 828 | 192 | 40 / 0 |
| P7 `coeff_u2` | 87 / 981 | 8.87 % | 221 / 1,963 | 11.26 % | 141 | 753 | 192 | 35 / 15 |

The corpus_d1 disagreement counts reproduce the guide's planning figures (1, 25, 87). For the v1
structural profiles the same count is 41 (P1), 0 (P2), 58 (P3) and 428 (P4)
(`results/precision_disagreement.json`, v1): the 4-bit ladder step is far gentler than any of
them except P2, and the 2-bit step sits between P3 and P4.

Changed states have small exact score gaps. Their median best-to-runner-up gaps are 2, 15, and 15 P0
units for P5, P6, and P7. Unchanged states have a median gap of 36. The quantized choices give up a
median P0 score of 2 / 15 / 15 and a maximum of 2 / 30 / 162. The exact winner is usually the
quantized runner-up in changed states. Full distributions are in
`results/v2/precision/development/summary.json`; per-state records regenerate with the tool
(`states_<corpus>_p<k>.jsonl`, not committed).

### Stability certificate

For a quantized profile with `M` levels let `δ_i = 76·q_i − M·w_i` (P5: (0, −5, −8, 34); P6:
(0, 23, −24, 26); P7: (0, −1, −32, 22)). For a candidate `c` with features `(L, A, Q, U)`,
`E(c) = Σ|δ_i|·f_i(c)` bounds `|76·S_q(c) − M·S(c)|`, so if the exact winner `g` satisfies
`M·(S(g) − S(c)) > E(g) + E(c)` for every other legal `c`, then `S_q(g) > S_q(c)` for all of them
and `g` is certified to survive the quantization (`model/sensitivity.py`; integer comparisons
only). A failed certificate is "not certified", not "changed"; the table shows that most
unchanged decisions are not certified (the bound is loose: `E` reaches 8,720 / 14,080 / 10,560
at the feature maxima) and that exact ties (192 states) are never certifiable. Soundness
(certified ⇒ unchanged) is asserted for every state by the tool and by the unit test; the unit
test also contains synthetic cases where the bound fails intentionally with the decision
unchanged, where it fails and the decision changes (the fixture mechanism isolated), and an exact
tie broken toward the higher id.

### The two committed divergences (`tests/fixtures/precision_v2_divergences.json`)

Derived tables: `results/v2/precision/divergence_explanations.json` (`make analyze-precision-v2`).

*State 7, piece O.* Exact winner candidate 8 (rotation 0, x = 8: A 28, Q 2, U 8, S = −1644) beats
candidate 4 (x = 4: A 29, Q 3, U 4, S = −1659) by 15. Under P6 both score −162 (`−140−6−16` and
`−145−9−8`): a tie is introduced and the lower id 4 wins. Under P7 candidate 4 scores −65 against
−66 for candidate 8: changed outright. Under P5 candidate 8 keeps a raw margin of 1 (−326 vs −327).
None of the three is certified (margins −508 / −1638 / −472).

*State 744, piece Z.* Exact winner candidate 12 (rotation 1, x = 2: A 141, Q 26, U 32,
S = −8703) beats candidate 10 (rotation 1, x = 0, one line cleared: A 139, Q 34, U 26,
S = −8705) by only 2. All three quantized profiles choose candidate 10 (P5 −1717 vs −1720): the
line-clear reward outweighs the holes once the coefficients are coarse. Exact gap 2, P0 loss 2.

## 4. Area: scorer alone versus complete core (`make synth-scorer-study`)

`results/v2/precision/scorer_study.json`, Yosys `synth_ecp5 -nodsp`, pinned suite.

Registered scorer microbenchmarks (`score` module alone; `valid_o` and all 32 `score_o` bits are
top-level ports and therefore observed: the FF counts below 33 are sign-extension copies merged
by `opt_merge` because they share one D input):

| Profile | LUT4 | FF | CCU2C | DSP |
|---|---|---|---|---|
| P0 exact (shift-add) | 97 | 20 | 26 | 0 |
| P0 exact, constant multiplies, DSP allowed (reference) | 25 | 18 | 17 | 4 |
| P1 powers_of_two | 17 | 18 | 13 | 0 |
| P2 two_terms | 53 | 18 | 26 | 0 |
| P3 cap_holes | 97 | 20 | 26 | 0 |
| P4 no_bumpiness | 72 | 19 | 20 | 0 |
| P5 coeff_u4 | 79 | 15 | 21 | 0 |
| P6 coeff_u3 | 63 | 13 | 18 | 0 |
| P7 coeff_u2 | 28 | 12 | 11 | 0 |

Complete A1/cache/depth-one/one-lane cores (`stream_wrapper`, identity-keyed synth records,
`-nodsp`; the v1 `results/implementation.csv` figures for P0–P4 used the default DSP policy and
the v1 toolchain and are a different identity):

| Core | LUT4 | FF | CCU2C | Δ LUT4 vs P0 | Δ FF | Δ CCU2C |
|---|---|---|---|---|---|---|
| `a1-cache-d1-p0-l1` | 4,030 | 2,220 | 342 | n/a | n/a | n/a |
| `p1` | 3,941 | 2,130 | 324 | −89 | −90 | −18 |
| `p2` | 4,041 | 2,220 | 342 | +11 | 0 | 0 |
| `p3` | 4,058 | 2,216 | 363 | +28 | −4 | +21 |
| `p4` | 3,908 | 2,167 | 272 | −122 | −53 | −70 |
| `p5` | 3,909 | 2,112 | 332 | −121 | −108 | −10 |
| `p6` | 3,882 | 2,100 | 329 | −148 | −120 | −13 |
| `p7` | 3,883 | 2,094 | 322 | −147 | −126 | −20 |

The scorer is 1–2 % of the core; the full-core area stays nearly flat (at most −3.7 % LUT4 and
−5.7 % FF for P7, the FF saving being narrower score registers), as the guide anticipated. The
scorer-only rows must not be read as core savings, and no DSP block appears in any `-nodsp`
core. Timing of the P5–P7 cores is not measured here (U17 routes them: twelve precision routes in
`benchmarks/hardware_v2.json`).

## 5. Scope of the evidence

Four-bit magnitudes change one decision in a thousand common states and cost nothing
measurable; three bits change 2.5–3.9 %, two bits 9–11 %, with the changed states concentrated
where the exact gap is small (median 15 P0 units versus 36 overall). Whether those changed
decisions matter for game outcomes is a question about trajectories, answered by the U15/U16
long-run benchmarks on fresh streams, not by this analysis; and the counts above come from the
corpus that selected the ladder.
