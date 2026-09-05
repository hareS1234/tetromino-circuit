// One-candidate evaluator with a stable start/busy/done transaction boundary.
// ARCH=0: sequential drop / merge / clear / features (A0).
// ARCH=1: closed-form landing from exact heights, mask merge, reused compactor, parallel
//         features (A1).  BOARD_REPR=1 takes the input-board heights from heights_i (a cache
//         built once per request by the parent); BOARD_REPR=0 profiles the input board itself.
// Every candidate starts from the immutable board_i; illegal candidates skip merge/clear/
// features and report legal_o=0 with zero action/score fields.
module candidate_eval #(
    parameter int ARCH = 0,
    parameter int BOARD_REPR = 0,
    parameter int PRECISION = 0
) (
    input  logic               clk,
    input  logic               rst,
    input  logic               start_i,
    input  logic [199:0]       board_i,
    input  logic [49:0]        heights_i,     // exact heights of board_i (BOARD_REPR=1 only)
    input  logic [2:0]         piece_i,
    input  logic [1:0]         rot_i,
    input  logic [3:0]         x_i,
    output logic               busy_o,
    output logic               done_o,
    output logic               legal_o,
    output logic [4:0]         y_o,
    output logic signed [31:0] score_o,
    output logic [2:0]         lines_o,
    output logic [199:0]       board_o,       // post-clear board (depth-two branch context)
    output logic [7:0]         a_o,
    output logic [7:0]         q_o,
    output logic [7:0]         u_o,
    output logic [199:0]       merged_o,      // debug
    output logic [5:0]         phys_y_o,      // debug
    output logic [15:0]        cycles_o       // cycles from start to done (measurement)
);
    typedef enum logic [3:0] {IDLE, DECODE, PROFILE, DROP_START, DROP_WAIT, MERGE_START, MERGE_WAIT,
                              CLEAR_START, CLEAR_WAIT, FEAT_START, FEAT_WAIT, SCORE_START, SCORE_WAIT, FINISH} state_t;
    state_t state;

    logic [199:0] board_q;
    logic [49:0]  heights_q;
    logic [2:0]   piece_q;
    logic [1:0]   rot_q;
    logic [3:0]   x_q;
    logic [15:0]  cyc;

    // geometry
    logic [7:0] dx, dy, bottom;
    logic [2:0] width, height;
    logic [3:0] colmask;
    logic       shape_valid;
    shape_rom u_rom (.piece_i(piece_q), .rot_i(rot_q), .dx_o(dx), .dy_o(dy), .width_o(width),
                     .height_o(height), .bottom_o(bottom), .colmask_o(colmask), .valid_o(shape_valid));

    // sub-unit handshake signals
    logic drop_start, drop_done, drop_legal;
    logic [4:0] drop_y;
    logic [5:0] drop_phys;
    logic merge_start, merge_done;
    logic [199:0] merged;
    logic clear_start, clear_done;
    logic [199:0] cleared;
    logic [4:0] clear_count;
    logic feat_start, feat_done;
    logic [7:0] fa, fq, fu;
    logic [49:0] feat_heights;
    logic score_start, score_valid;
    logic signed [31:0] score_w;
    logic [49:0]  prof_heights;

    generate
        if (ARCH == 0) begin : g_a0
            assign prof_heights = '0;
            drop_unit u_drop (.clk, .rst, .start_i(drop_start), .board_i(board_q), .dx_i(dx), .dy_i(dy),
                              .width_i(width), .height_i(height), .shape_valid_i(shape_valid), .x_i(x_q),
                              .busy_o(), .done_o(drop_done), .legal_o(drop_legal), .y_o(drop_y), .phys_y_o(drop_phys));
            merge_unit u_merge (.clk, .rst, .start_i(merge_start), .board_i(board_q), .dx_i(dx), .dy_i(dy),
                                .x_i(x_q), .y_i(drop_y), .busy_o(), .done_o(merge_done), .board_o(merged));
            features #(.PRECISION(PRECISION)) u_feat (.clk, .rst, .start_i(feat_start), .board_i(cleared),
                                                      .busy_o(), .done_o(feat_done), .a_o(fa), .q_o(fq), .u_o(fu), .heights_o(feat_heights));
        end else begin : g_a1
            // BOARD_REPR=0: profile the latched board in a PROFILE stage on every candidate;
            // BOARD_REPR=1: heights_q holds the parent's per-request cache (no profile logic here).
            if (BOARD_REPR == 1) begin : g_cache
                assign prof_heights = '0;
            end else begin : g_profile
                board_profile u_prof (.board_i(board_q), .heights_o(prof_heights), .columns_o(), .holes_o());
            end
            drop_fast u_drop (.clk, .rst, .start_i(drop_start), .heights_i(heights_q), .bottom_i(bottom), .colmask_i(colmask),
                              .width_i(width), .height_i(height), .shape_valid_i(shape_valid), .x_i(x_q),
                              .busy_o(), .done_o(drop_done), .legal_o(drop_legal), .y_o(drop_y), .phys_y_o(drop_phys));
            merge_fast u_merge (.clk, .rst, .start_i(merge_start), .board_i(board_q), .dx_i(dx), .dy_i(dy),
                                .x_i(x_q), .y_i(drop_y), .busy_o(), .done_o(merge_done), .board_o(merged));
            features_fast #(.PRECISION(PRECISION)) u_feat (.clk, .rst, .start_i(feat_start), .board_i(cleared),
                                                           .busy_o(), .done_o(feat_done), .a_o(fa), .q_o(fq), .u_o(fu), .heights_o(feat_heights));
        end
    endgenerate

    line_clear u_clear (.clk, .rst, .start_i(clear_start), .board_i(merged), .busy_o(), .done_o(clear_done),
                        .board_o(cleared), .count_o(clear_count));
    score #(.PRECISION(PRECISION)) u_score (.clk, .rst, .valid_i(score_start), .a_i(fa), .q_i(fq), .u_i(fu),
                                            .l_i(clear_count[2:0]), .valid_o(score_valid), .score_o(score_w));

    assign busy_o = (state != IDLE);
    assign merged_o = merged;

    always_ff @(posedge clk) begin
        if (rst) begin
            state <= IDLE; done_o <= 1'b0; legal_o <= 1'b0; y_o <= 5'd0; score_o <= 32'sd0; lines_o <= 3'd0;
            board_o <= '0; a_o <= 8'd0; q_o <= 8'd0; u_o <= 8'd0; phys_y_o <= 6'd0; cycles_o <= 16'd0;
            board_q <= '0; heights_q <= '0; piece_q <= 3'd0; rot_q <= 2'd0; x_q <= 4'd0; cyc <= 16'd0;
            drop_start <= 1'b0; merge_start <= 1'b0; clear_start <= 1'b0; feat_start <= 1'b0; score_start <= 1'b0;
        end else begin
            done_o <= 1'b0;
            drop_start <= 1'b0; merge_start <= 1'b0; clear_start <= 1'b0; feat_start <= 1'b0; score_start <= 1'b0;
            if (state != IDLE) cyc <= cyc + 16'd1;
            case (state)
                IDLE: if (start_i) begin
                    board_q <= board_i; heights_q <= heights_i; piece_q <= piece_i; rot_q <= rot_i; x_q <= x_i;
                    cyc <= 16'd0;
                    state <= DECODE;
                end
                DECODE: begin
                    // geometry is combinational from the latched piece/rotation; invalid rotation
                    // or an anchor past the right wall is rejected inside the drop unit
                    if (ARCH == 1 && BOARD_REPR == 0) state <= PROFILE;
                    else                              state <= DROP_START;
                end
                PROFILE: begin
                    heights_q <= prof_heights;      // per-candidate height derivation (bitmap-only A1)
                    state <= DROP_START;
                end
                DROP_START: begin
                    drop_start <= 1'b1;
                    state <= DROP_WAIT;
                end
                DROP_WAIT: if (drop_done) begin
                    if (drop_legal) state <= MERGE_START;
                    else begin
                        legal_o <= 1'b0; y_o <= 5'd0; score_o <= 32'sd0; lines_o <= 3'd0; board_o <= '0;
                        a_o <= 8'd0; q_o <= 8'd0; u_o <= 8'd0; phys_y_o <= drop_phys;
                        state <= FINISH;
                    end
                end
                MERGE_START: begin
                    merge_start <= 1'b1;
                    state <= MERGE_WAIT;
                end
                MERGE_WAIT: if (merge_done) state <= CLEAR_START;
                CLEAR_START: begin
                    clear_start <= 1'b1;
                    state <= CLEAR_WAIT;
                end
                CLEAR_WAIT: if (clear_done) state <= FEAT_START;
                FEAT_START: begin
                    feat_start <= 1'b1;
                    state <= FEAT_WAIT;
                end
                FEAT_WAIT: if (feat_done) state <= SCORE_START;
                SCORE_START: begin
                    score_start <= 1'b1;
                    state <= SCORE_WAIT;
                end
                SCORE_WAIT: if (score_valid) begin
                    legal_o <= 1'b1; y_o <= drop_y; score_o <= score_w; lines_o <= clear_count[2:0];
                    board_o <= cleared; a_o <= fa; q_o <= fq; u_o <= fu; phys_y_o <= drop_phys;
                    state <= FINISH;
                end
                FINISH: begin
                    done_o <= 1'b1;
                    cycles_o <= cyc + 16'd1;
                    state <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
