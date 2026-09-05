// Formal miter for the combinational compactor (guide §8.3 target 1, §6.4 item 2).
// The DUT (row_rank20 + line_clear_parallel) is compared with an INDEPENDENT description of the
// stable filter: a sequential scan with a running destination index, written without prefix ranks
// or match bits.  Nothing here assumes the expected output equals the DUT.  Decomposed properties
// (rank order/uniqueness, keep vs full-row detection, count, zero padding) are asserted too so a
// failure names the violated property.  board_i is a free symbolic 200-bit input.
module compactor_miter (
    input logic [199:0] board_i
);
    logic [199:0] dut_board;
    logic [4:0]   dut_count, dut_survivors;
    logic [19:0]  dut_keep;
    logic [99:0]  dut_rank;
    line_clear_parallel dut (.board_i(board_i), .board_o(dut_board), .count_o(dut_count), .survivors_o(dut_survivors),
                             .keep_o(dut_keep), .rank_o(dut_rank));

    // ---- independent stable filter: running index, explicit destination compare (no scatter) ----
    logic [199:0] ref_board;
    logic [4:0]   idx;            // number of survivors placed so far
    logic [4:0]   run [0:20];     // running index before source s (run[0] = 0)
    always_comb begin
        ref_board = '0;
        run[0] = 5'd0;
        for (int s = 0; s < 20; s++) begin
            run[s + 1] = run[s] + ((board_i[10 * s +: 10] != 10'h3FF) ? 5'd1 : 5'd0);
            for (int d = 0; d < 20; d++) begin
                if ((board_i[10 * s +: 10] != 10'h3FF) && (run[s] == 5'(d)))
                    ref_board[10 * d +: 10] = board_i[10 * s +: 10];
            end
        end
        idx = run[20];
    end

`ifdef FORMAL
    always_comb begin
        // 1. board equality with the independent filter
        assert (dut_board == ref_board);
        // 2. counts
        assert (dut_survivors == idx);
        assert (dut_count == 5'd20 - idx);
        assert (dut_count + dut_survivors == 5'd20);
        // 3. keep is exactly full-row detection
        for (int s = 0; s < 20; s++)
            assert (dut_keep[s] == (board_i[10 * s +: 10] != 10'h3FF));
        // 4. ranks: inclusive count of kept rows up to s; strictly increasing across survivors
        for (int s = 0; s < 20; s++) begin
            assert (dut_rank[5 * s +: 5] == run[s + 1]);
            assert (dut_rank[5 * s +: 5] <= 5'(s + 1));
            if (s > 0) assert (dut_rank[5 * s +: 5] - dut_rank[5 * (s - 1) +: 5] == (dut_keep[s] ? 5'd1 : 5'd0));
        end
        // 5. zero padding above the survivors; survivors are never full rows
        for (int d = 0; d < 20; d++) begin
            if (5'(d) >= idx) assert (dut_board[10 * d +: 10] == 10'd0);
            else              assert (dut_board[10 * d +: 10] != 10'h3FF);
        end
    end
    // reachability: the extreme cases are representable
    always_comb cover (dut_count == 5'd20);
    always_comb cover (dut_count == 5'd0 && dut_board != '0);
    always_comb cover (dut_count == 5'd4);
`endif
endmodule
