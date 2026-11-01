"""PreToolUse guard for approved claim statements.

Run by hooks.json through scripts/mpc (so it uses the plugin's Python):

* Write/Edit of a .model.md: simulate the edit, rebuild the Lean statements,
  and DENY the edit if it would change (or drop) a statement the author
  approved. The edit never happens.
* Write/Edit of a <paper>.proofs.json: DENY. The file is maintained by
  `mpc prove` and `mpc approve`.
* Bash running `mpc approve` (or a command that writes a .proofs.json):
  ASK. The user sees the statements in a [plugin:math-paper-creator]
  permission prompt and must confirm. This holds even in bypassPermissions
  mode, so approval stays with the author.

This guards against accidental or convenient drift (an agent weakening a
claim until it becomes provable). It is not a sandbox: a user can always
approve, and a determined process outside Claude Code can edit any file.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path


def emit(decision: str, reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def _theorems_for(source: str):
    from meta_compiler.compiler import check_document
    from meta_compiler.lean import build_theorems

    result = check_document(source, strict=False)
    if result.registry is None:
        return None, False
    theorems, _ = build_theorems(result.registry)
    return theorems, result.passed


def guard_model_edit(tool: str, tool_input: dict, path: Path) -> None:
    from meta_compiler.lean import approval_status, load_proofs, proofs_path

    cache = load_proofs(proofs_path(path))
    approved = cache.get("approved") or {}
    if not approved:
        return

    if tool == "Write":
        new = tool_input.get("content", "")
    else:
        try:
            old_text = path.read_text()
        except OSError:
            return
        old, repl = tool_input.get("old_string", ""), tool_input.get("new_string", "")
        if not old or old not in old_text:
            return  # the Edit will fail on its own
        count = -1 if tool_input.get("replace_all") else 1
        new = old_text.replace(old, repl, count)

    theorems, passed = _theorems_for(new)
    if theorems is None:
        return  # can't evaluate; the PostToolUse check still runs
    status = approval_status(theorems, cache)
    by_name = {t.name: t for t in theorems}
    changed = [n for n, s in status.items() if s == "changed"]
    removed = [n for n, s in status.items() if s == "removed" and passed]
    if not changed and not removed:
        return

    lines = ["This edit would change claim statements the author approved:"]
    for n in changed:
        lines.append(f"\n{n} — approved:\n{approved[n].get('statement', '')}\n"
                     f"{n} — after this edit:\n{by_name[n].statement}")
    for n in removed:
        lines.append(f"\n{n} would be removed (approved statement:\n{approved[n].get('statement', '')})")
    lines.append(
        "\nDon't change an approved statement to make a proof go through. If the author "
        "wants it changed, ask them, then revoke the approval with `mpc approve --revoke "
        "--name <claim>` (they will be asked to confirm) before editing, and have them "
        "approve the new statement afterwards."
    )
    emit("deny", "\n".join(lines))


def guard_bash(command: str, cwd: str) -> None:
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()

    is_mpc = any(w.endswith("/mpc") or w == "mpc" or "meta_compiler" in w for w in words)
    if is_mpc and "approve" in words:
        revoke = "--revoke" in words
        names = [words[i + 1] for i, w in enumerate(words[:-1]) if w == "--name"]
        model = next((w for w in words if w.endswith(".model.md")), None)
        detail = ""
        if model and not revoke:
            path = Path(model) if Path(model).is_absolute() else Path(cwd) / model
            try:
                theorems, _ = _theorems_for(path.read_text())
                by_name = {t.name: t for t in theorems or []}
                detail = "\n\n" + "\n\n".join(
                    f"{n}:\n{by_name[n].statement}" for n in names if n in by_name
                )
            except Exception:
                pass
        if revoke:
            reason = (f"math-paper-creator: withdraw YOUR approval of {', '.join(names)}? "
                      "Claude will then be able to change these statements.")
        else:
            reason = (f"math-paper-creator: record YOUR approval that the Lean statement(s) of "
                      f"{', '.join(names)} say what the paper claims?{detail}\n\n"
                      "Approve only if you have read them and agree.")
        emit("ask", reason)

    writes = re.search(r">|\btee\b|\bsed\s+-i|\bmv\b|\bcp\b|\brm\b|python|perl|truncate", command)
    if ".proofs.json" in command and writes and not is_mpc:
        emit("ask", "math-paper-creator: this command may modify a .proofs.json file, which "
                    "records Lean results and YOUR statement approvals. Allow it?")


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}

    if tool in ("Write", "Edit"):
        file_path = tool_input.get("file_path", "")
        if file_path.endswith(".proofs.json"):
            emit("deny", "math-paper-creator: <paper>.proofs.json is maintained by `mpc prove` "
                         "and `mpc approve`; don't edit it directly.")
        if file_path.endswith(".model.md"):
            try:
                guard_model_edit(tool, tool_input, Path(file_path))
            except SystemExit:
                raise
            except Exception:
                return  # never block on an internal error; PostToolUse still checks
    elif tool == "Bash":
        guard_bash(tool_input.get("command", ""), data.get("cwd") or ".")


if __name__ == "__main__":
    main()
