// A1 feature unit: parallel heights (priority encoders), per-column hole masks and popcounts,
// and balanced reduction trees for A, Q and U.  Two registered stages after start:
//   stage 1: heights, per-column hole counts, adjacent height differences
//   stage 2: sums (A, Q, U)
// PRECISION 3 uses four-bit saturating adds (min(15, a+b)) throughout the Q tree; PRECISION 4
// has no U datapath at all.
module features_fast #(
    parameter int PRECISION = 0
) (
    input  logic         clk,
    input  logic         rst,
    input  logic         start_i,
    input  logic [199:0] board_i,
    output logic         busy_o,
    output logic         done_o,
    output logic [7:0]   a_o,
    output logic [7:0]   q_o,
    output logic [7:0]   u_o,
    output logic [49:0]  heights_o
);
    logic [49:0]  heights_w;
    logic [199:0] columns_w, holes_w;
    board_profile u_prof (.board_i(board_i), .heights_o(heights_w), .columns_o(columns_w), .holes_o(holes_w));

    // ---- stage 1 combinational: per-column popcounts and |dh| ---------------------------
    logic [4:0] colholes [10];
    logic [4:0] absd [9];
    generate
        for (genvar c = 0; c < 10; c++) begin : g_pc
            logic [19:0] hm;
            logic [2:0]  p4 [5];      // popcount of 4-bit groups
            logic [3:0]  p8a, p8b;
            assign hm = holes_w[20 * c +: 20];
            for (genvar g = 0; g < 5; g++) begin : g_g
                assign p4[g] = {2'b00, hm[4*g]} + {2'b00, hm[4*g+1]} + {2'b00, hm[4*g+2]} + {2'b00, hm[4*g+3]};
            end
            assign p8a = {1'b0, p4[0]} + {1'b0, p4[1]};
            assign p8b = {1'b0, p4[2]} + {1'b0, p4[3]};
            assign colholes[c] = {1'b0, p8a} + {1'b0, p8b} + {2'b00, p4[4]};   // 0..19
        end
        for (genvar c = 1; c < 10; c++) begin : g_dh
            logic signed [6:0] dd;
            assign dd = $signed({2'b00, heights_w[5*c +: 5]}) - $signed({2'b00, heights_w[5*(c-1) +: 5]});
            assign absd[c-1] = dd[6] ? 5'(-dd) : 5'(dd);
        end
    endgenerate

    // ---- stage 1 registers ------------------------------------------------------------
    logic [49:0] heights_q;
    logic [4:0]  colholes_q [10];
    logic [4:0]  absd_q [9];
    logic        s1_valid;

    // ---- stage 2 combinational: balanced trees ------------------------------------------
    logic [7:0] a_sum, u_sum, q_sum;
    logic [5:0] a2 [5];
    logic [6:0] a4a, a4b;
    logic [5:0] u2 [4];
    logic [6:0] u4a, u4b;
    logic [5:0] q2 [5];
    logic [6:0] q4a, q4b;
    logic [3:0] qs1 [10];
    logic [3:0] qs2 [5];
    logic [4:0] qt2 [5];
    logic [3:0] qs4a, qs4b, qs8, qs10;
    logic [4:0] qt4a, qt4b, qt8, qt10;
    always_comb begin
        // A: ten five-bit heights, pairwise
        for (int i = 0; i < 5; i++) a2[i] = {1'b0, heights_q[10*i +: 5]} + {1'b0, heights_q[10*i+5 +: 5]};
        a4a = {1'b0, a2[0]} + {1'b0, a2[1]};
        a4b = {1'b0, a2[2]} + {1'b0, a2[3]};
        a_sum = {1'b0, a4a} + {1'b0, a4b} + {2'b00, a2[4]};
        // U: nine differences
        for (int i = 0; i < 4; i++) u2[i] = {1'b0, absd_q[2*i]} + {1'b0, absd_q[2*i+1]};
        u4a = {1'b0, u2[0]} + {1'b0, u2[1]};
        u4b = {1'b0, u2[2]} + {1'b0, u2[3]};
        u_sum = {1'b0, u4a} + {1'b0, u4b} + {3'b000, absd_q[8]};
        // Q exact tree
        for (int i = 0; i < 5; i++) q2[i] = {1'b0, colholes_q[2*i]} + {1'b0, colholes_q[2*i+1]};
        q4a = {1'b0, q2[0]} + {1'b0, q2[1]};
        q4b = {1'b0, q2[2]} + {1'b0, q2[3]};
        // Q saturating tree (PRECISION 3): sat(a,b) = min(15, a+b) at every node
        for (int i = 0; i < 10; i++) qs1[i] = (colholes_q[i] > 5'd15) ? 4'd15 : colholes_q[i][3:0];
        for (int i = 0; i < 5; i++) begin
            qt2[i] = {1'b0, qs1[2*i]} + {1'b0, qs1[2*i+1]};
            qs2[i] = (qt2[i] > 5'd15) ? 4'd15 : qt2[i][3:0];
        end
        qt4a = {1'b0, qs2[0]} + {1'b0, qs2[1]}; qs4a = (qt4a > 5'd15) ? 4'd15 : qt4a[3:0];
        qt4b = {1'b0, qs2[2]} + {1'b0, qs2[3]}; qs4b = (qt4b > 5'd15) ? 4'd15 : qt4b[3:0];
        qt8  = {1'b0, qs4a} + {1'b0, qs4b};     qs8  = (qt8 > 5'd15) ? 4'd15 : qt8[3:0];
        qt10 = {1'b0, qs8} + {1'b0, qs2[4]};    qs10 = (qt10 > 5'd15) ? 4'd15 : qt10[3:0];
        if (PRECISION == 3) q_sum = {4'd0, qs10};
        else                q_sum = {1'b0, q4a} + {1'b0, q4b} + {2'b00, q2[4]};
    end

    assign busy_o = s1_valid;
    assign heights_o = heights_q;

    always_ff @(posedge clk) begin
        if (rst) begin
            s1_valid <= 1'b0; done_o <= 1'b0; a_o <= 8'd0; q_o <= 8'd0; u_o <= 8'd0; heights_q <= '0;
            for (int i = 0; i < 10; i++) colholes_q[i] <= 5'd0;
            for (int i = 0; i < 9; i++) absd_q[i] <= 5'd0;
        end else begin
            s1_valid <= start_i;
            if (start_i) begin
                heights_q <= heights_w;
                for (int i = 0; i < 10; i++) colholes_q[i] <= colholes[i];
                for (int i = 0; i < 9; i++) absd_q[i] <= (PRECISION == 4) ? 5'd0 : absd[i];
            end
            done_o <= s1_valid;
            if (s1_valid) begin
                a_o <= a_sum;
                q_o <= q_sum;
                u_o <= (PRECISION == 4) ? 8'd0 : u_sum;
            end
        end
    end
endmodule
