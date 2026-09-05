// Persistent native Verilator driver for tetris_core.
//
// Protocol (newline-delimited, numeric, stdin -> stdout; diagnostics on stderr):
//   request:  piece next_piece b0 b1 b2 b3 b4 b5 b6      (b0..b6 = little-endian 32-bit board words,
//                                                         b6 uses its low eight bits)
//   response: error no_move rotation x y signed_score cycles interval
// cycles   = rising edges from the acceptance edge to the first edge with rsp_valid high
//            (same definition as the cocotb driver and the core's cycles_o, which is checked)
// interval = rising edges from the acceptance edge until req_ready is high again, with the
//            response consumed immediately (single-outstanding request spacing).
// pair request (batch mode, U10): "P piece next b0..b6 piece2 next2 c0..c6" drives the first request,
//   keeps the second request offered (req_valid high) while the first is processed, consumes the first
//   response on the edge it appears, and reports the real spacing between the two acceptance edges:
//   response line 1: error no_move rotation x y score cycles interval interval_measured
//   response line 2: the second request's normal eight fields
// EOF is clean termination; malformed input, a protocol violation, or a timeout exits nonzero.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>

#include "Vtetris_core.h"
#include "verilated.h"

namespace {

std::unique_ptr<VerilatedContext> ctx;
std::unique_ptr<Vtetris_core> top;
uint64_t max_cycles = 4000000;

void half(int clk) {
    top->clk = clk;
    top->eval();
    ctx->timeInc(5);
}

void tick() {
    half(0);
    half(1);
}

int fail(const std::string& msg) {
    std::cerr << "native driver error: " << msg << std::endl;
    top->final();
    return 2;
}

}  // namespace

