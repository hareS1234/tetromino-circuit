// Source-to-destination match bits (guide §6.2): match[d][s] = keep[s] && (rank[s] == d+1).
// Flat output bit 20*d + s.  At most one source matches a destination; a destination with no
// match receives a zero row downstream (natural zero padding of the top).
module rank_match (
    input  logic [19:0]  keep_i,
    input  logic [99:0]  rank_i,
    output logic [399:0] match_o
);
    generate
        for (genvar d = 0; d < 20; d++) begin : g_dst
            for (genvar s = 0; s < 20; s++) begin : g_src
                assign match_o[20 * d + s] = keep_i[s] && (rank_i[5 * s +: 5] == 5'(d + 1));
            end
        end
    endgenerate
endmodule
