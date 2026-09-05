// A1 merge: the four piece cells are decoded into row/column one-hots and combined into a
// 200-bit mask in one combinational step, then ORed with the original board and registered
// one cycle after start.  Same-row cells are combined in the mask, so there is no
// sequential-assignment ordering hazard.
module merge_fast (
    input  logic         clk,
    input  logic         rst,
    input  logic         start_i,
    input  logic [199:0] board_i,
    input  logic [7:0]   dx_i,
    input  logic [7:0]   dy_i,
    input  logic [3:0]   x_i,
    input  logic [4:0]   y_i,
    output logic         busy_o,
    output logic         done_o,
    output logic [199:0] board_o
);
    logic [4:0]   cy [4];
    logic [3:0]   cx [4];
    logic [19:0]  row_oh [4];
    logic [9:0]   col_oh [4];
    logic [199:0] mask;

    always_comb begin
        for (int k = 0; k < 4; k++) begin
            cy[k] = y_i + {3'd0, dy_i[2*k +: 2]};
            cx[k] = x_i + {2'd0, dx_i[2*k +: 2]};
            for (int y = 0; y < 20; y++) row_oh[k][y] = (cy[k] == 5'(y));
            for (int x = 0; x < 10; x++) col_oh[k][x] = (cx[k] == 4'(x));
        end
        for (int y = 0; y < 20; y++)
            for (int x = 0; x < 10; x++)
                mask[10 * y + x] = (row_oh[0][y] & col_oh[0][x]) | (row_oh[1][y] & col_oh[1][x]) |
                                   (row_oh[2][y] & col_oh[2][x]) | (row_oh[3][y] & col_oh[3][x]);
    end
    assign busy_o = 1'b0;
    always_ff @(posedge clk) begin
        if (rst) begin
            done_o <= 1'b0; board_o <= '0;
        end else begin
            done_o <= start_i;
            if (start_i) board_o <= board_i | mask;
        end
    end
endmodule
