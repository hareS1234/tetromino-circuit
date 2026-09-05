// Cycle-by-cycle trace exporter for the A2 core (U18, guide §12.2).  Built with --public-flat-rw so
// the pipeline's bank registers can be read without touching the RTL.
//
//   Vtetris_core_trace +requests=<file> +out=<trace.jsonl> [+max_cycles=N]
//
// The request file holds one request per line: "piece next b0 b1 b2 b3 b4 b5 b6" (little-endian board
// words as in sim/main.cpp).  Each request is driven with rsp_ready held high (the production search
// never stalls: m_ready is constant 1 inside search_pipeline).  One JSON object per rising clock edge:
//   sampling: handshakes and combinational flags are sampled just before the rising edge (pre-edge),
//   registers (bank valid/tag arrays, best, core state) just after it (post-edge).
// Fields: request, cycle, rst, req_accept, rsp_valid, advance, s (accepted candidate: id, tag, last),
// m (retired: id, tag, last, legal, y, score), banks (23 entries: valid and tag or null), best
// {valid, score, id, y} post-edge, best_changed, p9 {tag, keep, ranks} and p12 {tag, board} taken
// from the compactor's registers when those banks are valid, core_state.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

#include "Vtetris_core.h"
#include "Vtetris_core___024root.h"
#include "verilated.h"

#define R (top->rootp)
#define SP(x) tetris_core__DOT__g_a2__DOT__u_search__DOT__##x
#define PIPE(x) tetris_core__DOT__g_a2__DOT__u_search__DOT__u_pipe__DOT__##x

namespace {
std::unique_ptr<VerilatedContext> ctx;
std::unique_ptr<Vtetris_core> top;

struct Bank { int valid; int tag; int id; int last; };

static std::string hex200(const VlWide<7>& w) {
    char buf[64];
    std::string s;
    for (int i = 6; i >= 0; i--) { std::snprintf(buf, sizeof buf, "%08x", (unsigned)w[i]); s += buf; }
    return s;
}

static void banks_now(std::vector<Bank>& b) {
    b.clear();
    auto& rp = *R;
    for (int i = 0; i < 4; i++) {
        int v = (rp.PIPE(u_front__DOT__valid) >> i) & 1; uint32_t m = rp.PIPE(u_front__DOT__meta)[i];
        b.push_back({v, v ? (int)((m >> 1) & 0xFFFF) : -1, v ? (int)((m >> 17) & 0x3F) : -1, v ? (int)(m & 1) : 0});
    }
    for (int i = 0; i < 9; i++) {
        int v = (rp.PIPE(u_clear__DOT__valid) >> i) & 1; uint32_t m = rp.PIPE(u_clear__DOT__meta)[i];
        b.push_back({v, v ? (int)((m >> 1) & 0xFFFF) : -1, v ? (int)((m >> 17) & 0x3F) : -1, v ? (int)(m & 1) : 0});
    }
    for (int i = 0; i < 7; i++) {
        int v = (rp.PIPE(u_features__DOT__valid) >> i) & 1; uint32_t m = rp.PIPE(u_features__DOT__meta)[i];
        b.push_back({v, v ? (int)((m >> 1) & 0xFFFF) : -1, v ? (int)((m >> 17) & 0x3F) : -1, v ? (int)(m & 1) : 0});
    }
    for (int i = 0; i < 3; i++) {
        int v = (rp.PIPE(u_score__DOT__valid) >> i) & 1; uint32_t m = rp.PIPE(u_score__DOT__meta)[i];
        b.push_back({v, v ? (int)((m >> 1) & 0xFFFF) : -1, v ? (int)((m >> 17) & 0x3F) : -1, v ? (int)(m & 1) : 0});
    }
}
}  // namespace

