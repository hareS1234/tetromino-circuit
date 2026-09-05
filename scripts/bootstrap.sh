#!/usr/bin/env bash
# Idempotent environment bootstrap: pinned OSS CAD Suite under .tools/, Python venv under .venv/.
# Safe to re-run; reuses matching installations and never deletes unrelated files.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SUITE_DATE="${OSS_CAD_SUITE_DATE:-2026-09-04}"
SUITE_TAG="$SUITE_DATE"
SUITE_COMPACT="${SUITE_DATE//-/}"
TOOLS_DIR="$ROOT/.tools"
SUITE_DIR="$TOOLS_DIR/oss-cad-suite"
LOCK="$ROOT/toolchain.lock.json"
PYTHON_BIN="${PYTHON:-python3}"

log() { printf '[bootstrap] %s\n' "$*"; }
fail() { printf '[bootstrap] ERROR: %s\n' "$*" >&2; exit 1; }

# ---- 1. host facts ---------------------------------------------------------
OS="$(uname -s)"; ARCH="$(uname -m)"
case "$OS-$ARCH" in
  Linux-x86_64)  ASSET_FAMILY="linux-x64" ;;
  Linux-aarch64) ASSET_FAMILY="linux-arm64" ;;
  Darwin-x86_64) ASSET_FAMILY="darwin-x64" ;;
  Darwin-arm64)  ASSET_FAMILY="darwin-arm64" ;;
  *) fail "unsupported platform $OS-$ARCH" ;;
esac
command -v "$PYTHON_BIN" >/dev/null || fail "python3 not found"
PYVER="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
case "$PYVER" in 3.11|3.12) ;; *) fail "Python 3.11 or 3.12 required, found $PYVER" ;; esac
command -v make >/dev/null || fail "GNU make not found"
command -v git >/dev/null || fail "git not found"
command -v c++ >/dev/null || fail "C++ compiler not found (install build-essential or Xcode CLT)"
log "host: $OS $ARCH, python $PYVER, $(nproc 2>/dev/null || sysctl -n hw.ncpu) cpus"

# ---- 2. directories --------------------------------------------------------
mkdir -p "$TOOLS_DIR" model tests/unit tests/fixtures tb rtl/learning rtl/generated tools scripts sim docs \
  assets benchmarks/streams benchmarks/states results/evidence build .github/workflows

# ---- 3. OSS CAD Suite ------------------------------------------------------
ASSET="oss-cad-suite-${ASSET_FAMILY}-${SUITE_COMPACT}.tgz"
ASSET_URL="https://github.com/YosysHQ/oss-cad-suite-build/releases/download/${SUITE_TAG}/${ASSET}"
if [ -x "$SUITE_DIR/bin/yosys" ] && [ -f "$SUITE_DIR/.bootstrap-asset" ] && [ "$(cat "$SUITE_DIR/.bootstrap-asset")" = "$ASSET" ]; then
  log "OSS CAD Suite $ASSET already installed"
else
  if [ ! -f "$TOOLS_DIR/$ASSET" ]; then
    log "downloading $ASSET_URL"
    for attempt in 1 2 3; do
      if curl -fSL --retry 3 --max-time 3600 -o "$TOOLS_DIR/$ASSET.part" "$ASSET_URL"; then
        mv "$TOOLS_DIR/$ASSET.part" "$TOOLS_DIR/$ASSET"; break
      fi
      log "download attempt $attempt failed"; sleep 5
      [ "$attempt" = 3 ] && fail "could not download $ASSET_URL (GitHub release assets must be reachable; the GitHub API is not required)"
    done
  fi
  SHA="$(sha256sum "$TOOLS_DIR/$ASSET" 2>/dev/null | cut -d' ' -f1 || shasum -a 256 "$TOOLS_DIR/$ASSET" | cut -d' ' -f1)"
  if [ -f "$LOCK" ]; then
    EXPECTED="$("$PYTHON_BIN" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("archive_sha256",""))' "$LOCK")"
    if [ -n "$EXPECTED" ] && [ "$EXPECTED" != "$SHA" ]; then
      fail "archive sha256 $SHA does not match toolchain.lock.json ($EXPECTED)"
    fi
  fi
  log "extracting $ASSET (sha256 $SHA)"
  rm -rf "$SUITE_DIR.extracting"; mkdir -p "$SUITE_DIR.extracting"
  tar -xzf "$TOOLS_DIR/$ASSET" -C "$SUITE_DIR.extracting"
  rm -rf "$SUITE_DIR"; mv "$SUITE_DIR.extracting/oss-cad-suite" "$SUITE_DIR"; rmdir "$SUITE_DIR.extracting"
  echo "$ASSET" > "$SUITE_DIR/.bootstrap-asset"
  echo "$SHA" > "$SUITE_DIR/.bootstrap-sha256"
fi
for exe in yosys nextpnr-ecp5 verilator; do
  [ -x "$SUITE_DIR/bin/$exe" ] || fail "suite is missing $exe"
done

# ---- 4. Python environment -------------------------------------------------
if [ ! -x "$ROOT/.venv/bin/python" ]; then
  log "creating .venv with $PYTHON_BIN"
  "$PYTHON_BIN" -m venv "$ROOT/.venv"
fi
VPY="$ROOT/.venv/bin/python"
"$VPY" -m pip install --quiet --upgrade pip >/dev/null
if [ -f "$ROOT/requirements.lock" ]; then
  log "installing pinned requirements.lock"
  "$VPY" -m pip install --quiet -r "$ROOT/requirements.lock"
else
  log "resolving requirements.in for the first time (writes requirements.lock)"
  "$VPY" -m pip install --quiet -r "$ROOT/requirements.in"
  "$VPY" -m pip freeze --exclude-editable | grep -v '^tetromino-circuit' > "$ROOT/requirements.lock"
fi
"$VPY" -m pip install --quiet --no-deps --no-build-isolation -e "$ROOT"

# ---- 5. record the toolchain -------------------------------------------------
"$VPY" - "$LOCK" "$SUITE_DIR" "$ASSET" "$ASSET_URL" "$SUITE_DATE" "$OS" "$ARCH" "$PYVER" <<'EOF'
import json, subprocess, sys, pathlib, datetime
lock, suite, asset, url, date, os_, arch, pyver = sys.argv[1:]
def ver(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except Exception as exc:  # noqa: BLE001
        return f"unavailable: {exc}"
b = pathlib.Path(suite) / "bin"
doc = {
    "suite_release": date, "asset": asset, "asset_url": url,
    "archive_sha256": (pathlib.Path(suite) / ".bootstrap-sha256").read_text().strip(),
    "os": os_, "arch": arch, "python": pyver,
    "verilator": ver([str(b / "verilator"), "--version"]),
    "yosys": ver([str(b / "yosys"), "-V"]),
    "nextpnr_ecp5": ver([str(b / "nextpnr-ecp5"), "--version"]),
    "recorded_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "note": "archive_sha256 is a locally computed download hash (reproducibility record, not proof of origin)",
}
pathlib.Path(lock).write_text(json.dumps(doc, indent=1) + "\n")
print("[bootstrap] toolchain:", doc["verilator"], "|", doc["yosys"], "|", doc["nextpnr_ecp5"])
EOF
log "done. Use: bash scripts/env.sh <command>"
