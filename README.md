# math-paper-creator

<!-- badges-start -->
![Version](https://img.shields.io/badge/version-0.10.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Claude Code Plugin](https://img.shields.io/badge/Claude%20Code-plugin-blueviolet)
<!-- badges-end -->

A Claude Code plugin that turns mathematical papers into validated, executable models. You describe concepts in natural language — Claude formalizes them into rigorous mathematics with prose, LaTeX display math, and Python validation code, all in a single `.model.md` document. Every symbol is registered exactly once, every equation is tested against concrete data, and every section is validated before the next one begins.

## The Problem

Mathematical papers are written in LaTeX or Markdown, but the math is never tested. A typo in a subscript, an inconsistent variable name, or a constraint that contradicts an earlier definition — these errors are invisible until someone tries to implement the model. By then, the paper and the code have diverged, and reconciling them is expensive.

## The Solution

The meta-compiler embeds executable validation directly inside the paper. A `.model.md` file is a standard Markdown document with two additions:

- **`python:fixture` blocks** — small, realistic test scenarios (3-5 concrete set members with realistic parameter values)
- **`python:validate` blocks** — symbol registrations that declare sets, parameters, variables, expressions, constraints, and objectives using a Python API

When you run the checker, it executes the fixture data against the validation blocks and verifies:

- **No phantoms** — every referenced symbol is declared
- **No collisions** — every symbol name is unique across the entire document (sets, parameters, variables, expressions, constraints, and objectives share one namespace)
- **No index violations** — every indexed symbol references declared sets
- **No cycles** — no circular dependencies between expressions
- **Unit boundaries** — constraints don't mix incompatible units
- **Constraint satisfaction** — every constraint holds against the fixture data
- **Objective evaluation** — every objective produces a numeric value

If any check fails, the error is reported with the source line number. You fix it before moving on.

## Two Workflows

### Author a new paper (`/math-paper-creator:author`)

You describe a problem domain. Claude formalizes it section by section:

1. You provide a concept (vague or specific)
2. Claude writes a complete section: heading, prose, `$$...$$` display math, fixture data, validation code
3. Claude inserts it into the `.model.md` file and runs the checker
4. If the check fails, Claude fixes errors before presenting
5. You approve, request changes, or redirect
6. Next concept builds on the accumulated symbol registry

Each section is validated against all previous sections. A variable defined in section 1 can be referenced in section 5 — the checker ensures consistency across the entire document. A variable can only be defined once.

The author workflow includes template selection — choose a paper type to get a pre-defined section outline and structural checklist tailored to your problem domain.

### Review a paper (`/math-paper-creator:review`)

You have a draft paper (`.md`, `.model.md`, or `.pdf`) and want a mathematical coherence assessment before proceeding. Claude reviews it across five layers:

1. **Core model** — are the foundational definitions sound?
2. **Mathematical completeness** — are there gaps in the formalization?
3. **Internal consistency** — do definitions, constraints, and objectives align?
4. **Structure and organization** — does the paper flow logically?
5. **Prose and presentation** — is the exposition clear and precise?

Findings are saved to a `.review.md` file and can be discussed interactively. The author workflow is aware of review findings — if a review file exists, Claude consults it when writing new sections.

### Onboard an existing paper (`/math-paper-creator:onboard`)

You have a Markdown paper with `$$...$$` display math but no validation. Claude reads it section by section, proposes fixture + validate blocks for each, and inserts them after your approval. Same incremental validation — each section is checked before moving to the next.

## What You Get

When the paper is complete, `/math-paper-creator:compile` produces three artifacts:

| Artifact | What it is |
|----------|------------|
| **`paper.md`** | Clean publishable paper — all validation blocks stripped, only prose and math remain |
| **`runner.py`** | Standalone Python script with all fixture data and validation logic inlined — runs without the paper |
| **`report.txt`** | Validation report: symbol table, dependency graph, coverage metrics, verification levels, test results |
| **`Proofs.lean`** | Lean 4 statements and proofs of the paper's Properties and Theorems (when it has any) |

The `runner.py` gives exactly the same verdict as `check`: it embeds every fixture, results and validate block and runs them through the same engine. It is immediately repeatable. You can run it in CI, share it with collaborators, or use it as the foundation for an implementation — the symbol registrations document every set, parameter, variable, expression, constraint, and objective in the model.

## Installation

### From GitHub
```
/plugin marketplace add reggiechan74/math-paper-creator
/plugin install math-paper-creator@math-paper-creator
```

### Local Development
Clone `reggiechan74/math-paper-creator`, then either load it for a single session:
```
claude --plugin-dir /path/to/math-paper-creator
```
or register the clone as a marketplace (edits take effect after `/reload-plugins`):
```
/plugin marketplace add .
/plugin install math-paper-creator@math-paper-creator
```

Before committing, run the same checks as CI:
```
python -m pytest -q
claude plugin validate --strict .
```

## Skills

Each workflow is a plugin skill, invoked as a slash command. The interactive workflows (`author`, `onboard`, `review`, `compile`, `plain-english`) run only when you invoke them; `check`, `status`, `report` and `paper` can also be used by Claude on its own when relevant.

| Skill | Description |
|---------|-------------|
| `/math-paper-creator:author [file]` | Author a new paper interactively — ideate, formalize, validate section-by-section |
| `/math-paper-creator:onboard <file>` | Convert an existing paper — wrap existing math with validation blocks |
| `/math-paper-creator:review [file]` | Review a draft paper for mathematical coherence — layered assessment with interactive discussion |
| `/math-paper-creator:check <file>` | Run validation pipeline against a `.model.md` document |
| `/math-paper-creator:status <file>` | Show symbol table, coverage, and orphan/phantom status |
| `/math-paper-creator:report <file>` | Generate full validation report |
| `/math-paper-creator:paper <file>` | Generate clean paper artifact (strips validation blocks) |
| `/math-paper-creator:compile <file>` | Produce all artifacts: clean paper, standalone runner, validation report |
| `/math-paper-creator:plain-english <file> [output]` | Generate a plain-English companion with explanation callouts for math-heavy sections |
| `/math-paper-creator:prove <file> [claim ...]` | Machine-check Properties and Theorems in Lean 4 + Mathlib (opt-in, see [Lean proofs](#lean-proofs)) |

## Templates

The author workflow offers 10 paper-type templates, each providing a pre-defined section outline and structural checklist:

| Template | Domain |
|----------|--------|
| Constrained Optimization | LP, IP, MIP, convex, network flow, assignment |
| Statistical Modeling | Regression, time series, Bayesian inference |
| Game-Theoretic Analysis | Nash equilibrium, mechanism design, auctions |
| Simulation Model | Monte Carlo, agent-based, discrete-event |
| Decision Analysis | Decision trees, utility theory, MCDA |
| Financial Pricing | Derivatives pricing, stochastic calculus, term structure |
| Actuarial Model | Life tables, loss distributions, reserving |
| Econometric Model | Structural models, GMM, panel data, IV |
| Queueing Model | M/M/1, networks, scheduling |
| Graph and Network Analysis | Centrality, flow, matching, clustering |

A universal structural checklist applies to all paper types, covering required and advisory items.

## Live Validation

When installed, the plugin automatically validates `.model.md` files every time Claude writes or edits one. Validation errors are hard blocks — Claude must fix them before continuing.

The hook runs in **authoring mode**: symbol conflicts, undefined references, index mismatches, and dimensional errors are hard blocks. Orphan symbols produce warnings only (the symbol may be used in a later section).

## Levels of Evidence

Every claim in a paper carries one of four levels of evidence, shown in the report's **Verification Levels** section:

| Level | Meaning | Produced by |
|-------|---------|-------------|
| **assumed** | An `Axiom`. Stated without proof, but checked against the fixture data: a fixture with `H = -5` fails the axiom `H > 0` | `check` |
| **stated** | A claim that hasn't been verified | — |
| **Z3-checked** | A `Property` that follows from its axioms for *all* real values, not just the fixtures | `check` (Z3) |
| **Lean-proved** | A machine-checked proof in Lean 4 + Mathlib that depends only on Lean's standard axioms | `prove` |

Constraints and objectives are **tested**: they hold on the fixture data.

### Scenarios

Fixture data follows document order. Each section is checked against the data as it stands at that point. A scenario section that reassigns parameters doesn't change what earlier sections were checked against. Instead, earlier constraints and axioms are re-checked under the scenario's values, and violations are reported as warnings ("Under the fixture at line 42 (H: 8.0 → 12.0): ...").

### Linking the math to the code

Give symbols a `latex=` argument with the exact LaTeX the paper uses (`Parameter("beta", ..., latex=r"\beta")`), and the checker cross-references every `$$...$$` block. It warns when the math uses an identifier that no symbol declares, or when a declared symbol never appears in the math. This catches the paper and the validation code drifting apart.

## Lean Proofs

Lean support is **opt-in** because it needs Lean 4 and Mathlib, about 11 GB downloaded once. Enable **Enable Lean proofs** in `/plugin` → math-paper-creator → configure, then start a new session. The plugin installs Lean in the background into its data directory; progress is logged to `setup.log` there.

- **`Property(..., lean_proof=...)`**: the Lean *statement* is generated from the property's Z3 expression, with its `given` axioms as hypotheses. Lean therefore proves exactly what Z3 checked and the data was tested against. Only the proof is written by hand (or by Claude).
- **`Theorem(name, claim=..., lean=...)`**: a hand-written Lean statement, for claims Z3 can't express (derivatives, sums over arbitrary sets, statements for all n). Because the statement is hand-written, the `prove` workflow asks you to approve it as a faithful rendering of the paper's claim before proving it, and the report labels it as hand-written.
- `/math-paper-creator:prove` writes proofs, iterates on Lean's errors, and records results in `<paper>.proofs.json`. Keep that file next to the paper. Each result is tied to the exact claim and proof text, so editing either marks it stale.
- A proof only counts if it depends on nothing beyond Lean's three standard axioms. `sorry`, `native_decide` and smuggled `axiom` declarations are rejected.
- `compile` also writes `Proofs.lean` with every claim's Lean statement and proof.

To use your own Lean install instead, set `MPC_LEAN_PROJECT` to a Lake project that requires Mathlib.

### Approving statements

A proof is only worth something if its statement says what the paper claims. **You** approve that, and the plugin enforces it:

- When you agree that a claim's Lean statement is right, Claude runs `mpc approve`. The plugin then shows you the statement in a `[plugin:math-paper-creator]` confirmation prompt, so only you can complete it. This holds even in bypass-permissions mode.
- An approved statement is **locked**. The plugin refuses edits that would change it: for a Property, its expression, its given axioms or those axioms' expressions; for a Theorem, everything before its proof. Edits to the proofs themselves stay free. `check` reports any change that slips through as an error.
- To change an approved statement, revoke the approval first (`mpc approve --revoke`, which you also confirm), then approve the new version.
- `mpc approvals <paper>` lists each claim as approved, unapproved, or changed. The report marks hand-written Theorems as approved or not.

This guards against a claim being quietly weakened until it becomes provable. It isn't a sandbox: anything outside Claude Code can still edit the files.

### Interactive proof search

With Lean enabled, the plugin also runs a Lean MCP server ([lean-lsp-mcp](https://github.com/project-numina/lean-lsp-mcp), pinned version). It gives `prove` live goal states, multi-tactic attempts and Mathlib lemma search when a proof doesn't close straight away. It needs [uv](https://docs.astral.sh/uv/) (`uvx`). Its lemma-search tools send queries to external search services (LeanSearch, Loogle, LeanFinder). Without Lean, the server offers no tools. If you enable Lean during a session, the tools appear from the next session.

## The API

Every symbol is registered through a Python function call:

```python
from meta_compiler import Set, Parameter, Variable, Expression, Constraint, Objective, S, registry

Set("W", description="Set of workers")

Parameter("cap", index=["W"], domain="nonneg_real", units="hours",
          description="Capacity per worker")

Variable("x", index=["W", "T"], domain="continuous", bounds=(0, 1),
         units="hours", description="Hours assigned")

Expression("load",
           definition=lambda i: sum(x[i, t] for t in S("T")),
           index=["W"], units="hours",
           description="Total load per worker")

Constraint("cap_limit",
           expr=lambda i: sum(x[i, t] for t in S("T")) <= cap[i],
           over="W",
           description="Load cannot exceed capacity")

Objective("total_output",
          expr=lambda: sum(sum(x[i, t] for t in S("T")) for i in S("W")),
          sense="maximize",
          description="Maximize total productive hours")

registry.run_tests()
```

Constraints iterate over a single set via `over`. For multi-index constraints, iterate inner sets inside the lambda. Expression results cannot be indexed in constraint lambdas — inline the computation instead.

## Requirements

[`requirements.txt`](requirements.txt) lists everything. In short:

- **Python 3.10+** available as `python3` on your `PATH`, plus either [uv](https://docs.astral.sh/uv/) or the standard `venv` module (on Debian/Ubuntu: `apt install python3-venv`).
- **Optional, for Lean proofs:** turn on **Enable Lean proofs** (see [Lean Proofs](#lean-proofs)). Installing [elan](https://lean-lang.org/install/) the standard way (`curl https://elan.lean-lang.org/elan-init.sh -sSf | sh`) is recommended, and the plugin reuses it. Allow about 11 GB of disk.

That's all you need to install yourself. On the first session after install, the plugin creates a private virtual environment in its data directory (`~/.claude/plugins/data/<plugin-id>/venv`) and installs its dependencies there in the background:

- **numpy** (>=1.24) — required by the meta-compiler
- **z3-solver** (>=4.12) — axiom verification

The environment survives plugin updates and is rebuilt only when `requirements.txt` changes. Setup output goes to `setup.log` in the same data directory. Until setup finishes, the plugin uses `python3` from your `PATH`; if numpy isn't available there, live validation is skipped with a notice instead of failing.

## License

MIT — see [LICENSE](LICENSE).
