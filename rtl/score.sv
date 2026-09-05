// Registered heuristic scorer:  score = wL*L - wA*A - wQ*Q - wU*U  (signed 32 bits).
// Features are zero-extended into signed 32-bit temporaries before any arithmetic so
// that A=200 is never misread as a negative eight-bit value.  The PRECISION profile
// selects the coefficient structure at elaboration time (see docs/spec.md).
module score #(
    parameter int PRECISION = 0
) (
    input  logic               clk,
    input  logic               rst,
    input  logic               valid_i,
    input  logic [7:0]         a_i,
    input  logic [7:0]         q_i,
    input  logic [7:0]         u_i,
    input  logic [2:0]         l_i,
    output logic               valid_o,
    output logic signed [31:0] score_o
);
    logic signed [31:0] a32, q32, u32, l32, sum;
    assign a32 = $signed({24'd0, a_i});
    assign q32 = $signed({24'd0, q_i});
    assign u32 = $signed({24'd0, u_i});
    assign l32 = $signed({29'd0, l_i});

    generate
        if (PRECISION == 0 || PRECISION == 3) begin : g_exact
            // (76, 51, 36, 18); profile 3 receives an already-saturated Q
            assign sum = 32'sd76 * l32 - 32'sd51 * a32 - 32'sd36 * q32 - 32'sd18 * u32;
        end else if (PRECISION == 1) begin : g_pow2
            // (64, 64, 32, 16): pure shifts on widened operands
            assign sum = (l32 <<< 6) - (a32 <<< 6) - (q32 <<< 5) - (u32 <<< 4);
        end else if (PRECISION == 2) begin : g_two_terms
            // (80, 48, 36, 18) = (64+16, 32+16, 32+4, 16+2)
            assign sum = ((l32 <<< 6) + (l32 <<< 4)) - ((a32 <<< 5) + (a32 <<< 4))
                       - ((q32 <<< 5) + (q32 <<< 2)) - ((u32 <<< 4) + (u32 <<< 1));
        end else if (PRECISION == 4) begin : g_no_u
            // (76, 51, 36, 0): the U operand is structurally absent
            assign sum = 32'sd76 * l32 - 32'sd51 * a32 - 32'sd36 * q32;
        end else begin : g_bad
            $error("unsupported PRECISION");
        end
    endgenerate

    always_ff @(posedge clk) begin
        if (rst) begin
            valid_o <= 1'b0;
            score_o <= 32'sd0;
        end else begin
            valid_o <= valid_i;
            if (valid_i)
                score_o <= sum;
        end
    end
endmodule
