// Two-piece lookahead: a nested sequential search around one candidate evaluator.
// For every legal root candidate (current piece on the immutable root board) the post-clear
// board B1 and its line count L1 are copied into dedicated registers, an exact height cache of
// B1 is built once, and every next-piece candidate is evaluated on B1.  A leaf's score is the
// evaluator's own score (its L2 in 0-4) plus wL*L1 added here, so intermediate-board penalties
// are never counted twice.  Roots with at least one legal leaf ("surviving") are preferred; if
// none survives the best one-move score S1 is the defined fallback.  Ties break by the lower
// candidate_id at both levels.
module search_depth2 #(
    parameter int ARCH = 1,
    parameter int BOARD_REPR = 1,
    parameter int PRECISION = 0
) (
    input  logic               clk,
    input  logic               rst,
    input  logic               start_i,
    input  logic [199:0]       board_i,
    input  logic [49:0]        heights_i,        // exact heights of board_i (cache)
    input  logic [2:0]         piece_i,
    input  logic [2:0]         next_piece_i,
    output logic               busy_o,
    output logic               done_o,
    output logic               best_valid_o,
    output logic signed [31:0] best_score_o,     // S2 of the chosen branch, or S1 for the fallback
    output logic [5:0]         best_id_o,
    output logic [4:0]         best_y_o,
    output logic [5:0]         root_candidates_o,   // legal roots
    output logic [15:0]        leaf_candidates_o    // legal leaves evaluated in total
);
    typedef enum logic [3:0] {IDLE, ROOT_NEXT, ROOT_START, ROOT_WAIT, B1_CACHE, LEAF_NEXT, LEAF_START, LEAF_WAIT,
                              ROOT_UPDATE, FINISH} state_t;
    state_t state;

    // line bonus wL*L1 for the compiled profile
    localparam int WL = (PRECISION == 1) ? 64 : (PRECISION == 2) ? 80 : 76;

    logic [199:0] root_board, b1_board;
    logic [49:0]  root_heights, b1_heights;
    logic [2:0]   piece_q, next_q;
    logic [5:0]   jr, jl;                       // dense indices
    logic         leaf_phase;                   // evaluator context: 0 root, 1 leaf

    // candidate lists
    logic [5:0] root_count, leaf_count, root_cid, leaf_cid;
    cand_rom u_root (.piece_i(piece_q), .index_i(jr), .cand_id_o(root_cid), .index_valid_o(), .count_o(root_count));
    cand_rom u_leaf (.piece_i(next_q), .index_i(jl), .cand_id_o(leaf_cid), .index_valid_o(), .count_o(leaf_count));

    logic [5:0] cid_sel;
    logic [1:0] rot_sel;
    logic [3:0] x_sel;
    always_comb begin
        cid_sel = leaf_phase ? leaf_cid : root_cid;
        if (cid_sel >= 6'd30)      begin rot_sel = 2'd3; x_sel = 4'(cid_sel - 6'd30); end
        else if (cid_sel >= 6'd20) begin rot_sel = 2'd2; x_sel = 4'(cid_sel - 6'd20); end
        else if (cid_sel >= 6'd10) begin rot_sel = 2'd1; x_sel = 4'(cid_sel - 6'd10); end
        else                       begin rot_sel = 2'd0; x_sel = 4'(cid_sel); end
    end

    // one shared evaluator
    logic ev_start, ev_done, ev_legal;
    logic [4:0] ev_y;
    logic signed [31:0] ev_score;
    logic [2:0] ev_lines;
    logic [199:0] ev_board;
    candidate_eval #(.ARCH(ARCH), .BOARD_REPR(BOARD_REPR), .PRECISION(PRECISION)) u_eval (
        .clk, .rst, .start_i(ev_start),
        .board_i(leaf_phase ? b1_board : root_board), .heights_i(leaf_phase ? b1_heights : root_heights),
        .piece_i(leaf_phase ? next_q : piece_q), .rot_i(rot_sel), .x_i(x_sel),
        .busy_o(), .done_o(ev_done), .legal_o(ev_legal), .y_o(ev_y), .score_o(ev_score), .lines_o(ev_lines),
        .board_o(ev_board), .a_o(), .q_o(), .u_o(), .merged_o(), .phys_y_o(), .cycles_o());

    // B1 height cache (built once per legal root)
    logic [49:0] b1_prof;
    board_profile u_b1 (.board_i(b1_board), .heights_o(b1_prof), .columns_o(), .holes_o());

    // current root context
    logic [5:0]         root_id;
    logic [4:0]         root_y;
    logic signed [31:0] s1;
    logic [2:0]         l1;
    logic signed [31:0] bonus;
    always_comb begin
        case (l1)
            3'd0: bonus = 32'sd0;
            3'd1: bonus = 32'(WL);
            3'd2: bonus = 32'(2 * WL);
            3'd3: bonus = 32'(3 * WL);
            default: bonus = 32'(4 * WL);
        endcase
    end
    logic signed [31:0] s2;
    assign s2 = ev_score + bonus;

    // branch best (over leaves of the current root), surviving best, fallback best
    logic               branch_valid;
    logic signed [31:0] branch_score;
    logic               surv_valid, fb_valid;
    logic signed [31:0] surv_score, fb_score;
    logic [5:0]         surv_id, fb_id;
    logic [4:0]         surv_y, fb_y;

    assign busy_o = (state != IDLE);

    always_ff @(posedge clk) begin
        if (rst) begin
            state <= IDLE; done_o <= 1'b0; ev_start <= 1'b0; best_valid_o <= 1'b0; best_score_o <= 32'sd0;
            best_id_o <= 6'd0; best_y_o <= 5'd0; root_candidates_o <= 6'd0; leaf_candidates_o <= 16'd0;
            root_board <= '0; b1_board <= '0; root_heights <= '0; b1_heights <= '0; piece_q <= 3'd0; next_q <= 3'd0;
            jr <= 6'd0; jl <= 6'd0; leaf_phase <= 1'b0; root_id <= 6'd0; root_y <= 5'd0; s1 <= 32'sd0; l1 <= 3'd0;
            branch_valid <= 1'b0; branch_score <= 32'sd0; surv_valid <= 1'b0; fb_valid <= 1'b0;
            surv_score <= 32'sd0; fb_score <= 32'sd0; surv_id <= 6'd0; fb_id <= 6'd0; surv_y <= 5'd0; fb_y <= 5'd0;
        end else begin
            done_o <= 1'b0;
            ev_start <= 1'b0;
            case (state)
                IDLE: if (start_i) begin
                    root_board <= board_i; root_heights <= heights_i; piece_q <= piece_i; next_q <= next_piece_i;
                    jr <= 6'd0; leaf_phase <= 1'b0; surv_valid <= 1'b0; fb_valid <= 1'b0;
                    root_candidates_o <= 6'd0; leaf_candidates_o <= 16'd0;
                    state <= ROOT_NEXT;
                end
                ROOT_NEXT: begin
                    leaf_phase <= 1'b0;
                    if (jr < root_count) state <= ROOT_START;
                    else                 state <= FINISH;
                end
                ROOT_START: begin
                    ev_start <= 1'b1;
                    root_id <= root_cid;
                    state <= ROOT_WAIT;
                end
                ROOT_WAIT: if (ev_done) begin
                    if (ev_legal) begin
                        b1_board <= ev_board; l1 <= ev_lines; s1 <= ev_score; root_y <= ev_y;
                        root_candidates_o <= root_candidates_o + 6'd1;
                        branch_valid <= 1'b0; branch_score <= 32'sd0; jl <= 6'd0;
                        state <= B1_CACHE;
                    end else begin
                        jr <= jr + 6'd1;
                        state <= ROOT_NEXT;
                    end
                end
                B1_CACHE: begin
                    b1_heights <= b1_prof;          // exact heights of B1, built once per root
                    leaf_phase <= 1'b1;
                    state <= LEAF_NEXT;
                end
                LEAF_NEXT: begin
                    if (jl < leaf_count) state <= LEAF_START;
                    else                 state <= ROOT_UPDATE;
                end
                LEAF_START: begin
                    ev_start <= 1'b1;
                    state <= LEAF_WAIT;
                end
                LEAF_WAIT: if (ev_done) begin
                    if (ev_legal) begin
                        leaf_candidates_o <= leaf_candidates_o + 16'd1;
                        if (!branch_valid || s2 > branch_score) begin   // leaves visited in increasing id order
                            branch_valid <= 1'b1; branch_score <= s2;
                        end
                    end
                    jl <= jl + 6'd1;
                    state <= LEAF_NEXT;
                end
                ROOT_UPDATE: begin
                    if (branch_valid && (!surv_valid || branch_score > surv_score ||
                        (branch_score == surv_score && root_id < surv_id))) begin
                        surv_valid <= 1'b1; surv_score <= branch_score; surv_id <= root_id; surv_y <= root_y;
                    end
                    if (!fb_valid || s1 > fb_score || (s1 == fb_score && root_id < fb_id)) begin
                        fb_valid <= 1'b1; fb_score <= s1; fb_id <= root_id; fb_y <= root_y;
                    end
                    jr <= jr + 6'd1;
                    state <= ROOT_NEXT;
                end
                FINISH: begin
                    if (surv_valid) begin
                        best_valid_o <= 1'b1; best_score_o <= surv_score; best_id_o <= surv_id; best_y_o <= surv_y;
                    end else if (fb_valid) begin
                        best_valid_o <= 1'b1; best_score_o <= fb_score; best_id_o <= fb_id; best_y_o <= fb_y;
                    end else begin
                        best_valid_o <= 1'b0; best_score_o <= 32'sd0; best_id_o <= 6'd0; best_y_o <= 5'd0;
                    end
                    done_o <= 1'b1;
                    state <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
