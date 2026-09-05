// Combinational stable row compaction (guide §6.2): remove every full row, keep survivors in
// order, zero-pad the top.  Ranks come from row_rank20; the selection network is explicit:
//   match[d][s]  = keep[s] && (rank[s] == d+1)             (at most one s per destination d)
//   partial[d][g] = OR over the four sources s in group g of (row[s] & {10{match[d][s]}})
//   out_row[d]   = balanced OR of the five partials
// No procedural scatter (out[rank[s]] = row[s]) anywhere.  Accepts any board, including twenty
// full rows (then every output row is zero and count_o = 20).  This module is the reference for
// the pipelined line_clear_pipe (P4-P12) and the formal miter under formal/compactor/.
module line_clear_parallel (
    input  logic [199:0] board_i,
    output logic [199:0] board_o,
    output logic [4:0]   count_o,       // cleared rows, 0..20
    output logic [4:0]   survivors_o,   // 20 - count_o
    output logic [19:0]  keep_o,        // diagnostic: keep bits
    output logic [99:0]  rank_o         // diagnostic: inclusive ranks
);
    logic [19:0] keep;
    logic [99:0] rank;
    logic [4:0]  survivors, cleared;

    generate
        for (genvar s = 0; s < 20; s++) begin : g_keep
            assign keep[s] = (board_i[10 * s +: 10] != 10'h3FF);
        end
    endgenerate

    row_rank20 u_rank (.keep_i(keep), .rank_o(rank), .survivors_o(survivors), .cleared_o(cleared));

    // match bits (flat: bit 20*d + s) and grouped partial rows (flat: bits 10*(5*d + g) +: 10)
    logic [399:0] match;
    logic [999:0] partial;
    generate
        for (genvar d = 0; d < 20; d++) begin : g_dst
            for (genvar s = 0; s < 20; s++) begin : g_src
                assign match[20 * d + s] = keep[s] && (rank[5 * s +: 5] == 5'(d + 1));
            end
            for (genvar g = 0; g < 5; g++) begin : g_grp
                // explicit balanced OR of four masked sources
                logic [9:0] m0, m1, m2, m3;
                assign m0 = board_i[10 * (4 * g + 0) +: 10] & {10{match[20 * d + 4 * g + 0]}};
                assign m1 = board_i[10 * (4 * g + 1) +: 10] & {10{match[20 * d + 4 * g + 1]}};
                assign m2 = board_i[10 * (4 * g + 2) +: 10] & {10{match[20 * d + 4 * g + 2]}};
                assign m3 = board_i[10 * (4 * g + 3) +: 10] & {10{match[20 * d + 4 * g + 3]}};
                assign partial[10 * (5 * d + g) +: 10] = (m0 | m1) | (m2 | m3);
            end
            assign board_o[10 * d +: 10] = ((partial[10 * (5 * d + 0) +: 10] | partial[10 * (5 * d + 1) +: 10]) |
                                            (partial[10 * (5 * d + 2) +: 10] | partial[10 * (5 * d + 3) +: 10])) |
                                            partial[10 * (5 * d + 4) +: 10];
        end
    endgenerate

    assign count_o     = cleared;
    assign survivors_o = survivors;
    assign keep_o      = keep;
    assign rank_o      = rank;
endmodule
