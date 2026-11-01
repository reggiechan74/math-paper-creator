# Changelog

All notable changes to math-paper-creator will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.10.0] - 2026-11-01

### Added
- **Statement approval and locking (Phase 3).** `mpc approve <paper> --name <claim>` records the author's approval of a claim's Lean statement in `<paper>.proofs.json`, pinned by a digest of what fixes its meaning (a Property's expression and given axioms; a Theorem's text before its proof, helper lemmas included)
  - PreToolUse guard (`scripts/guard.py`): denies Write/Edit that would change or remove an approved statement (the edit is simulated first), denies direct edits of `.proofs.json`, and asks the user to confirm `mpc approve`/`--revoke` and shell writes to `.proofs.json`. The confirmation prompt shows the statements and holds even in bypass-permissions mode
  - `check` (and the PostToolUse validation hook) report changed approved statements as errors; `mpc approvals` lists approved/unapproved/changed claims
  - The report marks hand-written Theorems as approved or not; the prove skill no longer re-asks for approved statements
- **Lean MCP server (Phase 2).** `.mcp.json` runs a pinned `lean-lsp-mcp` (0.31.0) against the plugin's Lean project for live goal states, multi-tactic attempts and Mathlib search; without Lean it serves an inactive stub with no tools. `mpc lean --workspace` writes a paper's Lean file into the project for these tools
- The prove skill uses the MCP tools for interactive proof search; `mpc prove` stays the authority

## [0.9.0] - 2026-11-01

### Fixed
- **Fixture data now follows document order.** Previously all fixture blocks ran before any validation, so a later scenario section that reassigned a parameter silently changed the data every earlier section was checked against. Each validation block (and results block) now sees the data as it stands at its position; names defined only later fall back to their first definition
- **Axioms are checked against the fixture data.** Z3 constants are linked to Parameters by name (`Real("H")` ↔ `Parameter("H")`), so a fixture that violates a declared axiom is an error. Previously the axioms and the data could contradict each other silently
- **`runner.py` works and checks constraints.** The generated runner crashed on start-up (circular import), and even if fixed it never evaluated constraints, axioms or objectives numerically. It now embeds the document's blocks and runs them through the same engine as `check`
- `Axiom`/`Property` documents without z3 installed now warn that verification was skipped

### Added
- Scenario re-checks: constraints and axioms registered before a fixture that redefines data are re-evaluated under the new values; violations are reported as warnings
- `latex=` on Set/Parameter/Variable/Expression, and LaTeX ↔ symbol linkage warnings (opt-in, active once any symbol declares `latex=`)
- `mpc symbols [--json]`: the document's symbol table, used by the skills instead of tracking names in context
- **Lean 4 verification tier** (opt-in `enable_lean` option, ~11 GB):
  - `Property(..., lean_proof=...)` with a Lean statement generated from the Z3 expression and the given axioms
  - `Theorem(name, claim=..., lean=...)` for claims Z3 cannot express
  - `mpc lean` (print generated Lean) and `mpc prove` (check with Lean; results cached in `<paper>.proofs.json`, keyed by a hash of the exact source)
  - Proofs count only if they depend on Lean's standard axioms alone (`sorry` and smuggled `axiom`s are rejected)
  - `/math-paper-creator:prove` skill; report **Verification Levels** section; `Proofs.lean` compile artifact
  - Pinned Lake project template (`lean/`) installed in the background by the SessionStart hook
- Fixed a circular import between `checks` and the compiler package

## [0.8.0] - 2026-10-31

### Changed
- Migrated all nine slash commands from legacy `commands/` to `skills/<name>/SKILL.md`. Invocation names are unchanged (`/math-paper-creator:<name>`)
- Interactive skills (`author`, `onboard`, `review`, `compile`, `plain-english`) set `disable-model-invocation: true` so they run only when invoked explicitly
- Skills take arguments via `$ARGUMENTS` instead of the non-standard `arguments:` object list
- Meta-compiler API reference moved to a shared `references/meta-compiler-api.md` (the onboard copy had a stale note on scalar parameters); plain-english callout templates moved to a supporting file
- PostToolUse validation hook uses exec form and `if` filters, so it only starts for `.model.md` writes/edits; timeout raised from 30s to 120s
- Version is declared only in `plugin.json` (removed from the marketplace entry); `pyproject.toml` now tracks the plugin version
- Removed the redundant `commands` key from `plugin.json`

### Fixed
- Skills no longer `cd` into the plugin directory before running the CLI. Relative document paths previously resolved against the plugin install directory, and `compile`'s default `./output` was written there
- Validation hook reports a missing Python dependency as context instead of failing with a traceback

