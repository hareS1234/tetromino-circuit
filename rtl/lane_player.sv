// One evaluator lane: owns dense candidate indices LANE_INDEX, LANE_INDEX+LANES, ... of the
// current piece's valid-geometry list, evaluates them sequentially on a private candidate
// evaluator, and keeps a local best (higher score, then lower candidate_id).  A lane with no
// legal candidate reports best_valid_o=0.  Per-lane counters support the reuse study.
module lane_player #(
    parameter int ARCH = 0,
    parameter int BOARD_REPR = 0,
    parameter int PRECISION = 0,
    parameter int LANES = 1,
    parameter int LANE_INDEX = 0
) (
    input  logic               clk,
    input  logic               rst,
    input  logic               start_i,
    input  logic [199:0]       board_i,
    input  logic [49:0]        heights_i,
    input  logic [2:0]         piece_i,
    input  logic [5:0]         count_i,        // dense candidate count for piece_i
    output logic               busy_o,
    output logic               done_o,
    output logic               best_valid_o,
    output logic signed [31:0] best_score_o,
    output logic [5:0]         best_id_o,
    output logic [4:0]         best_y_o,
    output logic [5:0]         evaluated_o,    // geometric candidates evaluated by this lane
    output logic [5:0]         legal_o,        // of which legal
    output logic [15:0]        active_cycles_o // cycles from start to done
);
    typedef enum logic [2:0] {IDLE, NEXT, EVAL_START, EVAL_WAIT, UPDATE, FINISH} state_t;
    state_t state;

    logic [199:0] board_q;
    logic [49:0]  heights_q;
    logic [2:0]   piece_q;
    logic [5:0]   count_q, j;
    logic [15:0]  cyc;

    logic [5:0] cand_id;
    logic       index_valid;
    logic [5:0] rom_count;
    cand_rom u_cands (.piece_i(piece_q), .index_i(j), .cand_id_o(cand_id), .index_valid_o(index_valid), .count_o(rom_count));

    // candidate_id = 10*rotation + x decoded without division
    logic [1:0] rot;
    logic [3:0] x;
    always_comb begin
        if (cand_id >= 6'd30)      begin rot = 2'd3; x = 4'(cand_id - 6'd30); end
        else if (cand_id >= 6'd20) begin rot = 2'd2; x = 4'(cand_id - 6'd20); end
        else if (cand_id >= 6'd10) begin rot = 2'd1; x = 4'(cand_id - 6'd10); end
        else                       begin rot = 2'd0; x = 4'(cand_id); end
    end

    logic ev_start, ev_done, ev_legal;
    logic [4:0] ev_y;
    logic signed [31:0] ev_score;
    candidate_eval #(.ARCH(ARCH), .BOARD_REPR(BOARD_REPR), .PRECISION(PRECISION)) u_eval (
        .clk, .rst, .start_i(ev_start), .board_i(board_q), .heights_i(heights_q), .piece_i(piece_q),
        .rot_i(rot), .x_i(x), .busy_o(), .done_o(ev_done), .legal_o(ev_legal), .y_o(ev_y), .score_o(ev_score),
        .lines_o(), .board_o(), .a_o(), .q_o(), .u_o(), .merged_o(), .phys_y_o(), .cycles_o());

    logic [5:0] cand_id_q;
    assign busy_o = (state != IDLE);

    always_ff @(posedge clk) begin
        if (rst) begin
            state <= IDLE; done_o <= 1'b0; ev_start <= 1'b0; best_valid_o <= 1'b0; best_score_o <= 32'sd0;
            best_id_o <= 6'd0; best_y_o <= 5'd0; evaluated_o <= 6'd0; legal_o <= 6'd0; active_cycles_o <= 16'd0;
            board_q <= '0; heights_q <= '0; piece_q <= 3'd0; count_q <= 6'd0; j <= 6'd0; cyc <= 16'd0; cand_id_q <= 6'd0;
        end else begin
            done_o <= 1'b0;
            ev_start <= 1'b0;
            if (state != IDLE) cyc <= cyc + 16'd1;
            case (state)
                IDLE: if (start_i) begin
                    board_q <= board_i; heights_q <= heights_i; piece_q <= piece_i; count_q <= count_i;
                    j <= 6'(LANE_INDEX); best_valid_o <= 1'b0; best_score_o <= 32'sd0; best_id_o <= 6'd0; best_y_o <= 5'd0;
                    evaluated_o <= 6'd0; legal_o <= 6'd0; cyc <= 16'd0;
                    state <= NEXT;
                end
                NEXT: begin
                    if (j < count_q) state <= EVAL_START;
                    else             state <= FINISH;
                end
                EVAL_START: begin
                    ev_start <= 1'b1;
                    cand_id_q <= cand_id;
                    state <= EVAL_WAIT;
                end
                EVAL_WAIT: if (ev_done) state <= UPDATE;
                UPDATE: begin
                    evaluated_o <= evaluated_o + 6'd1;
                    if (ev_legal) begin
                        legal_o <= legal_o + 6'd1;
                        if (!best_valid_o || ev_score > best_score_o ||
                            (ev_score == best_score_o && cand_id_q < best_id_o)) begin
                            best_valid_o <= 1'b1; best_score_o <= ev_score; best_id_o <= cand_id_q; best_y_o <= ev_y;
                        end
                    end
                    j <= j + 6'(LANES);
                    state <= NEXT;
                end
                FINISH: begin
                    done_o <= 1'b1;
                    active_cycles_o <= cyc + 16'd1;
                    state <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
