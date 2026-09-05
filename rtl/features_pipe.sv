// Exact pipelined feature extraction: banks P13-P19 of the A2 candidate pipeline (guide §7.2).
//   P13  fixed-wiring transpose; per 4-bit column group: local height code (0 empty, else highest
//        occupied position + 1, range 1-4) and occupied count (0-4)
//   P14  height = 4*g + code_g of the highest nonempty group (balanced maximum of encoded values),
//        occupied = balanced sum of the five group counts (<= 20)
//   P15  holes = height - occupied (exact: every occupied cell lies at or below the column top),
//        adjacent |h[c] - h[c-1]| in signed 7-bit arithmetic
//   P16-P19  independent balanced sums of heights (A), holes (Q) and differences (U), padded to
//        16 leaves, widths 6/7/8/9; bounds checked before exposing the low eight bits
// L is the clear count carried from the compactor (3 bits after its bound check).  Same register
// discipline as the other blocks (valid shifts on advance_i, payload loads behind a valid).
module features_pipe (
    input  logic         clk,
    input  logic         rst,
    input  logic         advance_i,
    input  logic         s_valid_i,
    input  logic [199:0] s_board_i,
    input  logic [4:0]   s_cleared_i,
    input  logic         s_legal_i,
    input  logic [4:0]   s_y_i,
    input  logic [5:0]   s_id_i,
    input  logic [15:0]  s_tag_i,
    input  logic         s_last_i,
    output logic         m_valid_o,
    output logic [7:0]   m_a_o,
    output logic [7:0]   m_q_o,
    output logic [7:0]   m_u_o,
    output logic [2:0]   m_l_o,
    output logic         m_legal_o,
    output logic [4:0]   m_y_o,
    output logic [5:0]   m_id_o,
    output logic [15:0]  m_tag_o,
    output logic         m_last_o,
    output logic [6:0]   valid_o        // diagnostic: bank valid bits P13..P19
);
    localparam int MW = 29;             // {legal, y[4:0], id[5:0], tag[15:0], last}
    logic [6:0]    valid;
    logic [MW-1:0] meta [0:6];
    logic [4:0]    cleared [0:6];

    // ---- P13 combinational: transpose, group codes and counts ------------------------------
    logic [149:0] code_w, count_w;       // column c group g at [3*(5c+g) +: 3]
    generate
        for (genvar c = 0; c < 10; c++) begin : g_col
            for (genvar g = 0; g < 5; g++) begin : g_grp
                logic [3:0] bits;        // bits[i] = cell (c, 4g+i)
                assign bits = {s_board_i[10 * (4 * g + 3) + c], s_board_i[10 * (4 * g + 2) + c],
                               s_board_i[10 * (4 * g + 1) + c], s_board_i[10 * (4 * g + 0) + c]};
                assign code_w[3 * (5 * c + g) +: 3] = bits[3] ? 3'd4 : bits[2] ? 3'd3 : bits[1] ? 3'd2 : bits[0] ? 3'd1 : 3'd0;
                assign count_w[3 * (5 * c + g) +: 3] = {2'b00, bits[0]} + {2'b00, bits[1]} + {2'b00, bits[2]} + {2'b00, bits[3]};
            end
        end
    endgenerate
    logic [149:0] code13, count13;

    // ---- P14 combinational: heights and occupied counts ---------------------------------------
    logic [49:0] heights_w, occupied_w;
    generate
        for (genvar c = 0; c < 10; c++) begin : g_h
            logic [4:0] v [5];           // encoded 4g + code, or 0 for an empty group
            logic [4:0] m43, m21, m4321;
            logic [4:0] s01, s23, s0123;
            for (genvar g = 0; g < 5; g++) begin : g_v
                assign v[g] = (code13[3 * (5 * c + g) +: 3] != 3'd0) ? (5'(4 * g) + {2'b00, code13[3 * (5 * c + g) +: 3]}) : 5'd0;
            end
            assign m43   = (v[4] > v[3]) ? v[4] : v[3];
            assign m21   = (v[2] > v[1]) ? v[2] : v[1];
            assign m4321 = (m43 > m21) ? m43 : m21;
            assign heights_w[5 * c +: 5] = (m4321 > v[0]) ? m4321 : v[0];
            assign s01   = {2'b00, count13[3 * (5 * c + 0) +: 3]} + {2'b00, count13[3 * (5 * c + 1) +: 3]};
            assign s23   = {2'b00, count13[3 * (5 * c + 2) +: 3]} + {2'b00, count13[3 * (5 * c + 3) +: 3]};
            assign s0123 = s01 + s23;
            assign occupied_w[5 * c +: 5] = s0123 + {2'b00, count13[3 * (5 * c + 4) +: 3]};
        end
    endgenerate
    logic [49:0] heights14, occupied14;

    // ---- P15 combinational: holes and adjacent differences -----------------------------------
    logic [49:0] holes_w;
    logic [44:0] absd_w;                 // |h[c] - h[c-1]| for c = 1..9 at [5*(c-1) +: 5]
    generate
        for (genvar c = 0; c < 10; c++) begin : g_holes
            assign holes_w[5 * c +: 5] = heights14[5 * c +: 5] - occupied14[5 * c +: 5];
        end
        for (genvar c = 1; c < 10; c++) begin : g_dh
            logic signed [6:0] dd;
            assign dd = $signed({2'b00, heights14[5 * c +: 5]}) - $signed({2'b00, heights14[5 * (c - 1) +: 5]});
            assign absd_w[5 * (c - 1) +: 5] = dd[6] ? 5'(-dd) : 5'(dd);
        end
    endgenerate
    logic [49:0] heights15, holes15;
    logic [44:0] absd15;

    // ---- P16-P19 combinational: balanced sums, 16 leaves per feature ---------------------------
    // level 1 (6-bit): 8 partials; level 2 (7-bit): 4; level 3 (8-bit): 2; level 4 (9-bit): 1
    logic [5:0] a16_w [8], q16_w [8], u16_w [8];
    logic [5:0] a16 [8], q16 [8], u16 [8];
    logic [6:0] a17_w [4], q17_w [4], u17_w [4];
    logic [6:0] a17 [4], q17 [4], u17 [4];
    logic [7:0] a18_w [2], q18_w [2], u18_w [2];
    logic [7:0] a18 [2], q18 [2], u18 [2];
    logic [8:0] a19_w, q19_w, u19_w;
    always_comb begin
        for (int i = 0; i < 8; i++) begin
            a16_w[i] = (i < 5) ? ({1'b0, heights15[10 * i +: 5]} + {1'b0, heights15[10 * i + 5 +: 5]}) : 6'd0;
            q16_w[i] = (i < 5) ? ({1'b0, holes15[10 * i +: 5]} + {1'b0, holes15[10 * i + 5 +: 5]}) : 6'd0;
        end
        for (int i = 0; i < 4; i++) u16_w[i] = {1'b0, absd15[10 * i +: 5]} + {1'b0, absd15[10 * i + 5 +: 5]};
        u16_w[4] = {1'b0, absd15[40 +: 5]};
        u16_w[5] = 6'd0; u16_w[6] = 6'd0; u16_w[7] = 6'd0;
        for (int i = 0; i < 4; i++) begin
            a17_w[i] = {1'b0, a16[2 * i]} + {1'b0, a16[2 * i + 1]};
            q17_w[i] = {1'b0, q16[2 * i]} + {1'b0, q16[2 * i + 1]};
            u17_w[i] = {1'b0, u16[2 * i]} + {1'b0, u16[2 * i + 1]};
        end
        for (int i = 0; i < 2; i++) begin
            a18_w[i] = {1'b0, a17[2 * i]} + {1'b0, a17[2 * i + 1]};
            q18_w[i] = {1'b0, q17[2 * i]} + {1'b0, q17[2 * i + 1]};
            u18_w[i] = {1'b0, u17[2 * i]} + {1'b0, u17[2 * i + 1]};
        end
        a19_w = {1'b0, a18[0]} + {1'b0, a18[1]};
        q19_w = {1'b0, q18[0]} + {1'b0, q18[1]};
        u19_w = {1'b0, u18[0]} + {1'b0, u18[1]};
    end
    logic [7:0] a19, q19, u19;
    logic [2:0] l19;

    // ---- register discipline -----------------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (rst) begin
            valid <= '0;
        end else if (advance_i) begin
            valid[0] <= s_valid_i;
            for (int i = 1; i < 7; i++) valid[i] <= valid[i - 1];
        end
    end

    always_ff @(posedge clk) begin
        if (advance_i) begin
            if (s_valid_i) begin
                code13 <= code_w; count13 <= count_w; cleared[0] <= s_cleared_i; meta[0] <= {s_legal_i, s_y_i, s_id_i, s_tag_i, s_last_i};
            end
            if (valid[0]) begin
                heights14 <= heights_w; occupied14 <= occupied_w; cleared[1] <= cleared[0]; meta[1] <= meta[0];
            end
            if (valid[1]) begin
                heights15 <= heights14; holes15 <= holes_w; absd15 <= absd_w; cleared[2] <= cleared[1]; meta[2] <= meta[1];
            end
            if (valid[2]) begin
                for (int i = 0; i < 8; i++) begin a16[i] <= a16_w[i]; q16[i] <= q16_w[i]; u16[i] <= u16_w[i]; end
                cleared[3] <= cleared[2]; meta[3] <= meta[2];
            end
            if (valid[3]) begin
                for (int i = 0; i < 4; i++) begin a17[i] <= a17_w[i]; q17[i] <= q17_w[i]; u17[i] <= u17_w[i]; end
                cleared[4] <= cleared[3]; meta[4] <= meta[3];
            end
            if (valid[4]) begin
                for (int i = 0; i < 2; i++) begin a18[i] <= a18_w[i]; q18[i] <= q18_w[i]; u18[i] <= u18_w[i]; end
                cleared[5] <= cleared[4]; meta[5] <= meta[4];
            end
            if (valid[5]) begin
                // bounds A <= 200, Q <= 200 (conservative), U <= 180, L <= 4 hold for every board of a
                // legal placement; they are checked in simulation below and the low bits are exposed
                a19 <= a19_w[7:0]; q19 <= q19_w[7:0]; u19 <= u19_w[7:0]; l19 <= cleared[5][2:0];
                cleared[6] <= cleared[5]; meta[6] <= meta[5];
            end
        end
    end

`ifndef SYNTHESIS
    // simulation-only bound checks (guide §7.2): occupied <= height per column; feature/clear bounds
    always_ff @(posedge clk) begin
        if (!rst && advance_i && valid[1]) begin
            for (int c = 0; c < 10; c++)
                assert (occupied14[5 * c +: 5] <= heights14[5 * c +: 5]) else $error("features_pipe: occupied > height in column %0d", c);
        end
        if (!rst && advance_i && valid[5]) begin
            assert (a19_w <= 9'd200 && q19_w <= 9'd200 && u19_w <= 9'd180) else $error("features_pipe: feature bound violated A=%0d Q=%0d U=%0d", a19_w, q19_w, u19_w);
            assert (cleared[5] <= 5'd4 || !meta[5][MW-1]) else $error("features_pipe: legal token with %0d cleared rows", cleared[5]);
        end
    end
`endif

    assign m_valid_o = valid[6];
    assign m_a_o = a19;
    assign m_q_o = q19;
    assign m_u_o = u19;
    assign m_l_o = l19;
    assign {m_legal_o, m_y_o, m_id_o, m_tag_o, m_last_o} = meta[6];
    assign valid_o = valid;
endmodule
