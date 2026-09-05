#!/usr/bin/env bash
# Fresh-clone reproduction (v1 manual 8.5, upgrade guide U20): clone the committed state into a
# temporary directory, bootstrap from the committed locks, and run the release's reproduction steps
# from scratch: doctor, the Python tests, the smoke flow, directed RTL tests, the native A2 core
# subset, the A2 trace/demo regeneration, the viewer and report checks.  Every step's exit code and
# elapsed time, the host facts (OS, CPU, Python, compiler, tool versions) and the clone's commit are
# written to results/evidence/U20/fresh_clone_<family>.json in the *source* repository (schema
# fresh-clone-check-v2); tools/check_release_v2.py requires that record for an "executed" platform.
#
#   REUSE_ARCHIVE=1  seed the clone with the already-downloaded suite archive (skips only the download;
#                    extraction, venv creation and every check still run from scratch)
#   FRESH_COUNT=50   number of corpus states for the native A2 subset (default 50)
#   FRESH_KEEP=1     keep the temporary clone for inspection
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/tetromino-fresh.XXXXXX")"
COUNT="${FRESH_COUNT:-50}"
FAMILY="$(python3 - "$ROOT" <<'EOF'
import json, platform, sys
lock = json.load(open(sys.argv[1] + "/toolchains/oss_cad_suite.lock.json"))
print(lock["platform_map"].get(f"{platform.system()}-{platform.machine()}", "unsupported"))
EOF
)"
OUT="${FRESH_OUT:-$ROOT/results/evidence/U20/fresh_clone_${FAMILY}.json}"
STEPS="$TMP/steps.jsonl"
: > "$STEPS"
echo "[fresh] platform family $FAMILY; cloning into $TMP"
git clone -q "$ROOT" "$TMP/tetromino-circuit"
cd "$TMP/tetromino-circuit"
CLONE_COMMIT="$(git rev-parse HEAD)"
if [ "${REUSE_ARCHIVE:-0}" = "1" ]; then
  mkdir -p .tools
  cp "$ROOT"/.tools/oss-cad-suite-*.tgz .tools/
fi

step() {   # step <name> <command...>: run, record exit code + elapsed, stop on failure (the record is still written)
  local name="$1"; shift
  local t0 t1 rc
  t0=$(date +%s)
  echo "[fresh] step $name: $*"
  set +e
  "$@" > "$TMP/$name.log" 2>&1
  rc=$?
  set -e
  t1=$(date +%s)
  tail -n 3 "$TMP/$name.log" | sed 's/^/[fresh]   /'
  python3 - "$STEPS" "$name" "$rc" "$((t1 - t0))" "$*" <<'EOF'
import json, sys
with open(sys.argv[1], "a") as fh:
    fh.write(json.dumps({"name": sys.argv[2], "exit_code": int(sys.argv[3]), "elapsed_s": int(sys.argv[4]), "command": sys.argv[5]}) + "\n")
EOF
  if [ "$rc" -ne 0 ]; then
    echo "[fresh] FAILED at step $name (exit $rc); log: $TMP/$name.log"
    write_record 0
    exit "$rc"
  fi
}

write_record() {   # write_record <ok>
  python3 - "$OUT" "$STEPS" "$1" "$CLONE_COMMIT" "$FAMILY" "$TMP/tetromino-circuit" <<'EOF'
import datetime as dt, json, pathlib, platform, subprocess, sys
out, steps_path, ok, commit, family, clone = sys.argv[1:7]
steps = [json.loads(l) for l in open(steps_path) if l.strip()]
host_dir = pathlib.Path(clone) / "results" / "host"
obs = None
for p in sorted(host_dir.glob("*.json")):
    d = json.loads(p.read_text())
    if d.get("schema") == "host-observation-v1" and d.get("asset_family") == family:
        obs = d
def ver(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=clone)
        return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr).strip() else None
    except OSError:
        return None
cpu = platform.processor() or platform.machine()
try:
    if platform.system() == "Linux":
        for line in open("/proc/cpuinfo"):
            if line.lower().startswith("model name"):
                cpu = line.split(":", 1)[1].strip(); break
    elif platform.system() == "Darwin":
        cpu = ver(["sysctl", "-n", "machdep.cpu.brand_string"]) or cpu
except OSError:
    pass
host = {"os": platform.platform(), "system": platform.system(), "machine": platform.machine(), "cpu": cpu,
        "python": (obs or {}).get("python_full") or platform.python_version(),
        "compiler": (obs or {}).get("cxx") or ver(["c++", "--version"]),
        "tools": {k: (obs or {}).get(k) for k in ("yosys", "nextpnr_ecp5", "verilator")} if obs else None,
        "host_observation": obs}
rec = {"schema": "fresh-clone-check-v2", "family": family, "ok": bool(int(ok)) and all(s["exit_code"] == 0 for s in steps),
       "clone_commit": commit, "clone_dir": clone, "recorded_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
       "host": host, "steps": steps}
pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
pathlib.Path(out).write_text(json.dumps(rec, indent=1) + "\n")
print(f"CHECK fresh_clone {sum(1 for s in steps if s['exit_code'] == 0)}/{len(steps)}")
print("[fresh] record ->", out)
EOF
}

step bootstrap bash scripts/bootstrap.sh
step doctor bash scripts/env.sh python tools/doctor.py --profile full
step test-python make test-python
step smoke make smoke
step test-shapes make test-shapes
step demo-python make demo-python
step plots make plots
step report-v1 bash scripts/env.sh python tools/write_report.py --check
step check-a2-spec make check-a2-spec
step a2-core-subset make test-core ARCH=2 BOARD_REPR=1 COUNT="$COUNT" DRIVER=native
step trace-a2-demo make trace-a2-demo
step check-trace make check-trace
step render-a2-demo make render-a2-demo
step check-viewer make check-viewer
step report-v2 bash scripts/env.sh python tools/write_report_v2.py --check
step check-links bash scripts/env.sh python tools/check_links.py
step check-claims bash scripts/env.sh python tools/check_claims.py
step trace-identity python3 - <<'EOF'
import json
a = json.load(open("results/traces/a2_normal_search.json"))
cyc = a["requests"][0]["response"]["cycles"]
assert cyc == 63, f"regenerated normal-search trace responds in {cyc} cycles, expected 63"
print("regenerated trace: response in", cyc, "cycles")
EOF
step path-leaks bash -c '! grep -rn --include="*.py" --include="*.sh" --include=Makefile --exclude=check_release.py --exclude=fresh_clone_check.sh -E "/home/[a-z]+/|/Users/[a-z]+/" tools scripts tb model Makefile'
write_record 1
echo "[fresh] OK: bootstrap, tests, smoke, A2 subset, demo regeneration and report checks passed in $TMP/tetromino-circuit"
if [ "${FRESH_KEEP:-0}" != "1" ]; then rm -rf "$TMP"; fi
