#!/usr/bin/env bash
# Idempotent, platform-specific bootstrap: pinned OSS CAD Suite under .tools/, Python venv under .venv/.
#
#   bash scripts/bootstrap.sh            # normal: expects this platform's asset hash in toolchains/oss_cad_suite.lock.json
#   bash scripts/bootstrap.sh --enroll   # first run on a new platform: download the pinned asset, record its hash
#                                        #   in the lock for review/commit, then validate as usual
#
# Expected inputs live in toolchains/oss_cad_suite.lock.json (one hash per asset family).  Observed
# machine facts are written to results/host/<os>-<arch>.json and never into the lock.  The v1
# toolchain.lock.json is historical and is not modified.  Set TETROMINO_PLATFORM=Linux-x86_64 etc.
# to override detection for tests; TETROMINO_SKIP_PYTHON=1 skips the venv; TETROMINO_LOCK, TETROMINO_TOOLS_DIR,
# TETROMINO_HOST_DIR and TETROMINO_ARCHIVE_SOURCE redirect the lock, install dir, observations and download.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
LOCK="${TETROMINO_LOCK:-$ROOT/toolchains/oss_cad_suite.lock.json}"
TOOLS_DIR="${TETROMINO_TOOLS_DIR:-$ROOT/.tools}"
SUITE_DIR="$TOOLS_DIR/oss-cad-suite"
HOST_DIR="${TETROMINO_HOST_DIR:-$ROOT/results/host}"
PYTHON_BIN="${PYTHON:-python3}"
ENROLL=0
for a in "$@"; do
  case "$a" in
    --enroll) ENROLL=1 ;;
    -h|--help) sed -n 2,12p "$0"; exit 0 ;;
    *) echo "[bootstrap] unknown option $a" >&2; exit 2 ;;
  esac
done

log() { printf '[bootstrap] %s\n' "$*"; }
fail() { printf '[bootstrap] ERROR: %s\n' "$*" >&2; exit 1; }
sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
lockq() { "$PYTHON_BIN" - "$LOCK" "$@" <<'EOF'
import json, sys
doc = json.load(open(sys.argv[1]))
node = doc
for key in sys.argv[2:]:
    node = node[key] if isinstance(node, dict) and key in node else None
    if node is None:
        break
print("" if node is None else (node if isinstance(node, str) else json.dumps(node)))
EOF
}

[ -f "$LOCK" ] || fail "missing $LOCK"
command -v "$PYTHON_BIN" >/dev/null || fail "python3 not found"

# ---- 1. platform -> asset family ----------------------------------------------
PLATFORM="${TETROMINO_PLATFORM:-$(uname -s)-$(uname -m)}"
FAMILY="$(lockq platform_map "$PLATFORM")"
[ -n "$FAMILY" ] || fail "unsupported platform '$PLATFORM' (known: $(lockq platform_map | tr -d '\n'))"
RELEASE="$(lockq release)"
COMPACT="${RELEASE//-/}"
ASSET="$(lockq assets "$FAMILY" asset)"
EXPECTED="$(lockq assets "$FAMILY" sha256)"
STATUS="$(lockq assets "$FAMILY" status)"
[ "$ASSET" = "oss-cad-suite-${FAMILY}-${COMPACT}.tgz" ] || fail "lock asset name '$ASSET' does not match release $RELEASE / family $FAMILY"
ASSET_URL="https://github.com/YosysHQ/oss-cad-suite-build/releases/download/${RELEASE}/${ASSET}"
log "platform $PLATFORM -> $FAMILY, release $RELEASE, asset $ASSET (${STATUS:-?})"

