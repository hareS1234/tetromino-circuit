// Best-reduction proof (guide §8.3 target 3): after any accepted sequence, best equals the maximum
// under the (signed score, lower id) ordering, invalid/illegal tokens and equal scores included.
// Decomposed for k-induction:
//   (a) dominance: for an arbitrary fixed witness token (anyconst), once a legal valid token equal
//       to the witness has been accepted since the last clear, best is valid and >= the witness;
//   (b) provenance: best is always (invalid) or a token that was accepted since the last clear, so
//       best is never invented (tracked by a "best changed only on take" shadow);
//   (c) monotonic: an accepted step never makes best smaller under the ordering.
// (a)+(b) give "best is the maximum of the accepted legal tokens".
module reducer_proof (
    input logic               clk,
    input logic               rst,
    input logic               clear_i,
    input logic               valid_i,
    input logic               legal_i,
    input logic signed [31:0] score_i,
    input logic [5:0]         id_i,
    input logic [4:0]         y_i
);
    logic               best_valid;
    logic signed [31:0] best_score;
    logic [5:0]         best_id;
    logic [4:0]         best_y;
    best_reducer dut (.clk, .rst, .clear_i, .valid_i, .legal_i, .score_i, .id_i, .y_i,
                      .best_valid_o(best_valid), .best_score_o(best_score), .best_id_o(best_id), .best_y_o(best_y));

    // ordering: a >= b
    function automatic logic geq(input logic signed [31:0] sa, input logic [5:0] ia, input logic signed [31:0] sb, input logic [5:0] ib);
        geq = (sa > sb) || (sa == sb && ia <= ib);
    endfunction

`ifdef FORMAL
    (* anyconst *) logic signed [31:0] w_score;
    (* anyconst *) logic [5:0]         w_id;
    logic seen;                          // witness accepted (legal, valid) since the last clear/reset
    logic [4:0] w_y;                     // y of the accepted witness (for the provenance check)
    initial assume (rst);
    always_ff @(posedge clk) begin
        if (rst || clear_i) seen <= 1'b0;
        else if (valid_i && legal_i && score_i == w_score && id_i == w_id) seen <= 1'b1;
    end
    // shadow of the previous best for monotonicity
    logic               p_valid;
    logic signed [31:0] p_score;
    logic [5:0]         p_id;
    logic               p_clear;
    always_ff @(posedge clk) begin
        p_valid <= best_valid; p_score <= best_score; p_id <= best_id; p_clear <= rst || clear_i;
    end
    always_comb begin
        if (!$initstate) begin
            // (a) dominance
            if (seen) begin
                assert (best_valid);
                assert (geq(best_score, best_id, w_score, w_id));
            end
            // (c) monotonic: unless cleared, a valid best never gets worse and stays valid
            if (!p_clear && p_valid) begin
                assert (best_valid);
                assert (geq(best_score, best_id, p_score, p_id));
            end
            // after a clear the best is invalid
            if (p_clear) assert (!best_valid && best_score == 32'sd0 && best_id == 6'd0);
        end
    end
    // (b) provenance: best only changes to the token being accepted (legal, valid) or to the cleared state
    always_ff @(posedge clk) begin
        if (!$initstate && !p_clear && !(rst || clear_i)) begin
            if (best_valid != $past(best_valid) || best_score != $past(best_score) || best_id != $past(best_id) || best_y != $past(best_y)) begin
                assert ($past(valid_i) && $past(legal_i) && best_valid && best_score == $past(score_i) && best_id == $past(id_i) && best_y == $past(y_i));
            end
        end
    end
    always_comb cover (seen && best_valid && best_score == w_score && best_id == w_id);
    always_comb cover (seen && best_valid && best_score > w_score);
    always_comb cover (seen && best_valid && best_score == w_score && best_id < w_id);
`endif
endmodule
