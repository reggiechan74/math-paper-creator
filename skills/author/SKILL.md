---
name: author
description: Author a new validated math paper (.model.md) interactively — ideate, formalize into prose, LaTeX and Python validation blocks, and validate section by section. Also resumes an existing .model.md.
argument-hint: "[path-to-file.model.md | path-to-file.review.md]"
allowed-tools: Bash Read Write Edit Glob
disable-model-invocation: true
---

# Author a Math Paper

Create a new `.model.md` document through interactive ideation. You describe concepts — Claude formalizes them into complete paper sections with prose, display math, and validated Python blocks. Each section is written and validated before moving on.

**Arguments:** `$ARGUMENTS`

**Paths:** Resolve every file path to an absolute path before passing it to the CLI (relative paths are relative to the user's working directory). Run the CLI exactly as shown below via `"${CLAUDE_PLUGIN_ROOT}/scripts/mpc"` — never `cd` into the plugin directory.

**Symbol table:** to see which symbols exist (names, kinds, indices, units, LaTeX, defining line), run:

```bash
CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" symbols --json "<absolute_file_path>"
```

Use it whenever you need symbol names; never keep your own running list.

## Step 1: Initialize

**New paper** (no path given, or file doesn't exist):

0. **Check for review findings.** If the user provides a `.review.md` file as the path argument, or if a `<basename>.review.md` file exists adjacent to the target `.model.md` path, read the review findings. These contain a recommended template, outline, and key decisions from a prior `/math-paper-creator:review` session. Tell the user: "I found review findings from a prior session. I'll use these to guide template selection and authoring." Skip items 1-3 below and proceed directly to Step 1.5 with the review context loaded. If no review file is found, continue with item 1.
1. Ask the user to describe the problem domain. Accept anything from a vague concept ("I want to model workforce optimization under constraints") to a specific sketch ("I have sets I, J, P and an allocation variable x_ijp").
2. Create the `.model.md` file with YAML frontmatter:
   ```yaml
   ---
   title: <derived from user description>
   date: <today>
   author: <ask or infer>
   version: 0.1
   ---
   ```
3. The document's symbol table is the source of truth for symbol names. Never track it from memory — query it whenever you need it (see **Symbol table** below).
4. Proceed to Step 2.

**Resume** (path to an existing `.model.md` file):

1. Read the file.
2. Run the meta-compiler check to rebuild the symbol state:
   ```bash
   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" check "<absolute_file_path>"
   ```
3. Load the symbol table (see **Symbol table** below).
4. Show the user a summary: number of sections, symbol count by type, any warnings.
5. Ask where they want to continue. Proceed to the authoring loop (Step 3).

## Step 1.5: Template selection

After initialization (Step 1), present the template catalog:

1. Read the template files from `${CLAUDE_PLUGIN_ROOT}/templates/`. List the 10 templates + "Other" as a numbered menu:
   ```
   Select a paper type:
    1. Constrained Optimization — LP, IP, MIP, convex, network flow
    2. Statistical Modeling — regression, time series, Bayesian inference
    3. Game-Theoretic Analysis — Nash equilibrium, mechanism design, auctions
    4. Simulation Model — Monte Carlo, agent-based, discrete-event
    5. Decision Analysis — decision trees, utility theory, MCDA
    6. Financial Pricing — derivatives pricing, stochastic calculus, term structure
    7. Actuarial Model — life tables, loss distributions, reserving
    8. Econometric Model — structural models, GMM, panel data, IV
    9. Queueing Model — M/M/1, networks, scheduling
   10. Graph and Network Analysis — centrality, flow, matching, clustering
   11. Other — describe your paper and I'll generate a custom outline
   ```

2. **If preset (1–10):** Read the selected template file. Show the full section outline. Ask the user if they want to reorder, remove, or add sections before proceeding. Accept the outline as-is or with modifications.

3. **If "Other" (11):** Run a discovery conversation:
   - What is the paper about?
   - What are the major parts or layers?
   - What mathematical structures are involved?

   From the answers, generate a custom outline following the template format (section headings, descriptions, `**Symbols:**` types, `(optional)` markers). Present for approval.

4. Store the template name and working outline in the `.model.md` frontmatter:
   ```yaml
   ---
   title: Workforce Optimization Model
   date: 2026-03-14
   template: optimization        # or "custom" for Other
   outline:
     - Introduction
     - Sets and Indices
     - Parameters
     - Decision Variables
     - Derived Expressions
     - Constraints
     - Objective Function
     - Conclusion
   ---
   ```

5. Proceed to Step 2.

**Review findings behavior:** When review findings are loaded (from Step 1), use the recommended template and outline from the findings file instead of presenting the template selection menu. Show the recommended template and outline to the user: "Based on your review session, I'm using the [template] template with this outline: [outline]. Want to adjust anything before we start?" Accept confirmation or modifications, then proceed to Step 2.

**Resume behavior:** When resuming an existing `.model.md` that has `template` and `outline` fields in its frontmatter, skip template selection. Compare the outline against sections already written to determine which remain. If the file has no `template`/`outline` fields (pre-template file), offer to select a template or continue without one.

## Step 2: Opening section

Write an Introduction section into the `.model.md` file based on the user's initial description. This section contains:
- A `#` heading and introductory prose explaining the problem domain
- No math blocks or validation blocks (the Introduction frames the problem; formalization begins in subsequent sections)

Write it to the file immediately. Ask the user to approve, revise, or redirect.

### 2.1 Scope declaration

After the Introduction is approved, prompt:

> "What type of model is this paper? (1) Empirical — estimated from observed data, (2) Structural/theoretical — specifies mechanisms and derives consequences from assumptions, (3) Decision framework — helps reason more clearly even when exact calibration is unavailable."

If the user declines or says "skip", default to `structural` (the most conservative framing).

Store the choice in the YAML frontmatter:
```yaml
epistemic_type: structural  # or empirical, decision_framework
```

Generate a `**Scope and epistemic status:**` paragraph and append it to the Introduction section. Tailor by type:

- **Empirical:** "Parameters are estimated from observed data. Results reflect empirical regularities in the sample."
- **Structural / Decision framework:** "Parameters are illustrative, not estimated from observational data. Scenario outputs are model-implied examples, not observed outcomes."

Write the paragraph to the file, then continue to the axiom declaration (if applicable) or the authoring loop.

#### Axiom Declaration (structural / decision_framework papers only)

If `epistemic_type` is `structural` or `decision_framework`, prompt:

> "Would you like to declare foundational axioms for this model? Axioms are explicit assumptions stated without proof — everything else derives from them. (Recommended for structural papers.)"

If accepted, the first authoring section (before Parameters) is "Axioms and Assumptions." For each axiom:
- Prose statement explaining the assumption
- Display math: `$$H > 0$$`
- `python:validate` block registering: `Axiom("A1", statement="H > 0", z3_expr=lambda: zH > 0, description="...")`
- The `z3_expr` is optional — include it if Z3 verification is desired

Declare Z3 constants in the `python:validate` block (not in fixture blocks), **named exactly like the Parameter they stand for** but bound to a different Python name, so the Parameter keeps its fixture value:
```python
from z3 import Real
zH = Real("H")   # Z3 name "H" links to Parameter "H"
Axiom("A1", statement="H > 0", z3_expr=lambda: zH > 0, description="...")
```

Because the Z3 name matches the Parameter, the checker also tests every axiom against the fixture data: a fixture with `H = -5` fails `A1`. Never write `H = Real('H')` — that replaces the Parameter's value in later constraints.

**Lean proofs (optional).** Once a Property passes the Z3 check, it can also be machine-checked in Lean with `/math-paper-creator:prove`. This works if the user enabled the plugin's **Enable Lean proofs** option. For claims Z3 cannot express, such as derivatives (comparative statics), sums over arbitrary sets, or statements for all n, register a `Theorem` with a Lean statement instead (see the API reference). Before registering a Theorem, show the user its Lean statement with a plain-English reading and get explicit approval that it says what the paper claims. Use `sorry` as the proof until `/math-paper-creator:prove` fills it in. When the user approves, record it, and the plugin will ask them to confirm:

```bash
CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" approve "<absolute_file_path>" --name <claim>
```

Once approved, a statement is locked: the plugin refuses edits that would change it until the user revokes the approval (`approve --revoke`, which they also confirm).

**Review findings path:** If the paper was loaded from review findings (Step 1, item 0), the scope declaration prompt still fires — review findings do not set `epistemic_type`.

## Step 3: Authoring loop

Repeat for each concept the user wants to formalize:

### 3.1 Receive input

The user provides the next concept. This can be:
- A vague idea: "I need a way to measure employee reliability"
- A specific sketch: "Define R_i as a proxy score on {0, 4, 8, 12}"
- A relationship: "Total load should not exceed capacity"
- A request for suggestion: "What would this model need next?"

If the user asks what's needed next, combine three sources into a single suggestion:

1. **Template outline:** Check the outline (from frontmatter) for the next unwritten section. Suggest it by name and describe what goes there.
2. **Structural checklist:** Read `${CLAUDE_PLUGIN_ROOT}/templates/_checklist.md` and scan the Required items against the current document. Surface any structural gaps (e.g., "no computable output yet — consider adding an Expression, Constraint, or Objective").
3. **Symbol table:** Load the symbol table and suggest what a complete model typically requires (e.g., "You have sets and parameters but no constraints or objective yet").

Present all three as a unified recommendation, not three separate lists.

### 3.2 Formalize

Write a complete section consisting of:

a. **Section heading** (`##` or `###` as appropriate)

b. **Prose** — paper-quality narrative explaining the concept, its motivation, its relationship to previously defined symbols, and any assumptions or domain constraints.

c. **Display math** — `$$...$$` blocks with the formal mathematical definitions.

d. **`python:fixture` block** — realistic test data with 3-5 concrete members per set. Fixture data must cover ALL index combinations that will be accessed by the validate block. Reuse set members from earlier fixtures for consistency (e.g., if employees are `["alice", "bob", "carol"]` in section 1, use the same names throughout).

e. **`python:validate` block** — register the symbols using the meta-compiler API:
   - `Set`, `Parameter`, `Variable`, `Expression`, `Constraint`, `Objective`
   - End with `registry.run_tests()`

#### Parameter provenance

When a `python:fixture` block assigns values to Parameters, prompt for provenance. For blocks with multiple parameters, present all in a batch:

> "How were these parameter values determined?
> | Parameter | Value | Provenance |
> |-----------|-------|------------|
> | H | 8.0 | (a) data, (b) literature, (c) illustrative? |
> | beta | 0.75 | (a) data, (b) literature, (c) illustrative? |"

Use the response to frame the prose near each parameter definition:
- **(a) Estimated from data:** "Estimated from [source]..." (ask for source)
- **(b) Literature:** "Following [Author] ([year]), we set..." (ask for citation)
- **(c) Illustrative:** "We adopt [value] as a representative value..."

#### Scenario decomposition flag

When formalizing a scenario or sensitivity analysis section whose fixture block changes 2 or more parameters that were already defined in earlier fixtures, flag:

> "This scenario modifies [N] parameters at once ([list]). The combined effect should be decomposed — show each factor's contribution separately before reporting the total. Or say 'combined is fine' if these parameters are genuinely inseparable."

If decomposition is accepted, structure the section to show each parameter's individual effect before the combined result. This only applies to scenario/sensitivity sections, not initial parameter definitions.

#### Link the math to the symbols

Give every Set, Parameter, Variable and Expression a `latex=` argument holding the exact LaTeX used for it in the section's `$$...$$` blocks: the base letter for indexed symbols (`latex="x"` for $x_{ij}$), the full form for decorated scalars (`latex=r"c_{\max}"`, `latex=r"\bar{w}"`). The checker then warns when the math uses an identifier no symbol declares, or a declared symbol never appears in the math. Treat those warnings as defects in the section: fix the math or the registrations before presenting.

#### Scenario sections

Fixture data follows document order. A scenario section that reassigns earlier parameters in its own `python:fixture` block does **not** change the data earlier sections were checked against. The checker re-runs earlier constraints and axioms under the scenario's values and reports violations as warnings ("Under the fixture at line N (H: 8.0 → 12.0): ..."). Report those warnings to the user and say in the prose whether the scenario is meant to stay within the base model's assumptions.

### 3.3 Check names

Before presenting the section to the user, verify:
- No proposed symbol name collides with any name in the symbol table (load it fresh — don't rely on memory)
- All index sets referenced in `Parameter`, `Variable`, `Expression` are already registered (or being registered in this block)
- Constraint names are distinct from all other symbol names (they share the global namespace)

If a collision is detected, rename the new symbol before presenting.

### 3.4 Present and get approval

Show the complete section to the user. Ask them to approve, request changes, or skip.

**Do not proceed until the user explicitly approves.**

### 3.5 Write and validate

After approval:

1. Insert the section into the `.model.md` file at the end (before any Conclusion section if one exists).

2. Run the meta-compiler check on the full document:
   ```bash
   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" check "<absolute_file_path>"
   ```

3. **If the check fails:** Show the errors, fix them in the `.model.md` file, and re-run. Repeat until the check passes (errors only — orphan warnings are expected). Do NOT proceed to the next section until the current one passes.

4. **Prose-math reconciliation.** After the meta-compiler check passes, run reconciliation checks scoped to the current section:
   ```bash
   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" reconcile "<absolute_file_path>" --section "<heading>"
   ```
   - If warnings are printed, show them to the user.
   - Then show the manual reconciliation prompt:
     > "Reconciliation check:
     > - Do the interpretation paragraphs match the computed values?
     > - Are spatial/directional claims consistent with the boundary values?
     > - Are any claims made about variables that don't appear in the section's equations?
     >
     > Type 'confirmed' to proceed, or describe issues."
   - If the user describes issues: revise the section in `.model.md`, re-run the meta-compiler check (item 2 above), then re-run reconciliation.
   - If the user confirms: proceed to the next item.

5. **If the check passes:** Tell the user the section is validated, mention any new warnings (LaTeX linkage, scenario re-checks), and ask for the next concept.

### 3.6 Between sections

At any point between sections, the user may:

- **View the symbol table:** Run `status`, or load the symbol table and summarize it.
- **Revise a previous section:** Edit the section in place (modify prose, math, or validation blocks), then re-run the full-document check to ensure consistency.
- **Ask for suggestions:** Claude reviews the current model and suggests what's missing or what could be strengthened.
- **Signal completion:** Say "done", "that's all", or similar. Proceed to Step 4.

## Step 4: Completion

When the user signals they are done:

1. Run a final full-document check:
   ```bash
   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" check "<absolute_file_path>"
   ```

2. **Epistemic language scan.** Before showing the summary, scan the full `.model.md` text for language that may overstate epistemic status. Flag instances with suggested replacements:

   | Pattern | Suggestion |
   |---------|------------|
   | "the model proves" | "the model shows that, under these assumptions" |
   | "demonstrates that" (in empirical-sounding context, not formal math proofs) | "illustrates that" or "model-implied analysis suggests" |
   | "findings" (for scenario outputs) | "implications under illustrative calibration" |
   | "the math says" | "under these assumptions" |
   | "yields [N] results/findings" | "yields [N] implications" |

   Pattern matching is case-insensitive, whole-word. Use context to avoid false positives — "Theorem 3 demonstrates that" in a formal proof context should not be flagged.

   Calibrate framing by `epistemic_type` (from frontmatter):
   - `empirical`: "Review these — they may be appropriate for an empirical paper."
   - `structural` / `decision_framework`: "These may overstate what the model has earned."

   Present flagged instances with line context and suggestions. Do not auto-fix — let the author decide which to change. Offer to apply accepted changes.

3. **Four-tests conclusion frame** (conditional). Only offer for `epistemic_type: structural` or `decision_framework`. Skip for `empirical`.

   > "For a formalization-of-intuition paper, the conclusion can be strengthened by stating which formal tests the intuition passed. Would you like me to evaluate against the four-tests framework?"

   If accepted, evaluate the model qualitatively against:
   1. **Non-contradiction** — do the variables interact coherently without logical inconsistencies?
   2. **Mechanistic plausibility** — does the model have a causal structure rather than a curve-fit?
   3. **Comparative statics** — do parameter changes shift the optimum in the expected direction?
   4. **Organizational/domain interpretability** — can a practitioner inspect the result and understand *why* it occurs?

   Generate a conclusion paragraph reporting which tests pass, framed as: "The model does not identify the true empirical optimum. It formalizes a [common intuition] and shows that, under reasonable structural assumptions, [the core claim]."

   Tests 1-2 are partially inferable from meta-compiler validation (no cycles, explicit mechanisms). Tests 3-4 require reading scenario sections and prose.

#### Axiom Verification (if Z3 expressions present)

If any Axiom symbols have `z3_expr`, the executor automatically:
1. Checks axiom consistency
2. Checks property implications
3. Reports results in the completion summary:

```
Axiom verification (Z3):
  ✓ Axioms A1-A4 are consistent (sat in 0.02s)
  ✓ Property P1 follows from A1, A2, A3
  ✗ Property P2 does NOT follow from A1, A2 — counterexample: H=1, M=1, beta=2
```

Reference Z3 results in the four-tests conclusion frame:
- Test 1 (Non-contradiction): cite axiom consistency check
- Test 3 (Comparative statics): cite monotonicity verification if applicable

4. Show a summary:
   - Total sections with math blocks
   - Symbol count by type (Sets, Parameters, Variables, Expressions, Constraints, Objectives)
   - Any warnings (orphan symbols, etc.)
   - Epistemic language scan results (if any flagged)
   - **Structural checklist results:** Read `${CLAUDE_PLUGIN_ROOT}/templates/_checklist.md` and evaluate every item against the document:
     - **Required items:** Show pass/fail status for each. Failed items are warnings — the user should address them but they don't block compilation.
     - **Advisory items:** Show any that match as informational notes.

5. Ask the user:
   > "Would you like me to compile now? This produces a clean paper (prose + math only), a standalone runner.py (all validation logic as a self-contained script), and a validation report. Or you can do this later with `/math-paper-creator:compile`."

6. If the user wants to compile, run:
   ```bash
   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" compile "<absolute_file_path>" --output "<absolute_output_dir>"
   ```
   Show what was generated. If strict-mode validation fails (orphan errors), offer to fix or compile without strict.

## API reference and known constraints

Before writing any `python:fixture` or `python:validate` block, read `${CLAUDE_PLUGIN_ROOT}/references/meta-compiler-api.md`. It documents every symbol type (`Set`, `Parameter`, `Variable`, `Expression`, `Constraint`, `Objective`, `Axiom`, `Property`), the known pitfalls (single-set `over`, no proxy indexing of Expressions, lambda arity), and the single global namespace rule for symbol names.
