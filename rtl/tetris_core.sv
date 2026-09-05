// Drop-only Tetris decision engine: request (board, piece[, next piece]) -> best action.
// Ready/valid on both sides, one outstanding request, response fields held until consumed.
// Parameters (validated at elaboration against the supported matrix):
//   ARCH       0 serial A0 evaluator, 1 fast A1 evaluator, 2 pipelined candidate evaluator (A2, one lane,
//              cache representation, depth one, exact profile; docs/design_a2.md)
//   BOARD_REPR 0 bitmap only, 1 bitmap plus an exact height cache built once per request
//   LANES      1 or 2 evaluator lanes (depth one only)
//   DEPTH      1 or 2 (two-piece lookahead, A1/cache/one lane only)
//   PRECISION  0-4 numerical profile
module tetris_core #(
    parameter int ARCH = 0,
    parameter int BOARD_REPR = 0,
    parameter int LANES = 1,
    parameter int DEPTH = 1,
    parameter int PRECISION = 0
) (
    input  logic               clk,
    input  logic               rst,
    input  logic               req_valid,
    output logic               req_ready,
    input  logic [199:0]       board_i,
    input  logic [2:0]         piece_i,
    input  logic [2:0]         next_piece_i,
    output logic               rsp_valid,
    input  logic               rsp_ready,
    output logic               error_o,
    output logic               no_move_o,
    output logic [1:0]         rotation_o,
    output logic [3:0]         x_o,
    output logic [4:0]         y_o,
    output logic signed [31:0] score_o,
    output logic [31:0]        cycles_o
);
    // ---- supported configuration matrix ------------------------------------------------
    localparam bit CFG_OK =
        (ARCH == 0 && BOARD_REPR == 0 && LANES == 1 && DEPTH == 1 && PRECISION == 0) ||
        (ARCH == 1 && BOARD_REPR == 0 && LANES == 1 && DEPTH == 1 && PRECISION == 0) ||
        (ARCH == 1 && BOARD_REPR == 1 && LANES == 1 && DEPTH == 1 && PRECISION >= 0 && PRECISION <= 4) ||
        (ARCH == 1 && BOARD_REPR == 1 && LANES == 1 && DEPTH == 2 && PRECISION == 0) ||
        (ARCH == 1 && BOARD_REPR == 1 && LANES == 2 && DEPTH == 1 && PRECISION == 0) ||
        (ARCH == 2 && BOARD_REPR == 1 && LANES == 1 && DEPTH == 1 && PRECISION == 0);
    generate
        if (!CFG_OK) begin : g_bad_cfg
            $error("tetris_core: unsupported parameter combination ARCH/BOARD_REPR/LANES/DEPTH/PRECISION");
        end
    endgenerate

    typedef enum logic [3:0] {IDLE, CACHE, SEARCH_START, SEARCH_WAIT, REDUCE, FINALIZE, RESPOND} state_t;
    state_t state;

    logic [199:0] board_q;
    logic [2:0]   piece_q, next_q;
    logic [49:0]  heights_q;
    logic [31:0]  cyc;
    logic         err_q;

    // ---- exact height cache of the request board (BOARD_REPR=1) --------------------------
    logic [49:0] board_heights;
    generate
        if (BOARD_REPR == 1) begin : g_cache
            board_profile u_prof (.board_i(board_q), .heights_o(board_heights), .columns_o(), .holes_o());
        end else begin : g_nocache
            assign board_heights = '0;
        end
    endgenerate

    // ---- dense candidate count for the current piece ----------------------------------
    logic [5:0] count;
    cand_rom u_count (.piece_i(piece_q), .index_i(6'd0), .cand_id_o(), .index_valid_o(), .count_o(count));

    // ---- search engines ------------------------------------------------------------------
    logic               search_start;
    logic [LANES-1:0]   lane_done, lane_done_seen, lane_best_valid;
    logic signed [31:0] lane_score [LANES];
    logic [5:0]         lane_id [LANES];
    logic [4:0]         lane_y [LANES];
    logic               s_done, s_valid;
    logic signed [31:0] s_score;
    logic [5:0]         s_id;
    logic [4:0]         s_y;

    generate
        if (ARCH == 2) begin : g_a2
            // A2: one pipelined search mapped to lane slot 0; the existing SEARCH_WAIT/REDUCE/FINALIZE path is reused
            search_pipeline u_search (
                .clk, .rst, .start_i(search_start), .board_i(board_q), .heights_i(heights_q), .piece_i(piece_q),
                .count_i(count), .busy_o(), .done_o(lane_done[0]), .best_valid_o(lane_best_valid[0]),
                .best_score_o(lane_score[0]), .best_id_o(lane_id[0]), .best_y_o(lane_y[0]), .issued_o(), .retired_o());
            assign s_done = 1'b0; assign s_valid = 1'b0; assign s_score = 32'sd0; assign s_id = 6'd0; assign s_y = 5'd0;
        end else if (DEPTH == 1) begin : g_d1
            for (genvar k = 0; k < LANES; k++) begin : g_lane
                lane_player #(.ARCH(ARCH), .BOARD_REPR(BOARD_REPR), .PRECISION(PRECISION), .LANES(LANES), .LANE_INDEX(k)) u_lane (
                    .clk, .rst, .start_i(search_start), .board_i(board_q), .heights_i(heights_q), .piece_i(piece_q),
                    .count_i(count), .busy_o(), .done_o(lane_done[k]), .best_valid_o(lane_best_valid[k]),
                    .best_score_o(lane_score[k]), .best_id_o(lane_id[k]), .best_y_o(lane_y[k]),
                    .evaluated_o(), .legal_o(), .active_cycles_o());
            end
            assign s_done = 1'b0; assign s_valid = 1'b0; assign s_score = 32'sd0; assign s_id = 6'd0; assign s_y = 5'd0;
        end else begin : g_d2
            search_depth2 #(.ARCH(ARCH), .BOARD_REPR(BOARD_REPR), .PRECISION(PRECISION)) u_search (
                .clk, .rst, .start_i(search_start), .board_i(board_q), .heights_i(heights_q), .piece_i(piece_q),
                .next_piece_i(next_q), .busy_o(), .done_o(s_done), .best_valid_o(s_valid), .best_score_o(s_score),
                .best_id_o(s_id), .best_y_o(s_y), .root_candidates_o(), .leaf_candidates_o());
            assign lane_done = '0; assign lane_best_valid = '0;
            always_comb for (int k = 0; k < LANES; k++) begin lane_score[k] = 32'sd0; lane_id[k] = 6'd0; lane_y[k] = 5'd0; end
        end
    endgenerate

    // ---- reduction state ----------------------------------------------------------------
    logic               best_valid;
    logic signed [31:0] best_score;
    logic [5:0]         best_id;
    logic [4:0]         best_y;
    localparam int      RKW = (LANES > 1) ? $clog2(LANES) : 1;
    logic [RKW-1:0]     rk;                 // lane under reduction
    logic               all_done;
    assign all_done = (DEPTH == 1) ? (&(lane_done_seen | lane_done)) : (s_done);

    // best_id -> rotation / x
    logic [1:0] best_rot;
    logic [3:0] best_x;
    always_comb begin
        if (best_id >= 6'd30)      begin best_rot = 2'd3; best_x = 4'(best_id - 6'd30); end
        else if (best_id >= 6'd20) begin best_rot = 2'd2; best_x = 4'(best_id - 6'd20); end
        else if (best_id >= 6'd10) begin best_rot = 2'd1; best_x = 4'(best_id - 6'd10); end
        else                       begin best_rot = 2'd0; best_x = 4'(best_id); end
    end

    assign req_ready = (state == IDLE) && !rst;

    always_ff @(posedge clk) begin
        if (rst) begin
            state <= IDLE; rsp_valid <= 1'b0; error_o <= 1'b0; no_move_o <= 1'b0; rotation_o <= 2'd0; x_o <= 4'd0;
            y_o <= 5'd0; score_o <= 32'sd0; cycles_o <= 32'd0; board_q <= '0; piece_q <= 3'd0; next_q <= 3'd0;
            heights_q <= '0; cyc <= 32'd0; err_q <= 1'b0; search_start <= 1'b0; lane_done_seen <= '0;
            best_valid <= 1'b0; best_score <= 32'sd0; best_id <= 6'd0; best_y <= 5'd0; rk <= '0;
        end else begin
            search_start <= 1'b0;
            if (state != IDLE && state != RESPOND) cyc <= cyc + 32'd1;
            case (state)
                IDLE: if (req_valid) begin
                    board_q <= board_i; piece_q <= piece_i; next_q <= next_piece_i; cyc <= 32'd0;
                    err_q <= (piece_i == 3'd7) || (DEPTH == 2 && next_piece_i == 3'd7);
                    best_valid <= 1'b0; best_score <= 32'sd0; best_id <= 6'd0; best_y <= 5'd0;
                    lane_done_seen <= '0; rk <= '0;
                    state <= CACHE;
                end
                CACHE: begin
                    // one cycle: register the height cache from the latched board (BOARD_REPR=1);
                    // an error request skips the search entirely
                    heights_q <= board_heights;
                    if (err_q) state <= FINALIZE;
                    else       state <= SEARCH_START;
                end
                SEARCH_START: begin
                    search_start <= 1'b1;
                    state <= SEARCH_WAIT;
                end
                SEARCH_WAIT: begin
                    lane_done_seen <= lane_done_seen | lane_done;
                    if (all_done) begin
                        if (DEPTH == 1) state <= REDUCE;
                        else begin
                            best_valid <= s_valid; best_score <= s_score; best_id <= s_id; best_y <= s_y;
                            state <= FINALIZE;
                        end
                    end
                end
                REDUCE: begin
                    // one lane per cycle, deterministic order, global tie-break by candidate_id
                    if (lane_best_valid[rk] && (!best_valid || lane_score[rk] > best_score ||
                        (lane_score[rk] == best_score && lane_id[rk] < best_id))) begin
                        best_valid <= 1'b1; best_score <= lane_score[rk]; best_id <= lane_id[rk]; best_y <= lane_y[rk];
                    end
                    if (rk == RKW'(LANES - 1)) state <= FINALIZE;
                    rk <= rk + 1'b1;
                end
                FINALIZE: begin
                    error_o   <= err_q;
                    no_move_o <= !err_q && !best_valid;
                    rotation_o <= (!err_q && best_valid) ? best_rot : 2'd0;
                    x_o        <= (!err_q && best_valid) ? best_x : 4'd0;
                    y_o        <= (!err_q && best_valid) ? best_y : 5'd0;
                    score_o    <= (!err_q && best_valid) ? best_score : 32'sd0;
                    cycles_o   <= cyc + 32'd1;
                    rsp_valid  <= 1'b1;
                    state <= RESPOND;
                end
                RESPOND: if (rsp_ready) begin
                    rsp_valid <= 1'b0;
                    state <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
