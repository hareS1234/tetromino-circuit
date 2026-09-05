#!/usr/bin/env bash
# Run a command with the project's venv and OSS CAD Suite on PATH, from the repository root.
#   bash scripts/env.sh python tools/doctor.py --profile full
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/${TETROMINO_VENV:-.venv}"
export PATH="$VENV/bin:$ROOT/.tools/oss-cad-suite/bin:$PATH"
export VIRTUAL_ENV="$VENV"
export TETROMINO_ROOT="$ROOT"
# Verilator inside the suite needs its own share directory; the suite's wrapper sets it, keep any user override.
cd "$ROOT"
[ "$#" -gt 0 ] || { echo "usage: scripts/env.sh COMMAND [ARG ...]" >&2; exit 2; }
exec "$@"
