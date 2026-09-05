// Native micro-harness for the combinational compactor line_clear_parallel (U05, guide §6.4).
//   +mode=exhaustive           all 2^20 keep masks: survivors carry unique non-full tags (s+1),
//                              deleted rows are 1023; checks board, count, survivors, keep, ranks
//   +mode=random +count=N +seed=S   arbitrary 10-bit row payloads against a C++ list filter
// The harness instantiates the actual HDL top; the expected values come from an independent
// list filter and an independent prefix computation written here, never from the DUT.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <string>
#include "Vline_clear_parallel.h"
#include "verilated.h"

static const uint16_t FULL = 0x3FF;

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

static void expected_filter(const uint16_t rows[20], uint16_t out[20], int& cleared) {
    int n = 0;
    for (int s = 0; s < 20; s++) if (rows[s] != FULL) out[n++] = rows[s];
    for (int d = n; d < 20; d++) out[d] = 0;
    cleared = 20 - n;
}

static void expected_ranks(const uint16_t rows[20], uint8_t rank[20]) {
    int acc = 0;
    for (int s = 0; s < 20; s++) { if (rows[s] != FULL) acc++; rank[s] = (uint8_t)acc; }
}

static int failures = 0;
static bool check(Vline_clear_parallel* top, const uint16_t rows[20], const char* what, uint64_t idx) {
    uint32_t w[7];
    pack_board(w, rows);
    for (int i = 0; i < 7; i++) top->board_i[i] = w[i];
    top->eval();
    uint16_t got[20], exp[20];
    unpack_board(top->board_o.data(), got);
    int exp_cleared;
    expected_filter(rows, exp, exp_cleared);
    uint8_t exp_rank[20];
    expected_ranks(rows, exp_rank);
    bool ok = (top->count_o == exp_cleared) && (top->survivors_o == 20 - exp_cleared);
    for (int d = 0; d < 20 && ok; d++) ok = (got[d] == exp[d]);
    uint32_t exp_keep = 0;
    for (int s = 0; s < 20; s++) if (rows[s] != FULL) exp_keep |= 1u << s;
    if (ok) ok = (top->keep_o == exp_keep);
    for (int s = 0; s < 20 && ok; s++) {
        int off = 5 * s;
        const uint32_t* rk = top->rank_o.data();
        uint64_t v = (uint64_t)rk[off / 32] | ((off / 32 + 1 < 4) ? ((uint64_t)rk[off / 32 + 1] << 32) : 0);
        ok = (((v >> (off % 32)) & 31) == exp_rank[s]);
    }
    if (!ok && failures++ < 5) {
        std::printf("MISMATCH %s #%llu: count %u exp %d; rows:", what, (unsigned long long)idx, (unsigned)top->count_o, exp_cleared);
        for (int s = 0; s < 20; s++) std::printf(" %03x", rows[s]);
        std::printf("\n  got:");
        for (int d = 0; d < 20; d++) std::printf(" %03x", got[d]);
        std::printf("\n  exp:");
        for (int d = 0; d < 20; d++) std::printf(" %03x", exp[d]);
        std::printf("\n");
    }
    return ok;
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    std::string mode = "exhaustive";
    uint64_t count = 10000, seed = 1;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if (a.rfind("+mode=", 0) == 0) mode = a.substr(6);
        if (a.rfind("+count=", 0) == 0) count = std::strtoull(a.c_str() + 7, nullptr, 10);
        if (a.rfind("+seed=", 0) == 0) seed = std::strtoull(a.c_str() + 6, nullptr, 10);
    }
    Vline_clear_parallel* top = new Vline_clear_parallel;
    uint64_t total = 0, ok = 0;
    uint16_t rows[20];
    if (mode == "exhaustive") {
        for (uint64_t mask = 0; mask < (1ull << 20); mask++) {
            for (int s = 0; s < 20; s++) rows[s] = ((mask >> s) & 1) ? (uint16_t)(s + 1) : FULL;
            total++;
            if (check(top, rows, "mask", mask)) ok++;
        }
        std::printf("CHECK compactor_exhaustive %llu/%llu\n", (unsigned long long)ok, (unsigned long long)total);
    } else if (mode == "random") {
        std::mt19937_64 rng(seed);
        for (uint64_t i = 0; i < count; i++) {
            double p_full = (double)(rng() % 10) / 10.0;
            for (int s = 0; s < 20; s++) {
                double u = (double)(rng() % 1000) / 1000.0;
                rows[s] = (u < p_full) ? FULL : (uint16_t)(rng() % FULL);
            }
            total++;
            if (check(top, rows, "random", i)) ok++;
        }
        std::printf("CHECK compactor_random %llu/%llu\n", (unsigned long long)ok, (unsigned long long)total);
    } else {
        std::fprintf(stderr, "unknown mode %s\n", mode.c_str());
        return 2;
    }
    std::printf("native: %llu of %llu boards match (%s)\n", (unsigned long long)ok, (unsigned long long)total, mode.c_str());
    delete top;
    return (ok == total) ? 0 : 1;
}
