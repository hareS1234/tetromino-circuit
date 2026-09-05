// Control-conservation proof (guide §8.3 target 2) on an abstract payload pipeline that uses the
// exact register/valid discipline of the A2 blocks (valid shifts on advance, payload loads behind a
// valid, reset with priority, advance = !rst && (!valid[last] || m_ready)).  The payload is a token
// serial number assigned at acceptance, so every property is about control:
//   no spontaneous output   outputs never exceed accepted inputs (in-flight count bounded by BANKS)
//   no duplicate retirement retired serial numbers are strictly increasing by one
//   stability under stalls  a valid, unconsumed output does not change
//   flush on reset          no valid bit survives a reset; the next output serial is a post-reset token
//   covers                  the pipeline fills completely and drains to empty
module abstract_pipe #(
    parameter int BANKS = 5
) (
    input  logic clk,
    input  logic rst,
    input  logic s_valid,
    output logic s_ready,
    input  logic m_ready,
    output logic m_valid,
    output logic [15:0] m_serial
);
    logic [BANKS-1:0] valid;
    logic [15:0] payload [0:BANKS-1];
    logic [15:0] next_serial;
    logic advance;
    assign advance = !rst && (!valid[BANKS-1] || m_ready);
    assign s_ready = advance;
    assign m_valid = valid[BANKS-1] && !rst;
    assign m_serial = payload[BANKS-1];

    always_ff @(posedge clk) begin
        if (rst) begin
            valid <= '0;
            next_serial <= 16'd0;
        end else if (advance) begin
            valid[0] <= s_valid;
            for (int i = 1; i < BANKS; i++) valid[i] <= valid[i - 1];
            if (s_valid) next_serial <= next_serial + 16'd1;
        end
    end
    always_ff @(posedge clk) begin
        if (advance) begin
            if (s_valid) payload[0] <= next_serial;
            for (int i = 1; i < BANKS; i++) if (valid[i - 1]) payload[i] <= payload[i - 1];
        end
    end

`ifdef FORMAL
    initial assume (rst);
    logic [15:0] accepted, retired, last_retired;
    logic [15:0] younger [0:BANKS-1];    // number of valid banks after bank i (toward the input)
    logic [15:0] expected_serial [0:BANKS-1];
    logic [15:0] inflight;               // 16-bit modular difference (serials wrap)
    assign inflight = accepted - retired;
    always_comb begin
        for (int i = 0; i < BANKS; i++) begin
            younger[i] = 16'd0;
            for (int k = i + 1; k < BANKS; k++) younger[i] = younger[i] + {15'd0, valid[k]};
            expected_serial[i] = retired + younger[i];
        end
    end
    logic seen_output, p_rst;
    logic p_valid, p_ready; logic [15:0] p_serial;
    always_ff @(posedge clk) begin
        p_rst <= rst; p_valid <= m_valid; p_ready <= m_ready; p_serial <= m_serial;
        if (rst) begin accepted <= 16'd0; retired <= 16'd0; seen_output <= 1'b0; last_retired <= 16'd0; end
        else begin
            if (s_valid && s_ready) accepted <= accepted + 16'd1;
            if (m_valid && m_ready) begin retired <= retired + 16'd1; last_retired <= m_serial; seen_output <= 1'b1; end
        end
    end
    always_comb begin
        if (!$initstate && !rst) begin
            // conservation: in-flight tokens are exactly the set valid bits, never more than BANKS
            assert (inflight == 16'($countones(valid)));
            assert (inflight <= 16'(BANKS));
            // the serial at the output is the next one to retire (order, no duplicates, no invention)
            if (m_valid) assert (m_serial == retired);
            // stability: a valid unconsumed output holds
            if (p_valid && !p_ready && !p_rst) begin assert (m_valid); assert (m_serial == p_serial); end
            // the accepted count equals next_serial
            assert (accepted == next_serial);
            // strengthening invariant for induction: the valid banks hold consecutive serials, the
            // oldest (closest to the output) being the next to retire
            for (int i = 0; i < BANKS; i++)
                if (valid[i]) assert (payload[i] == expected_serial[i]);
        end
        // flush: right after a reset nothing is valid
        if (!$initstate && p_rst) assert (valid == '0);
    end
    always_comb cover (valid == '1);                                  // full
    always_comb cover (!$initstate && !rst && seen_output && valid == '0);   // drained after use
`endif
endmodule
