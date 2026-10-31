#!/usr/bin/env python3
"""SessionStart hook: provision the plugin's Python environment.

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
LOCK_STALE_SECONDS = 15 * 60


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


def install(data: Path) -> int:
    """Background worker: build/refresh the venv. Output goes to setup.log."""
    venv = data / "venv"
    lock = data / ".setup.lock"
    want = requirements_hash()

    if is_current(venv, want):
        return 0
    if not acquire_lock(lock):
        print("Another setup is in progress; skipping.")
        return 0

    try:
        # Drop the ready marker first so callers fall back to python3
        # while the environment is being rebuilt.
        (venv / ".ready").unlink(missing_ok=True)

        build_venv(venv)

        (venv / ".ready").write_text(want + "\n")
        print(f"[{time.ctime()}] Environment ready.")
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
        if is_current(data / "venv", requirements_hash()):
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
