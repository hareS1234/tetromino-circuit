"""Single hardware/policy configuration validator shared by every build and run tool."""
from __future__ import annotations

from dataclasses import dataclass, asdict

ARCH_NAMES = {0: "a0", 1: "a1"}
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


# The nine required hardware configurations (manual E16/7E.1).  Nothing else is
# accepted by build, simulation, synthesis, routing or benchmark tools.
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
)
SUPPORTED_IDS = {c.id: c for c in SUPPORTED}


def validate(cfg: Config) -> Config:
    if cfg.arch not in ARCH_NAMES or cfg.board_repr not in REPR_NAMES:
        raise ValueError(f"unknown ARCH/BOARD_REPR in {cfg}")
    if cfg not in SUPPORTED:
        raise ValueError(f"configuration {cfg.id} is not implemented/verified; supported: "
                         + ", ".join(sorted(SUPPORTED_IDS)))
    return cfg


def from_args(args) -> Config:
    return validate(Config(int(args.arch), int(args.board_repr), int(args.lanes), int(args.depth), int(args.precision)))


def add_config_arguments(parser, defaults: Config = Config()):
    parser.add_argument("--arch", type=int, default=defaults.arch, help="0 serial A0, 1 fast A1")
    parser.add_argument("--board-repr", dest="board_repr", type=int, default=defaults.board_repr,
                        help="0 bitmap only, 1 bitmap plus exact height cache")
    parser.add_argument("--lanes", type=int, default=defaults.lanes)
    parser.add_argument("--depth", type=int, default=defaults.depth)
    parser.add_argument("--precision", type=int, default=defaults.precision)
