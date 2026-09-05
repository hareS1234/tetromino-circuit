// A0 landing search: literal descent from anchor y=20 (entirely above the board).
// Each cycle tests the four cells one row lower; above-board cells are empty, cells below
// the floor or outside the walls collide, in-board cells collide when occupied.
// legal_o = (landed piece entirely inside rows 0-19); y_o is zero when illegal.
module drop_unit (
    input  logic         clk,
    input  logic         rst,
    input  logic         start_i,
    input  logic [199:0] board_i,
    input  logic [7:0]   dx_i,
    input  logic [7:0]   dy_i,
    input  logic [2:0]   width_i,
    input  logic [2:0]   height_i,
    input  logic         shape_valid_i,
    input  logic [3:0]   x_i,
    output logic         busy_o,
    output logic         done_o,
    output logic         legal_o,
    output logic [4:0]   y_o,
    output logic [5:0]   phys_y_o     // physical anchor 0-20 (debug; meaningful even when illegal)
);
    typedef enum logic [1:0] {IDLE, CHECK, DESCEND, FINISH} state_t;
    state_t state;

    logic [199:0] board_q;
    logic [7:0]   dx_q, dy_q;
    logic [2:0]   height_q, width_q;
    logic         shape_valid_q;
    logic [3:0]   x_q;
    logic [5:0]   y_q;          // 0..20
    logic         geom_ok;

    // Collision test for the piece one row below the current anchor.
    logic               collide;
    logic signed [7:0]  cy [4];
    logic [4:0]         cx [4];
    logic [7:0]         idx [4];
    logic [3:0]         hit;
    always_comb begin
        for (int k = 0; k < 4; k++) begin
            cy[k]  = $signed({2'b00, y_q}) - 8'sd1 + $signed({6'd0, dy_q[2*k +: 2]});
            cx[k]  = {1'b0, x_q} + {3'd0, dx_q[2*k +: 2]};
            // index is always computed; it is only *used* when the cell is inside the board
            idx[k] = {cy[k][4:0], 3'b000} + {2'b00, cy[k][4:0], 1'b0} + {3'd0, cx[k]};  // y*10 + x without a multiplier
            if (cy[k] < 0 || cx[k] > 5'd9)
                hit[k] = 1'b1;
            else if (cy[k] < 8'sd20)
                hit[k] = (idx[k] < 8'd200) ? board_q[idx[k]] : 1'b0;
            else
                hit[k] = 1'b0;
        end
        collide = |hit;
    end

    assign geom_ok = shape_valid_q && ({1'b0, x_q} + {2'b00, width_q} <= 5'd10);
    assign busy_o  = (state != IDLE);

    always_ff @(posedge clk) begin
        if (rst) begin
            state <= IDLE; done_o <= 1'b0; legal_o <= 1'b0; y_o <= 5'd0; phys_y_o <= 6'd0;
            board_q <= '0; dx_q <= '0; dy_q <= '0; height_q <= '0; width_q <= '0; shape_valid_q <= 1'b0;
            x_q <= '0; y_q <= 6'd20;
        end else begin
            done_o <= 1'b0;
            case (state)
                IDLE: if (start_i) begin
                    board_q <= board_i; dx_q <= dx_i; dy_q <= dy_i; height_q <= height_i; width_q <= width_i;
                    shape_valid_q <= shape_valid_i; x_q <= x_i; y_q <= 6'd20;
                    state <= CHECK;
                end
                CHECK: begin
                    if (!geom_ok) state <= FINISH;          // never index the board for bad geometry
                    else          state <= DESCEND;
                end
                DESCEND: begin
                    if (y_q == 6'd0 || collide) state <= FINISH;
                    else                        y_q <= y_q - 6'd1;
                end
                FINISH: begin
                    legal_o  <= geom_ok && ({1'b0, y_q} + {4'd0, height_q} <= 7'd20);
                    y_o      <= (geom_ok && ({1'b0, y_q} + {4'd0, height_q} <= 7'd20)) ? y_q[4:0] : 5'd0;
                    phys_y_o <= y_q;
                    done_o   <= 1'b1;
                    state    <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
