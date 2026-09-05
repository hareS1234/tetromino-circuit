// Simulation-only wrapper exposing the A1 datapath modules for module-level tests.
module fast_tb (
    input  logic         clk,
    input  logic         rst,
    input  logic [199:0] board_i,
    // profile (combinational)
    output logic [49:0]  heights_o,
    output logic [199:0] columns_o,
    output logic [199:0] holes_o,
    // drop_fast
    input  logic         drop_start_i,
    input  logic [49:0]  drop_heights_i,
    input  logic [2:0]   piece_i,
    input  logic [1:0]   rot_i,
    input  logic [3:0]   x_i,
    output logic         drop_done_o,
    output logic         drop_legal_o,
    output logic [4:0]   drop_y_o,
    output logic [5:0]   drop_phys_o,
    // merge_fast
    input  logic         merge_start_i,
    input  logic [4:0]   merge_y_i,
    output logic         merge_done_o,
    output logic [199:0] merged_o,
    // features_fast
    input  logic         feat_start_i,
    output logic         feat_done_o,
    output logic [7:0]   a_o,
    output logic [7:0]   q_o,
    output logic [7:0]   u_o,
    output logic [49:0]  feat_heights_o
);
    parameter int PRECISION = 0;
    board_profile u_prof (.board_i, .heights_o, .columns_o, .holes_o);

    logic [7:0] dx, dy, bottom;
    logic [2:0] width, height;
    logic [3:0] colmask;
    logic       valid;
    shape_rom u_rom (.piece_i, .rot_i, .dx_o(dx), .dy_o(dy), .width_o(width), .height_o(height),
                     .bottom_o(bottom), .colmask_o(colmask), .valid_o(valid));
    drop_fast u_drop (.clk, .rst, .start_i(drop_start_i), .heights_i(drop_heights_i), .bottom_i(bottom), .colmask_i(colmask),
                      .width_i(width), .height_i(height), .shape_valid_i(valid), .x_i, .busy_o(),
                      .done_o(drop_done_o), .legal_o(drop_legal_o), .y_o(drop_y_o), .phys_y_o(drop_phys_o));
    merge_fast u_merge (.clk, .rst, .start_i(merge_start_i), .board_i, .dx_i(dx), .dy_i(dy), .x_i, .y_i(merge_y_i),
                        .busy_o(), .done_o(merge_done_o), .board_o(merged_o));
    features_fast #(.PRECISION(PRECISION)) u_feat (.clk, .rst, .start_i(feat_start_i), .board_i, .busy_o(),
                                                   .done_o(feat_done_o), .a_o, .q_o, .u_o, .heights_o(feat_heights_o));
endmodule
