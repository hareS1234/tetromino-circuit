// One level of the explicit inclusive prefix scan over twenty 5-bit values (guide §6.1):
//   next[s] = prev[s] + (s >= STRIDE ? prev[s-STRIDE] : 0)
// Every node reads only the previous level.  Combinational; instantiated five times (strides
// 1, 2, 4, 8, 16) by row_rank20 and once per bank P5-P9 by line_clear_pipe, so the pipelined
// ranks are computed by exactly the structure the formal miter proves.
module rank_level #(
    parameter int STRIDE = 1
) (
    input  logic [99:0] prev_i,
    output logic [99:0] next_o
);
    generate
        for (genvar s = 0; s < 20; s++) begin : g_node
            if (s >= STRIDE) begin : g_add
                assign next_o[5 * s +: 5] = prev_i[5 * s +: 5] + prev_i[5 * (s - STRIDE) +: 5];
            end else begin : g_pass
                assign next_o[5 * s +: 5] = prev_i[5 * s +: 5];
            end
        end
    endgenerate
endmodule
