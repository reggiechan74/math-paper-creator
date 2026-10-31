---
name: paper
description: Generate the clean paper artifact from a .model.md document — validation blocks stripped, only prose and math kept — optionally filtered by depth (executive, technical, appendix).
argument-hint: "<path-to-file.model.md> [--depth executive|technical|appendix] [output-path]"
allowed-tools: Bash Read Write Glob
---

# Generate Paper Artifact

Compile a clean paper from a `.model.md` document. Strips all validation blocks, leaving only prose and math.

**Arguments:** `$ARGUMENTS`

## Steps

1. **Locate the file:** Use the path from the arguments. If no path is given, search with Glob for `**/*.model.md`. Resolve it (and any output path) to an absolute path (relative paths are relative to the user's working directory).

2. **Build the command:**

   ```bash
   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" paper "<absolute_file_path>"
   ```

   Add `--depth <depth>` if a depth filter was specified.
   Add `--output "<absolute_output_path>"` if an output path was specified.

3. **Execute and report:** Run the command. If an output path was given, confirm the file was written. If no output path, display the paper content or write it to a sensible default next to the source document (e.g., `<basename>.paper.md`).
