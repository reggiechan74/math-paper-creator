---
name: compile
description: Compile all three artifacts from a finished .model.md — clean paper, standalone runner.py and validation report — in strict mode.
argument-hint: "<path-to-file.model.md> [output-dir] [--depth executive|technical|appendix]"
allowed-tools: Bash Read Write Glob
disable-model-invocation: true
---

# Compile All Artifacts

Produce all three artifacts from a `.model.md` document:
1. **Paper** — clean Markdown with validation blocks stripped
2. **Runner** — standalone Python script extracted from validation blocks
3. **Validation Report** — symbol table, dependencies, coverage, test results

This runs in **strict mode** — orphan symbols are hard errors. Use this when the document is complete.

**Arguments:** `$ARGUMENTS`

**Security:** this runs the paper's Python code. A `.model.md` is a program. If the paper came from someone else (downloaded, emailed, from a repository the user doesn't control) and the user hasn't said they trust it, ask before running it. Suggest reading its `python:fixture` and `python:validate` blocks first, or running it in a sandbox.

## Steps

1. **Locate the file:** Use the path from the arguments. If no path is given, search with Glob for `**/*.model.md`. Resolve it to an absolute path (relative paths are relative to the user's working directory).

2. **Choose the output directory:** Use the output directory from the arguments if given, otherwise `output/` in the same directory as the `.model.md` file. Resolve it to an absolute path. Never write output inside the plugin directory.

3. **Robustness sweep first:**

   ```bash
   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" sweep "<absolute_file_path>"
   ```

   If it reports defects (exit code 2), show them and ask whether to fix them first or compile anyway. A compiled paper whose formulas crash on inputs it allows is publishable but wrong.

4. **Build the command:**

   ```bash
   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" compile "<absolute_file_path>" --output "<absolute_output_dir>"
   ```

   Add `--depth <depth>` if a depth filter was specified. `paper.md` notes each claim's evidence level and ends with a Verification summary. Add `--no-verification` only if the user asks to omit them. Run `/math-paper-creator:prove` first if the user wants Lean-proved claims shown as such.

5. **Execute:** Run the command. If validation fails (strict mode), report the errors and offer to help fix them before retrying.

6. **Report:** Show the user what was generated:
   - `<output>/paper.md` — the clean paper
   - `<output>/runner.py` — standalone Python runner extracted from validation blocks
   - `<output>/report.txt` — the validation report

7. **Verify runner:** Optionally run the generated runner with the plugin's Python environment:

   ```bash
   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" --python "<absolute_output_dir>/runner.py"
   ```

   Report pass/fail status.
