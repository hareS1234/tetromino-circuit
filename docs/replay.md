# Watching A2 think, one clock at a time (U18)

The replay exists because staring at twenty-three banks of RTL is a rotten way to learn a pipeline.
It shows tags moving, the running winner changing, and stalls or resets taking effect at the exact
edge where the Verilated design saw them.

This is not a hand-drawn timing sketch. Occupancy, handshakes, compactor samples, and best-reducer
registers come from RTL. Boards, features, and scores come from the literal-descent oracle and are
joined to RTL tokens by tag. `tools/check_trace.py` checks that the marriage is sound.

## The three traces

All live under `results/traces/` and use schema `a2-trace-v1`.

| File | Setup | What is interesting about it |
|---|---|---|
| `a2_normal_search.json` | production `tetris_core`, corpus state 3 | 34 T-piece candidates, a line-clear option, six running-best changes, and the final response at `N + 29 = 63` cycles |
| `a2_last_candidate_wins.json` | production core, corpus state 800 | the final dense I-piece candidate is the unique winner, which is a tidy trap for off-by-one reduction bugs |
| `a2_stall_reset.json` | standalone `candidate_pipe` verification harness | fills all 23 banks, freezes nine edges behind `m_ready = 0`, releases work, flushes a full pipe on reset, then starts cleanly again |

The last case is intentionally not sold as production behavior. `search_pipeline` ties `m_ready`
high; the standalone interface is where output back-pressure can be demonstrated honestly. Fixture
selection rules and the development-corpus source are recorded in each header.

Every trace says which top, toolchain, source hash, stage-manifest hash, and native harness produced
it. Cycles contain the control signals, bank tags, retiring token, running best, P9 keep/rank sample,
P12 compacted-board sample, and either the core request/response state or the standalone harness
phase. Candidate payloads are stored once and referenced by tag, which keeps the files large but not
comically large.

The harnesses use Verilator's `--public-flat-rw` to observe registers without touching production
RTL. That flag is part of the native identity.

## What the checker insists on

`make check-trace` verifies:

- schema, stage manifest, and reported source identity;
- one retirement per accepted tag unless reset flushed it;
- in-order movement and retirement;
- completely stable banks while `advance = 0`;
- no valid bank after reset;
- RTL legality, landing y, score, and id against the matching oracle payload;
- P9 keep bits/ranks and P12 cleared board against independent compaction;
- every running-best change, final winner, and public response; and
- the production response law `cycles = N + 29`.

The committed totals are 1,108 checks for normal search, 580 for the last-candidate winner, and 698
for stall/reset.

## Browser viewer

`viewer/index.html` can load a trace served from the repository root. `viewer/demo.html` is the same
viewer with the normal trace bundled, so it also opens directly from disk.

```bash
python -m http.server
# then open http://localhost:8000/viewer/
```

The left side shows the board and selected candidate. The middle shows 23 banks grouped as landing,
merge, ranks, select, features, and score. The explanation panel follows full rows, keep bits, ranks,
A/Q/U/L, score, the current best, and the RTL/reference comparison. The timeline marks acceptance,
retirement, best updates, stalls, resets, and the public response.

Keyboard controls, accessible names, labelled canvases, live regions, and non-colour state cues are
covered by `make check-viewer`. The selected token is P22 when one is retiring, otherwise the newest
in flight, otherwise the final winner. This rule matters: it prevents the winning board from being
quietly drawn under some unrelated tag.

## GIFs and static diagrams

`make render-a2-demo` produces one frame per recorded edge:

- `assets/a2_pipeline.gif`
- `assets/a2_last_candidate_wins.gif`
- `assets/a2_stall_reset.gif`

First, middle, and final inspection frames sit under `results/traces/frames/`. The normal trace's
middle frame catches all 23 banks occupied; its last frame shows an empty pipe, best id 16 at score
−887, and the public response.

`make render-showcase` cuts the two README animations from the longer saved games. The neon reel
animates the straight drop between recorded positions and flashes the rows the replay actually
cleared. The architecture race advances A0, A1, and A2 by the same 13,031-cycle budget. Replay paths
are also tucked into each GIF's comment field, so `make check-viewer` can catch a swapped source.

`tools/diagrams.py` also draws the static SVGs in `assets/diagrams/`: the top-level search path, the
A0/A1 evaluator FSM, the grouped A2 pipe, a non-adjacent line-clear example, and four-lane ownership.
Measured residency and latency values come from result files and the stage manifest, not from a
label typed into the picture.
