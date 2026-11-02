---
name: paper
description: Generate the clean paper artifact from a .model.md document — validation blocks stripped, only prose and math kept — optionally filtered by depth (executive, technical, appendix).
argument-hint: "<path-to-file.model.md> [--depth executive|technical|appendix] [output-path]"
allowed-tools: Bash Read Write Glob
---

# Generate Paper Artifact

Compile a clean paper from a `.model.md` document. Strips all validation blocks, leaving only prose and math.

**Arguments:** `$ARGUMENTS`

**Security:** this runs the paper's Python code. A `.model.md` is a program. If the paper came from someone else (downloaded, emailed, from a repository the user doesn't control) and the user hasn't said they trust it, ask before running it. Suggest reading its `python:fixture` and `python:validate` blocks first, or running it in a sandbox.

## Steps

1. **Locate the file:** Use the path from the arguments. If no path is given, search with Glob for `**/*.model.md`. Resolve it (and any output path) to an absolute path (relative paths are relative to the user's working directory).

2. **Build the command:**

   ```bash
   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" paper "<absolute_file_path>"
   ```

   Add `--depth <depth>` if a depth filter was specified.
   The paper notes each claim's evidence level (assumption / Verified (Z3) / Proved (Lean)) where it is made, and ends with a Verification summary. Add `--no-verification` only if the user asks for a paper without these notes.
   Add `--output "<absolute_output_path>"` if an output path was specified.

3. **Execute and report:** Run the command. If an output path was given, confirm the file was written. If no output path, display the paper content or write it to a sensible default next to the source document (e.g., `<basename>.paper.md`).
