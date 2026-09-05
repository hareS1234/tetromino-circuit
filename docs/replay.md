# Architecture replay: cycle-by-cycle traces of the A2 pipeline (U18)

The replay makes the pipeline visible before anyone opens the RTL. Everything it shows comes from
the Verilated RTL itself — bank occupancy, tags, handshakes, the best-reducer registers, the
compactor's keep bits, ranks and cleared board — sampled every clock edge; the candidate payloads
(boards, features, scores) come from the literal-descent reference and are linked to the RTL tokens
by tag. `tools/check_trace.py` proves the two views agree.

## Traces (`results/traces/`, schema `a2-trace-v1`)

| File | Scenario | Source | Story |
|---|---|---|---|
| `a2_normal_search.json` | `normal-search` | production core `tetris_core` (`a2-cache-d1-p0-l1`), `sim/trace_main.cpp` | corpus state 3 (piece T, 34 candidates, ≥ 30 legal, a line-clearing candidate, 6 running-best updates); 70 cycles; response rotation 1, x 6, y 0, score −887 in 63 cycles = N + 29 |
| `a2_last_candidate_wins.json` | `last-candidate-wins` | production core | corpus state 800 (`last_candidate_winner`, piece I): the final dense candidate is the unique winner — the last retirement changes the best; 53 cycles, response in 46 cycles |
| `a2_stall_reset.json` | `stall-reset` | standalone `candidate_pipe` harness, `sim/pipe_trace_main.cpp` (**verification scenario**) | 8 candidates issued; `m_ready` dropped — the elastic pipeline keeps advancing until P22 holds a token (23 in flight), then **freezes** for 9 edges (no acceptance, no movement); release retires 6; **reset** with 23 stages occupied clears every valid bit at one edge; 5 more candidates issued and drained |

The production search never blocks its output (`m_ready` is constant 1 inside `search_pipeline`),
so the stall and the reset with occupied stages are demonstrated on the standalone candidate
interface and labelled as such in the trace header (`scenario_kind`). Fixtures are chosen by a
declared search over `benchmarks/states/corpus_d1.jsonl` in id order (rule recorded in the header,
`fixture.selection`); they are demonstrations from the development corpus, not held-out samples.

Header fields: `schema`, `backend` (verilator-native), `top`, `native_key` (harness identity),
`source_sha256`, `toolchain_id`, `configuration_id`, `stage_manifest_sha256`, `scenario`,
`scenario_kind`, `sampling` ("handshakes pre-edge; registers post-edge"), `timing_projection`
(`null`: cycles only, no clock is implied), `fixture`, `bank_names`, `stage_groups`. Each cycle
record: `cycle`, `rst`, `advance`, `s` (accepted id/tag/last), `m` (retired id/tag/last/legal/y/
score, plus `consumed` in the standalone trace), `banks` (23 entries: `{tag, id, last}` or null),
`best` (production), `best_changed`, `p9` (`keep`, `ranks` of the token at P9), `p12` (cleared
`board` of the token at P12), `req_accept`/`rsp_valid` (production) or `phase`/`m_ready`/
`occupancy` (standalone). Candidate payloads are stored once per candidate under
`requests[0].candidates` and linked by `tag` (= dense index); `events` lists request acceptance,
candidate acceptances/retirements, best updates, resets, blocked-output cycles and the response.

The harnesses are built with `--public-flat-rw` (`tools/build_native.py build_harness(...,
extra_flags)`) so the bank registers are read without touching the RTL; the flag is part of the
harness identity (`native_key`).

## Checker (`make check-trace`)

For every trace: schema and stage-manifest hash; token conservation (every accepted tag retires
once, or was in flight at a reset edge); acceptance-order retirement; movement (a token in bank i
under `advance` is in bank i+1 next cycle, a token in P22 retires on the advance); stall stability
(banks unchanged while `advance = 0`); reset flush (no valid bank after a reset edge); retired
`legal/y/score/id` against the reference payload of the same tag; the RTL compactor's keep bits,
inclusive ranks (P9) and cleared board (P12) against the reference for every legal token that
passes those banks; the running best after each change against the reference running best; the
final best and the public response against the oracle decision; `cycles = N + 29`. Current
counts: normal-search 1,108/1,108, last-candidate-wins 580/580, stall-reset 698/698 checks.

## Viewer (`viewer/`, plain HTML/CSS/JS, no server state)

`viewer/index.html` loads a trace served next to the repository (`python -m http.server` from the
repository root, then open `viewer/index.html`) or a local file; `viewer/demo.html` is the bundled
standalone demo with the normal-search trace and the stage manifest embedded (`make
render-a2-demo`). Three regions: board with the selected candidate (hatched cells, dashed full
rows) and its hypothetical merged board; the 23 banks in six functional blocks (landing, merge,
ranks, select, features, score) with the tag of each occupied bank — click or press Enter on a
block to list its banks and the registers each bank carries (from `architecture/a2_stages.json`);
the explanation (full-row mask, keep bits, inclusive ranks, A/Q/U/L, score, the RTL retirement
compared with the reference, the RTL P9/P12 samples) with the compacted board and the current best
(dashed outline; the same outline marks the best token in the pipeline). A timeline shows accept
and retire handshakes, advance/stall, reset and best updates; controls: play/pause, previous/next
cycle (also arrow keys and space), speed, jump to request / first acceptance / first retirement /
each best update / output blocked / pipeline frozen / reset / last result / response consumed,
jump to a candidate tag, and a filter (all tokens, selected only, best only). The selected token is
the one in P22 (about to retire), otherwise the newest in flight, otherwise the final winner once
the search is complete; the final winner's board is never shown under other tokens. Playback shows
the pipeline frozen when the trace says `advance = 0` and clears every token at the recorded reset
edge. State is readable from labels and outlines, not colour alone; controls carry accessible
names and the status/explanation/best panels are live regions (`make check-viewer`).

## GIFs and diagrams (`make render-a2-demo`)

`assets/a2_pipeline.gif` (normal search, 70 frames), `assets/a2_last_candidate_wins.gif`,
`assets/a2_stall_reset.gif`: one frame per clock edge of the trace, rendered by
`tools/render_a2_demo.py` with the same three regions and timeline; first/middle/last stills under
`results/traces/frames/<trace>/` (inspected: frame 1 shows the reset and empty pipeline, frame 36
of the normal search shows 23/23 occupancy with token 6 in P22 and token 5 just retired
(−1770 = reference), frame 70 shows the empty pipeline with the final best id 16 / −887 and the
public response). Static SVG diagrams in `assets/diagrams/` (`tools/diagrams.py`): the
request/cache/search/reduction/response architecture, the A0/A1 evaluator FSM with measured state
residency (from `results/stage_cycles_*.json`), the grouped A2 pipeline with the immutable context,
a compaction example with non-adjacent full rows, and the four-lane ownership/reduction.