### Added
- `scripts/mpc` launcher for the meta-compiler CLI (works from any directory, uses the managed environment when ready)
- SessionStart hook (`scripts/setup_env.py`) that provisions a venv with numpy and z3-solver in `${CLAUDE_PLUGIN_DATA}` in the background
- `requirements.txt`, `LICENSE` (MIT), plugin icon, `displayName`
- GitHub Actions CI: pytest on Python 3.10/3.13 and `claude plugin validate --strict`
- Plugin packaging tests (`tests/plugin/test_plugin_layout.py`)

## [0.7.0] - 2026-03-21

### Fixed
- Unit checker now uses AST-based dimensional algebra instead of pairwise string comparison — `*`/`/` combine units correctly, only `+`/`-`/comparisons require matching units (#12)
- Constraint `NameError` for unregistered fixture variables now suggests adding a `Parameter()` registration instead of the misleading "name is not defined" (#14)

### Added
- `--skip-validation` flag for the `paper` subcommand — generate papers without running validation (#13)

## [0.6.0] - 2026-03-21

### Added
- `Axiom` and `Property` symbol types for declaring foundational axioms and derived properties
- Z3-based verification module (`verification.py`) with consistency and implication checking
- `verify` CLI subcommand for standalone Z3 axiom verification
- Axiom/Property support in registry, executor, report, and orphan checks
- z3-solver as optional dependency via `[verification]` extra
- Axiom authoring workflow in author command (Step 2) and verification output in completion (Step 4)

## [0.5.0] - 2026-03-21

### Added
- Prose-math reconciliation checkpoint in author skill section loop (#11)
- `reconcile` CLI subcommand with `--section` scoping flag
- `check_directional_claims` — flags directional keywords in prose for manual verification
- `check_value_reporting` — warns when computed values are absent from prose
- `check_constraint_tolerance` — flags suspiciously large arithmetic offsets in constraints via AST inspection
- `extract_section_blocks` parser helper for section-level block scoping

## [0.4.1] - 2026-03-21

### Fixed
- Constraint evaluation now accepts `np.True_` from numpy-backed computations (#9)
- Scalar auto-unwrap detects `np.float64`/`np.int64` instead of wrapping them as `SymbolProxy` (#9)
- Objective numeric check accepts numpy scalar types (#9)

## [0.4.0] - 2026-03-20

### Added
- **Epistemic hygiene checks** — scope declaration prompt at Step 2 with `epistemic_type` stored in frontmatter (#8)
- Parameter provenance batch prompt (data / literature / illustrative) at Step 3.2 (#8)
- Scenario decomposition flag for multi-parameter changes at Step 3.2 (#8)
- Epistemic language scan at Step 4, calibrated by paper type (#8)
- Four-tests conclusion frame for structural/decision framework papers at Step 4 (#8)
- Four advisory checklist items for epistemic completeness (#8)
- Expr-based dependency tracing for scalar models in report dependency graph (#7)

### Changed
- Orphan checking fully suppressed for scalar models (no Sets) — no more warning noise in reports
- Scalar parameter API note updated in author skill to reflect v0.3.0 auto-unwrap

## [0.3.0] - 2026-03-20

### Added
- **Scalar model support** — scalar fixture values (int, float, str) are auto-unwrapped as raw Python types instead of SymbolProxy, enabling `M * beta` arithmetic directly in expressions (#3)
- `collect_scalar_refs()` helper in checks.py for tokenizer-based scalar access logging
- `--no-strict` CLI flag for `compile`, `paper`, and `report` subcommands (#4)
- `strict` parameter on `compile_document()` (default `True`) for programmatic control (#4)
- `Report.__str__()` delegating to `to_text()` — `str(report)` and `print(report)` now work as expected (#5)

### Changed
- **Strict mode auto-detection** — when no `Set` symbols are registered, orphan warnings are automatically demoted from errors to warnings in strict mode (#4)
- `generate_report` signature: `(blocks, *, registry, test_result=None)` — `blocks` is now the first positional arg, `registry` is keyword-only (**breaking**) (#6)
- `generate_runner` signature: `(blocks, *, model_path="model.model.md")` — `blocks` is now the first positional arg, `model_path` is keyword-only with default (**breaking**) (#6)
- `Registry.data_store` type annotation broadened from `dict[str, dict]` to `dict[str, Any]`

## [0.2.0] - 2026-03-14

### Added
- Template system for 10 mathematical paper types (optimization, statistical, game-theoretic, simulation, decision-analysis, financial-pricing, actuarial, econometric, queueing, graph-network)

## [0.1.0] - 2026-03-10

### Added
- Initial release with meta-compiler v2, interactive authoring workflow, and validation engine
