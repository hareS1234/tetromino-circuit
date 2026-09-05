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
