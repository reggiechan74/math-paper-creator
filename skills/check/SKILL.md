---
name: check
description: Run the meta-compiler validation pipeline against a .model.md math paper and report errors, warnings and coverage. Use when the user asks to check or validate a .model.md file.
argument-hint: "<path-to-file.model.md> [--strict]"
allowed-tools: Bash Read Glob
---

# Validate Mathematical Model Document

Run the meta-compiler validation pipeline against the specified `.model.md` file.

**Arguments:** `$ARGUMENTS`

## Steps

1. **Locate the file:** Use the path from the arguments. If no path is given, search the current directory for `.model.md` files using Glob with pattern `**/*.model.md` and ask the user which one to validate if multiple are found. Resolve the path to an absolute path (relative paths are relative to the user's working directory).

2. **Run validation:**

   ```bash
   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" check "<absolute_file_path>"
   ```

   If the arguments include `--strict` (or the user asks for strict/compilation mode, where orphan symbols are errors), add the flag:

   ```bash
   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" check --strict "<absolute_file_path>"
   ```

3. **Report results:** Show the output to the user. If validation passed, confirm success and list any warnings. If validation failed, show the errors and offer to help fix them.
