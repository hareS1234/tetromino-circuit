// Native streaming harness for line_clear_pipe through line_clear_pipe_harness (U06, guide §6.4 5-6).
//   +count=N +seed=S [+stalls=P] [+bubbles=P]
// Phases (each prints a CHECK line):
//   continuous  N tokens, no bubbles, output always ready: acceptance/retirement spacing 1, visible
//               latency 8 edges and transfer latency 9 edges for the nine banks P4-P12
//   random      N tokens with P% input bubbles and P% output stalls: order, count, tags, stability
//   stalls      deterministic stalls of 1/3/17/100 cycles at the first and at the last output
//   backtoback  alternating all-full / no-full / mixed boards with no bubbles (data-rank alignment)
//   reset       reset at every occupancy 0..9, while the output is stalled, at last-token issue and
//               just before retirement: no pre-reset token may emerge afterwards
// Scoreboard discipline (guide §8.2): handshakes and input payload are sampled before the edge; the
// expected queue is a plain deque updated only on accepted tokens; registered outputs are compared
// on transfer; a separate monitor checks m_* stability while m_valid && !m_ready.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <random>
#include <string>
#include <vector>
#include "Vline_clear_pipe_harness.h"
#include "verilated.h"

static const uint16_t FULL = 0x3FF;
static const int BANKS = 9;

struct Token { uint16_t rows[20]; uint16_t out[20]; int cleared; int legal, y, id, tag, last; uint64_t accept_edge; };

static void pack_board(uint32_t* w, const uint16_t rows[20]) {
    for (int i = 0; i < 7; i++) w[i] = 0;
    for (int s = 0; s < 20; s++) {
        int off = 10 * s;
        uint64_t v = (uint64_t)(rows[s] & FULL) << (off % 32);
        w[off / 32] |= (uint32_t)(v & 0xFFFFFFFFu);
        if (off % 32 > 22) w[off / 32 + 1] |= (uint32_t)(v >> 32);
    }
}
static void unpack_board(const uint32_t* w, uint16_t rows[20]) {
    for (int s = 0; s < 20; s++) {
        int off = 10 * s;
        uint64_t v = (uint64_t)w[off / 32] | ((off / 32 + 1 < 7) ? ((uint64_t)w[off / 32 + 1] << 32) : 0);
        rows[s] = (uint16_t)((v >> (off % 32)) & FULL);
    }
}
static void expected(Token& t) {
    int n = 0;
    for (int s = 0; s < 20; s++) if (t.rows[s] != FULL) t.out[n++] = t.rows[s];
    for (int d = n; d < 20; d++) t.out[d] = 0;
    t.cleared = 20 - n;
}

struct Harness {
    Vline_clear_pipe_harness* top;
    std::deque<Token> queue;          // expected results in acceptance order
    uint64_t edge = 0, accepted = 0, retired = 0, mismatches = 0, stability_violations = 0, spurious = 0;
    uint64_t last_accept_edge = 0, last_retire_edge = 0;
    std::vector<uint64_t> accept_spacing, retire_spacing, transfer_latency;
    bool have_prev = false; uint16_t prev_rows[20]; int prev_cleared, prev_legal, prev_y, prev_id, prev_tag, prev_last;
    int next_tag = 1;
    std::mt19937_64 rng;

    explicit Harness(uint64_t seed) : rng(seed) { top = new Vline_clear_pipe_harness; top->clk = 0; top->rst = 1; top->m_ready = 1; top->s_valid = 0; top->eval(); }

    void tick() { top->clk = 1; top->eval(); top->clk = 0; top->eval(); edge++; }

    void reset_pulse() {
        top->rst = 1; top->s_valid = 0; top->eval(); tick(); top->rst = 0; top->eval();
        queue.clear(); have_prev = false;
    }