int main(int argc, char** argv) {
    ctx = std::make_unique<VerilatedContext>();
    ctx->commandArgs(argc, argv);
    std::string req_file, out_file;
    uint64_t max_cycles = 200000;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if (a.rfind("+requests=", 0) == 0) req_file = a.substr(10);
        else if (a.rfind("+out=", 0) == 0) out_file = a.substr(5);
        else if (a.rfind("+max_cycles=", 0) == 0) max_cycles = std::strtoull(a.c_str() + 12, nullptr, 10);
    }
    if (req_file.empty() || out_file.empty()) { std::fprintf(stderr, "need +requests=<file> +out=<file>\n"); return 2; }
    top = std::make_unique<Vtetris_core>(ctx.get());
    std::ofstream out(out_file);
    if (!out) { std::fprintf(stderr, "cannot write %s\n", out_file.c_str()); return 2; }

    uint64_t cycle = 0;
    int request = -1;
    int prev_best_valid = 0; int32_t prev_best_score = 0; int prev_best_id = 0;
    std::vector<Bank> banks;

    auto emit = [&](bool rst, int req_accept, int rsp_valid_pre) {
        // ---- pre-edge samples (combinational / handshake view) ----
        auto& rp = *R;
        int advance = rp.PIPE(advance);
        int s_hand = rp.SP(s_valid) && rp.SP(s_ready) && !rst;
        int s_id = rp.SP(cand_id), s_tag = rp.SP(j), s_last = (rp.SP(j) + 1 == rp.SP(n_q));
        int m_valid = rp.SP(m_valid) && !rst;
        int m_id = rp.SP(m_id), m_tag = rp.SP(m_tag), m_last = rp.SP(m_last), m_legal = rp.SP(m_legal), m_y = rp.SP(m_y);
        int32_t m_score = (int32_t)rp.SP(m_score);
        int state_pre = rp.tetris_core__DOT__state;
        // ---- rising edge ----
        top->clk = 1; top->eval(); ctx->timeInc(5);
        top->clk = 0; top->eval(); ctx->timeInc(5);
        cycle++;
        // ---- post-edge samples (registers) ----
        banks_now(banks);
        int bv = rp.SP(u_best__DOT__best_valid_o); int32_t bs = (int32_t)rp.SP(u_best__DOT__best_score_o);
        int bid = rp.SP(u_best__DOT__best_id_o); int by = rp.SP(u_best__DOT__best_y_o);
        int best_changed = (bv != prev_best_valid) || (bv && (bs != prev_best_score || bid != prev_best_id));
        prev_best_valid = bv; prev_best_score = bs; prev_best_id = bid;
        out << "{\"request\":" << request << ",\"cycle\":" << cycle << ",\"rst\":" << (rst ? 1 : 0)
            << ",\"req_accept\":" << req_accept << ",\"rsp_valid\":" << (int)top->rsp_valid << ",\"rsp_valid_pre\":" << rsp_valid_pre
            << ",\"advance\":" << advance << ",\"core_state_pre\":" << state_pre << ",\"core_state\":" << (int)rp.tetris_core__DOT__state;
        if (s_hand) out << ",\"s\":{\"id\":" << s_id << ",\"tag\":" << s_tag << ",\"last\":" << s_last << "}"; else out << ",\"s\":null";
        if (m_valid) out << ",\"m\":{\"id\":" << m_id << ",\"tag\":" << m_tag << ",\"last\":" << m_last << ",\"legal\":" << m_legal
                         << ",\"y\":" << m_y << ",\"score\":" << m_score << "}"; else out << ",\"m\":null";
        out << ",\"banks\":[";
        for (size_t i = 0; i < banks.size(); i++) {
            if (i) out << ",";
            if (banks[i].valid) out << "{\"tag\":" << banks[i].tag << ",\"id\":" << banks[i].id << ",\"last\":" << banks[i].last << "}";
            else out << "null";
        }
        out << "],\"best\":{\"valid\":" << bv << ",\"score\":" << bs << ",\"id\":" << bid << ",\"y\":" << by << "},\"best_changed\":" << best_changed;
        // compactor samples: P9 (index 5 of the clear block: ranks final, keep) and P12 (index 8: cleared board)
        if ((rp.PIPE(u_clear__DOT__valid) >> 5) & 1) {
            uint32_t m = rp.PIPE(u_clear__DOT__meta)[5];
            out << ",\"p9\":{\"tag\":" << ((m >> 1) & 0xFFFF) << ",\"keep\":" << (rp.PIPE(u_clear__DOT__keep)[5] & 0xFFFFF) << ",\"ranks\":[";
            const VlWide<4>& lv = rp.PIPE(u_clear__DOT__lvl)[5];
            for (int r = 0; r < 20; r++) {
                int bit = 5 * r; int word = bit / 32, off = bit % 32;
                uint64_t v = ((uint64_t)lv[word] >> off);
                if (off > 27 && word < 3) v |= ((uint64_t)lv[word + 1] << (32 - off));
                out << (r ? "," : "") << (v & 31);
            }
            out << "]}";
        } else out << ",\"p9\":null";
        if ((rp.PIPE(u_clear__DOT__valid) >> 8) & 1) {
            uint32_t m = rp.PIPE(u_clear__DOT__meta)[8];
            out << ",\"p12\":{\"tag\":" << ((m >> 1) & 0xFFFF) << ",\"board\":\"" << hex200(rp.PIPE(u_clear__DOT__board12)) << "\"}";
        } else out << ",\"p12\":null";
        out << "}\n";
    };

    // reset
    top->clk = 0; top->rst = 1; top->req_valid = 0; top->rsp_ready = 1; top->piece_i = 0; top->next_piece_i = 0;
    for (int i = 0; i < 7; i++) top->board_i[i] = 0;
    top->eval();
    emit(true, 0, 0);
    emit(true, 0, 0);
    top->rst = 0; top->eval();
    emit(false, 0, 0);

    std::ifstream in(req_file);
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream ss(line);
        unsigned piece, nxt; uint32_t b[7];
        ss >> piece >> nxt; for (int i = 0; i < 7; i++) ss >> b[i];
        request++;
        top->piece_i = piece; top->next_piece_i = nxt; for (int i = 0; i < 7; i++) top->board_i[i] = b[i];
        top->req_valid = 1; top->eval();
        // wait for acceptance (req_ready high pre-edge)
        uint64_t guard = 0;
        while (!top->req_ready) { emit(false, 0, top->rsp_valid); if (++guard > max_cycles) return 3; }
        emit(false, 1, top->rsp_valid);          // acceptance edge
        top->req_valid = 0; top->eval();
        guard = 0;
        while (!top->rsp_valid) { emit(false, 0, 0); if (++guard > max_cycles) { std::fprintf(stderr, "timeout\n"); return 3; } }
        // rsp_valid is high post-edge now; the consuming edge (rsp_ready=1) follows
        emit(false, 0, 1);
        std::fprintf(stdout, "request %d: error %u no_move %u rotation %u x %u y %u score %d cycles %u\n", request,
                     (unsigned)top->error_o, (unsigned)top->no_move_o, (unsigned)top->rotation_o, (unsigned)top->x_o, (unsigned)top->y_o,
                     (int32_t)top->score_o, (unsigned)top->cycles_o);
        out.flush();
        // idle cycles between requests so the timeline shows the boundary
        for (int i = 0; i < 2; i++) emit(false, 0, 0);
    }
    top->final();
    return 0;
}
