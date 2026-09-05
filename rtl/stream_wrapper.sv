// Registered 32-bit streaming wrapper around tetris_core for place-and-route.
// Request: eight words — w0 = {next_piece[5:3], piece[2:0]}, w1..w6 = board bits 191:0
// (little-endian words), w7 = board bits 199:192 in bits 7:0.  Reserved bits are ignored.
// Response: three words — w0 = {y[12:8], x[7:4], rotation[3:2], no_move[1], error[0]},
// w1 = signed score bit pattern, w2 = core cycles.  Each output word holds while m_valid && !m_ready.
// Input readiness returns only after the whole response has been transmitted.  Reset discards
// an incomplete packet.  All parameters are forwarded explicitly to the core.
module stream_wrapper #(
    parameter int ARCH = 0,
    parameter int BOARD_REPR = 0,
    parameter int LANES = 1,
    parameter int DEPTH = 1,
    parameter int PRECISION = 0
) (
    input  logic        clk,
    input  logic        rst,
    input  logic [31:0] s_data,
    input  logic        s_valid,
    output logic        s_ready,
    output logic [31:0] m_data,
    output logic        m_valid,
    input  logic        m_ready
);
    typedef enum logic [1:0] {RX, REQ, WAIT, TX} state_t;
    state_t state;

    logic [2:0]   widx;           // request word index 0..7
    logic [1:0]   tidx;           // response word index 0..2
    logic [199:0] board_q;
    logic [2:0]   piece_q, next_q;

    logic               req_valid, req_ready, rsp_valid, rsp_ready;
    logic               error_w, no_move_w;
    logic [1:0]         rotation_w;
    logic [3:0]         x_w;
    logic [4:0]         y_w;
    logic signed [31:0] score_w;
    logic [31:0]        cycles_w;
    logic [31:0]        rsp0_q, rsp1_q, rsp2_q;

    tetris_core #(.ARCH(ARCH), .BOARD_REPR(BOARD_REPR), .LANES(LANES), .DEPTH(DEPTH), .PRECISION(PRECISION)) u_core (
        .clk, .rst, .req_valid, .req_ready, .board_i(board_q), .piece_i(piece_q), .next_piece_i(next_q),
        .rsp_valid, .rsp_ready, .error_o(error_w), .no_move_o(no_move_w), .rotation_o(rotation_w),
        .x_o(x_w), .y_o(y_w), .score_o(score_w), .cycles_o(cycles_w));

    assign s_ready   = (state == RX) && !rst;
    assign req_valid = (state == REQ);
    assign rsp_ready = (state == WAIT);
    assign m_valid   = (state == TX);
    always_comb begin
        case (tidx)
            2'd0: m_data = rsp0_q;
            2'd1: m_data = rsp1_q;
            default: m_data = rsp2_q;
        endcase
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            state <= RX; widx <= 3'd0; tidx <= 2'd0; board_q <= '0; piece_q <= 3'd0; next_q <= 3'd0;
            rsp0_q <= 32'd0; rsp1_q <= 32'd0; rsp2_q <= 32'd0;
        end else begin
            case (state)
                RX: if (s_valid) begin
                    case (widx)
                        3'd0: begin piece_q <= s_data[2:0]; next_q <= s_data[5:3]; end
                        3'd7: board_q[199:192] <= s_data[7:0];
                        default: board_q[32 * (widx - 3'd1) +: 32] <= s_data;
                    endcase
                    if (widx == 3'd7) state <= REQ;    // request issued on a later cycle: last byte is registered
                    widx <= widx + 3'd1;
                end
                REQ: if (req_ready) state <= WAIT;
                WAIT: if (rsp_valid) begin
                    rsp0_q <= {19'd0, y_w, x_w, rotation_w, no_move_w, error_w};
                    rsp1_q <= score_w;
                    rsp2_q <= cycles_w;
                    tidx <= 2'd0;
                    state <= TX;
                end
                TX: if (m_ready) begin
                    if (tidx == 2'd2) begin
                        state <= RX;
                        widx <= 3'd0;
                    end
                    tidx <= tidx + 2'd1;
                end
                default: state <= RX;
            endcase
        end
    end
endmodule
