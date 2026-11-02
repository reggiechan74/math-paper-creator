#!/usr/bin/env python3
"""Maintainer tool: move the plugin's pinned Lean + Mathlib to a new release.

    python3 scripts/bump_lean.py v4.37.0

Mathlib publishes a tag per Lean release (e.g. v4.37.0); the toolchain and
Mathlib must move together. This rewrites lean/lean-toolchain and the Mathlib
`rev` in lean/lakefile.toml, then runs `lake update` in a scratch copy to
regenerate lean/lake-manifest.json (needs elan on PATH, and a Mathlib clone).

What happens for users after the release ships:
  * scripts/setup_env.py sees the changed template and rebuilds the Lean
    project in the background on their next session start;
  * every recorded Lean result becomes stale (results are keyed by the
    toolchain), so `mpc prove` must run again — proofs that relied on renamed
    Mathlib lemmas need fixing;
  * statement approvals stay valid (they pin statements, not toolchains).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

LEAN = Path(__file__).resolve().parent.parent / "lean"


def main() -> int:
    if len(sys.argv) != 2 or not re.fullmatch(r"v\d+\.\d+\.\d+(-rc\d+)?", sys.argv[1]):
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        print("usage: bump_lean.py vX.Y.Z[-rcN]", file=sys.stderr)
        return 2
    version = sys.argv[1]
    lake = shutil.which("lake")
    if lake is None:
        print("lake not found: install elan (https://lean-lang.org/install/)", file=sys.stderr)
        return 1

    toolchain = f"leanprover/lean4:{version}\n"
    lakefile = (LEAN / "lakefile.toml").read_text()
    lakefile, n = re.subn(r'(?m)^rev = "[^"]*"', f'rev = "{version}"', lakefile)
    if n != 1:
        print("could not find the Mathlib rev in lean/lakefile.toml", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="mpc-bump-") as tmp:
        work = Path(tmp)
        (work / "lean-toolchain").write_text(toolchain)
        (work / "lakefile.toml").write_text(lakefile)
        print(f"Resolving Mathlib {version} (this clones Mathlib)...", flush=True)
        if subprocess.run([lake, "update", "mathlib"], cwd=work).returncode != 0:
            print("lake update failed; nothing was changed", file=sys.stderr)
            return 1
        manifest = (work / "lake-manifest.json").read_text()

    old_toolchain = (LEAN / "lean-toolchain").read_text()
    old_manifest = (LEAN / "lake-manifest.json").read_text()
    (LEAN / "lean-toolchain").write_text(toolchain)
    (LEAN / "lakefile.toml").write_text(lakefile)
    (LEAN / "lake-manifest.json").write_text(manifest)

    if old_toolchain == toolchain and json.loads(old_manifest) == json.loads(manifest):
        print(f"Already pinned to {version}; nothing changed.")
        return 0
    print(f"Pinned Lean + Mathlib to {version}.")
    print("Next: run the Lean tests (MPC_LEAN_PROJECT on a fresh project from lean/),")
    print("bump the plugin version, and note in the CHANGELOG that `mpc prove` must be re-run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
