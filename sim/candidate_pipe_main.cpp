// Native harness for the A2 candidate pipeline (U09, guide §8.1 V06-V09).
//   +vectors=<file> [+stream=4096] [+seed=1] [+stalls=30] [+bubbles=20] [+trace=<vcd>]
// Phases (each prints CHECK lines):
//   stream    one stable context, its candidates repeated with distinct 16-bit tags until +stream
//             tokens: acceptance and retirement spacing 1, visible latency 22, transfer latency 23
//   traffic   every context of the vector file with random input bubbles and output stalls; the
//             context changes only when the pipeline is empty (search-level ownership); illegal
//             tokens (invalid rotation/x, blocked landings) interleaved; an illegal final token
//   metadata  repeated identical candidates with distinct tags; rotation/x changing every cycle
//   reset     reset at every occupancy 0..23, while the output is stalled, at last-token issue and
//             just before retirement: no pre-reset token emerges
// Expected values come from the vector file (Python oracle), never from the DUT.  Scoreboard:
// handshakes sampled before the edge, expected deque updated on accepted tokens only, registered
// outputs compared on transfer, separate stability monitor while m_valid && !m_ready.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <fstream>
#include <map>
#include <random>
#include <sstream>
#include <string>
#include <vector>
#include "Vcandidate_pipe.h"
#include "verilated.h"
#if VM_TRACE
#include "verilated_vcd_c.h"
#endif

static const int BANKS = 23;

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

struct Expect { int legal, y, id, tag, last; int32_t score; uint64_t accept_edge; };

struct Harness {
    Vcandidate_pipe* top;
#if VM_TRACE
    VerilatedVcdC* tfp = nullptr;
#endif
    std::deque<Expect> queue;
    uint64_t edge = 0, accepted = 0, retired = 0, mismatches = 0, stability = 0, spurious = 0, last_accept = 0, last_retire = 0;
    std::vector<uint64_t> accept_spacing, retire_spacing, transfer_latency, visible_latency;
    std::map<int, uint64_t> first_visible;      // tag -> edge index after which the tag was first visible
    std::map<int, uint64_t> accept_edge_of;
    bool have_prev = false; int p_legal, p_last, p_id, p_tag, p_y; int32_t p_score;
    int next_tag = 1;
    std::mt19937_64 rng;
    uint64_t occ_max = 0, occ_sum = 0, occ_samples = 0;      // occupancy (set valid banks) after every edge

    explicit Harness(uint64_t seed) : rng(seed) {
        top = new Vcandidate_pipe; top->clk = 0; top->rst = 1; top->m_ready = 1; top->s_valid = 0; top->eval();
    }
    void set_context(const Ctx& c) {
        for (int i = 0; i < 7; i++) top->ctx_board_i[i] = c.board[i];
        top->ctx_heights_i = c.heights; top->ctx_piece_i = c.piece;
    }
    void tick() {
        top->clk = 1; top->eval();
#if VM_TRACE
        if (tfp) tfp->dump(10 * edge + 5);
#endif
        top->clk = 0; top->eval();
#if VM_TRACE
        if (tfp) tfp->dump(10 * edge + 10);
#endif
        edge++;
        if (top->m_valid) { int t = top->m_tag; if (!first_visible.count(t)) first_visible[t] = edge - 1; }
        uint64_t occ = __builtin_popcount((unsigned)top->occupancy_o);
        if (occ > occ_max) occ_max = occ;
        occ_sum += occ; occ_samples++;
    }
    static void minmax(const std::vector<uint64_t>& v, uint64_t& lo, uint64_t& hi) {
        lo = hi = v.empty() ? 0 : v[0];
        for (auto e : v) { if (e < lo) lo = e; if (e > hi) hi = e; }
    }
    void stats(const char* phase, uint64_t tokens) const {
        uint64_t a0, a1, r0, r1, v0, v1, t0, t1;
        minmax(accept_spacing, a0, a1); minmax(retire_spacing, r0, r1); minmax(visible_latency, v0, v1); minmax(transfer_latency, t0, t1);
        std::printf("STATS {\"phase\":\"%s\",\"tokens\":%llu,\"accept_spacing\":[%llu,%llu],\"retire_spacing\":[%llu,%llu],"
                    "\"visible_latency\":[%llu,%llu],\"transfer_latency\":[%llu,%llu],\"occupancy_max\":%llu,\"occupancy_mean\":%.3f,\"edges\":%llu}\n",
                    phase, (unsigned long long)tokens, (unsigned long long)a0, (unsigned long long)a1, (unsigned long long)r0, (unsigned long long)r1,
                    (unsigned long long)v0, (unsigned long long)v1, (unsigned long long)t0, (unsigned long long)t1, (unsigned long long)occ_max,
                    occ_samples ? (double)occ_sum / (double)occ_samples : 0.0, (unsigned long long)edge);
    }
    void reset_pulse() { top->rst = 1; top->s_valid = 0; top->eval(); tick(); top->rst = 0; top->eval(); queue.clear(); have_prev = false; first_visible.clear(); }

