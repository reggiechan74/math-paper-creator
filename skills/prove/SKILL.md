---
name: prove
description: Machine-check the claims of a .model.md paper in Lean 4 + Mathlib — write Lean proofs for Properties (whose Lean statements are generated from their Z3 expressions) and for hand-written Theorems, iterate on Lean's errors, and record results in <paper>.proofs.json.
argument-hint: "<path-to-file.model.md> [claim-name ...]"
allowed-tools: Bash Read Edit Glob
disable-model-invocation: true
---

# Prove Claims in Lean

Raise claims in a `.model.md` paper to the strongest level of evidence: **assumed < stated < Z3-checked < Lean-proved**. A Lean proof is accepted only when Lean checks it *and* it depends on no axioms beyond Lean's standard three, so `sorry`, `admit`, `native_decide` and smuggled `axiom` declarations never count.

**Arguments:** `$ARGUMENTS`

**Paths:** Resolve every file path to an absolute path before passing it to the CLI (relative paths are relative to the user's working directory). Run the CLI exactly as shown, via `"${CLAUDE_PLUGIN_ROOT}/scripts/mpc"` — never `cd` into the plugin directory.

## Rules — read before writing any proof

1. **Never change what is being proved to make a proof go through.** Don't edit a Property's `z3_expr`, `claim` or `given` list, or a Theorem's statement. If a claim looks false or needs an extra assumption, stop and tell the user what is missing (e.g. "this needs `H > 0`, which A2 doesn't give") and let them decide.
2. A Property's Lean statement is **generated** from its Z3 expressions: its hypotheses are exactly its `given` axioms, named after them (`A1`, `A2`, …). You only write the proof, in `lean_proof=`.
3. A **Theorem** has a hand-written statement. Before proving a new Theorem, show the user its Lean statement together with a plain-English reading of it, and get explicit approval that it says what the paper claims. Pay special attention to quantifiers, strict vs. non-strict inequalities, domains (ℝ vs ℕ), and division (in Lean `x / 0 = 0`).
4. Don't write `sorry`, `admit`, `native_decide`, or new `axiom`s. They're rejected anyway.
5. If a claim can't be proved after about six honest attempts, stop on that claim. Leave its proof out rather than committing a failing one, and report the last Lean error.

## Steps

### 1. Check what needs proving

```bash
CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" prove --json "<absolute_file_path>"
```

- **Exit code 3:** Lean isn't available. Tell the user to enable the plugin's **Enable Lean proofs** option (`/plugin` → math-paper-creator → configure), start a new session, and wait for the one-time ~11 GB download, which is logged in the plugin data directory's `setup.log`. Alternatively, they can set `MPC_LEAN_PROJECT` to their own Lake project that requires Mathlib. Stop here.
- **Exit code 1:** the document doesn't validate. Fix it first; run `/math-paper-creator:check`.
- Otherwise each claim has a status: `proved`, `sorry` (no proof yet), `failed`, `untranslatable`, or `error`.

If the arguments name specific claims, work only on those.

Skip any Property that the regular check reports as `does NOT follow from …`: Z3 found a counterexample, so the claim is false under its axioms. Report the counterexample to the user instead.

For `untranslatable` Properties (the Z3 expression uses something with no Lean counterpart), explain why, and offer to restate the claim as a `Theorem`, subject to rule 3.

### 2. Read the generated statement

```bash
CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" lean "<absolute_file_path>" --name <claim>
```

### 3. Write the proof

Put the tactic proof in the Property's `lean_proof=` argument in its `python:validate` block. Use a raw triple-quoted string for multi-line proofs:

```python
Property("P1", claim="beta (H - M) >= 0", z3_expr=lambda: zb * (zH - zM) >= 0,
         given=["A2", "A3"], description="...",
         lean_proof=r"""
obtain ⟨hM0, hMH⟩ := A2
obtain ⟨hb0, hb1⟩ := A3
exact mul_nonneg hb0.le (by linarith)
""")
```

For a Theorem, edit the proof part of its `lean=` source only.

Tactics that close most claims in these papers:

| Goal shape | Try |
|---|---|
| Linear (in)equalities from hypotheses | `linarith` |
| Products and squares | `nlinarith [sq_nonneg (a - b), mul_pos ha hb, mul_nonneg ha hb]` (feed it the products it needs) |
| "Obviously positive" terms | `positivity` |
| Fractions | `rw [div_le_iff₀ hpos]` / `field_simp` then `ring_nf` / `nlinarith` |
| Monotone in one argument | `gcongr` |
| Numeric facts | `norm_num` |
| Algebraic identities | `ring` / `ring_nf` |
| Derivatives (Theorems) | `simp`, `deriv_const_mul`, `HasDerivAt` lemmas, then `ring` |

Conjunction hypotheses (axioms like `0 ≤ M ∧ M ≤ H`) must be split first with `obtain ⟨h1, h2⟩ := A2`. Look up Mathlib lemma names with `exact?` in a scratch attempt, but remove it before committing because it is slow.

### 4. Check, read errors, iterate

```bash
CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" prove --json "<absolute_file_path>" --name <claim>
```

Errors come with the line relative to the theorem and the goal state. Fix the proof and rerun. One run checks every selected claim at once, in a few seconds.

### 5. Finish

Run `prove` once more without `--name`, so that `<paper>.proofs.json` records every claim against the current text. Then show the evidence summary:

```bash
CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" report --no-strict "<absolute_file_path>"
```

Report the **Verification Levels** section to the user: which claims are Lean-proved, which remain Z3-checked and why, and any claim that needs a decision from them (rules 1 and 5). Remind them to keep `<paper>.proofs.json` next to the paper. Results are tied to the exact claim and proof text, so editing either one marks the result stale until `prove` runs again.
