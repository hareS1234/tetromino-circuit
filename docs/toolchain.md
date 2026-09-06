# Toolchain record

Two files describe the toolchain and they have different roles:

* `toolchains/oss_cad_suite.lock.json` (schema `toolchain-lock-v2`) holds the **expected inputs**:
  the pinned OSS CAD Suite release, one archive entry per asset family with its SHA-256, the
  `uname -s`/`uname -m` → family map, the required executables, the minimum Verilator version, the
  supported Python versions and the pinned pip. `scripts/bootstrap.sh` reads it and never writes to
  it except during explicit enrollment (below).
* `results/host/<OS>-<arch>.json` (schema `host-observation-v1`) holds the **observed machine
  facts** written by every bootstrap run: the archive hash that was actually verified, the tool
  version strings, the compiler, the Python build and the OS release. Observations are evidence;
  they never feed back into the lock.
* `toolchain.lock.json` at the repository root is the v1 record (Linux x86-64 only) and is kept
  unchanged for the historical E00–E19 results; `make doctor` reports it and does not enforce it.

| Item | Value |
|---|---|
| OSS CAD Suite release | 2026-09-04 (`https://github.com/YosysHQ/oss-cad-suite-build/releases/download/2026-09-04/<asset>`; 741 MB download, ~2.1 GB extracted on Linux x64) |
| Verilator / Yosys / nextpnr-ecp5 (Linux x64) | 5.051 devel rev v5.050-309-g228635918 / 0.68+182 (git 0bf55a858) / 0.11.1-19-g8dbcee5c |
| Verilator minimum | 5.036 (cocotb 2.0.1) |
| Python | 3.11 or 3.12 (venv; `requirements.lock` resolved on 3.11; pip pinned to 26.2.1) |
| cocotb | 2.0.1 |
| FPGA target | ECP5 LFE5U-85F, CABGA381, speed grade 6, 50 MHz constraint (v2 sweeps 50–100 MHz) |

## Platform table

| `uname -s`-`uname -m` | Asset family | Archive | Status |
|---|---|---|---|
| Linux-x86_64 | linux-x64 | `oss-cad-suite-linux-x64-20260904.tgz` | verified: `8fb2384c…de44` (imported unchanged from v1; results/host/Linux-x86_64.json) |
| Linux-aarch64, Linux-arm64 | linux-arm64 | `oss-cad-suite-linux-arm64-20260904.tgz` | unenrolled |
| Darwin-x86_64 (Intel Mac) | darwin-x64 | `oss-cad-suite-darwin-x64-20260904.tgz` | unenrolled |
| Darwin-arm64 (Apple silicon) | darwin-arm64 | `oss-cad-suite-darwin-arm64-20260904.tgz` | verified (enrolled on the maintainer's Mac, U20) |

The family is chosen from the real `uname` output (override with `TETROMINO_PLATFORM` for tests
only); owning a Mac does not decide between Intel and Apple silicon. A download is compared only
with its own family's entry. An unenrolled family fails with an enrollment hint; the Linux hash is
never used for another platform and hash checking is never disabled.

## Enrolling a new platform

1. On that machine run `bash scripts/bootstrap.sh --enroll`. It downloads the exact pinned
   official asset for the detected family (`.part` file, atomic rename, direct release-asset URL,
   no GitHub API), records the observed SHA-256 into the family's lock entry with status
   `enrolled-unreviewed`, then runs the normal validation, extraction, execution check and host
   observation.
2. Review the recorded hash (compare it with the checksum published for the release asset if
   available), change the status to `verified`, and commit the lock together with
   `results/host/<platform>.json`.
3. Every later bootstrap on that family verifies against the committed hash.

macOS: the bootstrap removes `com.apple.quarantine` from the archive only when the attribute is
present. If `yosys -V` still fails, it prints the suite's `./activate` remedy instead of fiddling
with anything outside `.tools/`. Enrollment and doctor now pass on the Apple-silicon Mac; U20 stays
blocked until that committed lock is exercised from a clean clone and the demo is inspected.

## Checks

`make doctor` (`tools/doctor.py --profile full`) verifies that `verilator`, `yosys` and
`nextpnr-ecp5` on PATH come from `.tools/oss-cad-suite/bin`, that Verilator meets the lock's
minimum, that the installed suite's `.bootstrap-sha256`/`.bootstrap-asset` markers match this
platform's lock entry, and that this host's observation exists. `make test-bootstrap` runs
`tests/unit/test_bootstrap.py`: mocked platforms with a fake archive cover matching hash, wrong
hash, unsupported platform, Mac-vs-Linux hash isolation, enrollment, missing compiler, interrupted
download, idempotent reinstall, asset/release consistency, the doctor checks above, and the cocotb
runner from an out-of-tree working directory.

`scripts/fresh_clone_check.sh` reproduces from a clean clone (`REUSE_ARCHIVE=1` seeds only the
downloaded archive; hash verification, extraction and every check still run).
