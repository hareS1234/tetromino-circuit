// Standalone ready/valid wrapper for drop_merge_pipe (U07); not a production module.
module drop_merge_pipe_harness (
    input  logic         clk,
    input  logic         rst,
    input  logic [199:0] ctx_board,
    input  logic [49:0]  ctx_heights,
    input  logic [2:0]   ctx_piece,
    input  logic         s_valid,
    output logic         s_ready,
    input  logic [1:0]   s_rotation,
    input  logic [3:0]   s_x,
    input  logic [5:0]   s_id,
    input  logic [15:0]  s_tag,
    input  logic         s_last,
    output logic         m_valid,
    input  logic         m_ready,
    output logic [199:0] m_board,
    output logic         m_legal,
    output logic [4:0]   m_y,
    output logic [5:0]   m_id,
    output logic [15:0]  m_tag,
    output logic         m_last,
    output logic [3:0]   occupancy_bits
);
    logic advance, pipe_valid;
    assign advance = !rst && (!pipe_valid || m_ready);
    assign s_ready = advance;
    assign m_valid = pipe_valid && !rst;
    drop_merge_pipe u_pipe (
        .clk, .rst, .advance_i(advance), .ctx_board_i(ctx_board), .ctx_heights_i(ctx_heights), .ctx_piece_i(ctx_piece),
        .s_valid_i(s_valid && advance), .s_rotation_i(s_rotation), .s_x_i(s_x), .s_id_i(s_id), .s_tag_i(s_tag), .s_last_i(s_last),
        .m_valid_o(pipe_valid), .m_board_o(m_board), .m_legal_o(m_legal), .m_y_o(m_y), .m_id_o(m_id), .m_tag_o(m_tag),
        .m_last_o(m_last), .valid_o(occupancy_bits));
endmodule
