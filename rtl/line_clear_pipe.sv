// Pipelined stable row compaction: banks P4-P12 of the A2 candidate pipeline (guide §5.5, §6),
// nine registered banks under one shared advance_i.  Every bank holds one token or a bubble.
//   P4  keep bits and prefix level 0            P5-P8  prefix strides 1, 2, 4, 8
//   P9  stride 16, final ranks, clear count     P10    20x20 match bits + delayed board
//   P11 five partial rows per destination       P12    compacted board
// The datapath blocks (rank_level, rank_match, row_select_groups, row_select_final) are the
// ones composed combinationally in line_clear_parallel, whose miter proof covers them; this
// module adds only the register/valid discipline:
//   valid[i] <= valid[i-1] on an advancing edge (a bubble shifts through), payload[i] loads
//   stage_function(payload[i-1]) only when valid[i-1]; everything holds when advance_i is low;
//   rst clears every valid bit with priority over advance_i.
// Metadata (legal, y, candidate id, tag, last) travels with its token to the output; the clear
// count is formed at P9 and carried from there.  No output handshake here: the enclosing
// candidate_pipe (or the standalone line_clear_pipe_harness) derives advance_i.
module line_clear_pipe (
    input  logic         clk,
    input  logic         rst,
    input  logic         advance_i,
    input  logic         s_valid_i,
    input  logic [199:0] s_board_i,
    input  logic         s_legal_i,
    input  logic [4:0]   s_y_i,
    input  logic [5:0]   s_id_i,
    input  logic [15:0]  s_tag_i,
    input  logic         s_last_i,
    output logic         m_valid_o,
    output logic [199:0] m_board_o,
    output logic [4:0]   m_cleared_o,
    output logic         m_legal_o,
    output logic [4:0]   m_y_o,
    output logic [5:0]   m_id_o,
    output logic [15:0]  m_tag_o,
    output logic         m_last_o,
    output logic [8:0]   valid_o        // diagnostic: bank valid bits, bit 0 = P4 ... bit 8 = P12
);
    localparam int BANKS = 9;
    localparam int MW = 29;             // {legal, y[4:0], id[5:0], tag[15:0], last}

    // ---- bank registers ----------------------------------------------------------------------
    logic [BANKS-1:0] valid;
    logic [MW-1:0]    meta  [0:BANKS-1];
    logic [199:0]     board [0:5];      // P4..P9 carry the source board; P10 carries it too (board[6] below)
    logic [199:0]     board10;
    logic [19:0]      keep  [0:5];      // P4..P9
    logic [99:0]      lvl   [0:5];      // P4: level 0 ... P9: final ranks
    logic [4:0]       cleared9, cleared10, cleared11, cleared12;
    logic [399:0]     match10;
    logic [999:0]     partial11;
    logic [199:0]     board12;

    // ---- combinational stage functions ---------------------------------------------------------
    logic [19:0]  keep_in;
    logic [99:0]  p0_in, nxt [1:5];
    logic [399:0] match_w;
    logic [999:0] partial_w;
    logic [199:0] board_out_w;
    logic [MW-1:0] meta_in;
    assign meta_in = {s_legal_i, s_y_i, s_id_i, s_tag_i, s_last_i};
    generate
        for (genvar s = 0; s < 20; s++) begin : g_keep
            assign keep_in[s] = (s_board_i[10 * s +: 10] != 10'h3FF);
            assign p0_in[5 * s +: 5] = {4'd0, keep_in[s]};
        end
        for (genvar l = 1; l <= 5; l++) begin : g_level
            rank_level #(.STRIDE(1 << (l - 1))) u_level (.prev_i(lvl[l - 1]), .next_o(nxt[l]));
        end
    endgenerate
    rank_match        u_match  (.keep_i(keep[5]), .rank_i(lvl[5]), .match_o(match_w));
    row_select_groups u_groups (.board_i(board10), .match_i(match10), .partial_o(partial_w));
    row_select_final  u_final  (.partial_i(partial11), .board_o(board_out_w));

    // ---- register discipline -----------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (rst) begin
            valid <= '0;
        end else if (advance_i) begin
            valid[0] <= s_valid_i;
            for (int i = 1; i < BANKS; i++) valid[i] <= valid[i - 1];
        end
    end

    always_ff @(posedge clk) begin
        if (advance_i) begin
            // P4: keep, level 0, board, metadata
            if (s_valid_i) begin
                keep[0] <= keep_in; lvl[0] <= p0_in; board[0] <= s_board_i; meta[0] <= meta_in;
            end
            // P5-P9: one prefix level each; board/keep/metadata delayed alongside
            for (int l = 1; l <= 5; l++) begin
                if (valid[l - 1]) begin
                    lvl[l] <= nxt[l]; keep[l] <= keep[l - 1]; board[l] <= board[l - 1]; meta[l] <= meta[l - 1];
                end
            end
            if (valid[4]) cleared9 <= 5'd20 - nxt[5][95 +: 5];   // P9 forms the count from the final ranks
            // P10: match bits, delayed board and count
            if (valid[5]) begin
                match10 <= match_w; board10 <= board[5]; cleared10 <= cleared9; meta[6] <= meta[5];
            end
            // P11: partial rows
            if (valid[6]) begin
                partial11 <= partial_w; cleared11 <= cleared10; meta[7] <= meta[6];
            end
            // P12: compacted board
            if (valid[7]) begin
                board12 <= board_out_w; cleared12 <= cleared11; meta[8] <= meta[7];
            end
        end
    end

    assign m_valid_o   = valid[BANKS - 1];
    assign m_board_o   = board12;
    assign m_cleared_o = cleared12;
    assign {m_legal_o, m_y_o, m_id_o, m_tag_o, m_last_o} = meta[BANKS - 1];
    assign valid_o     = valid;
endmodule
