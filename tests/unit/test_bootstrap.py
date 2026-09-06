"""Exercise the platform bootstrap with tiny fake CAD-suite archives."""
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BOOT = ROOT / "scripts" / "bootstrap.sh"
LOCK = json.loads((ROOT / "toolchains" / "oss_cad_suite.lock.json").read_text())


def fake_archive(tmp: Path, family: str) -> Path:
    """A tiny oss-cad-suite/ tarball whose executables print plausible versions."""
    name = f"oss-cad-suite-{family}-{LOCK['release'].replace('-', '')}.tgz"
    suite = tmp / "src" / "oss-cad-suite" / "bin"
    suite.mkdir(parents=True)
    versions = {"yosys": "Yosys 0.68+182 (fake)", "nextpnr-ecp5": '"nextpnr-ecp5" -- fake 0.11.1',
                "verilator": "Verilator 5.051 fake"}
    for exe, text in versions.items():
        p = suite / exe
        p.write_text(f"#!/bin/sh\necho '{text}'\n")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    path = tmp / name
    with tarfile.open(path, "w:gz") as tf:
        tf.add(tmp / "src" / "oss-cad-suite", arcname="oss-cad-suite")
    return path


def lock_with(tmp: Path, family: str, sha: str | None, status="verified") -> Path:
    doc = json.loads(json.dumps(LOCK))
    for fam in doc["assets"]:
        doc["assets"][fam]["sha256"] = None
        doc["assets"][fam]["status"] = "unenrolled"
    doc["assets"][family]["sha256"] = sha
    doc["assets"][family]["status"] = status
    p = tmp / "lock.json"
    p.write_text(json.dumps(doc, indent=1))
    return p


def run(tmp: Path, platform: str, lock: Path, archive: Path | None, extra_env=None, args=()):
    env = dict(os.environ)
    env.update({"TETROMINO_PLATFORM": platform, "TETROMINO_LOCK": str(lock), "TETROMINO_TOOLS_DIR": str(tmp / "tools"),
                "TETROMINO_HOST_DIR": str(tmp / "host"), "TETROMINO_SKIP_PYTHON": "1"})
    if archive is not None:
        env["TETROMINO_ARCHIVE_SOURCE"] = str(archive)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(["bash", str(BOOT), *args], cwd=ROOT, env=env, capture_output=True, text=True)


@pytest.fixture
def linux(tmp_path):
    arch = fake_archive(tmp_path, "linux-x64")
    sha = hashlib.sha256(arch.read_bytes()).hexdigest()
    return tmp_path, arch, sha


def test_matching_hash_installs_and_records_observation(linux):
    tmp, arch, sha = linux
    r = run(tmp, "Linux-x86_64", lock_with(tmp, "linux-x64", sha), arch)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp / "tools" / "oss-cad-suite" / ".bootstrap-sha256").read_text().strip() == sha
    obs = json.loads((tmp / "host" / "Linux-x86_64.json").read_text())
    assert obs["archive_sha256_observed"] == sha == obs["archive_sha256_expected"]
    assert "fake" in obs["yosys"]
    # the lock is an input: it must be byte-identical after a normal run
    assert json.loads((tmp / "lock.json").read_text())["assets"]["linux-x64"]["sha256"] == sha


def test_wrong_hash_is_rejected_by_family(linux):
    tmp, arch, sha = linux
    r = run(tmp, "Linux-x86_64", lock_with(tmp, "linux-x64", "0" * 64), arch)
    assert r.returncode != 0
    assert "does not match the linux-x64 entry" in r.stderr
    assert not (tmp / "tools" / "oss-cad-suite").exists()


def test_unsupported_platform(linux):
    tmp, arch, sha = linux
    r = run(tmp, "FreeBSD-amd64", lock_with(tmp, "linux-x64", sha), arch)
    assert r.returncode != 0 and "unsupported platform" in r.stderr


def test_mac_download_never_compared_with_linux_hash(tmp_path):
    """darwin-arm64 with only the Linux hash recorded must refuse (not compare against Linux)."""
    mac = fake_archive(tmp_path, "darwin-arm64")
    linux_sha = "8fb2384c2f88126f8936fc8f680ed2ebdf0ce440a7457c8f5a21c5c6e3e2de44"
    lock = lock_with(tmp_path, "linux-x64", linux_sha)
    r = run(tmp_path, "Darwin-arm64", lock, mac)
    assert r.returncode != 0
    assert "no recorded hash for darwin-arm64" in r.stderr and "--enroll" in r.stderr
    assert linux_sha not in r.stderr.split("no recorded")[0]


def test_enrollment_records_hash_then_validates(tmp_path):
    mac = fake_archive(tmp_path, "darwin-arm64")
    sha = hashlib.sha256(mac.read_bytes()).hexdigest()
    lock = lock_with(tmp_path, "linux-x64", "1" * 64)
    r = run(tmp_path, "Darwin-arm64", lock, mac, args=("--enroll",))
    assert r.returncode == 0, r.stdout + r.stderr
    doc = json.loads(lock.read_text())
    assert doc["assets"]["darwin-arm64"]["sha256"] == sha
    assert doc["assets"]["darwin-arm64"]["status"] == "enrolled-unreviewed"
    assert doc["assets"]["linux-x64"]["sha256"] == "1" * 64, "other families untouched"
    # second run without --enroll: already installed with the (now recorded) hash
    r2 = run(tmp_path, "Darwin-arm64", lock, mac)
    assert r2.returncode == 0 and "already installed" in r2.stdout


