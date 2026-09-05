#!/usr/bin/env bash
# Fresh-clone reproduction (manual 8.5): clone into a temporary directory, bootstrap from the
# committed locks, run the software demo, one RTL test, and rebuild a plot from committed results.
# Set REUSE_ARCHIVE=1 to seed the clone with the already-downloaded suite archive (skips only the
# 740 MB download; extraction, venv creation and every check still run from scratch).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d /tmp/tetromino-fresh.XXXXXX)"
echo "[fresh] cloning into $TMP"
git clone -q "$ROOT" "$TMP/tetromino-circuit"
cd "$TMP/tetromino-circuit"
if [ "${REUSE_ARCHIVE:-0}" = "1" ]; then
  mkdir -p .tools
  cp "$ROOT"/.tools/oss-cad-suite-*.tgz .tools/
fi
bash scripts/bootstrap.sh
bash scripts/env.sh python tools/doctor.py --profile full
make test-python
make smoke
make test-shapes
make demo-python
make plots
bash scripts/env.sh python tools/write_report.py --check
if grep -rn --include='*.py' --include='*.sh' --include=Makefile --exclude=check_release.py --exclude=fresh_clone_check.sh -E "/home/[a-z]+/|/Users/[a-z]+/" tools scripts tb model Makefile; then
  echo "[fresh] ERROR: absolute paths leaked"; exit 1
fi
echo "[fresh] OK: software demo, RTL smoke/ROM tests and plot regeneration passed in $TMP/tetromino-circuit"