# ---- 2. host prerequisites ------------------------------------------------------
PYVER="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
case "$(lockq python supported)" in *"\"$PYVER\""*) ;; *) fail "Python $(lockq python supported) required, found $PYVER" ;; esac
command -v make >/dev/null || fail "GNU make not found"
command -v git >/dev/null || fail "git not found"
command -v c++ >/dev/null || fail "C++ compiler not found (install build-essential or Xcode command-line tools)"
command -v curl >/dev/null || fail "curl not found"
command -v tar >/dev/null || fail "tar not found"
mkdir -p "$TOOLS_DIR" "$HOST_DIR" build results/evidence

# ---- 3. archive: download (.part + atomic rename), hash, enroll or verify --------
if [ -n "$EXPECTED" ] && [ -x "$SUITE_DIR/bin/yosys" ] && [ -f "$SUITE_DIR/.bootstrap-sha256" ] \
   && [ "$(cat "$SUITE_DIR/.bootstrap-sha256")" = "$EXPECTED" ] && [ "$(cat "$SUITE_DIR/.bootstrap-asset" 2>/dev/null)" = "$ASSET" ]; then
  log "OSS CAD Suite $ASSET already installed with the locked hash"
else
  if [ ! -f "$TOOLS_DIR/$ASSET" ]; then
    if [ -n "${TETROMINO_ARCHIVE_SOURCE:-}" ]; then
      log "copying archive from TETROMINO_ARCHIVE_SOURCE"
      cp "$TETROMINO_ARCHIVE_SOURCE" "$TOOLS_DIR/$ASSET.part" && mv "$TOOLS_DIR/$ASSET.part" "$TOOLS_DIR/$ASSET"
    else
      log "downloading $ASSET_URL"
      rm -f "$TOOLS_DIR/$ASSET.part"
      ok=0
      for attempt in 1 2 3; do
        if curl -fSL --retry 3 --max-time 3600 -o "$TOOLS_DIR/$ASSET.part" "$ASSET_URL"; then ok=1; break; fi
        log "download attempt $attempt failed"; sleep 5
      done
      [ "$ok" = 1 ] || { rm -f "$TOOLS_DIR/$ASSET.part"; fail "could not download $ASSET_URL (release assets must be reachable; the GitHub API is not used)"; }
      mv "$TOOLS_DIR/$ASSET.part" "$TOOLS_DIR/$ASSET"
    fi
  fi
  SHA="$(sha256 "$TOOLS_DIR/$ASSET")"
  if [ -z "$EXPECTED" ]; then
    if [ "$ENROLL" = 1 ]; then
      log "enrolling $FAMILY: recording sha256 $SHA in $LOCK (review and commit it)"
      "$PYTHON_BIN" - "$LOCK" "$FAMILY" "$SHA" "$PLATFORM" <<'EOF'
import json, sys, datetime
lock, family, sha, platform = sys.argv[1:]
doc = json.load(open(lock))
doc["assets"][family].update({"sha256": sha, "status": "enrolled-unreviewed",
    "recorded": f"enrolled on {platform} at {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"})
open(lock, "w").write(json.dumps(doc, indent=1) + "\n")
EOF
      EXPECTED="$SHA"
    else
      fail "no recorded hash for $FAMILY in $LOCK; run 'bash scripts/bootstrap.sh --enroll' on this platform to record the pinned asset's hash (the Linux hash is never used for another platform)"
    fi
  fi
  [ "$SHA" = "$EXPECTED" ] || fail "archive sha256 $SHA does not match the $FAMILY entry ($EXPECTED); delete $TOOLS_DIR/$ASSET and retry"
  case "$PLATFORM" in Darwin-*)
    if command -v xattr >/dev/null && xattr -p com.apple.quarantine "$TOOLS_DIR/$ASSET" >/dev/null 2>&1; then
      log "quarantine attribute present on the archive; applying the documented remedy (xattr -d com.apple.quarantine)"
      xattr -d com.apple.quarantine "$TOOLS_DIR/$ASSET"
    fi ;;
  esac
  log "extracting $ASSET (sha256 $SHA)"
  rm -rf "$SUITE_DIR.extracting"; mkdir -p "$SUITE_DIR.extracting"
  tar -xzf "$TOOLS_DIR/$ASSET" -C "$SUITE_DIR.extracting"
  [ -d "$SUITE_DIR.extracting/oss-cad-suite" ] || fail "archive layout unexpected: no oss-cad-suite/ directory"
  rm -rf "$SUITE_DIR"; mv "$SUITE_DIR.extracting/oss-cad-suite" "$SUITE_DIR"; rmdir "$SUITE_DIR.extracting"
  echo "$ASSET" > "$SUITE_DIR/.bootstrap-asset"
  echo "$SHA" > "$SUITE_DIR/.bootstrap-sha256"