    bool step(const Cand* k, bool m_ready, bool rst = false, int last = 0, int force_tag = -1) {
        top->rst = rst; top->m_ready = m_ready;
        int tag = 0;
        if (k) { tag = (force_tag >= 0) ? force_tag : (next_tag++ & 0xFFFF); top->s_rotation = k->rot; top->s_x = k->x; top->s_candidate_id = k->id; top->s_tag = tag; top->s_last = last; top->s_valid = 1; }
        else top->s_valid = 0;
        top->eval();
        bool s_hand = top->s_valid && top->s_ready && !rst;
        bool m_hand = top->m_valid && top->m_ready && !rst;
        if (top->m_valid && have_prev) {
            bool same = (p_legal == top->m_legal) && (p_last == top->m_last) && (p_id == top->m_candidate_id) && (p_tag == top->m_tag) && (p_y == top->m_y) && (p_score == (int32_t)top->m_score);
            if (!same && stability++ < 3) std::printf("STABILITY: output changed while valid and unconsumed at edge %llu\n", (unsigned long long)edge);
        }
        if (m_hand) {
            if (queue.empty()) { if (spurious++ < 3) std::printf("SPURIOUS output tag %u at edge %llu\n", (unsigned)top->m_tag, (unsigned long long)edge); }
            else {
                Expect e = queue.front(); queue.pop_front();
                bool ok = (top->m_legal == e.legal) && (top->m_last == e.last) && (top->m_candidate_id == e.id) && (top->m_tag == e.tag) &&
                          (top->m_y == e.y) && ((int32_t)top->m_score == e.score);
                if (!ok && mismatches++ < 5)
                    std::printf("MISMATCH edge %llu: got legal %u last %u id %u tag %u y %u score %d; expected legal %d last %d id %d tag %d y %d score %d\n",
                                (unsigned long long)edge, (unsigned)top->m_legal, (unsigned)top->m_last, (unsigned)top->m_candidate_id, (unsigned)top->m_tag,
                                (unsigned)top->m_y, (int32_t)top->m_score, e.legal, e.last, e.id, e.tag, e.y, e.score);
                retired++;
                if (retired > 1) retire_spacing.push_back(edge - last_retire);
                last_retire = edge;
                transfer_latency.push_back(edge - e.accept_edge);
                if (first_visible.count(e.tag)) visible_latency.push_back(first_visible[e.tag] - e.accept_edge);
                first_visible.erase(e.tag);
            }
        }
        if (s_hand) {
            Expect e{k->legal, k->y, k->id, tag, last, k->score, edge};
            queue.push_back(e); accepted++;
            if (accepted > 1) accept_spacing.push_back(edge - last_accept);
            last_accept = edge;
        }
        have_prev = top->m_valid && !m_hand && !rst;
        if (have_prev) { p_legal = top->m_legal; p_last = top->m_last; p_id = top->m_candidate_id; p_tag = top->m_tag; p_y = top->m_y; p_score = (int32_t)top->m_score; }
        tick();
        return s_hand;
    }
    void drain(int max_cycles = 200) { for (int i = 0; i < max_cycles && !queue.empty(); i++) step(nullptr, true); }
    bool empty() const { return top->occupancy_o == 0; }
    bool clean() const { return mismatches == 0 && stability == 0 && spurious == 0 && queue.empty(); }
};

