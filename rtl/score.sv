// Registered heuristic scorer:  score = wL*L - wA*A - wQ*Q - wU*U  (signed 32-bit port).
// Features are zero-extended into signed temporaries before any arithmetic so that A=200 is
// never misread as a negative eight-bit value.  The PRECISION profile selects the coefficient
// structure at elaboration time (docs/spec.md; P5-P7 in docs/precision_v2.md).
module score #(
    parameter int PRECISION = 0,
    parameter int USE_MULT  = 0   // 1: write the exact profile with '*' (Yosys maps it to DSP slices)
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
        if ((PRECISION == 0 || PRECISION == 3) && USE_MULT == 1) begin : g_exact_mult
            // (76, 51, 36, 18) as constant multiplies: measured to infer MULT18X18D blocks
            assign sum = 32'sd76 * l32 - 32'sd51 * a32 - 32'sd36 * q32 - 32'sd18 * u32;
        end else if (PRECISION == 0 || PRECISION == 3) begin : g_exact
            // (76, 51, 36, 18) = (64+8+4, 32+16+2+1, 32+4, 16+2): eleven shifted terms, no DSP.
            // Profile 3 receives an already-saturated Q.
            assign sum = ((l32 <<< 6) + (l32 <<< 3) + (l32 <<< 2))
                       - ((a32 <<< 5) + (a32 <<< 4) + (a32 <<< 1) + a32)
                       - ((q32 <<< 5) + (q32 <<< 2))
                       - ((u32 <<< 4) + (u32 <<< 1));
        end else if (PRECISION == 1) begin : g_pow2
            // (64, 64, 32, 16): pure shifts on widened operands
            assign sum = (l32 <<< 6) - (a32 <<< 6) - (q32 <<< 5) - (u32 <<< 4);
        end else if (PRECISION == 2) begin : g_two_terms
            // (80, 48, 36, 18) = (64+16, 32+16, 32+4, 16+2)
            assign sum = ((l32 <<< 6) + (l32 <<< 4)) - ((a32 <<< 5) + (a32 <<< 4))
                       - ((q32 <<< 5) + (q32 <<< 2)) - ((u32 <<< 4) + (u32 <<< 1));
        end else if (PRECISION == 4) begin : g_no_u
            // (76, 51, 36, 0): the U operand is structurally absent
            assign sum = ((l32 <<< 6) + (l32 <<< 3) + (l32 <<< 2))
                       - ((a32 <<< 5) + (a32 <<< 4) + (a32 <<< 1) + a32)
                       - ((q32 <<< 5) + (q32 <<< 2));
        end else if (PRECISION >= 5 && PRECISION <= 7) begin : g_quant
            // Coefficient-magnitude budgets (U14, model/numeric.py quantize_magnitudes):
            //   P5 coeff_u4 (15, 10, 7, 4) : 15L = (L<<4)-L   10A = (A<<3)+(A<<1)  7Q = (Q<<3)-Q   4U = U<<2   score in [-4120, 60]
            //   P6 coeff_u3 (7, 5, 3, 2)   :  7L = (L<<3)-L    5A = (A<<2)+A      3Q = (Q<<1)+Q   2U = U<<1   score in [-1960, 28]
            //   P7 coeff_u2 (3, 2, 1, 1)   :  3L = (L<<1)+L    2A = A<<1           Q               U          score in [-780, 12]
            // The features are zero-extended into signed SW-bit operands (the sufficient signed width of
            // the profile's score range for A<=200, Q<=200, U<=180, L<=4: 14/12/11 bits), the shift-add
            // sum is formed at that width and sign-extended onto the 32-bit public port.  Raw scores are
            // in the profile's own units (76/M of the baseline); the argmax is unchanged by the scale.
            localparam int SW = (PRECISION == 5) ? 14 : (PRECISION == 6) ? 12 : 11;
            logic signed [SW-1:0] a_s, q_s, u_s, l_s, sum_s;
            assign a_s = $signed({{(SW - 8){1'b0}}, a_i});
            assign q_s = $signed({{(SW - 8){1'b0}}, q_i});
            assign u_s = $signed({{(SW - 8){1'b0}}, u_i});
            assign l_s = $signed({{(SW - 3){1'b0}}, l_i});
            if (PRECISION == 5) begin : g_u4
                assign sum_s = ((l_s <<< 4) - l_s) - ((a_s <<< 3) + (a_s <<< 1)) - ((q_s <<< 3) - q_s) - (u_s <<< 2);
            end else if (PRECISION == 6) begin : g_u3
                assign sum_s = ((l_s <<< 3) - l_s) - ((a_s <<< 2) + a_s) - ((q_s <<< 1) + q_s) - (u_s <<< 1);
            end else begin : g_u2
                assign sum_s = ((l_s <<< 1) + l_s) - (a_s <<< 1) - q_s - u_s;
            end
            assign sum = {{(32 - SW){sum_s[SW - 1]}}, sum_s};
`ifndef SYNTHESIS
            // the narrow width relies on the feature-unit bounds; a caller violating them is a bug, not a rounding
            always_ff @(posedge clk)
                if (!rst && valid_i)
                    assert (a_i <= 8'd200 && q_i <= 8'd200 && u_i <= 8'd180 && l_i <= 3'd4)
                        else $error("score: P%0d inputs outside the bounded range A=%0d Q=%0d U=%0d L=%0d", PRECISION, a_i, q_i, u_i, l_i);
`endif
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
