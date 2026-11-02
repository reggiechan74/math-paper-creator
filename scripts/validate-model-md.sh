#!/usr/bin/env bash
# validate-model-md.sh — PostToolUse hook for .model.md live validation
#
# Reads PostToolUse JSON from stdin.
# If the edited file is .model.md, runs the meta-compiler check pipeline.
# Returns structured JSON feedback to Claude Code.
#
# hooks.json already filters to Write/Edit on *.model.md via `if`; the checks
# below are kept so the script is safe to run on its own.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Prefer the managed venv (see setup_env.py); fall back to python3 on PATH.
PY="python3"
if [ -n "${CLAUDE_PLUGIN_DATA:-}" ] && [ -f "${CLAUDE_PLUGIN_DATA}/venv/.ready" ]; then
  for candidate in "${CLAUDE_PLUGIN_DATA}/venv/bin/python" "${CLAUDE_PLUGIN_DATA}/venv/Scripts/python.exe"; do
    if [ -x "$candidate" ]; then
      PY="$candidate"
      break
    fi
  done
fi

# Read stdin before the heredoc consumes it
HOOK_INPUT="$(cat)"

# The plugin's `live_validation` option: a .model.md is a program, so users
# can stop the hook from running papers they don't trust.
case "$(printf '%s' "${CLAUDE_PLUGIN_OPTION_LIVE_VALIDATION:-true}" | tr '[:upper:]' '[:lower:]')" in
  false|0|no|off)
    exit 0
    ;;
esac

# Delegate everything to Python for safe JSON handling
HOOK_INPUT="$HOOK_INPUT" exec "$PY" - "$PROJECT_DIR" <<'PYTHON_SCRIPT'
import json
import os
import sys
from pathlib import Path

project_dir = Path(sys.argv[1])

# Read and parse hook input from environment variable
try:
    hook_input = json.loads(os.environ.get("HOOK_INPUT", ""))
except (json.JSONDecodeError, ValueError):
    sys.exit(0)

tool_name = hook_input.get("tool_name", "")
file_path = hook_input.get("tool_input", {}).get("file_path", "")

# Only process Write and Edit on .model.md files
if tool_name not in ("Write", "Edit"):
    sys.exit(0)

if not file_path.endswith(".model.md"):
    sys.exit(0)

file_path_obj = Path(file_path)
if not file_path_obj.is_file():
    sys.exit(0)

# Add meta-compiler src to path
sys.path.insert(0, str(project_dir / "src"))

try:
    import numpy  # noqa: F401  (required by the meta-compiler)
    from meta_compiler.compiler import check_document
    from meta_compiler.compiler.parser import parse_document, coverage_metric
except ImportError as exc:
    data_dir = os.environ.get("CLAUDE_PLUGIN_DATA", "")
    hint = (
        f" The plugin installs its dependencies in the background on session start;"
        f" see {data_dir}/setup.log if this persists."
        if data_dir
        else " Install numpy for the python3 on PATH (pip install numpy)."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"math-paper-creator: live validation of {file_path} was skipped "
                f"because a Python dependency is missing ({exc}).{hint}"
            ),
        }
    }))
    sys.exit(0)

source = file_path_obj.read_text()

# Run validation in authoring mode (orphans are warnings, not errors)
result = check_document(source, strict=False)

# Check coverage
blocks = parse_document(source)
cov = coverage_metric(blocks)

# Approved claim statements must not change (see scripts/guard.py)
if result.registry is not None:
    try:
        from meta_compiler.lean import (
            approval_problems, build_theorems, load_proofs, proofs_path,
        )
        cache = load_proofs(proofs_path(file_path_obj))
        if cache.get("approved"):
            theorems, _ = build_theorems(result.registry)
            problems = approval_problems(theorems, cache)
            if problems:
                result.errors.extend(problems)
                result.passed = False
    except Exception:
        pass

if not result.passed:
    # Validation failed — block with error details
    errors = "; ".join(result.errors)
    output = {
        "decision": "block",
        "reason": f"Validation failed for {file_path}: {errors}",
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "Fix the validation errors before continuing. Re-run all validation blocks from the top of the document after your fix.",
        },
    }
    print(json.dumps(output))
else:
    # Validation passed — collect warnings and coverage info
    context_parts = []

    if cov.total_math > 0 and cov.covered_math < cov.total_math:
        uncovered = cov.total_math - cov.covered_math
        sections = ", ".join(cov.uncovered_sections) if cov.uncovered_sections else "unknown"
        context_parts.append(
            f"WARNING: {uncovered} math blocks have no validation block. "
            f"Unvalidated sections: {sections}"
        )

    if result.warnings:
        context_parts.extend(result.warnings)

    if context_parts:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "; ".join(context_parts),
            }
        }
        print(json.dumps(output))
PYTHON_SCRIPT