fi
for exe in $(lockq required_executables | tr -d '[]",'); do
  [ -x "$SUITE_DIR/bin/$exe" ] || fail "suite is missing $exe"
done
if ! "$SUITE_DIR/bin/yosys" -V >/dev/null 2>"$TOOLS_DIR/yosys-check.err"; then
  case "$PLATFORM" in Darwin-*)
    log "yosys failed to execute; if the message below is a Gatekeeper/quarantine error, run: cd $SUITE_DIR && ./activate"
    cat "$TOOLS_DIR/yosys-check.err" >&2 ;;
  esac
  fail "installed suite does not execute (see $TOOLS_DIR/yosys-check.err)"
fi

# ---- 4. Python environment (pinned installer, locked requirements) -------------
if [ "${TETROMINO_SKIP_PYTHON:-0}" != 1 ]; then
  if [ ! -x "$ROOT/.venv/bin/python" ]; then
    log "creating .venv with $PYTHON_BIN"
    "$PYTHON_BIN" -m venv "$ROOT/.venv"
  fi
  VPY="$ROOT/.venv/bin/python"
  PIP_PIN="$(lockq python pip)"
  "$VPY" -m pip install --quiet "pip==$PIP_PIN" >/dev/null
  [ -f "$ROOT/requirements.lock" ] || fail "requirements.lock missing; resolve it deliberately and commit it"
  log "installing pinned requirements.lock"
  "$VPY" -m pip install --quiet -r "$ROOT/requirements.lock"
  "$VPY" -m pip install --quiet --no-deps --no-build-isolation -e "$ROOT"
fi

# ---- 5. observed host facts (never the lock) ------------------------------------
"$PYTHON_BIN" - "$HOST_DIR" "$SUITE_DIR" "$ASSET" "$ASSET_URL" "$RELEASE" "$PLATFORM" "$FAMILY" "$PYVER" "$EXPECTED" <<'EOF'
import json, subprocess, sys, pathlib, datetime, platform as pf
host_dir, suite, asset, url, release, plat, family, pyver, expected = sys.argv[1:]
def ver(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except Exception as exc:  # noqa: BLE001
        return f"unavailable: {exc}"
b = pathlib.Path(suite) / "bin"
doc = {
    "schema": "host-observation-v1", "platform": plat, "asset_family": family, "release": release, "asset": asset,
    "asset_url": url, "archive_sha256_observed": (pathlib.Path(suite) / ".bootstrap-sha256").read_text().strip(),
    "archive_sha256_expected": expected, "python": pyver, "python_full": sys.version.split()[0],
    "os_release": pf.platform(), "cxx": ver(["c++", "--version"]),
    "verilator": ver([str(b / "verilator"), "--version"]), "yosys": ver([str(b / "yosys"), "-V"]),
    "nextpnr_ecp5": ver([str(b / "nextpnr-ecp5"), "--version"]),
    "recorded_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
out = pathlib.Path(host_dir) / f"{plat}.json"
out.write_text(json.dumps(doc, indent=1) + "\n")
print("[bootstrap] toolchain:", doc["verilator"], "|", doc["yosys"], "|", doc["nextpnr_ecp5"])
print("[bootstrap] host observation ->", out)
EOF
log "done. Use: bash scripts/env.sh <command>"
