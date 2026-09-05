// Row selection network, first half (guide §6.2, bank P11); the second half is row_select_final.sv.
//   row_select_groups: for each destination d and group g of four sources,
//       partial[d][g] = OR over s in group of (row[s] & replicate_10(match[d][s]))
//       (flat output bits 10*(5*d+g) +: 10; 20 x 5 x 10 = 1,000 bits)
//   row_select_final : out_row[d] = balanced OR of the five partials of d
// No procedural scatter; impossible matches (d > s) are left to synthesis.
module row_select_groups (
    input  logic [199:0] board_i,
    input  logic [399:0] match_i,
    output logic [999:0] partial_o
);
    generate
        for (genvar d = 0; d < 20; d++) begin : g_dst
            for (genvar g = 0; g < 5; g++) begin : g_grp
                logic [9:0] m0, m1, m2, m3;
                assign m0 = board_i[10 * (4 * g + 0) +: 10] & {10{match_i[20 * d + 4 * g + 0]}};
                assign m1 = board_i[10 * (4 * g + 1) +: 10] & {10{match_i[20 * d + 4 * g + 1]}};
                assign m2 = board_i[10 * (4 * g + 2) +: 10] & {10{match_i[20 * d + 4 * g + 2]}};
                assign m3 = board_i[10 * (4 * g + 3) +: 10] & {10{match_i[20 * d + 4 * g + 3]}};
                assign partial_o[10 * (5 * d + g) +: 10] = (m0 | m1) | (m2 | m3);
            end
        end
    endgenerate
endmodule
