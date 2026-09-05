// Verification-scenario trace exporter for the standalone candidate pipeline (U18, guide §12.2):
// several occupied stages, a deliberately blocked candidate output (m_ready low), and a reset flush.
// Built with --public-flat-rw so the bank registers are read without RTL changes.
//
//   Vcandidate_pipe_trace +vectors=<a2-vectors file> +out=<trace.jsonl> [+context=I +stall_at=N +stall_len=M +reset_at=K]
//
// Story: the first context's candidates are offered back to back; after `stall_at` acceptances the
// output is blocked for `stall_len` edges (tokens freeze in place; the input is not accepted); after
// `reset_at` further edges the reset is pulsed while stages are occupied (every valid bit clears at
// that edge); a few more candidates are then issued and drained to show the pipeline working again.
// Sampling as in sim/trace_main.cpp: handshakes pre-edge, registers post-edge.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

#include "Vcandidate_pipe.h"
#include "Vcandidate_pipe___024root.h"
#include "verilated.h"

#define R (top->rootp)
#define P(x) candidate_pipe__DOT__##x

namespace {
std::unique_ptr<VerilatedContext> ctx;
std::unique_ptr<Vcandidate_pipe> top;
struct Cand { int rot, x, id, legal, y; int32_t score; };
struct Ctx { uint32_t board[7]; uint64_t heights; int piece; std::vector<Cand> cands; };

static void parse_hex_words(const std::string& hex, uint32_t* w, int words) {
    for (int i = 0; i < words; i++) w[i] = 0;
    int bit = 0;
    for (int i = (int)hex.size() - 1; i >= 0; i--) {
        int v = std::stoi(std::string(1, hex[i]), nullptr, 16);
        for (int b = 0; b < 4; b++, bit++) if (bit < 32 * words && ((v >> b) & 1)) w[bit / 32] |= 1u << (bit % 32);
    }
}

static std::vector<Ctx> load(const std::string& path) {
    std::ifstream in(path);
    std::vector<Ctx> out;
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream ss(line);
        std::string kind; ss >> kind;
        if (kind == "C") {
            Ctx c; std::string bh, hh; ss >> bh >> hh >> c.piece;
            parse_hex_words(bh, c.board, 7);
            uint32_t hw[2]; parse_hex_words(hh, hw, 2);
            c.heights = (uint64_t)hw[0] | ((uint64_t)hw[1] << 32);
            out.push_back(c);
        } else if (kind == "T") {
            Cand k; long long sc; ss >> k.rot >> k.x >> k.id >> k.legal >> k.y >> sc; k.score = (int32_t)sc;
            out.back().cands.push_back(k);
        }
    }
    return out;
}

static void bank(std::ostream& o, int v, uint32_t m, bool first) {
    if (!first) o << ",";
    if (v) o << "{\"tag\":" << ((m >> 1) & 0xFFFF) << ",\"id\":" << ((m >> 17) & 0x3F) << ",\"last\":" << (m & 1) << "}"; else o << "null";
}
}  // namespace

