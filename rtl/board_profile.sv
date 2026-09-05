// Combinational board profile: transpose the 200-bit board into ten 20-bit columns and find
// each column's exact height (1 + highest occupied y, 0 for an empty column) with a 20-input
// priority encoder per column.  Also exposes the columns and per-column hole masks
// (empty cells below the top occupied cell) for the fast feature unit.
module board_profile (
    input  logic [199:0] board_i,
    output logic [49:0]  heights_o,
    output logic [199:0] columns_o,    // column c occupies columns_o[20c +: 20], bit y = cell (c,y)
    output logic [199:0] holes_o       // hole mask per column, same layout
);
    generate
        for (genvar c = 0; c < 10; c++) begin : g_col
            logic [19:0] col;
            logic [4:0]  h;
            logic [19:0] below_top;
            for (genvar y = 0; y < 20; y++) begin : g_bit
                assign col[y] = board_i[10 * y + c];
            end
            always_comb begin
                h = 5'd0;
                for (int y = 0; y < 20; y++)
                    if (col[y]) h = 5'(y + 1);      // last assignment wins: highest occupied row
            end
            // below_top = (1 << h) - 1 using a 21-bit shift so h = 20 works
            assign below_top = 20'((21'd1 << h) - 21'd1);
            assign heights_o[5 * c +: 5]   = h;
            assign columns_o[20 * c +: 20] = col;
            assign holes_o[20 * c +: 20]   = below_top & ~col;
        end
    endgenerate
endmodule
