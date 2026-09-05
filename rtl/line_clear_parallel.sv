// Combinational stable row compaction (guide §6.2): remove every full row, keep survivors in
// order, zero-pad the top.  Composed of exactly the blocks the pipelined line_clear_pipe registers
// between banks: row_rank20 (five rank_level scans), rank_match, row_select_groups,
// row_select_final.  Accepts any board, including twenty full rows (then every output row is zero
// and count_o = 20).  Reference for the formal miter under formal/compactor/.
module line_clear_parallel (
    input  logic [199:0] board_i,
    output logic [199:0] board_o,
    output logic [4:0]   count_o,       // cleared rows, 0..20
    output logic [4:0]   survivors_o,   // 20 - count_o
    output logic [19:0]  keep_o,        // diagnostic: keep bits
    output logic [99:0]  rank_o         // diagnostic: inclusive ranks
);
    logic [19:0]  keep;
    logic [99:0]  rank;
    logic [4:0]   survivors, cleared;
    logic [399:0] match;
    logic [999:0] partial;

    generate
        for (genvar s = 0; s < 20; s++) begin : g_keep
            assign keep[s] = (board_i[10 * s +: 10] != 10'h3FF);
        end
    endgenerate

    row_rank20        u_rank   (.keep_i(keep), .rank_o(rank), .survivors_o(survivors), .cleared_o(cleared));
    rank_match        u_match  (.keep_i(keep), .rank_i(rank), .match_o(match));
    row_select_groups u_groups (.board_i(board_i), .match_i(match), .partial_o(partial));
    row_select_final  u_final  (.partial_i(partial), .board_o(board_o));

    assign count_o     = cleared;
    assign survivors_o = survivors;
    assign keep_o      = keep;
    assign rank_o      = rank;
endmodule