int main(int argc, char** argv) {
    ctx = std::make_unique<VerilatedContext>();
    ctx->commandArgs(argc, argv);
    std::string vectors, out_file;
    int stall_at = 12, stall_len = 9, reset_at = 8, tail = 6, context = 0;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if (a.rfind("+vectors=", 0) == 0) vectors = a.substr(9);
        else if (a.rfind("+out=", 0) == 0) out_file = a.substr(5);
        else if (a.rfind("+stall_at=", 0) == 0) stall_at = std::atoi(a.c_str() + 10);
        else if (a.rfind("+stall_len=", 0) == 0) stall_len = std::atoi(a.c_str() + 11);
        else if (a.rfind("+reset_at=", 0) == 0) reset_at = std::atoi(a.c_str() + 10);
        else if (a.rfind("+context=", 0) == 0) context = std::atoi(a.c_str() + 9);
    }
    if (vectors.empty() || out_file.empty()) { std::fprintf(stderr, "need +vectors= and +out=\n"); return 2; }
    auto ctxs = load(vectors);
    if ((int)ctxs.size() <= context) { std::fprintf(stderr, "no context %d\n", context); return 2; }
    const Ctx& c = ctxs[context];
    top = std::make_unique<Vcandidate_pipe>(ctx.get());
    std::ofstream out(out_file);
    uint64_t cycle = 0; int tag_next = 0;
    size_t idx = 0;
    std::string phase = "fill";

    auto step = [&](const Cand* k, bool m_ready, bool rst, int last) {
        top->rst = rst; top->m_ready = m_ready;
        int tag = -1;
        if (k) { tag = tag_next; top->s_rotation = k->rot; top->s_x = k->x; top->s_candidate_id = k->id; top->s_tag = tag; top->s_last = last; top->s_valid = 1; }
        else top->s_valid = 0;
        top->eval();
        auto& rp = *R;
        int advance = rp.P(advance);
        int s_hand = top->s_valid && top->s_ready && !rst;
        int m_hand = top->m_valid && top->m_ready && !rst;
        int m_valid = top->m_valid && !rst;
        int m_id = top->m_candidate_id, m_tag = top->m_tag, m_last = top->m_last, m_legal = top->m_legal, m_y = top->m_y; int32_t m_score = (int32_t)top->m_score;
        top->clk = 1; top->eval(); ctx->timeInc(5);
        top->clk = 0; top->eval(); ctx->timeInc(5);
        cycle++;
        if (s_hand) tag_next++;
        out << "{\"request\":0,\"cycle\":" << cycle << ",\"rst\":" << (rst ? 1 : 0) << ",\"phase\":\"" << phase << "\",\"m_ready\":" << (m_ready ? 1 : 0)
            << ",\"advance\":" << advance << ",\"s_valid\":" << (int)(k != nullptr) << ",\"s_ready_pre\":" << (int)(advance);
        if (s_hand) out << ",\"s\":{\"id\":" << k->id << ",\"tag\":" << tag << ",\"last\":" << last << "}"; else out << ",\"s\":null";
        if (m_valid) out << ",\"m\":{\"id\":" << m_id << ",\"tag\":" << m_tag << ",\"last\":" << m_last << ",\"legal\":" << m_legal << ",\"y\":" << m_y
                         << ",\"score\":" << m_score << ",\"consumed\":" << m_hand << "}"; else out << ",\"m\":null";
        out << ",\"banks\":[";
        bool first = true;
        for (int i = 0; i < 4; i++) { bank(out, (rp.P(u_front__DOT__valid) >> i) & 1, rp.P(u_front__DOT__meta)[i], first); first = false; }
        for (int i = 0; i < 9; i++) bank(out, (rp.P(u_clear__DOT__valid) >> i) & 1, rp.P(u_clear__DOT__meta)[i], false);
        for (int i = 0; i < 7; i++) bank(out, (rp.P(u_features__DOT__valid) >> i) & 1, rp.P(u_features__DOT__meta)[i], false);
        for (int i = 0; i < 3; i++) bank(out, (rp.P(u_score__DOT__valid) >> i) & 1, rp.P(u_score__DOT__meta)[i], false);
        out << "],\"occupancy\":" << __builtin_popcount((unsigned)top->occupancy_o) << "}\n";
        return s_hand;
    };

    for (int i = 0; i < 7; i++) top->ctx_board_i[i] = c.board[i];
    top->ctx_heights_i = c.heights; top->ctx_piece_i = c.piece;
    top->clk = 0; top->rst = 1; top->m_ready = 1; top->s_valid = 0; top->eval();
    step(nullptr, true, true, 0);
    step(nullptr, true, true, 0);
    int accepted = 0;
    // fill: back-to-back candidates until stall_at acceptances
    while (accepted < stall_at && idx < c.cands.size()) {
        if (step(&c.cands[idx], true, false, 0)) { accepted++; idx++; }
    }
    // block the output: the pipeline keeps advancing (elastic) until the output bank P22 holds a token,
    // then advance drops and every token freezes; the offered candidate is not accepted while frozen
    phase = "output-blocked";
    int guard = 0;
    while (!(top->m_valid) && guard++ < 40) { if (step(idx < c.cands.size() ? &c.cands[idx] : nullptr, false, false, 0)) idx++; }
    phase = "stall";
    for (int i = 0; i < stall_len; i++) { if (step(idx < c.cands.size() ? &c.cands[idx] : nullptr, false, false, 0)) idx++; }
    // release for reset_at edges, then reset while stages are occupied
    phase = "release";
    for (int i = 0; i < reset_at; i++) { if (step(idx < c.cands.size() ? &c.cands[idx] : nullptr, true, false, 0)) idx++; }
    phase = "reset";
    step(nullptr, true, true, 0);
    // after reset: a few candidates issued and fully drained (the last one carries `last`)
    phase = "after-reset";
    int after = 0;
    while (after < tail && idx < c.cands.size()) {
        if (step(&c.cands[idx], true, false, (after + 1 == tail || idx + 1 == c.cands.size()) ? 1 : 0)) { after++; idx++; }
    }
    phase = "drain";
    for (int i = 0; i < 26; i++) step(nullptr, true, false, 0);
    std::fprintf(stdout, "pipe trace: %llu cycles, %d accepted before stall, stall %d edges, reset after %d more edges, %d after reset, occupancy at end %u\n",
                 (unsigned long long)cycle, accepted, stall_len, reset_at, after, (unsigned)__builtin_popcount((unsigned)top->occupancy_o));
    top->final();
    return 0;
}
