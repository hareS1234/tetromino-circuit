"""Cycle-level abstract token model of the A2 candidate pipeline and its search controller (U04).

The model has no datapath: a token is an opaque tag.  It reproduces the register/handshake
contract of docs/design_a2.md exactly so the fill/drain timing, the latency definitions and the
decision-latency formula can be tested before any RTL exists and re-checked against RTL later.

Edge convention (guide §5.6): handshakes are sampled before an edge; registered outputs are
observed after it.  With B banks an input accepted at edge a is visible as m_valid after edge
a+B-1 and is transferred (consumed) at edge a+B when m_ready is high.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BANKS = 23
# Existing tetris_core controller edges relative to request acceptance (guide §5.6 table)
CORE_LATCH, CORE_CACHE, CORE_SEARCH_START, CTRL_ACCEPT, FIRST_ISSUE = 0, 1, 2, 3, 4


@dataclass
class Pipe:
    """Globally stallable B-bank pipeline: one advance signal, valid bits shift with bubbles."""
    banks: int = BANKS
    valid: list = field(default_factory=list)
    payload: list = field(default_factory=list)
    edge: int = 0
    accepted: list = field(default_factory=list)      # (edge, tag) input handshakes
    transferred: list = field(default_factory=list)   # (edge, tag) output handshakes
    first_visible: dict = field(default_factory=dict) # tag -> edge after which m_valid first showed it

    def __post_init__(self):
        self.valid = [False] * self.banks
        self.payload = [None] * self.banks

    # pre-edge combinational view
    @property
    def m_valid(self) -> bool:
        return self.valid[-1]

    @property
    def m_payload(self):
        return self.payload[-1]

    def advance(self, m_ready: bool, rst: bool = False) -> bool:
        return (not rst) and ((not self.valid[-1]) or m_ready)

    def s_ready(self, m_ready: bool, rst: bool = False) -> bool:
        """s_ready equals the global advance signal (guide §5.4)."""
        return self.advance(m_ready, rst)

    def step(self, s_valid: bool, s_payload, m_ready: bool, rst: bool = False) -> dict:
        """One clock edge.  Returns the handshakes that happened at this edge."""
        adv = self.advance(m_ready, rst)
        out = {"edge": self.edge, "accepted": None, "transferred": None, "advance": adv}
        if self.valid[-1] and m_ready and not rst:
            out["transferred"] = self.payload[-1]
            self.transferred.append((self.edge, self.payload[-1]))
        if rst:
            self.valid = [False] * self.banks
            self.payload = [None] * self.banks
        elif adv:
            for i in range(self.banks - 1, 0, -1):
                self.valid[i] = self.valid[i - 1]
                self.payload[i] = self.payload[i - 1] if self.valid[i - 1] else None
            self.valid[0] = bool(s_valid)
            self.payload[0] = s_payload if s_valid else None
            if s_valid:
                out["accepted"] = s_payload
                self.accepted.append((self.edge, s_payload))
        if self.valid[-1] and self.payload[-1] not in self.first_visible:
            self.first_visible[self.payload[-1]] = self.edge
        self.edge += 1
        return out

    @property
    def occupancy(self) -> int:
        return sum(self.valid)


def stream(n_tokens: int, banks: int = BANKS, ready=lambda edge: True, bubbles=lambda edge: False) -> dict:
    """Push n tokens back to back (optionally with input bubbles / output stalls) and measure."""
    p = Pipe(banks)
    issued = 0
    edge = 0
    while len(p.transferred) < n_tokens and edge < 100000:
        s_valid = issued < n_tokens and not bubbles(edge)
        res = p.step(s_valid, issued if s_valid else None, ready(edge))
        if res["accepted"] is not None:
            issued += 1
        edge += 1
    acc = dict(p.accepted[i][::-1] for i in range(len(p.accepted)))  # tag -> edge
    xfer = dict(p.transferred[i][::-1] for i in range(len(p.transferred)))
    visible = {t: p.first_visible[t] - acc[t] for t in acc if t in p.first_visible}
    transfer = {t: xfer[t] - acc[t] for t in acc if t in xfer}
    spacings = [p.accepted[i + 1][0] - p.accepted[i][0] for i in range(len(p.accepted) - 1)]
    return {"tokens": n_tokens, "accept_spacings": spacings, "visible_latency": visible, "transfer_latency": transfer,
            "order_preserved": [t for _, t in p.transferred] == list(range(n_tokens)), "edges": edge}


def decision_latency(n_candidates: int, banks: int = BANKS) -> dict:
    """Edges relative to core request acceptance for a search over N dense candidates.

    0 core latches the request; 1 registers the height cache; 2 asserts registered search_start;
    3 search controller accepts start and enables issue; 4 first candidate accepted at P0;
    N+3 last accepted; N+3+(B-1) last visible at the final bank; +1 reducer registers final best
    and done; +1 core observes done (SEARCH_WAIT -> REDUCE); +1 core registers the best (REDUCE ->
    FINALIZE); +1 rsp_valid (FINALIZE -> RESPOND).  With B=23: D(N) = N + 29."""
    n = n_candidates
    ev = {"core_latch": CORE_LATCH, "core_cache": CORE_CACHE, "core_search_start": CORE_SEARCH_START,
          "controller_accept": CTRL_ACCEPT, "first_issue": FIRST_ISSUE, "last_issue": FIRST_ISSUE + n - 1,
          "last_visible": FIRST_ISSUE + n - 1 + (banks - 1)}
    ev["reducer_done"] = ev["last_visible"] + 1
    ev["core_reduce"] = ev["reducer_done"] + 1
    ev["core_finalize"] = ev["core_reduce"] + 1
    ev["rsp_valid"] = ev["core_finalize"] + 1
    ev["decision_cycles"] = ev["rsp_valid"]
    # RESPOND -> IDLE at the edge after rsp_valid when rsp_ready is high; the next request is
    # accepted at the following edge (req_ready = state == IDLE)
    ev["next_accept_with_immediate_consumption"] = ev["rsp_valid"] + 2
    return ev


def formula(n_candidates: int, banks: int = BANKS) -> int:
    return n_candidates + banks + 6


def request_interval(n_candidates: int, banks: int = BANKS) -> int:
    return decision_latency(n_candidates, banks)["next_accept_with_immediate_consumption"]


def simulate_search(n_candidates: int, banks: int = BANKS) -> dict:
    """Drive the abstract pipe from the controller schedule and count the reducer's retirements."""
    p = Pipe(banks)
    retired = 0
    edge = 0
    done_edge = None
    best_published_edge = None
    while done_edge is None and edge < 10000:
        s_valid = FIRST_ISSUE <= edge < FIRST_ISSUE + n_candidates   # issue enabled from edge 4
        res = p.step(s_valid, edge - FIRST_ISSUE if s_valid else None, True)
        if res["transferred"] is not None:
            retired += 1
            if retired == n_candidates:
                done_edge = edge              # the consuming edge registers the final best and done
                best_published_edge = done_edge
        edge += 1
    rsp_edge = done_edge + 3                  # core: observe done, register best, rsp_valid
    return {"issued": len(p.accepted), "retired": retired, "reducer_done_edge": done_edge,
            "best_published_edge": best_published_edge, "rsp_valid_edge": rsp_edge, "formula": formula(n_candidates, banks)}


if __name__ == "__main__":
    s = stream(64)
    print("visible", set(s["visible_latency"].values()), "transfer", set(s["transfer_latency"].values()), "spacings", set(s["accept_spacings"]))
    for n in (9, 17, 34):
        print(n, decision_latency(n)["decision_cycles"], simulate_search(n)["rsp_valid_edge"], "interval", request_interval(n))
