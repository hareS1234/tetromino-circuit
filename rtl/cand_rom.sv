// Dense candidate list: (piece, dense index) -> candidate_id = 10*rotation + x, in
// increasing candidate_id order, plus the per-piece list length (17,9,34,17,17,34,34).
module cand_rom (
    input  logic [2:0] piece_i,
    input  logic [5:0] index_i,
    output logic [5:0] cand_id_o,
    output logic       index_valid_o,
    output logic [5:0] count_o
);
    always_comb begin
        cand_id_o = 6'd0;
        index_valid_o = 1'b0;
        case ({piece_i, index_i})
`include "generated/cand_case.svh"
            default: ;
        endcase
        index_valid_o = (index_i < count_o);
    end
    always_comb begin
        count_o = 6'd0;
        case (piece_i)
`include "generated/cand_count_case.svh"
            default: ;
        endcase
    end
endmodule
