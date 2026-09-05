"""Single hardware/policy configuration validator shared by every build and run tool.

Two levels of support:

* SUPPORTED — implemented and verified configurations (the nine v1 configurations, extended by
  later upgrade jobs once their gates pass).  Every build, simulation, synthesis, routing and
  benchmark tool accepts only these.
* DECLARED — configurations whose interface and identity are frozen by a specification but whose
  sources do not exist or have not passed their gates yet (A2 after U04).  They have an id and
  parameters so manifests and documents can name them, but `validate()` rejects them with an
  explicit "declared, not verified" error; no tool may return a canned result for them.

Configuration ids are generated here only (`Config.id`); the Makefile asks this module.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, asdict

ARCH_NAMES = {0: "a0", 1: "a1", 2: "a2"}
REPR_NAMES = {0: "bitmap", 1: "cache"}


@dataclass(frozen=True)
class Config:
    arch: int = 0
    board_repr: int = 0
    lanes: int = 1
    depth: int = 1
    precision: int = 0

    @property
    def id(self) -> str:
        return f"{ARCH_NAMES[self.arch]}-{REPR_NAMES[self.board_repr]}-d{self.depth}-p{self.precision}-l{self.lanes}"

    def params(self) -> dict:
        return {"ARCH": self.arch, "BOARD_REPR": self.board_repr, "LANES": self.lanes,
                "DEPTH": self.depth, "PRECISION": self.precision}

    def as_dict(self) -> dict:
        return asdict(self)


# The nine verified v1 hardware configurations (manual E16/7E.1), the A2 candidate pipeline
# (docs/design_a2.md; declared in U04, promoted in U10) and the four-lane A1 replication (U13).
SUPPORTED = (
    Config(0, 0, 1, 1, 0),
    Config(1, 0, 1, 1, 0),
    Config(1, 1, 1, 1, 0),
    Config(1, 1, 1, 1, 1),
    Config(1, 1, 1, 1, 2),
    Config(1, 1, 1, 1, 3),
    Config(1, 1, 1, 1, 4),
    Config(1, 1, 1, 2, 0),
    Config(1, 1, 2, 1, 0),
    Config(2, 1, 1, 1, 0),
    Config(1, 1, 4, 1, 0),   # four-lane A1 (U13)
)
SUPPORTED_IDS = {c.id: c for c in SUPPORTED}
V1_SUPPORTED_IDS = {c.id for c in SUPPORTED[:9]}   # the frozen v1 matrix

# Declared by a specification but not yet verified (empty since U10; four-lane A1 is added by U13
# directly as verified).  Every other A2 combination (bitmap, depth two, several lanes, approximate
# profiles) is unsupported outright.
DECLARED = ()
DECLARED_IDS = {c.id: c for c in DECLARED}


def status(cfg: Config) -> str:
    if cfg in SUPPORTED:
        return "verified"
    if cfg in DECLARED:
        return "declared"
    return "unsupported"


def validate(cfg: Config) -> Config:
    if cfg.arch not in ARCH_NAMES or cfg.board_repr not in REPR_NAMES:
        raise ValueError(f"unknown ARCH/BOARD_REPR in {cfg}")
    if cfg in SUPPORTED:
        return cfg
    if cfg in DECLARED:
        raise ValueError(f"configuration {cfg.id} is declared (docs/design_a2.md) but not implemented/verified; "
                         "it cannot be built, simulated, synthesized or benchmarked until its upgrade job passes")
    if cfg.arch == 2:
        raise ValueError(f"configuration {cfg.id} is not supported: A2 is specified only as a2-cache-d1-p0-l1 "
                         "(cache representation, one lane, depth one, exact profile)")
    raise ValueError(f"configuration {cfg.id} is not implemented/verified; supported: "
                     + ", ".join(sorted(SUPPORTED_IDS)))


def from_args(args) -> Config:
    return validate(Config(int(args.arch), int(args.board_repr), int(args.lanes), int(args.depth), int(args.precision)))


def add_config_arguments(parser, defaults: Config = Config()):
    parser.add_argument("--arch", type=int, default=defaults.arch, help="0 serial A0, 1 fast A1, 2 pipelined candidate evaluator A2")
    parser.add_argument("--board-repr", dest="board_repr", type=int, default=defaults.board_repr,
                        help="0 bitmap only, 1 bitmap plus exact height cache")
    parser.add_argument("--lanes", type=int, default=defaults.lanes)
    parser.add_argument("--depth", type=int, default=defaults.depth)
    parser.add_argument("--precision", type=int, default=defaults.precision)


if __name__ == "__main__":
    # `python -m model.config ARCH BOARD_REPR LANES DEPTH PRECISION` prints the id (used by the Makefile)
    if len(sys.argv) == 6:
        cfg = Config(*(int(a) for a in sys.argv[1:]))
        print(cfg.id)
    elif len(sys.argv) == 2 and sys.argv[1] == "--list":
        for c in SUPPORTED:
            print(f"{c.id}\tverified")
        for c in DECLARED:
            print(f"{c.id}\tdeclared")
    else:
        raise SystemExit("usage: python -m model.config ARCH BOARD_REPR LANES DEPTH PRECISION | --list")