static int g_bad = 0;
static void report(const char* name, bool ok, uint64_t n) {
    std::printf("CHECK a2_%s %llu/%llu\n", name, (unsigned long long)(ok ? n : 0), (unsigned long long)n);
    if (!ok) g_bad++;
}
static bool all_equal(const std::vector<uint64_t>& v, uint64_t x) { for (auto e : v) if (e != x) return false; return !v.empty(); }

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    std::string vectors, trace, phase = "all";
    uint64_t stream_n = 4096, seed = 1; int stalls = 30, bubbles = 20;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if (a.rfind("+vectors=", 0) == 0) vectors = a.substr(9);
        if (a.rfind("+stream=", 0) == 0) stream_n = std::strtoull(a.c_str() + 8, nullptr, 10);
        if (a.rfind("+seed=", 0) == 0) seed = std::strtoull(a.c_str() + 6, nullptr, 10);
        if (a.rfind("+stalls=", 0) == 0) stalls = std::atoi(a.c_str() + 8);
        if (a.rfind("+bubbles=", 0) == 0) bubbles = std::atoi(a.c_str() + 9);
        if (a.rfind("+trace=", 0) == 0) trace = a.substr(7);
        if (a.rfind("+phase=", 0) == 0) phase = a.substr(7);
    }
    auto want = [&](const char* name) { return phase == "all" || phase == name; };
    if (vectors.empty()) { std::fprintf(stderr, "need +vectors=<file>\n"); return 2; }
    std::vector<Ctx> ctxs = load(vectors);
    if (ctxs.empty()) { std::fprintf(stderr, "no contexts in %s\n", vectors.c_str()); return 2; }
    std::printf("native: %zu contexts, %zu tokens in %s\n", ctxs.size(), [&]{ size_t n = 0; for (auto& c : ctxs) n += c.cands.size(); return n; }(), vectors.c_str());

    // ---- stream: one context, distinct tags, no stalls ------------------------------------------
    if (want("stream")) {
        Harness h(seed); h.reset_pulse(); h.set_context(ctxs[0]);
        size_t i = 0; uint64_t issued = 0;
        while (h.retired < stream_n) {
            const Cand* k = (issued < stream_n) ? &ctxs[0].cands[i] : nullptr;
            if (h.step(k, true, false, (issued + 1 == stream_n) ? 1 : 0)) { issued++; i = (i + 1) % ctxs[0].cands.size(); }
        }
        bool ok = h.clean() && all_equal(h.accept_spacing, 1) && all_equal(h.retire_spacing, 1) && all_equal(h.transfer_latency, BANKS) &&
                  all_equal(h.visible_latency, BANKS - 1) && h.accept_spacing.size() == stream_n - 1 && h.visible_latency.size() == stream_n;
        std::printf("native: stream %llu tokens: acceptance spacing %s, retirement spacing %s, visible latency %s, transfer latency %s\n",
                    (unsigned long long)h.retired, all_equal(h.accept_spacing, 1) ? "1" : "NOT 1", all_equal(h.retire_spacing, 1) ? "1" : "NOT 1",
                    all_equal(h.visible_latency, BANKS - 1) ? "22" : "NOT 22", all_equal(h.transfer_latency, BANKS) ? "23" : "NOT 23");
        h.stats("stream", stream_n);
        report("stream", ok, stream_n);
    }
    // ---- traffic: every context, bubbles and stalls, illegal tokens, illegal final token --------
    if (want("traffic")) {
        Harness h(seed + 1); h.reset_pulse();
        uint64_t total = 0; bool ok = true; int illegal_last = 0;
        for (size_t ci = 0; ci < ctxs.size(); ci++) {
            const Ctx& c = ctxs[ci];
            h.set_context(c);
            size_t n = c.cands.size(), issued = 0; uint64_t guard = 0;
            uint64_t before = h.retired;
            while (h.retired - before < n && guard++ < 400 * n) {
                bool bubble = (int)(h.rng() % 100) < bubbles;
                bool ready = (int)(h.rng() % 100) >= stalls;
                const Cand* k = (issued < n && !bubble) ? &c.cands[issued] : nullptr;
                int last = (issued + 1 == n) ? 1 : 0;
                if (k && last && !k->legal) illegal_last++;
                if (h.step(k, ready, false, last)) issued++;
            }
            while (!h.empty()) h.step(nullptr, true);      // context changes only when the pipeline is empty
            total += n;
            if (!(h.retired - before == n)) ok = false;
        }
        ok = ok && h.clean();
        std::printf("native: traffic %llu tokens over %zu contexts (bubbles %d%%, stalls %d%%): %llu mismatches, %llu stability, %llu spurious, %d illegal final tokens\n",
                    (unsigned long long)total, ctxs.size(), bubbles, stalls, (unsigned long long)h.mismatches, (unsigned long long)h.stability,
                    (unsigned long long)h.spurious, illegal_last);
        h.stats("traffic", total);
        report("traffic", ok, total);
    }
    // ---- metadata: identical candidates with distinct tags; rotation/x changing every cycle ------
    if (want("metadata")) {
        Harness h(seed + 2); h.reset_pulse(); h.set_context(ctxs[0]);
        const Cand& k0 = ctxs[0].cands[0];
        for (int i = 0; i < 64; i++) h.step(&k0, true);
        h.drain();
        // alternate the two most different candidates every cycle, tags distinct
        std::vector<const Cand*> alt = {&ctxs[0].cands[0], &ctxs[0].cands[ctxs[0].cands.size() - 1]};
        for (int i = 0; i < 128; i++) h.step(alt[i & 1], true, false, (i == 127));
        h.drain();
        // last carried by an illegal token: an invalid rotation at the end of a burst
        Cand bad{3, 15, 45 & 63, 0, 0, 0};
        for (int i = 0; i < 8; i++) h.step(&ctxs[0].cands[i % ctxs[0].cands.size()], true);
        h.step(&bad, true, false, 1);
        h.drain();
        report("metadata", h.clean() && h.retired == 64 + 128 + 9, 64 + 128 + 9);
    }
    // ---- reset at every occupancy, stalled or not, at last issue and just before retirement -------
    if (want("reset")) {
        uint64_t checks = 0; bool ok = true;
        for (int occ = 0; occ <= BANKS; occ++) for (int stalled = 0; stalled < 2; stalled++) {
            Harness h(seed + 100 + occ); h.reset_pulse(); h.set_context(ctxs[1 % ctxs.size()]);
            const Ctx& c = ctxs[1 % ctxs.size()];
            for (int i = 0; i < occ; i++) h.step(&c.cands[i % c.cands.size()], !stalled);
            h.step(nullptr, !stalled, true);           // reset
            h.queue.clear(); h.have_prev = false; h.first_visible.clear();
            if (!h.empty()) { ok = false; std::printf("RESET occupancy %d: pipeline not empty after reset\n", occ); }
            uint64_t before = h.retired, sp = h.spurious; int issued = 0; uint64_t guard = 0;
            while (h.retired - before < 20 && guard++ < 600) { if (h.step(issued < 20 ? &c.cands[issued % c.cands.size()] : nullptr, true)) issued++; }
            checks++;
            if (!(h.clean() && h.retired - before == 20 && h.spurious == sp)) { ok = false; std::printf("RESET occupancy %d stalled %d failed\n", occ, stalled); }
        }
        for (int variant = 0; variant < 2; variant++) {
            Harness h(seed + 200 + variant); h.reset_pulse(); h.set_context(ctxs[0]);
            const Ctx& c = ctxs[0];
            for (int i = 0; i < 4; i++) h.step(&c.cands[i], true);
            if (variant == 0) h.step(&c.cands[4], true, true, 1);                                   // reset on the edge issuing last
            else { h.step(&c.cands[4], true, false, 1); for (int k = 0; k < BANKS - 1; k++) h.step(nullptr, true); h.step(nullptr, true, true); }
            h.queue.clear(); h.have_prev = false; h.first_visible.clear();
            uint64_t before = h.retired, sp = h.spurious; int issued = 0; uint64_t guard = 0;
            while (h.retired - before < 10 && guard++ < 300) { if (h.step(issued < 10 ? &c.cands[issued] : nullptr, true)) issued++; }
            checks++;
            if (!(h.clean() && h.retired - before == 10 && h.spurious == sp && h.empty())) { ok = false; std::printf("RESET last-token variant %d failed\n", variant); }
        }
        report("reset", ok, checks);
    }