int main(int argc, char** argv) {
    ctx = std::make_unique<VerilatedContext>();
    ctx->commandArgs(argc, argv);
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if (a.rfind("+max_cycles=", 0) == 0) max_cycles = std::strtoull(a.c_str() + 12, nullptr, 10);
    }
    top = std::make_unique<Vtetris_core>(ctx.get());

    // initialise every input and apply synchronous reset
    top->clk = 0;
    top->rst = 1;
    top->req_valid = 0;
    top->rsp_ready = 0;
    top->piece_i = 0;
    top->next_piece_i = 0;
    for (int i = 0; i < 7; i++) top->board_i[i] = 0;
    top->eval();
    tick();
    tick();
    top->rst = 0;
    tick();

    std::string line;
    uint64_t requests = 0;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        if (line[0] == 'P') {
            // ---- batch mode: two requests, the second offered while the first is in flight ----
            std::istringstream in(line.substr(1));
            unsigned p1, n1, p2, n2;
            uint32_t w1[7], w2[7];
            if (!(in >> p1 >> n1)) return fail("malformed pair line: " + line);
            for (int i = 0; i < 7; i++) if (!(in >> w1[i])) return fail("malformed pair board 1");
            if (!(in >> p2 >> n2)) return fail("malformed pair line (second request)");
            for (int i = 0; i < 7; i++) if (!(in >> w2[i])) return fail("malformed pair board 2");
            w1[6] &= 0xFFu; w2[6] &= 0xFFu;
            top->piece_i = p1; top->next_piece_i = n1;
            for (int i = 0; i < 7; i++) top->board_i[i] = w1[i];
            top->req_valid = 1; top->rsp_ready = 1;          // response consumed immediately when it appears
            uint64_t waited = 0;
            while (true) { half(0); bool ready = top->req_ready; half(1); if (ready) break; if (++waited > 1000) return fail("core never became ready"); }
            // first acceptance edge happened; immediately offer the second request
            top->piece_i = p2; top->next_piece_i = n2;
            for (int i = 0; i < 7; i++) top->board_i[i] = w2[i];
            top->req_valid = 1;
            uint64_t e = 0, cycles1 = 0, accept2 = 0; bool got1 = false;
            unsigned error1 = 0, no_move1 = 0, rot1 = 0, x1 = 0, y1 = 0; int32_t score1 = 0;
            while (accept2 == 0) {
                half(0);
                bool ready = top->req_ready;                 // sampled before the edge with req_valid high
                if (!got1 && top->rsp_valid) {               // response visible before this edge: it is consumed at this edge
                    got1 = true; cycles1 = e;
                    error1 = top->error_o; no_move1 = top->no_move_o; rot1 = top->rotation_o; x1 = top->x_o; y1 = top->y_o; score1 = (int32_t)top->score_o;
                    if (top->cycles_o != cycles1) return fail("cycles_o disagrees with the edge counter (pair)");
                }
                half(1);
                e++;
                if (ready) accept2 = e;                      // this edge accepted the second request
                if (e > max_cycles) return fail("timeout in pair mode");
            }
            if (!got1) return fail("second request accepted before the first response");
            top->req_valid = 0;
            top->rsp_ready = 0;
            // interval (inferred, as in single mode) = cycles + 1 (consumption) + edges until ready; here the
            // consumption edge is the rsp edge itself, so the inferred value is cycles1 + 2 for this core
            std::printf("%u %u %u %u %u %d %llu %llu %llu\n", error1, no_move1, rot1, x1, y1, score1,
                        (unsigned long long)cycles1, (unsigned long long)(cycles1 + 2), (unsigned long long)accept2);
            // second request: normal completion and consumption
            uint64_t cycles2 = 0;
            while (!top->rsp_valid) { tick(); if (++cycles2 > max_cycles) return fail("timeout waiting for the second response"); }
            unsigned error2 = top->error_o, no_move2 = top->no_move_o, rot2 = top->rotation_o, x2 = top->x_o, y2 = top->y_o;
            int32_t score2 = (int32_t)top->score_o;
            if (top->cycles_o != cycles2) return fail("cycles_o disagrees (second request)");
            top->rsp_ready = 1; tick(); top->rsp_ready = 0;
            uint64_t interval2 = cycles2 + 1;
            while (true) { half(0); bool ready = top->req_ready; half(1); interval2++; if (ready) break; if (interval2 > max_cycles) return fail("core never returned to idle"); }
            std::printf("%u %u %u %u %u %d %llu %llu\n", error2, no_move2, rot2, x2, y2, score2, (unsigned long long)cycles2, (unsigned long long)interval2);
            std::fflush(stdout);
            requests += 2;
            continue;
        }
        std::istringstream in(line);
        unsigned piece, next;
        uint32_t words[7];
        if (!(in >> piece >> next)) return fail("malformed request line: " + line);
        for (int i = 0; i < 7; i++) {
            if (!(in >> words[i])) return fail("malformed board words: " + line);
        }
        if (piece > 7 || next > 7) return fail("piece id out of range");
        words[6] &= 0xFFu;

        top->piece_i = piece;
        top->next_piece_i = next;
        for (int i = 0; i < 7; i++) top->board_i[i] = words[i];
        top->req_valid = 1;
        top->rsp_ready = 0;

        // wait for the acceptance edge: req_ready is inspected before the rising edge
        uint64_t waited = 0;
        while (true) {
            half(0);
            bool ready = top->req_ready;
            half(1);
            if (ready) break;
            if (++waited > 1000) return fail("core never became ready");
        }
        top->req_valid = 0;
        // inputs are latched: scrambling them here must not change the answer
        top->piece_i = 7;
        top->next_piece_i = 7;
        for (int i = 0; i < 7; i++) top->board_i[i] = 0xFFFFFFFFu;
        top->board_i[6] = 0xFFu;

        uint64_t cycles = 0;
        while (!top->rsp_valid) {
            tick();
            if (++cycles > max_cycles) return fail("timeout waiting for a response");
            if (top->req_ready) return fail("req_ready asserted while a request was outstanding");
        }
        unsigned error = top->error_o, no_move = top->no_move_o, rotation = top->rotation_o, x = top->x_o, y = top->y_o;
        int32_t score = static_cast<int32_t>(top->score_o);
        uint32_t reported = top->cycles_o;
        if (reported != cycles) return fail("cycles_o disagrees with the edge counter");

        // consume the response immediately and measure the request interval
        top->rsp_ready = 1;
        tick();
        top->rsp_ready = 0;
        uint64_t interval = cycles + 1;          // the consumption edge
        if (top->rsp_valid) return fail("rsp_valid still high after consumption");
        while (true) {
            half(0);
            bool ready = top->req_ready;         // sampled before the edge, like a requester would
            half(1);
            interval++;                          // this edge could accept the next request
            if (ready) break;
            if (interval > max_cycles) return fail("core never returned to idle");
        }
        // interval = minimum spacing between two acceptance edges with immediate consumption
        std::printf("%u %u %u %u %u %d %llu %llu\n", error, no_move, rotation, x, y, score,
                    static_cast<unsigned long long>(cycles), static_cast<unsigned long long>(interval));
        std::fflush(stdout);
        requests++;
    }
    top->final();
    std::cerr << "native driver: " << requests << " requests, " << ctx->time() / 10 << " cycles" << std::endl;
    return 0;
}