    Token make_token(int mode) {
        Token t{};
        double p_full = (mode == 1) ? 1.0 : (mode == 2) ? 0.0 : (double)(rng() % 6) / 10.0;
        for (int s = 0; s < 20; s++) {
            double u = (double)(rng() % 1000) / 1000.0;
            t.rows[s] = (u < p_full) ? FULL : (uint16_t)(rng() % FULL);
        }
        t.legal = rng() & 1; t.y = rng() % 20; t.id = rng() % 40; t.tag = next_tag++ & 0xFFFF; t.last = (rng() % 8 == 0);
        expected(t);
        return t;
    }

    void drive(const Token* t) {
        if (t) {
            uint32_t w[7]; pack_board(w, t->rows);
            for (int i = 0; i < 7; i++) top->s_board[i] = w[i];
            top->s_legal = t->legal; top->s_y = t->y; top->s_id = t->id; top->s_tag = t->tag; top->s_last = t->last;
            top->s_valid = 1;
        } else {
            top->s_valid = 0;
        }
    }

    // one cycle: present inputs, evaluate handshakes pre-edge, check output, then clock.
    // returns true if the token was accepted
    bool step(const Token* t, bool m_ready, bool rst = false) {
        top->rst = rst;
        top->m_ready = m_ready;
        drive(t);
        top->eval();
        bool s_hand = top->s_valid && top->s_ready && !rst;
        bool m_hand = top->m_valid && top->m_ready && !rst;
        // stability monitor: a valid, unconsumed output must not change between observations
        uint16_t rows[20]; unpack_board(top->m_board.data(), rows);
        if (top->m_valid) {
            if (have_prev) {
                bool same = (prev_cleared == top->m_cleared) && (prev_legal == top->m_legal) && (prev_y == top->m_y) &&
                            (prev_id == top->m_id) && (prev_tag == top->m_tag) && (prev_last == top->m_last);
                for (int d = 0; d < 20 && same; d++) same = (prev_rows[d] == rows[d]);
                if (!same) { if (stability_violations++ < 3) std::printf("STABILITY: output changed while valid and not consumed (edge %llu, tag %u)\n", (unsigned long long)edge, (unsigned)top->m_tag); }
            }
        }
        if (m_hand) {
            if (queue.empty()) { spurious++; if (spurious < 3) std::printf("SPURIOUS output tag %u at edge %llu\n", (unsigned)top->m_tag, (unsigned long long)edge); }
            else {
                Token e = queue.front(); queue.pop_front();
                bool ok = (top->m_cleared == e.cleared) && (top->m_legal == e.legal) && (top->m_y == e.y) && (top->m_id == e.id) &&
                          (top->m_tag == e.tag) && (top->m_last == e.last);
                for (int d = 0; d < 20 && ok; d++) ok = (rows[d] == e.out[d]);
                if (!ok && mismatches++ < 3) {
                    std::printf("MISMATCH at edge %llu: got tag %u cleared %u legal %u y %u id %u last %u; expected tag %u cleared %d\n",
                                (unsigned long long)edge, (unsigned)top->m_tag, (unsigned)top->m_cleared, (unsigned)top->m_legal, (unsigned)top->m_y,
                                (unsigned)top->m_id, (unsigned)top->m_last, e.tag, e.cleared);
                }
                retired++;
                if (retired > 1) retire_spacing.push_back(edge - last_retire_edge);
                last_retire_edge = edge;
                transfer_latency.push_back(edge - e.accept_edge);
            }
        }
        if (s_hand) {
            Token a = *t; a.accept_edge = edge; queue.push_back(a);
            accepted++;
            if (accepted > 1) accept_spacing.push_back(edge - last_accept_edge);
            last_accept_edge = edge;
        }
        // remember the output for the stability monitor (only meaningful when it stays valid & unconsumed)
        have_prev = top->m_valid && !m_hand && !rst;
        if (have_prev) { for (int d = 0; d < 20; d++) prev_rows[d] = rows[d]; prev_cleared = top->m_cleared; prev_legal = top->m_legal; prev_y = top->m_y; prev_id = top->m_id; prev_tag = top->m_tag; prev_last = top->m_last; }
        tick();
        return s_hand;
    }

