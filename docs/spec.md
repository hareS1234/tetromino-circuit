# Game contract `drop-v1.1`

This identifier is stored in every replay, corpus, and result file. The earlier
`drop-v1` rule (piece initialised inside the board at `y = 20 - height`) is retired
because it let a piece appear beneath an overhang; see the regression fixture below.

## Board and coordinates

Width `W = 10`, height `H = 20`, no hidden rows. `x = 0` is the leftmost column,
`y = 0` the bottom row. Python stores a board as a tuple of twenty integers, bottom
row first; bit `x` of `rows[y]` is one for an occupied cell. The RTL input is
`logic [199:0] board_i` with cell `(x, y)` at `board_i[10*y + x]`; packing is
`sum(rows[y] << (10*y))`. Inputs to the complete player contain no full rows.

Rendering uses screen row `19 - y`; the stored representation is never reversed.

## Pieces

| ID | Piece | Rotation-zero cells `(dx, dy)` |
|---|---|---|
| 0 | I | (0,0) (1,0) (2,0) (3,0) |
| 1 | O | (0,0) (1,0) (0,1) (1,1) |
| 2 | T | (0,0) (1,0) (2,0) (1,1) |
| 3 | S | (0,0) (1,0) (1,1) (2,1) |
| 4 | Z | (1,0) (2,0) (0,1) (1,1) |
| 5 | J | (0,0) (1,0) (2,0) (0,1) |
| 6 | L | (0,0) (1,0) (2,0) (2,1) |

Orientations: apply clockwise rotation `(dx, dy) -> (dy, -dx)`, subtract the minimum
x and y, sort by `(dy, dx)`, keep unique orientations in order of first appearance.
Orientation counts are 2, 1, 4, 2, 2, 4, 4; an orientation of width `w` has `11 - w`
anchors, giving 17, 9, 34, 17, 17, 34, 34 candidates (162 total, at most 34 per
decision). `candidate_id = 10*rotation + x`. Piece ID 7 is a defined error.

## Action and landing

An action is `(rotation, x)` chosen above the board; the piece then drops straight
down. No lateral movement, hold, lock delay, kicks, tucks, or timing.

Entry starts with the bounding-box anchor at `y = 20` (every cell above the stored
board). During descent a cell with `y >= 20` is empty, a cell with `y < 0` or `x`
outside 0–9 collides, and an in-board cell collides when its bit is set. The piece
moves one row down repeatedly and stops at the first collision or at the floor. A
candidate is **legal only if all four landed cells lie in rows 0–19**
(`y_land + height <= 20`); otherwise `legal = 0` and the public action fields are zero.
Neither an inside-board spawn nor a floor-up search is allowed: both can miss an
obstruction on the entry path.

### Closed-form landing

For each occupied piece column `dx`, `bottom[dx]` is the smallest `dy` in that column;
`hs[c]` is the exact height of board column `c` (0–20).

```
y_land = max(0, max over occupied dx of (hs[x+dx] - bottom[dx]))
legal  = valid_shape and x + width <= 10 and y_land + height <= 20
```

The Python oracle (`model/game.py`, `tests/reference_grid.py`) uses literal
cell-by-cell descent; the fast model (`model/fast.py`) and the A1 RTL use the formula.
They are compared on 40,500 candidate cases in `tests/unit/test_reference.py`.

**Regression fixture `spawn_under_overhang_J`:** rows 15 and 18 equal 4, J rotation 3
(cells (0,0) (1,0) (1,1) (1,2)) at x = 2. The retired rule accepted y = 16; entry from
above stops at anchor y = 19 with cells above the board, so the candidate is illegal.

## Lock and clear

Set the four bits on a copy of the board, remove every full row simultaneously,
preserve the order of surviving rows, and add zero rows at the top. A legal placement
on a normalized board clears 0–4 rows; the standalone compactor accepts any board
(0–20 rows, five-bit count).

## Features and score

On the post-clear board: `A` = sum of column heights (height = 1 + highest occupied y,
0 for an empty column); `Q` = empty cells with an occupied cell above in the same
column; `U` = sum of absolute adjacent height differences (walls excluded). With `L`
lines just cleared:

```
score = 76*L - 51*A - 36*Q - 18*U
```

Coefficients are an attributed baseline (Yiyuan Lee, 2013), not tuned here. Bounds:
`A <= 200`, `Q <= 190`, `U <= 180`, `L <= 4`; even with `Q <= 200` the score lies in
`[-20640, 304]`, so signed 16 bits suffice given widened intermediates. The RTL uses
signed 32 bits. The winner is the highest score; equal scores go to the lower
`candidate_id`. A separate `best_valid` flag (never a numeric sentinel) marks that a
legal candidate exists.

## Numerical profiles (`PRECISION`)

| PRECISION | name | (wL, wA, wQ, wU) | rule |
|---|---|---|---|
| 0 | exact | (76, 51, 36, 18) | baseline |
| 1 | powers_of_two | (64, 64, 32, 16) | shifts |
| 2 | two_terms | (80, 48, 36, 18) | each magnitude = two powers of two |
| 3 | cap_holes | (76, 51, 36, 18) | scoring uses min(Q, 15); heights and landing exact |
| 4 | no_bumpiness | (76, 51, 36, 0) | U datapath removed |
| 5 | coeff_u4 | (15, 10, 7, 4) | v2 (U14): 4-bit coefficient magnitudes, `M = 15`; raw score units 76/15 of the baseline |
| 6 | coeff_u3 | (7, 5, 3, 2) | v2 (U14): 3-bit magnitudes, `M = 7` |
| 7 | coeff_u2 | (3, 2, 1, 1) | v2 (U14): 2-bit magnitudes, `M = 3` |

Profiles change scoring only; landing, collision, and clearing are identical. Profiles 5–7 are
generated from the exact coefficients by `model.numeric.quantize_magnitudes` (nearest rounding,
half-ties upward), keep every feature exact, drop the common scale 76/M (the argmax is unchanged),
and are supported on A1/cache/depth-one/one-lane only; see docs/precision_v2.md. Their raw scores
are not in baseline units and must not be compared with P0 scores directly.

## Depth two (`DEPTH=2`)

For each legal current move (board `B1`, lines `L1`) enumerate every legal next-piece
move (board `B2`, lines `L2`) and evaluate `S2 = wL*(L1+L2) - wA*A(B2) - wQ*Q(B2) - wU*U(B2)`
(the leaf scorer sees its own `L2`; the controller adds `wL*L1`). A root's value is its
best `S2`; roots with a legal second move are preferred over roots with none; if no
root survives but current moves exist, the best one-move score `S1` wins. Ties break by
lower candidate ID at every level. The response carries the current action and `S2`
(or `S1` for the fallback). Depth one ignores the preview entirely.

## Piece streams

Seven-bag: shuffle `[0..6]` with `random.Random(seed)`, emit seven, repeat. Streams are
2,001 pieces (2,000 decisions plus one preview) and are committed under
`benchmarks/streams/` with SHA-256 hashes. Splits: training 1000–1049, validation
2000–2019, test 3000–3099. The random baseline uses seed `stream_seed + 1_000_000`.
Primary metric: total cleared lines; also pieces locked and whether the game topped out
or reached the cap.

## Excluded mechanics

| Mechanic | Status |
|---|---|
| Super Rotation System, wall kicks, tucks, spins | excluded |
| Hold, lock delay, soft/hard drop timing, gravity levels | excluded |
| Hidden rows above the board | excluded (entry space is modelled as empty) |
| Level/bonus scoring, back-to-back, combos | excluded |
| Garbage, multiplayer | excluded |
