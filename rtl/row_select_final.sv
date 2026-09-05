// Final balanced OR of the five partial rows per destination (bank P12); see row_select_groups.sv.
module row_select_final (
    input  logic [999:0] partial_i,
    output logic [199:0] board_o
);
    generate
        for (genvar d = 0; d < 20; d++) begin : g_dst
            assign board_o[10 * d +: 10] = ((partial_i[10 * (5 * d + 0) +: 10] | partial_i[10 * (5 * d + 1) +: 10]) |
                                            (partial_i[10 * (5 * d + 2) +: 10] | partial_i[10 * (5 * d + 3) +: 10])) |
                                            partial_i[10 * (5 * d + 4) +: 10];
        end
    endgenerate
endmodule