    void drain(int max_cycles = 64) { for (int i = 0; i < max_cycles && !queue.empty(); i++) step(nullptr, true); }
    bool clean() const { return mismatches == 0 && spurious == 0 && stability_violations == 0 && queue.empty(); }
};

static uint64_t g_bad = 0;
static void report(const char* name, bool ok, uint64_t n) {
    std::printf("CHECK compactor_stream_%s %llu/%llu\n", name, (unsigned long long)(ok ? n : 0), (unsigned long long)n);
    if (!ok) g_bad++;
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    uint64_t count = 4096, seed = 1; int stalls = 30, bubbles = 20;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if (a.rfind("+count=", 0) == 0) count = std::strtoull(a.c_str() + 7, nullptr, 10);
        if (a.rfind("+seed=", 0) == 0) seed = std::strtoull(a.c_str() + 6, nullptr, 10);
        if (a.rfind("+stalls=", 0) == 0) stalls = std::atoi(a.c_str() + 8);
        if (a.rfind("+bubbles=", 0) == 0) bubbles = std::atoi(a.c_str() + 9);
    }
    Harness h(seed);
    h.reset_pulse();

    // ---- continuous ------------------------------------------------------------------------
    {
        uint64_t issued = 0;
        while (issued < count) { Token t = h.make_token(0); if (h.step(&t, true)) issued++; }
        h.drain();
        bool spacing_ok = true;
        for (auto s : h.accept_spacing) if (s != 1) spacing_ok = false;
        for (auto s : h.retire_spacing) if (s != 1) spacing_ok = false;
        bool lat_ok = true;
        for (auto l : h.transfer_latency) if (l != BANKS) lat_ok = false;
        bool ok = h.clean() && spacing_ok && lat_ok && h.retired == count && h.accept_spacing.size() == count - 1;
        std::printf("native: continuous %llu tokens, acceptance spacing %s, retirement spacing %s, transfer latency %s (%d edges)\n",
                    (unsigned long long)h.retired, spacing_ok ? "1" : "NOT 1", spacing_ok ? "1" : "NOT 1", lat_ok ? "uniform" : "VARIES", BANKS);
        report("continuous", ok, count);
    }
    // ---- random bubbles and stalls ------------------------------------------------------------
    {
        Harness r(seed + 1); r.reset_pulse();
        uint64_t issued = 0; Token pending = r.make_token(0); bool have = true;
        uint64_t guard = 0;
        while (r.retired < count && guard++ < 200 * count) {
            bool bubble = (int)(r.rng() % 100) < bubbles;
            bool ready = (int)(r.rng() % 100) >= stalls;
            if (!have && issued < count) { pending = r.make_token(0); have = true; }
            bool acc = r.step((have && !bubble && issued < count) ? &pending : nullptr, ready);
            if (acc) { issued++; have = false; }
        }
        bool lat_ok = true;
        for (auto l : r.transfer_latency) if (l < (uint64_t)BANKS) lat_ok = false;
        bool ok = r.clean() && r.retired == count && lat_ok;
        std::printf("native: random traffic %llu tokens (bubbles %d%%, stalls %d%%): %llu mismatches, %llu stability violations, %llu spurious\n",
                    (unsigned long long)r.retired, bubbles, stalls, (unsigned long long)r.mismatches, (unsigned long long)r.stability_violations, (unsigned long long)r.spurious);
        report("random", ok, count);
    }
    // ---- deterministic stalls at the first and the last output ---------------------------------
    {
        const int lengths[4] = {1, 3, 17, 100};
        uint64_t checks = 0; bool ok = true;
        for (int li = 0; li < 4; li++) for (int at_last = 0; at_last < 2; at_last++) {
            Harness d(seed + 10 + li); d.reset_pulse();
            const int n = 12; std::vector<Token> toks; for (int i = 0; i < n; i++) toks.push_back(d.make_token(0));
            int issued = 0; int stall_left = 0; bool stall_armed = true;
            uint64_t guard = 0;
            while (d.retired < (uint64_t)n && guard++ < 5000) {
                bool ready = true;
                bool target = at_last ? (d.retired == (uint64_t)(n - 1)) : (d.retired == 0);
                if (d.top->m_valid && target && stall_armed) { if (stall_left == 0) stall_left = lengths[li]; }
                if (stall_left > 0) { ready = false; stall_left--; if (stall_left == 0) stall_armed = false; }
                bool acc = d.step(issued < n ? &toks[issued] : nullptr, ready);
                if (acc) issued++;
            }
            checks++;
            if (!(d.clean() && d.retired == (uint64_t)n)) ok = false;
        }
        report("stalls", ok, checks);
    }
    // ---- back-to-back all-full / no-full / mixed boards ---------------------------------------
    {
        Harness b(seed + 20); b.reset_pulse();
        const int n = 300; int issued = 0;
        while (b.retired < (uint64_t)n) { Token t = b.make_token(issued % 3 == 0 ? 1 : (issued % 3 == 1 ? 2 : 0)); if (issued < n) { if (b.step(&t, true)) issued++; } else b.step(nullptr, true); }
        bool ok = b.clean() && b.retired == (uint64_t)n;
        report("backtoback", ok, n);
    }
    // ---- reset at every occupancy, while stalled, at last-token issue, before retirement -------
    {
        uint64_t checks = 0; bool ok = true;
        for (int occ = 0; occ <= BANKS; occ++) for (int stalled = 0; stalled < 2; stalled++) {
            Harness z(seed + 30 + occ); z.reset_pulse();
            // fill occ tokens (stalled output keeps them in the pipe when occ == BANKS)
            std::vector<Token> old; for (int i = 0; i < occ; i++) old.push_back(z.make_token(0));
            for (int i = 0; i < occ; i++) z.step(&old[i], !stalled);
            // reset while (possibly) stalled; the scoreboard forgets the old tokens
            z.step(nullptr, !stalled, true);
            z.queue.clear(); z.have_prev = false;
            // drive fresh tokens; only they may ever appear
            uint64_t before = z.retired; uint64_t spurious_before = z.spurious;
            std::vector<Token> fresh; for (int i = 0; i < 16; i++) fresh.push_back(z.make_token(0));
            int issued = 0; uint64_t guard = 0;
            while (z.retired - before < 16 && guard++ < 400) { bool acc = z.step(issued < 16 ? &fresh[issued] : nullptr, true); if (acc) issued++; }
            checks++;
            if (!(z.clean() && z.retired - before == 16 && z.spurious == spurious_before)) { ok = false; std::printf("RESET case occupancy %d stalled %d failed\n", occ, stalled); }
        }
        // reset exactly at last-token issue and just before retirement of a last token
        for (int variant = 0; variant < 2; variant++) {
            Harness z(seed + 50 + variant); z.reset_pulse();
            std::vector<Token> toks; for (int i = 0; i < 5; i++) { toks.push_back(z.make_token(0)); }
            toks[4].last = 1;
            for (int i = 0; i < 4; i++) z.step(&toks[i], true);
            if (variant == 0) { z.step(&toks[4], true, true); }                  // reset at the edge issuing last
            else { z.step(&toks[4], true); for (int k = 0; k < BANKS - 1; k++) z.step(nullptr, true); z.step(nullptr, true, true); } // just before retirement
            z.queue.clear(); z.have_prev = false;
            uint64_t before = z.retired, sp = z.spurious;
            std::vector<Token> fresh; for (int i = 0; i < 8; i++) fresh.push_back(z.make_token(0));
            int issued = 0; uint64_t guard = 0;
            while (z.retired - before < 8 && guard++ < 200) { bool acc = z.step(issued < 8 ? &fresh[issued] : nullptr, true); if (acc) issued++; }
            checks++;
            if (!(z.clean() && z.retired - before == 8 && z.spurious == sp)) { ok = false; std::printf("RESET last-token variant %d failed\n", variant); }
        }
        report("reset", ok, checks);
    }
    std::printf("native: compactor stream harness %s\n", g_bad ? "FAILED" : "all phases passed");
    return g_bad ? 1 : 0;
}
