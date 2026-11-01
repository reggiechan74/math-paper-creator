---
name: onboard
description: Onboard an existing Markdown math paper into a validated .model.md — generate fixture and validation blocks section by section with interactive approval. The original file is never modified.
argument-hint: "<path-to-paper.md>"
allowed-tools: Bash Read Write Edit Glob
disable-model-invocation: true
---

# Onboard a Math Paper

Convert an existing markdown math paper into a fully validated `.model.md` document with working `python:validate` blocks. This is an interactive, section-by-section process — you will approve each validation block before moving on.

**Arguments:** `$ARGUMENTS`

**Paths:** Resolve every file path to an absolute path before passing it to the CLI (relative paths are relative to the user's working directory). Run the CLI exactly as shown below via `"${CLAUDE_PLUGIN_ROOT}/scripts/mpc"` — never `cd` into the plugin directory.

## Step 1: Locate the file

Use the provided path argument. If no path is given, search with Glob for `**/*.md` (excluding `*.model.md` files). If multiple results are found:
- Show at most 20 matches and ask the user which one to onboard.
- If more than 20 matches exist, ask the user to provide a path directly.

## Step 2: Guard rails

Before proceeding, check two conditions:

1. **Already a `.model.md` file?** If the file ends in `.model.md`, tell the user: "This file is already a `.model.md` document. Use `/math-paper-creator:check` to validate it or `/math-paper-creator:status` to see its current state." Stop here.

2. **No math blocks?** Read the file and check for `$$...$$` display math blocks. If none are found, tell the user: "No display math blocks (`$$...$$`) were found in this file. There is nothing to onboard." Stop here.

## Step 3: Read and analyze

Read the entire document. Identify:
- All sections (by heading level: `#`, `##`, `###`, etc.)
- All `$$...$$` display math blocks and which section each belongs to
- The mathematical model being described: sets, parameters, variables, expressions, constraints, objectives

Build a mental model of the paper's structure and mathematical content.

## Step 4: Present overview

Show the user a summary:
- Number of sections containing math blocks
- Total number of display math blocks
- A high-level interpretation of the model, e.g.: "This paper describes a linear program for workforce scheduling with 3 sets, 5 parameters, 2 variables, and 4 constraints."

Ask the user to confirm or correct this interpretation. The user may respond with free-form corrections. If they do, re-interpret and re-present until the user confirms.

**Do not proceed until the user explicitly confirms.**

## Step 5: Initialize the output file

Create the `.model.md` file immediately as a copy of the original:
- **Filename:** `<original-basename>.model.md` in the same directory as the original file.
- Copy all original content verbatim.
- **Never modify the original file.**

This file will be incrementally updated as each section is approved and validated.

## Step 6: Section-by-section conversion

**Use the document's symbol table, not memory.** Before proposing any new block, load the current symbol table and check that proposed names do not collide with existing ones:

```bash
CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" symbols --json "<absolute_output_path>"
```

For each section that contains `$$...$$` math blocks, in document order:

1. **Show context.** Display the section heading and the math block(s) it contains.

2. **Propose a fixture block followed by a validation block.** For each section, generate two consecutive blocks:

   a. **`python:fixture` block** — define a small, realistic test scenario with 3–5 concrete set members and realistic parameter values. This block populates the registry with test data so the subsequent validation block can exercise real indexing and arithmetic. Example: if the section defines a set of workers, create `["alice", "bob", "carol"]` as the fixture members.

   b. **`python:validate` block** — register the symbols and relationships defined in that section using the meta-compiler API:
   - `Set(name, description=..., latex=...)` for sets
   - `Parameter(name, index=[...], domain=..., units=..., description=..., latex=...)` for parameters
   - `Variable(name, index=[...], domain=..., bounds=(...), units=..., description=..., latex=...)` for variables
   - `Expression(name, definition=lambda ...: ..., index=[...], units=..., description=..., latex=...)` for derived expressions
   - `latex=` is the exact LaTeX the paper uses for the symbol (base letter for indexed symbols). It lets the checker confirm each `$$...$$` block's identifiers are registered — the point of onboarding.
   - `Constraint(name, expr=lambda ...: ..., over=..., type=..., description=...)` for constraints
   - `Objective(name, expr=lambda ...: ..., sense=..., description=...)` for objectives
   - End each block with `registry.run_tests()` to validate incrementally.

   Always place the `python:fixture` block immediately before its corresponding `python:validate` block.

   **Before proposing, verify:**
   - No proposed symbol name collides with any previously registered name (including Constraint names — these share the same namespace as Parameters, Variables, etc.)
   - Fixture data covers all index combinations that will be accessed (e.g., if a Constraint iterates over I and references `x[i, j, p]`, the `x` fixture must have entries for ALL I×J×P tuples)

3. **Clarify ambiguity.** If notation is ambiguous (implicit sets, unclear units or domains, undefined subscripts), ask the user to clarify **before** finalizing the block. Do not guess — wait for the user's answer.

4. **Get approval.** Present the proposed block and ask the user to approve it, request changes, or skip it. Do not move to the next section until the user explicitly approves.

5. **Write and validate immediately.** After approval:
   a. Insert the approved fixture + validate blocks into the `.model.md` file, placed immediately after the last `$$...$$` math block in that section.
   b. Run the meta-compiler check on the partial document:
      ```bash
      CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" check "<absolute_output_path>"
      ```
   c. **If the check fails:** Show the errors to the user, fix them in the `.model.md` file, and re-run the check. Repeat until the check passes (errors only — orphan warnings are expected in authoring mode). Do NOT proceed to the next section until the current section's blocks pass validation.
   d. **If the check passes:** Report any LaTeX linkage warnings for the section (they mean the paper's math and the validation code disagree), resolve them with the user, then move to the next section.

### API reference and known constraints

Before writing any `python:fixture` or `python:validate` block, read `${CLAUDE_PLUGIN_ROOT}/references/meta-compiler-api.md`. It documents every symbol type (`Set`, `Parameter`, `Variable`, `Expression`, `Constraint`, `Objective`, `Axiom`, `Property`), the known pitfalls (single-set `over`, no proxy indexing of Expressions, lambda arity), and the single global namespace rule for symbol names.

## Step 7: Final validation

After all sections are processed, run one final full-document check:

```bash
CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" check "<absolute_output_path>"
```

This should pass cleanly (since each section was validated incrementally). If any new errors appear from cross-section interactions, fix them.

## Step 8: Report

Show the validation result and coverage metric to the user.

- **If validation passed:** Confirm success. List any warnings (e.g., orphan symbols that represent terminal outputs of the model).
- **If validation failed:** Show the errors, fix them in the `.model.md` file, and re-run check. Repeat up to 3 times. If still failing after 3 attempts, show the remaining errors and ask the user for guidance.