#if VM_TRACE
    // ---- bounded trace of a difficult passing stall/reset scenario (guide U09 step 6) ------------
    if (!trace.empty()) {
        Verilated::traceEverOn(true);
        Harness h(seed + 300);
        h.tfp = new VerilatedVcdC; h.top->trace(h.tfp, 99); h.tfp->open(trace.c_str());
        h.reset_pulse(); h.set_context(ctxs[0]);
        const Ctx& c = ctxs[0];
        for (int i = 0; i < 30; i++) h.step(&c.cands[i % c.cands.size()], (i % 5) != 4, false, i == 29);   // fill with stalls
        for (int i = 0; i < 6; i++) h.step(nullptr, false);                                                // hold
        h.step(nullptr, true, true);                                                                        // reset mid-stall
        h.queue.clear(); h.have_prev = false; h.first_visible.clear();
        for (int i = 0; i < 40; i++) h.step(i < 12 ? &c.cands[i] : nullptr, true, false, i == 11);
        h.tfp->close(); delete h.tfp;
        std::printf("native: trace written to %s (%s)\n", trace.c_str(), h.clean() ? "scenario passed" : "scenario FAILED");
        if (!h.clean()) g_bad++;
    }
#endif
    std::printf("native: candidate pipeline harness %s\n", g_bad ? "FAILED" : "all phases passed");
    return g_bad ? 1 : 0;
}
