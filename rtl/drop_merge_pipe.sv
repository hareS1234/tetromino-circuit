// Landing and merge front end: banks P0-P3 of the A2 candidate pipeline (guide §5.5, §7.1).
//   P0  shape decode (generated ROM), x/rotation validity, selection of up to four ORIGINAL
//       column heights from the immutable context (defined zero for unoccupied or out-of-range
//       columns; no packed index is formed from an out-of-range column)
//   P1  four signed 7-bit height-minus-bottom differences (-1 for unoccupied columns)
//   P2  balanced maximum, clamp at zero, legal = geom_ok && y + height <= 20
//   P3  parallel four-cell merge into the immutable context board; each destination row is the OR
//       of the original row and the (up to four) cell contributions with matching global y; an
//       illegal candidate merges a canonical zero board and carries legal = 0
// Same register discipline as line_clear_pipe: valid bits shift on advance_i (bubbles included),
// payloads load only behind a valid, reset has priority.  The context inputs must be stable while
// any token is in flight (search-level ownership, docs/design_a2.md §3).
module drop_merge_pipe (
    input  logic         clk,
    input  logic         rst,
    input  logic         advance_i,
    input  logic [199:0] ctx_board_i,
    input  logic [49:0]  ctx_heights_i,
    input  logic [2:0]   ctx_piece_i,
    input  logic         s_valid_i,
    input  logic [1:0]   s_rotation_i,
    input  logic [3:0]   s_x_i,
    input  logic [5:0]   s_id_i,
    input  logic [15:0]  s_tag_i,
    input  logic         s_last_i,
    output logic         m_valid_o,
    output logic [199:0] m_board_o,
    output logic         m_legal_o,
    output logic [4:0]   m_y_o,
    output logic [5:0]   m_id_o,
    output logic [15:0]  m_tag_o,
    output logic         m_last_o,
    output logic [3:0]   valid_o        // diagnostic: bank valid bits P0..P3
);
    localparam int MW = 23;             // {id[5:0], tag[15:0], last}

    // ---- P0 combinational: decode and height selection ------------------------------------
    logic [7:0] dx_w, dy_w, bottom_w;
    logic [2:0] width_w, height_w;
    logic [3:0] colmask_w;
    logic       shape_valid_w;
    shape_rom u_rom (.piece_i(ctx_piece_i), .rot_i(s_rotation_i), .dx_o(dx_w), .dy_o(dy_w), .width_o(width_w),
                     .height_o(height_w), .bottom_o(bottom_w), .colmask_o(colmask_w), .valid_o(shape_valid_w));
    logic       geom_ok_w;
    logic [4:0] col_w [4];
    logic [4:0] hsel_w [4];
    always_comb begin
        geom_ok_w = shape_valid_w && ({1'b0, s_x_i} + {2'b00, width_w} <= 5'd10);
        for (int k = 0; k < 4; k++) begin
            col_w[k]  = {1'b0, s_x_i} + 5'(k);
            hsel_w[k] = 5'd0;
            for (int c = 0; c < 10; c++)
                if (col_w[k] == 5'(c) && colmask_w[k]) hsel_w[k] = ctx_heights_i[5 * c +: 5];
        end
    end

    // ---- bank 0 (P0) registers ------------------------------------------------------------
    logic [3:0]  valid;
    logic [MW-1:0] meta [0:3];
    logic        geom_ok0;
    logic [3:0]  x0;
    logic [7:0]  dx0, dy0, bottom0;
    logic [2:0]  height0;
    logic [3:0]  colmask0;
    logic [4:0]  hsel0 [4];

    // ---- P1 combinational: signed differences ----------------------------------------------
    logic signed [6:0] diff_w [4];
    always_comb begin
        for (int k = 0; k < 4; k++)
            diff_w[k] = colmask0[k] ? ($signed({2'b00, hsel0[k]}) - $signed({5'd0, bottom0[2 * k +: 2]})) : -7'sd1;
    end
    logic signed [6:0] diff1 [4];
    logic        geom_ok1;
    logic [3:0]  x1;
    logic [7:0]  dx1, dy1;
    logic [2:0]  height1;

    // ---- P2 combinational: balanced maximum, clamp, legality --------------------------------
    logic signed [6:0] m01_w, m23_w, m_w;
    logic [5:0]  y_land_w;
    logic        legal_w;
    always_comb begin
        m01_w = (diff1[0] > diff1[1]) ? diff1[0] : diff1[1];
        m23_w = (diff1[2] > diff1[3]) ? diff1[2] : diff1[3];
        m_w   = (m01_w > m23_w) ? m01_w : m23_w;
        y_land_w = (m_w < 0) ? 6'd0 : 6'(m_w);
        legal_w  = geom_ok1 && ({1'b0, y_land_w} + {4'd0, height1} <= 7'd20);
    end
    logic        legal2;
    logic [4:0]  y2;
    logic [3:0]  x2;
    logic [7:0]  dx2, dy2;

    // ---- P3 combinational: explicit per-row merge ---------------------------------------------
    logic [4:0]   cy_w [4];
    logic [3:0]   cx_w [4];
    logic [9:0]   cell_oh_w [4];        // one-hot column mask of cell k (in-range guard)
    logic [199:0] cell_rows_w [4];      // contribution of cell k to every row: row r at [10r +: 10]
    logic [199:0] merged_w;
    always_comb begin
        for (int k = 0; k < 4; k++) begin
            cy_w[k] = y2 + {3'd0, dy2[2 * k +: 2]};
            cx_w[k] = x2 + {2'd0, dx2[2 * k +: 2]};
            cell_oh_w[k] = (cx_w[k] <= 4'd9) ? (10'd1 << cx_w[k]) : 10'd0;
            for (int r = 0; r < 20; r++)
                cell_rows_w[k][10 * r +: 10] = (cy_w[k] == 5'(r)) ? cell_oh_w[k] : 10'd0;
        end
        for (int r = 0; r < 20; r++) begin
            merged_w[10 * r +: 10] = legal2 ? (ctx_board_i[10 * r +: 10] |
                                               ((cell_rows_w[0][10 * r +: 10] | cell_rows_w[1][10 * r +: 10]) |
                                                (cell_rows_w[2][10 * r +: 10] | cell_rows_w[3][10 * r +: 10]))) : 10'd0;
        end
    end
    logic [199:0] board3;
    logic         legal3;
    logic [4:0]   y3;

    // ---- register discipline -------------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (rst) begin
            valid <= '0;
        end else if (advance_i) begin
            valid[0] <= s_valid_i;
            valid[1] <= valid[0];
            valid[2] <= valid[1];
            valid[3] <= valid[2];
        end
    end

    always_ff @(posedge clk) begin
        if (advance_i) begin
            if (s_valid_i) begin
                geom_ok0 <= geom_ok_w; x0 <= s_x_i; dx0 <= dx_w; dy0 <= dy_w; bottom0 <= bottom_w; height0 <= height_w;
                colmask0 <= colmask_w; meta[0] <= {s_id_i, s_tag_i, s_last_i};
                for (int k = 0; k < 4; k++) hsel0[k] <= hsel_w[k];
            end
            if (valid[0]) begin
                for (int k = 0; k < 4; k++) diff1[k] <= diff_w[k];
                geom_ok1 <= geom_ok0; x1 <= x0; dx1 <= dx0; dy1 <= dy0; height1 <= height0; meta[1] <= meta[0];
            end
            if (valid[1]) begin
                legal2 <= legal_w; y2 <= legal_w ? y_land_w[4:0] : 5'd0; x2 <= x1; dx2 <= dx1; dy2 <= dy1; meta[2] <= meta[1];
            end
            if (valid[2]) begin
                board3 <= merged_w; legal3 <= legal2; y3 <= y2; meta[3] <= meta[2];
            end
        end
    end

    assign m_valid_o = valid[3];
    assign m_board_o = board3;
    assign m_legal_o = legal3;
    assign m_y_o     = y3;
    assign {m_id_o, m_tag_o, m_last_o} = meta[3];
    assign valid_o   = valid;
endmodule
