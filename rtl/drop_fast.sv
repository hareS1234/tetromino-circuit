// A1 landing: closed form from exact column heights and the piece's bottom offsets.
//   y_land = max(0, max over occupied columns dx of (heights[x+dx] - bottom[dx]))
//   legal  = shape valid, x + width <= 10, y_land + height <= 20
// Two registered stages after start (select/subtract, then max/clamp/check) so the path fits
// the 50 MHz target.  Subtractions are signed seven-bit so a height smaller than the bottom
// offset cannot wrap.
module drop_fast (
    input  logic        clk,
    input  logic        rst,
    input  logic        start_i,
    input  logic [49:0] heights_i,
    input  logic [7:0]  bottom_i,
    input  logic [3:0]  colmask_i,
    input  logic [2:0]  width_i,
    input  logic [2:0]  height_i,
    input  logic        shape_valid_i,
    input  logic [3:0]  x_i,
    output logic        busy_o,
    output logic        done_o,
    output logic        legal_o,
    output logic [4:0]  y_o,
    output logic [5:0]  phys_y_o
);
    // ---- stage 1 (registered on start): geometry check, height selection, signed differences
    logic               geom_ok_w, geom_ok_q, s1_valid;
    logic signed [6:0]  d_w [4];
    logic signed [6:0]  d_q [4];
    logic [2:0]         height_q;
    logic [4:0]         hsel [4];
    logic [3:0]         col [4];
    logic [5:0]         hidx [4];

    always_comb begin
        geom_ok_w = shape_valid_i && ({1'b0, x_i} + {2'b00, width_i} <= 5'd10);
        for (int k = 0; k < 4; k++) begin
            col[k]  = x_i + 4'(k);                         // bounded by geom_ok when used
            hidx[k] = {col[k], 2'b00} + {2'b00, col[k]};   // 5*col without a multiplier
            hsel[k] = (col[k] <= 4'd9) ? heights_i[hidx[k] +: 5] : 5'd0;
            d_w[k]  = colmask_i[k] ? ($signed({2'b00, hsel[k]}) - $signed({5'd0, bottom_i[2*k +: 2]})) : -7'sd1;
        end
    end

    // ---- stage 2 (registered): maximum, clamp at zero, in-board check --------------------
    logic signed [6:0]  m;
    logic [5:0]         y_land;
    always_comb begin
        m = d_q[0];
        for (int k = 1; k < 4; k++)
            if (d_q[k] > m) m = d_q[k];
        y_land = (m < 0) ? 6'd0 : 6'(m);
    end

    assign busy_o = s1_valid;

    always_ff @(posedge clk) begin
        if (rst) begin
            s1_valid <= 1'b0; done_o <= 1'b0; legal_o <= 1'b0; y_o <= 5'd0; phys_y_o <= 6'd0;
            geom_ok_q <= 1'b0; height_q <= 3'd0;
            for (int k = 0; k < 4; k++) d_q[k] <= 7'sd0;
        end else begin
            s1_valid <= start_i;
            if (start_i) begin
                geom_ok_q <= geom_ok_w;
                height_q  <= height_i;
                for (int k = 0; k < 4; k++) d_q[k] <= d_w[k];
            end
            done_o <= s1_valid;
            if (s1_valid) begin
                legal_o  <= geom_ok_q && ({1'b0, y_land} + {4'd0, height_q} <= 7'd20);
                y_o      <= (geom_ok_q && ({1'b0, y_land} + {4'd0, height_q} <= 7'd20)) ? y_land[4:0] : 5'd0;
                phys_y_o <= geom_ok_q ? y_land : 6'd20;
            end
        end
    end
endmodule
