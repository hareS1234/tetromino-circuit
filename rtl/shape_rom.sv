// Combinational piece geometry ROM (generated case body).
// Cell k of the orientation occupies dx_o[2k+:2], dy_o[2k+:2]; bottom_o[2k+:2] is the
// smallest dy in bounding-box column k; colmask_o bit k is set when column k is occupied.
module shape_rom (
    input  logic [2:0] piece_i,
    input  logic [1:0] rot_i,
    output logic [7:0] dx_o,
    output logic [7:0] dy_o,
    output logic [2:0] width_o,
    output logic [2:0] height_o,
    output logic [7:0] bottom_o,
    output logic [3:0] colmask_o,
    output logic       valid_o
);
    always_comb begin
        dx_o = 8'h00; dy_o = 8'h00; width_o = 3'd0; height_o = 3'd0;
        bottom_o = 8'h00; colmask_o = 4'b0000; valid_o = 1'b0;
        case ({piece_i, rot_i})
`include "generated/shape_case.svh"
            default: ;
        endcase
    end
endmodule
