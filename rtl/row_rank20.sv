// Inclusive prefix ranks of twenty keep bits by an explicit five-level scan (guide §6.1).
//   p0[s]     = zero_extend_5(keep[s])
//   level l+1 : next[s] = prev[s] + (s >= stride ? prev[s-stride] : 0), stride = 1,2,4,8,16
// Five bits suffice: every partial sum is at most 20.  rank_o[5s +: 5] is the inclusive rank of
// source row s; a surviving row's destination is rank-1, tested downstream as rank == d+1 so no
// subtraction sits on the selection path.  survivors_o = rank[19]; cleared_o = 20 - survivors_o
// (both five bits: the standalone count is never truncated).
module row_rank20 (
    input  logic [19:0] keep_i,
    output logic [99:0] rank_o,
    output logic [4:0]  survivors_o,
    output logic [4:0]  cleared_o
);
    logic [99:0] p0, p1, p2, p3, p4, p5;
    generate
        for (genvar s = 0; s < 20; s++) begin : g_init
            assign p0[5 * s +: 5] = {4'd0, keep_i[s]};
        end
    endgenerate
    rank_level #(.STRIDE(1))  u_l1 (.prev_i(p0), .next_o(p1));
    rank_level #(.STRIDE(2))  u_l2 (.prev_i(p1), .next_o(p2));
    rank_level #(.STRIDE(4))  u_l3 (.prev_i(p2), .next_o(p3));
    rank_level #(.STRIDE(8))  u_l4 (.prev_i(p3), .next_o(p4));
    rank_level #(.STRIDE(16)) u_l5 (.prev_i(p4), .next_o(p5));

    assign rank_o      = p5;
    assign survivors_o = p5[95 +: 5];
    assign cleared_o   = 5'd20 - p5[95 +: 5];
endmodule
