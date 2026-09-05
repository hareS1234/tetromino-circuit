// A2 candidate pipeline: banks P0-P22 under one global advance (docs/design_a2.md §4-§6).
//   drop_merge_pipe P0-P3  ->  line_clear_pipe P4-P12  ->  features_pipe P13-P19  ->  score_pipe P20-P22
// Token interface (guide §5.3): one result per accepted candidate, illegal candidates included
// (legal = 0, y = 0, score = 0, metadata carried).  Global advance (guide §5.4):
//   advance = !rst && (!valid[22] || m_ready);  s_ready = advance;  m_valid = valid[22] && !rst
// Every bank of every block uses this one advance; no block starts a private transaction or moves
// while the output is blocked.  The context (board, heights, piece) must be stable while any token
// is in flight: the enclosing search owns it (docs/design_a2.md §3).  Diagnostic values live in
// candidate_pipe_diag.sv, not on production pins.
module candidate_pipe (
    input  logic               clk,
    input  logic               rst,
    input  logic [199:0]       ctx_board_i,
    input  logic [49:0]        ctx_heights_i,
    input  logic [2:0]         ctx_piece_i,
    input  logic               s_valid,
    output logic               s_ready,
    input  logic [1:0]         s_rotation,
    input  logic [3:0]         s_x,
    input  logic [5:0]         s_candidate_id,
    input  logic [15:0]        s_tag,
    input  logic               s_last,
    output logic               m_valid,
    input  logic               m_ready,
    output logic               m_legal,
    output logic               m_last,
    output logic [5:0]         m_candidate_id,
    output logic [15:0]        m_tag,
    output logic [4:0]         m_y,
    output logic signed [31:0] m_score,
    output logic [22:0]        occupancy_o     // bank valid bits P0..P22 (control state for the search's empty check and tests)
);
    localparam int BANKS = 23;          // must equal architecture/a2_stages.json (checked by tools/check_a2_spec.py)
    localparam int VISIBLE_LATENCY = BANKS - 1;
    localparam int TRANSFER_LATENCY = BANKS;

    logic advance, last_valid;
    assign advance = !rst && (!last_valid || m_ready);
    assign s_ready = advance;
    assign m_valid = last_valid && !rst;

    // ---- P0-P3 ---------------------------------------------------------------------------------
    logic         dm_valid, dm_legal, dm_last;
    logic [199:0] dm_board;
    logic [4:0]   dm_y;
    logic [5:0]   dm_id;
    logic [15:0]  dm_tag;
    logic [3:0]   dm_valid_bits;
    drop_merge_pipe u_front (
        .clk, .rst, .advance_i(advance), .ctx_board_i, .ctx_heights_i, .ctx_piece_i,
        .s_valid_i(s_valid), .s_rotation_i(s_rotation), .s_x_i(s_x), .s_id_i(s_candidate_id), .s_tag_i(s_tag), .s_last_i(s_last),
        .m_valid_o(dm_valid), .m_board_o(dm_board), .m_legal_o(dm_legal), .m_y_o(dm_y), .m_id_o(dm_id), .m_tag_o(dm_tag),
        .m_last_o(dm_last), .valid_o(dm_valid_bits));

    // ---- P4-P12 -------------------------------------------------------------------------------
    logic         lc_valid, lc_legal, lc_last;
    logic [199:0] lc_board;
    logic [4:0]   lc_cleared, lc_y;
    logic [5:0]   lc_id;
    logic [15:0]  lc_tag;
    logic [8:0]   lc_valid_bits;
    line_clear_pipe u_clear (
        .clk, .rst, .advance_i(advance),
        .s_valid_i(dm_valid), .s_board_i(dm_board), .s_legal_i(dm_legal), .s_y_i(dm_y), .s_id_i(dm_id), .s_tag_i(dm_tag), .s_last_i(dm_last),
        .m_valid_o(lc_valid), .m_board_o(lc_board), .m_cleared_o(lc_cleared), .m_legal_o(lc_legal), .m_y_o(lc_y), .m_id_o(lc_id),
        .m_tag_o(lc_tag), .m_last_o(lc_last), .valid_o(lc_valid_bits));

    // ---- P13-P19 ------------------------------------------------------------------------------
    logic        ft_valid, ft_legal, ft_last;
    logic [7:0]  ft_a, ft_q, ft_u;
    logic [2:0]  ft_l;
    logic [4:0]  ft_y;
    logic [5:0]  ft_id;
    logic [15:0] ft_tag;
    logic [6:0]  ft_valid_bits;
    features_pipe u_features (
        .clk, .rst, .advance_i(advance),
        .s_valid_i(lc_valid), .s_board_i(lc_board), .s_cleared_i(lc_cleared), .s_legal_i(lc_legal), .s_y_i(lc_y), .s_id_i(lc_id),
        .s_tag_i(lc_tag), .s_last_i(lc_last),
        .m_valid_o(ft_valid), .m_a_o(ft_a), .m_q_o(ft_q), .m_u_o(ft_u), .m_l_o(ft_l), .m_legal_o(ft_legal), .m_y_o(ft_y),
        .m_id_o(ft_id), .m_tag_o(ft_tag), .m_last_o(ft_last), .valid_o(ft_valid_bits));

    // ---- P20-P22 ------------------------------------------------------------------------------
    logic [2:0] sc_valid_bits;
    score_pipe u_score (
        .clk, .rst, .advance_i(advance),
        .s_valid_i(ft_valid), .s_a_i(ft_a), .s_q_i(ft_q), .s_u_i(ft_u), .s_l_i(ft_l), .s_legal_i(ft_legal), .s_y_i(ft_y),
        .s_id_i(ft_id), .s_tag_i(ft_tag), .s_last_i(ft_last),
        .m_valid_o(last_valid), .m_score_o(m_score), .m_legal_o(m_legal), .m_y_o(m_y), .m_id_o(m_candidate_id), .m_tag_o(m_tag),
        .m_last_o(m_last), .valid_o(sc_valid_bits));

    // the authoritative valid/token schedule: 4 + 9 + 7 + 3 banks
    assign occupancy_o = {sc_valid_bits, ft_valid_bits, lc_valid_bits, dm_valid_bits};
    if (BANKS != 23 || VISIBLE_LATENCY != 22 || TRANSFER_LATENCY != 23) begin : g_bad_schedule
        $error("candidate_pipe: bank schedule constants disagree with architecture/a2_stages.json");
    end
endmodule
