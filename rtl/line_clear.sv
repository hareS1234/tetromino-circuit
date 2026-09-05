// Row compactor: scans rows 0..19 with separate read and write pointers, drops full rows,
// preserves the order of surviving rows, and zero-fills the top.  Accepts arbitrary boards
// (clear count 0-20, five bits).  A FINISH state lets the last write settle before done.
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
    logic [4:0]   read_y, write_y;
    logic [9:0]   row;

    assign row    = in_q[10 * read_y +: 10];
    assign busy_o = (state != IDLE);

    always_ff @(posedge clk) begin
        if (rst) begin
            state <= IDLE; done_o <= 1'b0; board_o <= '0; count_o <= 5'd0; in_q <= '0; read_y <= 5'd0; write_y <= 5'd0;
        end else begin
            done_o <= 1'b0;
            case (state)
                IDLE: if (start_i) begin
                    in_q <= board_i; board_o <= '0; count_o <= 5'd0; read_y <= 5'd0; write_y <= 5'd0;
                    state <= SCAN;
                end
                SCAN: begin
                    if (row == 10'h3FF) begin
                        count_o <= count_o + 5'd1;
                    end else begin
                        if (write_y < 5'd20)
                            board_o[10 * write_y +: 10] <= row;
                        write_y <= write_y + 5'd1;
                    end
                    if (read_y == 5'd19) state <= FINISH;
                    read_y <= read_y + 5'd1;
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
