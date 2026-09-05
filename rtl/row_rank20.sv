// Inclusive prefix ranks of twenty keep bits by an explicit five-level scan (guide §6.1).
//   p0[s]     = zero_extend_5(keep[s])
//   level l+1 : next[s] = prev[s] + (s >= stride ? prev[s-stride] : 0), stride = 1,2,4,8,16
// Every node of one level reads only the previous level (a different dependency graph from an
// in-place loop).  Five bits suffice: every partial sum is at most 20.  rank_o[5s +: 5] is the
// inclusive rank of source row s; a surviving row's destination is rank-1, tested downstream as
// rank == d+1 so no subtraction sits on the selection path.  survivors_o = rank[19];
// cleared_o = 20 - survivors_o (both five bits: the standalone count is never truncated).
module row_rank20 (
    input  logic [19:0] keep_i,
    output logic [99:0] rank_o,
    output logic [4:0]  survivors_o,
    output logic [4:0]  cleared_o
);
    // lvl[l] packs twenty 5-bit values; lvl[0] = p0, lvl[5] = final inclusive ranks
    logic [99:0] lvl [0:5];

    generate
        for (genvar s = 0; s < 20; s++) begin : g_init
            assign lvl[0][5 * s +: 5] = {4'd0, keep_i[s]};
        end
        for (genvar l = 0; l < 5; l++) begin : g_level
            localparam int STRIDE = 1 << l;
            for (genvar s = 0; s < 20; s++) begin : g_node
                if (s >= STRIDE) begin : g_add
                    assign lvl[l + 1][5 * s +: 5] = lvl[l][5 * s +: 5] + lvl[l][5 * (s - STRIDE) +: 5];
                end else begin : g_pass
                    assign lvl[l + 1][5 * s +: 5] = lvl[l][5 * s +: 5];
                end
            end
        end
    endgenerate

    assign rank_o      = lvl[5];
    assign survivors_o = lvl[5][95 +: 5];
    assign cleared_o   = 5'd20 - lvl[5][95 +: 5];
endmodule
