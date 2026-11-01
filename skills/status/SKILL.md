---
name: status
description: Show the symbol table, defined/undefined/orphan status and validation coverage of a .model.md math paper. Use when the user asks what a .model.md defines or how complete its validation is.
argument-hint: "<path-to-file.model.md>"
allowed-tools: Bash Read Glob
---

# Show Model Status

Display the current symbol table, dependency status, and coverage metric for a `.model.md` document.

**Arguments:** `$ARGUMENTS`

## Steps

1. **Locate the file:** Use the path from the arguments. If no path is given, search with Glob for `**/*.model.md` and ask the user which one if multiple are found. Resolve the path to an absolute path (relative paths are relative to the user's working directory).

2. **Run the validation report:**

   ```bash
   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" report "<absolute_file_path>"
   ```

3. **Present the results:** Format the report output for the user, highlighting:
   - Total symbols defined by type (Sets, Parameters, Variables, Expressions, Constraints, Objectives)
   - Any orphan symbols (defined but never referenced)
   - Any phantom references (referenced but never defined)
   - Coverage ratio (math blocks with corresponding validation blocks)
   - Unvalidated sections (if any)
   - LaTeX linkage gaps: identifiers in the math with no registered symbol, and symbols whose `latex=` never appears

   For a structured view of the symbols themselves, run:

   ```bash
   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" symbols "<absolute_file_path>"
   ```
