#!/usr/bin/env python3
"""SessionStart hook: provision the plugin's Python (and optional Lean) environment.

Creates a venv at ${CLAUDE_PLUGIN_DATA}/venv and installs requirements.txt
into it. ${CLAUDE_PLUGIN_DATA} survives plugin updates, so this runs the
install once and then again only when requirements.txt changes.

The hook must never slow down or break session start:
  * The fast path (environment already current) is a hash comparison.
  * When an install is needed, the work is handed to a detached background
    process and the hook returns immediately.
  * Every failure is logged to ${CLAUDE_PLUGIN_DATA}/setup.log and the hook
    exits 0. Until the venv is marked ready, scripts/mpc and the validation
    hook fall back to python3 on PATH.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"
LEAN_TEMPLATE = ROOT / "lean"
LEAN_TEMPLATE_FILES = ("lakefile.toml", "lean-toolchain", "lake-manifest.json")
ELAN_INIT_URL = "https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh"
LOCK_STALE_SECONDS = 90 * 60  # a first Mathlib download can take a while


def lean_enabled() -> bool:
    """The plugin's `enable_lean` userConfig option (exported to hooks)."""
    value = os.environ.get("CLAUDE_PLUGIN_OPTION_ENABLE_LEAN", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def lean_hash() -> str:
    digest = hashlib.sha256()
    for name in LEAN_TEMPLATE_FILES:
        digest.update((LEAN_TEMPLATE / name).read_bytes())
    return digest.hexdigest()


def lean_is_current(data: Path) -> bool:
    try:
        return (data / "lean" / ".ready").read_text().strip() == lean_hash()
    except OSError:
        return False


def requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def is_current(venv: Path, want: str) -> bool:
    stamp = venv / ".ready"
    try:
        return stamp.read_text().strip() == want and venv_python(venv).exists()
    except OSError:
        return False


def acquire_lock(lock: Path) -> bool:
    try:
        lock.mkdir()
        return True
    except FileExistsError:
        try:
            age = time.time() - lock.stat().st_mtime
        except OSError:
            return False
        if age > LOCK_STALE_SECONDS:
            try:
                lock.rmdir()
                lock.mkdir()
                return True
            except OSError:
                return False
        return False


def run(cmd: list[str]) -> bool:
    print(f"[{time.ctime()}] $ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd).returncode == 0


def build_venv(venv: Path) -> None:
    """Create the venv and install requirements, trying in order:

    1. uv (fast, and doesn't need ensurepip)
    2. stdlib venv with pip
    3. stdlib venv --without-pip, filled by the system pip's --python option
       (Debian/Ubuntu ship python3 without ensurepip unless python3-venv is
       installed)
    """
    req = str(REQUIREMENTS)
    py = str(venv_python(venv))

    uv = shutil.which("uv")
    if uv and run([uv, "venv", "--allow-existing", "--python", sys.executable, str(venv)]) \
            and run([uv, "pip", "install", "--python", py, "-q", "-r", req]):
        return

    if run([sys.executable, "-m", "venv", str(venv)]) and \
            run([py, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", req]):
        return

    if run([sys.executable, "-m", "venv", "--clear", "--without-pip", str(venv)]) and \
            run([sys.executable, "-m", "pip", "--python", py, "install",
                 "--disable-pip-version-check", "-q", "-r", req]):
        return

    raise RuntimeError(
        "could not build the environment. Install uv, or python3-venv "
        "(Debian/Ubuntu), then start a new session."
    )


def build_lean(data: Path) -> None:
    """Install elan + the pinned Lean toolchain and Mathlib (several GB).

    Layout under ${CLAUDE_PLUGIN_DATA}/lean:
      elan/      ELAN_HOME (toolchains)
      project/   copy of the plugin's lean/ template, with Mathlib's build cache
      .ready     hash of the template files, written last
    """
    import urllib.request

    if os.name == "nt":
        raise RuntimeError("automatic Lean setup is not supported on Windows; "
                           "set MPC_LEAN_PROJECT to a Lake project that requires Mathlib")
    lean_dir = data / "lean"
    project = lean_dir / "project"
    (lean_dir / ".ready").unlink(missing_ok=True)
    lean_dir.mkdir(parents=True, exist_ok=True)

    # Reuse the user's own elan (the standard ~/.elan install) when there is
    # one; otherwise install a private copy under the plugin's data directory.
    system_elan = os.environ.get("ELAN_HOME") or str(Path.home() / ".elan")
    if (Path(system_elan) / "bin" / "elan").exists():
        elan_home = Path(system_elan)
        print(f"[{time.ctime()}] Using elan at {elan_home}", flush=True)
    else:
        elan_home = lean_dir / "elan"

    env = dict(os.environ, ELAN_HOME=str(elan_home))
    env["PATH"] = str(elan_home / "bin") + os.pathsep + env.get("PATH", "")

    if not (elan_home / "bin" / "elan").exists():
        script = lean_dir / "elan-init.sh"
        print(f"[{time.ctime()}] Downloading elan", flush=True)
        urllib.request.urlretrieve(ELAN_INIT_URL, script)
        if subprocess.run(["sh", str(script), "-y", "--no-modify-path",
                           "--default-toolchain", "none"], env=env).returncode != 0:
            raise RuntimeError("elan installation failed")

    project.mkdir(exist_ok=True)
    for name in LEAN_TEMPLATE_FILES:
        shutil.copy2(LEAN_TEMPLATE / name, project / name)

    lake = str(elan_home / "bin" / "lake")
    print(f"[{time.ctime()}] Fetching Mathlib build cache (several GB)", flush=True)
    if subprocess.run([lake, "exe", "cache", "get"], cwd=project, env=env).returncode != 0:
        raise RuntimeError("`lake exe cache get` failed")

    smoke = project / "Smoke.lean"
    smoke.write_text("import Mathlib\nexample (x : ℝ) : x ^ 2 ≥ 0 := by positivity\n")
    check = [lake, "env", "lean", str(smoke)]
    if subprocess.run(check, cwd=project, env=env).returncode != 0:
        # `cache get` skips unpacking when the archives are already in the
        # shared ~/.cache/mathlib (e.g. a second project); unpack explicitly.
        print(f"[{time.ctime()}] Unpacking Mathlib build cache", flush=True)
        subprocess.run([lake, "exe", "cache", "unpack"], cwd=project, env=env)
        if subprocess.run(check, cwd=project, env=env).returncode != 0:
            raise RuntimeError("Lean smoke test failed")
    smoke.unlink()

    (lean_dir / ".ready").write_text(lean_hash() + "\n")
    print(f"[{time.ctime()}] Lean + Mathlib ready.", flush=True)


def install(data: Path) -> int:
    """Background worker: build/refresh the environments. Output goes to setup.log."""
    venv = data / "venv"
    lock = data / ".setup.lock"
    want = requirements_hash()
    want_lean = lean_enabled() and not lean_is_current(data)

    if is_current(venv, want) and not want_lean:
        return 0
    if not acquire_lock(lock):
        print("Another setup is in progress; skipping.")
        return 0

    try:
        if not is_current(venv, want):
            # Drop the ready marker first so callers fall back to python3
            # while the environment is being rebuilt.
            (venv / ".ready").unlink(missing_ok=True)
            build_venv(venv)
            (venv / ".ready").write_text(want + "\n")
            print(f"[{time.ctime()}] Environment ready.")
        if want_lean:
            build_lean(data)
        return 0
    except (RuntimeError, OSError) as exc:
        print(f"[{time.ctime()}] Setup failed: {exc}")
        return 0
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


def main() -> int:
    data_env = os.environ.get("CLAUDE_PLUGIN_DATA", "")
    if not data_env:
        return 0
    data = Path(data_env)

    if len(sys.argv) > 1 and sys.argv[1] == "--install":
        return install(data)

    # Drain hook input so the writer never blocks on a full pipe.
    try:
        sys.stdin.read()
    except (OSError, ValueError):
        pass

    try:
        data.mkdir(parents=True, exist_ok=True)
        if is_current(data / "venv", requirements_hash()) and (
            not lean_enabled() or lean_is_current(data)
        ):
            return 0

        log = open(data / "setup.log", "a")
        kwargs: dict = {
            "stdin": subprocess.DEVNULL,
            "stdout": log,
            "stderr": subprocess.STDOUT,
            "cwd": str(data),
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--install"], **kwargs)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
