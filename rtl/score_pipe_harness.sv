// Standalone ready/valid wrapper for score_pipe (U08); not a production module.
module score_pipe_harness (
    input  logic               clk,
    input  logic               rst,
    input  logic               s_valid,
    output logic               s_ready,
    input  logic [7:0]         s_a,
    input  logic [7:0]         s_q,
    input  logic [7:0]         s_u,
    input  logic [2:0]         s_l,
    input  logic               s_legal,
    input  logic [4:0]         s_y,
    input  logic [5:0]         s_id,
    input  logic [15:0]        s_tag,
    input  logic               s_last,
    output logic               m_valid,
    input  logic               m_ready,
    output logic signed [31:0] m_score,
    output logic               m_legal,
    output logic [4:0]         m_y,
    output logic [5:0]         m_id,
    output logic [15:0]        m_tag,
    output logic               m_last,
    output logic [2:0]         occupancy_bits
);
    logic advance, pipe_valid;
    assign advance = !rst && (!pipe_valid || m_ready);
    assign s_ready = advance;
    assign m_valid = pipe_valid && !rst;
    score_pipe u_pipe (
        .clk, .rst, .advance_i(advance), .s_valid_i(s_valid && advance), .s_a_i(s_a), .s_q_i(s_q), .s_u_i(s_u), .s_l_i(s_l),
        .s_legal_i(s_legal), .s_y_i(s_y), .s_id_i(s_id), .s_tag_i(s_tag), .s_last_i(s_last),
        .m_valid_o(pipe_valid), .m_score_o(m_score), .m_legal_o(m_legal), .m_y_o(m_y), .m_id_o(m_id), .m_tag_o(m_tag),
        .m_last_o(m_last), .valid_o(occupancy_bits));
endmodule
