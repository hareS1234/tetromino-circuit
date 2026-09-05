// Signed scoring: banks P20-P22 of the A2 candidate pipeline (guide §7.3), exact profile P0 only.
//   P20  widened shift-add coefficient terms on signed 32-bit intermediates:
//        76L = (L<<6)+(L<<3)+(L<<2)   51A = (A<<5)+(A<<4)+(A<<1)+A   36Q = (Q<<5)+(Q<<2)   18U = (U<<4)+(U<<1)
//   P21  pos = 76L - 51A ; neg = 36Q + 18U            (signed 32)
//   P22  score = pos - neg for a legal token, canonical 0 otherwise
// Features are zero-extended into signed 32-bit temporaries before any arithmetic (A = 200 is
// never read as a negative byte).  The conservative exact score bound is [-20640, 304].
module score_pipe (
    input  logic               clk,
    input  logic               rst,
    input  logic               advance_i,
    input  logic               s_valid_i,
    input  logic [7:0]         s_a_i,
    input  logic [7:0]         s_q_i,
    input  logic [7:0]         s_u_i,
    input  logic [2:0]         s_l_i,
    input  logic               s_legal_i,
    input  logic [4:0]         s_y_i,
    input  logic [5:0]         s_id_i,
    input  logic [15:0]        s_tag_i,
    input  logic               s_last_i,
    output logic               m_valid_o,
    output logic signed [31:0] m_score_o,
    output logic               m_legal_o,
    output logic [4:0]         m_y_o,
    output logic [5:0]         m_id_o,
    output logic [15:0]        m_tag_o,
    output logic               m_last_o,
    output logic [2:0]         valid_o        // diagnostic: bank valid bits P20..P22
);
    localparam int MW = 29;
    logic [2:0]    valid;
    logic [MW-1:0] meta [0:2];

    // ---- P20 combinational -------------------------------------------------------------------
    logic signed [31:0] a32, q32, u32, l32, tl_w, ta_w, tq_w, tu_w;
    assign a32 = $signed({24'd0, s_a_i});
    assign q32 = $signed({24'd0, s_q_i});
    assign u32 = $signed({24'd0, s_u_i});
    assign l32 = $signed({29'd0, s_l_i});
    assign tl_w = (l32 <<< 6) + (l32 <<< 3) + (l32 <<< 2);
    assign ta_w = (a32 <<< 5) + (a32 <<< 4) + (a32 <<< 1) + a32;
    assign tq_w = (q32 <<< 5) + (q32 <<< 2);
    assign tu_w = (u32 <<< 4) + (u32 <<< 1);
    logic signed [31:0] tl20, ta20, tq20, tu20;

    // ---- P21 combinational -------------------------------------------------------------------
    logic signed [31:0] pos_w, neg_w, pos21, neg21;
    assign pos_w = tl20 - ta20;
    assign neg_w = tq20 + tu20;

    // ---- P22 combinational -------------------------------------------------------------------
    logic signed [31:0] score_w, score22;
    assign score_w = meta[1][MW-1] ? (pos21 - neg21) : 32'sd0;

    always_ff @(posedge clk) begin
        if (rst) begin
            valid <= '0;
        end else if (advance_i) begin
            valid[0] <= s_valid_i;
            valid[1] <= valid[0];
            valid[2] <= valid[1];
        end
    end

    always_ff @(posedge clk) begin
        if (advance_i) begin
            if (s_valid_i) begin
                tl20 <= tl_w; ta20 <= ta_w; tq20 <= tq_w; tu20 <= tu_w; meta[0] <= {s_legal_i, s_y_i, s_id_i, s_tag_i, s_last_i};
            end
            if (valid[0]) begin
                pos21 <= pos_w; neg21 <= neg_w; meta[1] <= meta[0];
            end
            if (valid[1]) begin
                score22 <= score_w; meta[2] <= meta[1];
            end
        end
    end

    assign m_valid_o = valid[2];
    assign m_score_o = score22;
    assign {m_legal_o, m_y_o, m_id_o, m_tag_o, m_last_o} = meta[2];
    assign valid_o = valid;
endmodule
