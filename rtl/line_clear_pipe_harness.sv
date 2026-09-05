// Standalone ready/valid wrapper for line_clear_pipe (U06): derives the global advance from the
// output handshake exactly as candidate_pipe will (guide §5.4):
//   advance = !rst && (!m_valid || m_ready);  s_ready = advance;  m_valid = valid[last] && !rst
// Used by tb/tb_clear_pipe.py and sim/compactor_pipe_main.cpp to create output congestion,
// input bubbles and resets at every occupancy.  Not a production module.
module line_clear_pipe_harness (
    input  logic         clk,
    input  logic         rst,
    input  logic         s_valid,
    output logic         s_ready,
    input  logic [199:0] s_board,
    input  logic         s_legal,
    input  logic [4:0]   s_y,
    input  logic [5:0]   s_id,
    input  logic [15:0]  s_tag,
    input  logic         s_last,
    output logic         m_valid,
    input  logic         m_ready,
    output logic [199:0] m_board,
    output logic [4:0]   m_cleared,
    output logic         m_legal,
    output logic [4:0]   m_y,
    output logic [5:0]   m_id,
    output logic [15:0]  m_tag,
    output logic         m_last,
    output logic [8:0]   occupancy_bits
);
    logic advance, pipe_valid;
    assign advance = !rst && (!pipe_valid || m_ready);
    assign s_ready = advance;
    assign m_valid = pipe_valid && !rst;

    line_clear_pipe u_pipe (
        .clk, .rst, .advance_i(advance),
        .s_valid_i(s_valid && advance), .s_board_i(s_board), .s_legal_i(s_legal), .s_y_i(s_y), .s_id_i(s_id),
        .s_tag_i(s_tag), .s_last_i(s_last),
        .m_valid_o(pipe_valid), .m_board_o(m_board), .m_cleared_o(m_cleared), .m_legal_o(m_legal), .m_y_o(m_y),
        .m_id_o(m_id), .m_tag_o(m_tag), .m_last_o(m_last), .valid_o(occupancy_bits));
endmodule
