// Running-best reducer for retired candidate tokens (docs/design_a2.md §7).
//   take = valid_i && legal_i && (!best_valid_o || score_i > best_score_o ||
//                                 (score_i == best_score_o && id_i < best_id_o))      (signed score)
// clear_i restarts the reduction (best_valid_o = 0) with priority over take.  The output registers
// hold the best of all legal tokens retired since the last clear; the token retired on the same edge
// as last is included (search_pipeline reads best_* one cycle after done).  Unit-tested (V10 winner
// hazards) and proved under formal/reducer/.
module best_reducer (
    input  logic               clk,
    input  logic               rst,
    input  logic               clear_i,
    input  logic               valid_i,
    input  logic               legal_i,
    input  logic signed [31:0] score_i,
    input  logic [5:0]         id_i,
    input  logic [4:0]         y_i,
    output logic               best_valid_o,
    output logic signed [31:0] best_score_o,
    output logic [5:0]         best_id_o,
    output logic [4:0]         best_y_o
);
    logic take;
    assign take = valid_i && legal_i && (!best_valid_o || score_i > best_score_o ||
                                         (score_i == best_score_o && id_i < best_id_o));
    always_ff @(posedge clk) begin
        if (rst || clear_i) begin
            best_valid_o <= 1'b0; best_score_o <= 32'sd0; best_id_o <= 6'd0; best_y_o <= 5'd0;
        end else if (take) begin
            best_valid_o <= 1'b1; best_score_o <= score_i; best_id_o <= id_i; best_y_o <= y_i;
        end
    end
endmodule