def test_missing_compiler_fails_early(linux):
    tmp, arch, sha = linux
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    for tool in ("bash", "python3", "make", "git", "curl", "tar", "sha256sum", "cut", "cat", "mkdir", "rm", "mv", "cp",
                 "sed", "tr", "printf", "dirname", "uname", "sleep", "rmdir", "env", "sh"):
        src = shutil.which(tool)
        if src:
            os.symlink(src, bin_dir / tool)
    r = run(tmp, "Linux-x86_64", lock_with(tmp, "linux-x64", sha), arch, extra_env={"PATH": str(bin_dir)})
    assert r.returncode != 0 and "C++ compiler not found" in r.stderr


def test_interrupted_download_leaves_no_partial_file(linux):
    tmp, arch, sha = linux
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    fake_curl = bin_dir / "curl"
    fake_curl.write_text("#!/bin/sh\nout=''\nwhile [ $# -gt 0 ]; do if [ \"$1\" = -o ]; then out=$2; shift; fi; shift; done\n"
                         "printf 'partial' > \"$out\"\nexit 22\n")
    fake_curl.chmod(0o755)
    r = run(tmp, "Linux-x86_64", lock_with(tmp, "linux-x64", sha), None,
            extra_env={"PATH": f"{bin_dir}:{os.environ['PATH']}"})
    assert r.returncode != 0 and "could not download" in r.stderr
    assert not list((tmp / "tools").glob("*.part")), "partial download must be removed"
    assert not list((tmp / "tools").glob("*.tgz"))


def test_already_installed_is_idempotent(linux):
    tmp, arch, sha = linux
    lock = lock_with(tmp, "linux-x64", sha)
    assert run(tmp, "Linux-x86_64", lock, arch).returncode == 0
    r = run(tmp, "Linux-x86_64", lock, arch)
    assert r.returncode == 0 and "already installed" in r.stdout


def test_lock_asset_name_must_match_release(linux):
    tmp, arch, sha = linux
    doc = json.loads(lock_with(tmp, "linux-x64", sha).read_text())
    doc["assets"]["linux-x64"]["asset"] = "oss-cad-suite-linux-x64-20250101.tgz"
    (tmp / "lock.json").write_text(json.dumps(doc))
    r = run(tmp, "Linux-x86_64", tmp / "lock.json", arch)
    assert r.returncode != 0 and "does not match release" in r.stderr


def doctor(tmp: Path, platform: str, lock: Path, extra_env=None):
    """Run doctor with the interpreter running this test (whichever venv that is)."""
    env = dict(os.environ)
    venv_name = Path(sys.prefix).name
    env.update({"TETROMINO_PLATFORM": platform, "TETROMINO_LOCK": str(lock), "TETROMINO_TOOLS_DIR": str(tmp / "tools"),
                "TETROMINO_HOST_DIR": str(tmp / "host"), "TETROMINO_VENV": venv_name,
                "PATH": f"{tmp / 'tools' / 'oss-cad-suite' / 'bin'}:{os.environ['PATH']}"})
    if extra_env:
        env.update(extra_env)
    return subprocess.run([sys.executable, str(ROOT / "tools" / "doctor.py"), "--profile", "full"],
                          cwd=ROOT, env=env, capture_output=True, text=True)


def test_doctor_validates_installed_suite_against_platform_entry(linux):
    """doctor reads the v2 lock: the fake suite passes the toolchain identity checks for its own family
    (the fake nextpnr lacks real options, which is the only reported problem), an unenrolled platform,
    a foreign-family install and a missing host observation are each reported."""
    tmp, arch, sha = linux
    lock = lock_with(tmp, "linux-x64", sha)
    assert run(tmp, "Linux-x86_64", lock, arch).returncode == 0
    r = doctor(tmp, "Linux-x86_64", lock)
    problems = [l.strip() for l in r.stdout.splitlines() if l.strip().startswith("- ")]
    assert "installed_sha256" in r.stdout and "linux-x64" in r.stdout
    assert all("lacks expected ECP5 options" in p for p in problems), problems
    # same install, examined as an unenrolled Mac: hash missing, foreign asset, no observation
    r = doctor(tmp, "Darwin-arm64", lock)
    assert r.returncode == 1
    assert "no recorded archive hash for darwin-arm64" in r.stdout and "--enroll" in r.stdout
    assert "is not the locked oss-cad-suite-darwin-arm64" in r.stdout
    assert "host observation" in r.stdout and "Darwin-arm64.json missing" in r.stdout
    # observation removed on the right platform: reported, hash still validated
    (tmp / "host" / "Linux-x86_64.json").unlink()
    r = doctor(tmp, "Linux-x86_64", lock)
    assert r.returncode == 1 and "Linux-x86_64.json missing" in r.stdout
    # a tampered lock hash is caught against the installed marker
    lock2 = lock_with(tmp, "linux-x64", "f" * 64)
    r = doctor(tmp, "Linux-x86_64", lock2)
    assert r.returncode == 1 and "differs from the linux-x64 lock entry" in r.stdout


@pytest.mark.skipif(not (ROOT / ".tools" / "oss-cad-suite" / "bin" / "verilator").exists(), reason="suite not installed")
def test_cocotb_runner_works_from_outside_the_source_tree(tmp_path):
    """Regression for the PYTHONPATH defect: run the counter test with an unrelated working directory."""
    r = subprocess.run(["bash", str(ROOT / "scripts" / "env.sh"), "python", "tools/run_rtl.py", "--top", "counter",
                        "--test", "tb_counter", "--source", "rtl/learning/counter.sv", "--build-tag", "oot"],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert "RTL tests: 1 total, 0 failed" in r.stdout
