// A0 merge: copy the board into a private register, then set one piece cell per cycle.
// Writing one cell per cycle avoids the multiple-nonblocking-writes-to-one-row hazard.
module merge_unit (
    input  logic         clk,
    input  logic         rst,
    input  logic         start_i,
    input  logic [199:0] board_i,
    input  logic [7:0]   dx_i,
    input  logic [7:0]   dy_i,
    input  logic [3:0]   x_i,
    input  logic [4:0]   y_i,
    output logic         busy_o,
    output logic         done_o,
    output logic [199:0] board_o
);
    typedef enum logic [1:0] {IDLE, WRITE, FINISH} state_t;
    state_t state;
    logic [7:0] dx_q, dy_q;
    logic [3:0] x_q;
    logic [4:0] y_q;
    logic [1:0] k;
    logic [7:0] idx;

    always_comb begin
        idx = ({3'd0, y_q} + {6'd0, dy_q[2*k +: 2]}) * 8'd10 + {4'd0, x_q} + {6'd0, dx_q[2*k +: 2]};
    end
    assign busy_o = (state != IDLE);

    always_ff @(posedge clk) begin
        if (rst) begin
            state <= IDLE; done_o <= 1'b0; board_o <= '0; dx_q <= '0; dy_q <= '0; x_q <= '0; y_q <= '0; k <= 2'd0;
        end else begin
            done_o <= 1'b0;
            case (state)
                IDLE: if (start_i) begin
                    board_o <= board_i; dx_q <= dx_i; dy_q <= dy_i; x_q <= x_i; y_q <= y_i; k <= 2'd0;
                    state <= WRITE;
                end
                WRITE: begin
                    if (idx < 8'd200)
                        board_o[idx] <= 1'b1;
                    if (k == 2'd3) state <= FINISH;
                    k <= k + 2'd1;
                end
                FINISH: begin
                    done_o <= 1'b1;
                    state  <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
