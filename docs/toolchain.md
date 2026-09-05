# Toolchain record

Pinned in `toolchain.lock.json` by `scripts/bootstrap.sh`; `make doctor` verifies that
the executables on PATH come from the pinned suite and that Verilator is new enough
for cocotb 2.0.1 (>= 5.036).

| Item | Value |
|---|---|
| OSS CAD Suite release | 2026-09-04 (`oss-cad-suite-linux-x64-20260904.tgz`, 741 MB download, ~2.1 GB extracted) |
| Archive SHA-256 | 8fb2384c2f88126f8936fc8f680ed2ebdf0ce440a7457c8f5a21c5c6e3e2de44 (locally computed) |
| Verilator | 5.051 devel rev v5.050-309-g228635918 |
| Yosys | 0.68+182 (git 0bf55a858) |
| nextpnr-ecp5 | 0.11.1-19-g8dbcee5c |
| Python | 3.11 (venv; `requirements.lock` resolved on 3.11) |
| cocotb | 2.0.1 |
| Host used for the recorded results | Ubuntu 24.04, x86-64, 2 vCPU, 7 GB RAM |
| FPGA target | ECP5 LFE5U-85F, CABGA381, speed grade 6, 50 MHz constraint |

Notes: the GitHub *release asset* URL was reachable from the build environment while
the GitHub REST API was not; `scripts/bootstrap.sh` therefore downloads the asset
directly and never queries the API. The bootstrap is idempotent: matching installations
and lock files are reused; the archive hash must match `toolchain.lock.json` once recorded.
