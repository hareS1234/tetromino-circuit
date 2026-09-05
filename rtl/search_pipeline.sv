// A2 search: dense candidate enumeration into candidate_pipe and a signed running-best reducer
// (docs/design_a2.md §7).  Same start/done interface as lane_player so tetris_core maps it to lane
// slot 0.  The context (board_i, heights_i, piece_i) is owned by the core for the whole search
// and must not change while any token is in flight; start_i is accepted only when idle and the
// pipeline is empty (issued == retired, occupancy zero).
//   issue : s_valid while active && j < N; rotation/x/id/tag/last held until s_valid && s_ready;
//           j increments only on that handshake; last when j == N-1
//   retire: m_ready is constant 1 during a search; on every retired token
//             take = m_legal && (!best_valid || m_score > best_score ||
//                                (m_score == best_score && m_candidate_id < best_id))
//           and when the retired token carries last, done_o pulses for one cycle at the same edge
//           and the published best is best_next (the final candidate may win)
// Invariants (simulation-only assertions): retired <= issued <= N; completion after exactly N
// retirements, illegal tokens included.
module search_pipeline (
    input  logic               clk,
    input  logic               rst,
    input  logic               start_i,
    input  logic [199:0]       board_i,
    input  logic [49:0]        heights_i,
    input  logic [2:0]         piece_i,
    input  logic [5:0]         count_i,        // dense candidate count N for piece_i
    output logic               busy_o,
    output logic               done_o,
    output logic               best_valid_o,
    output logic signed [31:0] best_score_o,
    output logic [5:0]         best_id_o,
    output logic [4:0]         best_y_o,
    output logic [5:0]         issued_o,       // diagnostic counters
    output logic [5:0]         retired_o
);
    logic       active;
    logic [5:0] j, n_q;

    // ---- enumeration ---------------------------------------------------------------------
    logic [5:0] cand_id;
    logic       index_valid;
    logic [5:0] rom_count;
    cand_rom u_cands (.piece_i(piece_i), .index_i(j), .cand_id_o(cand_id), .index_valid_o(index_valid), .count_o(rom_count));
    logic [1:0] rot;
    logic [3:0] x;
    always_comb begin
        if (cand_id >= 6'd30)      begin rot = 2'd3; x = 4'(cand_id - 6'd30); end
        else if (cand_id >= 6'd20) begin rot = 2'd2; x = 4'(cand_id - 6'd20); end
        else if (cand_id >= 6'd10) begin rot = 2'd1; x = 4'(cand_id - 6'd10); end
        else                       begin rot = 2'd0; x = 4'(cand_id); end
    end
    logic s_valid, s_ready, s_last;
    assign s_valid = active && (j < n_q);
    assign s_last  = (j == n_q - 6'd1);

    // ---- pipeline ------------------------------------------------------------------------
    logic               m_valid, m_legal, m_last;
    logic [5:0]         m_id;
    logic [15:0]        m_tag;
    logic [4:0]         m_y;
    logic signed [31:0] m_score;
    logic [22:0]        occupancy;
    candidate_pipe u_pipe (
        .clk, .rst, .ctx_board_i(board_i), .ctx_heights_i(heights_i), .ctx_piece_i(piece_i),
        .s_valid(s_valid), .s_ready(s_ready), .s_rotation(rot), .s_x(x), .s_candidate_id(cand_id), .s_tag({10'd0, j}), .s_last(s_last),
        .m_valid(m_valid), .m_ready(1'b1), .m_legal(m_legal), .m_last(m_last), .m_candidate_id(m_id), .m_tag(m_tag), .m_y(m_y),
        .m_score(m_score), .occupancy_o(occupancy));

    // ---- running best (best_reducer: signed score, lower id on ties, last token included) --------
    logic accept_start;
    assign accept_start = !active && start_i;
    best_reducer u_best (.clk, .rst, .clear_i(accept_start), .valid_i(m_valid), .legal_i(m_legal), .score_i(m_score), .id_i(m_id),
                         .y_i(m_y), .best_valid_o, .best_score_o, .best_id_o, .best_y_o);
    assign busy_o = active;

    always_ff @(posedge clk) begin
        if (rst) begin
            active <= 1'b0; j <= 6'd0; n_q <= 6'd0; done_o <= 1'b0; issued_o <= 6'd0; retired_o <= 6'd0;
        end else begin
            done_o <= 1'b0;
            if (accept_start) begin
                active <= 1'b1; j <= 6'd0; n_q <= count_i; issued_o <= 6'd0; retired_o <= 6'd0;
            end
            if (s_valid && s_ready) begin
                j <= j + 6'd1;
                issued_o <= issued_o + 6'd1;
            end
            if (m_valid) begin               // m_ready is 1: every visible token retires this edge
                retired_o <= retired_o + 6'd1;
                if (m_last) begin
                    done_o <= 1'b1;
                    active <= 1'b0;
                end
            end
        end
    end

`ifndef SYNTHESIS
    always_ff @(posedge clk) begin
        if (!rst) begin
            assert (retired_o <= issued_o) else $error("search_pipeline: retired %0d > issued %0d", retired_o, issued_o);
            assert (issued_o <= n_q || !active) else $error("search_pipeline: issued %0d > N %0d", issued_o, n_q);
            if (start_i && (active || occupancy != 23'd0))
                $error("search_pipeline: start while busy (active %0d, occupancy %h)", active, occupancy);
            if (m_valid && m_last && (retired_o + 6'd1 != n_q))
                $error("search_pipeline: last token retired after %0d of %0d tokens", retired_o + 6'd1, n_q);
            if (m_valid && m_tag != {10'd0, retired_o})
                $error("search_pipeline: token order violated (tag %0d, retired %0d)", m_tag, retired_o);
        end
    end
`endif
    logic unused_ok;
    assign unused_ok = index_valid | (|rom_count);
endmodule
