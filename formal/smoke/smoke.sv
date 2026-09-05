// Formal smoke proof: confirms the pinned suite's SBY/solver/syntax before any real harness.
// A saturating 4-bit counter never exceeds its limit and returns to zero only on reset.
module smoke (input logic clk, input logic rst, input logic inc, output logic [3:0] q);
    always_ff @(posedge clk)
        if (rst) q <= 4'd0;
        else if (inc && q != 4'd10) q <= q + 4'd1;
`ifdef FORMAL
    // the initial state is unconstrained: the first run without this assumption produced a real
    // counterexample (q started at 15), which is how the solver/syntax smoke check was confirmed
    initial assume (rst);
    always_comb if (!$initstate) assert (q <= 4'd10);
    always_ff @(posedge clk)
        if (!$initstate && $past(rst)) assert (q == 4'd0);
    always_comb cover (q == 4'd10);
`endif
endmodule
