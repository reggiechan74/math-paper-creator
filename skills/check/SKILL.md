---
name: check
description: Run the meta-compiler validation pipeline against a .model.md math paper and report errors, warnings and coverage. Use when the user asks to check or validate a .model.md file.
argument-hint: "<path-to-file.model.md> [--strict]"
allowed-tools: Bash Read Glob
---

# Validate Mathematical Model Document

Run the meta-compiler validation pipeline against the specified `.model.md` file.

**Arguments:** `$ARGUMENTS`

**Security:** this runs the paper's Python code. A `.model.md` is a program. If the paper came from someone else (downloaded, emailed, from a repository the user doesn't control) and the user hasn't said they trust it, ask before running it. Suggest reading its `python:fixture` and `python:validate` blocks first, or running it in a sandbox.

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

4. **Robustness sweep (when validation passed):** `check` tests the model only at the fixture values. The sweep re-evaluates it at random inputs the paper's own domains, bounds and axioms allow:

   ```bash
   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" sweep "<absolute_file_path>"
   ```

   Exit code 2 means it found **defects**: formulas that crash or give NaN/inf on admissible inputs, each with an example input. Typical cases are dividing by a difference that can reach zero (`x / (H - M)` when `M = H`), or taking a log or square root of something that can go negative. Report each defect and offer a fix. Usual fixes are tightening an axiom or domain (e.g. `M < H`) or guarding the formula. The constraint "holds in k/N samples" lines are informational, because constraints restrict the decision for given data.
