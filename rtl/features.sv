// A0 feature extractor: scans x = 0..9, y = 19..0 one cell_bit per cycle, records each column's
// height on its first occupied cell_bit and counts holes only after that; then a ten-cycle
// reduction sums heights (A) and adjacent height differences (U).  PRECISION 3 saturates the
// hole count at 15; PRECISION 4 removes the U datapath.
module features #(
    parameter int PRECISION = 0
) (
    input  logic         clk,
    input  logic         rst,
    input  logic         start_i,
    input  logic [199:0] board_i,
    output logic         busy_o,
    output logic         done_o,
    output logic [7:0]   a_o,
    output logic [7:0]   q_o,       // Q_used (saturated for PRECISION 3)
    output logic [7:0]   u_o,       // U_used (zero for PRECISION 4)
    output logic [49:0]  heights_o  // ten exact five-bit heights (debug/cache)
);
    typedef enum logic [1:0] {IDLE, SCAN, REDUCE, FINISH} state_t;
    state_t state;
    logic [199:0] board_q;
    logic [3:0]   sx;          // column under scan
    logic [4:0]   sy;          // row under scan (19 down to 0)
    logic         seen;        // column has an occupied cell_bit above the current row
    logic [49:0]  heights;     // packed ten five-bit heights
    logic [3:0]   rx;          // reduction column
    logic [7:0]   idx;
    logic         cell_bit;

    assign idx  = {sy, 3'b000} + {2'b00, sy, 1'b0} + {4'd0, sx};  // y*10 + x without a multiplier
    assign cell_bit = board_q[idx];
    assign busy_o = (state != IDLE);

    assign heights_o = heights;

    // adjacent-height difference magnitude for the reduction pass
    logic [4:0]        h_cur, h_prev;
    logic signed [6:0] diff;
    logic [5:0]        absdiff;
    logic [3:0]        rxm1;
    logic [5:0]        ridx, pidx, sidx;    // 5*rx, 5*(rx-1), 5*sx without multipliers
    always_comb begin
        rxm1   = rx - 4'd1;
        ridx   = {rx, 2'b00} + {2'b00, rx};
        pidx   = {rxm1, 2'b00} + {2'b00, rxm1};
        sidx   = {sx, 2'b00} + {2'b00, sx};
        h_cur  = heights[ridx +: 5];
        h_prev = (rx == 4'd0) ? 5'd0 : heights[pidx +: 5];
        diff = $signed({2'b00, h_cur}) - $signed({2'b00, h_prev});
        absdiff = diff[6] ? 6'(-diff) : 6'(diff);
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            state <= IDLE; done_o <= 1'b0; a_o <= 8'd0; q_o <= 8'd0; u_o <= 8'd0; board_q <= '0;
            sx <= 4'd0; sy <= 5'd19; seen <= 1'b0; rx <= 4'd0;
            heights <= '0;
        end else begin
            done_o <= 1'b0;
            case (state)
                IDLE: if (start_i) begin
                    board_q <= board_i; a_o <= 8'd0; q_o <= 8'd0; u_o <= 8'd0;
                    sx <= 4'd0; sy <= 5'd19; seen <= 1'b0; rx <= 4'd0;
                    heights <= '0;
                    state <= SCAN;
                end
                SCAN: begin
                    if (cell_bit) begin
                        if (!seen) begin
                            heights[sidx +: 5] <= sy + 5'd1;
                            seen <= 1'b1;
                        end
                    end else if (seen) begin
                        if (PRECISION == 3) begin
                            if (q_o < 8'd15) q_o <= q_o + 8'd1;     // saturating hole count
                        end else begin
                            q_o <= q_o + 8'd1;
                        end
                    end
                    if (sy == 5'd0) begin
                        sy <= 5'd19; seen <= 1'b0;
                        if (sx == 4'd9) state <= REDUCE;
                        sx <= sx + 4'd1;
                    end else begin
                        sy <= sy - 5'd1;
                    end
                end
                REDUCE: begin
                    a_o <= a_o + {3'd0, h_cur};
                    if (PRECISION != 4 && rx != 4'd0)
                        u_o <= u_o + {2'd0, absdiff};
                    if (rx == 4'd9) state <= FINISH;
                    rx <= rx + 4'd1;
                end
                FINISH: begin
                    done_o <= 1'b1;
                    state  <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
