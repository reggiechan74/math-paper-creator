---
name: report
description: Generate the full validation report for a .model.md math paper — symbol table, dependency graph, test results and coverage audit — optionally saved to a file.
argument-hint: "<path-to-file.model.md> [output-path]"
allowed-tools: Bash Read Write Glob
---

# Generate Validation Report

Produce a full validation report from a `.model.md` document including symbol table, dependency graph, test results, and coverage audit.

**Arguments:** `$ARGUMENTS`

## Steps

1. **Locate the file:** Use the first path from the arguments. If no path is given, search with Glob for `**/*.model.md`. Resolve it (and any output path) to an absolute path (relative paths are relative to the user's working directory).

2. **Run the report command:**

   ```bash
   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" report "<absolute_file_path>"
   ```

   Add `--output "<absolute_output_path>"` if an output path was given.

3. **Present results:** Show the full report to the user. Highlight any errors, warnings, orphan symbols, or coverage gaps.
