// Row compactor: twenty-iteration scan with no indexed access.  Each cycle the top row of the
// latched input is examined and the input is shifted up by one row; a surviving row is pushed
// into the bottom of the output register (shifting earlier survivors up), so the survivors keep
// their order and the vacated top rows are zero.  Accepts arbitrary boards (0-20 full rows).
// A FINISH state lets the last push settle before done.
module line_clear (
    input  logic         clk,
    input  logic         rst,
    input  logic         start_i,
    input  logic [199:0] board_i,
    output logic         busy_o,
    output logic         done_o,
    output logic [199:0] board_o,
    output logic [4:0]   count_o
);
    typedef enum logic [1:0] {IDLE, SCAN, FINISH} state_t;
    state_t state;
    logic [199:0] in_q;
    logic [4:0]   step;
    logic [9:0]   row;

    assign row    = in_q[199:190];       // row 19 of the remaining input
    assign busy_o = (state != IDLE);

    always_ff @(posedge clk) begin
        if (rst) begin
            state <= IDLE; done_o <= 1'b0; board_o <= '0; count_o <= 5'd0; in_q <= '0; step <= 5'd0;
        end else begin
            done_o <= 1'b0;
            case (state)
                IDLE: if (start_i) begin
                    in_q <= board_i; board_o <= '0; count_o <= 5'd0; step <= 5'd0;
                    state <= SCAN;
                end
                SCAN: begin
                    if (row == 10'h3FF)
                        count_o <= count_o + 5'd1;
                    else
                        board_o <= {board_o[189:0], row};
                    in_q <= {in_q[189:0], 10'd0};
                    if (step == 5'd19) state <= FINISH;
                    step <= step + 5'd1;
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
