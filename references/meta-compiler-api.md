# Meta-compiler API reference and known constraints

Shared reference for the `author` and `onboard` skills. Every `python:validate` block in a `.model.md` document uses this API; `python:fixture` blocks supply the concrete test data.

```python
from meta_compiler import Set, Parameter, Variable, Expression, Constraint, Objective, S, Axiom, Property, Theorem, registry

# Every Set/Parameter/Variable/Expression takes latex= — the exact LaTeX the
# paper uses for it (base letter for indexed symbols). The checker warns when
# the $$...$$ math and the registered symbols disagree.

# Sets — fixture data must be a list
Set("W", description="Set of workers", latex="W")

# Parameters (indexed, with units) — fixture data must be a dict
Parameter("cap", index=["W"], domain="nonneg_real", units="hours",
          description="Capacity per worker", latex=r"\bar{c}")

# Variables (indexed, with bounds) — fixture data must be a dict
Variable("x", index=["W", "T"], domain="continuous", bounds=(0, None),
         units="hours", description="Hours assigned", latex="x")

# Expressions — define derived quantities
# NOTE: Expression results are NOT available through proxy indexing.
# You cannot do `load[i]` in a Constraint lambda — the proxy only
# looks up fixture data, and Expressions have no fixture data.
# Instead, inline the computation in Constraints/Objectives.
Expression("load",
           definition=lambda i: sum(x[i, t] for t in S("T")),
           index=["W"], units="hours",
           description="Total load per worker")

# Constraints — lambda must take exactly ONE positional argument
# The `over` parameter accepts a SINGLE set name (not a list of sets).
# For multi-index iteration, use `over` for the outer set and iterate
# inner sets inside the lambda body.
Constraint("cap_limit",
           expr=lambda i: sum(x[i, t] for t in S("T")) <= cap[i],
           over="W",
           description="Load cannot exceed capacity")

# WRONG — multi-set `over` does not work:
#   over=["W", "T"]  ← only uses first element, lambda gets 1 arg
#
# WRONG — Expression proxy indexing does not work:
#   expr=lambda i: load[i] <= cap[i]  ← raises "No fixture data for 'load'"
#
# RIGHT — inline the expression computation:
#   expr=lambda i: sum(x[i, t] for t in S("T")) <= cap[i]

# For multi-set constraints, iterate inner sets inside the lambda:
Constraint("demand",
           expr=lambda j: all(
               sum(x[i, j, p] for i in S("W")) >= d[j, p]
               for p in S("P")
           ),
           over="J",
           description="Demand coverage for every project type and team")

# Scalar parameters in Objective/Constraint lambdas:
# Scalar fixture values (int, float, str) are auto-unwrapped as raw
# Python types, so arithmetic works directly: M * beta, H - M, etc.
# No need to extract from registry.data_store for scalars.

# Axioms — foundational assumptions (z3_expr optional, for machine verification)
# Name each Z3 constant exactly like its Parameter ("H"), but bind it to a
# different Python name (zH) so the Parameter keeps its fixture value.
# The Z3 name links the axiom to the data: a fixture with H = -5 fails A1.
from z3 import Real
zH, zM = Real("H"), Real("M")
Axiom("A1", statement="H > 0", z3_expr=lambda: zH > 0, description="Positivity")

# Properties — derived claims that follow from axioms
Property("P1", claim="H - M >= 0",
         z3_expr=lambda: zH - zM >= 0,
         given=["A1", "A2"],
         description="Non-negative effective time")

# Lean proofs (optional; needs the plugin's "Enable Lean proofs" option).
# A Property's Lean statement is GENERATED from its z3_expr, with its given
# axioms as hypotheses named A1, A2, ... — you only write the tactic proof:
Property("P2", claim="H - M <= H",
         z3_expr=lambda: zH - zM <= zH,
         given=["A2"],
         description="Meetings never add time",
         lean_proof=r"""
obtain ⟨hM0, hMH⟩ := A2
linarith
""")

# Claims Z3 cannot express (derivatives, sums over arbitrary sets, all n)
# are stated directly in Lean 4. Mathlib is imported; declare `theorem <name>`.
# The statement is hand-written, so the user must approve it as faithful.
Theorem("T1", claim="Output rises with focus: d/dβ [β (H - M)] = H - M",
        lean=r"""
theorem T1 (H M : ℝ) :
    deriv (fun b : ℝ => b * (H - M)) = fun _ => H - M := by
  funext b
  simp
""", description="Comparative statics of effective time in beta")

# Objectives — lambda takes ZERO arguments
Objective("total_output",
          expr=lambda: sum(
              sum(x[i, t] for t in S("T"))
              for i in S("W")
          ),
          sense="maximize",
          description="Maximize total productive hours")

# Always end with
registry.run_tests()
```

## Symbol naming rules

All symbol types (Sets, Parameters, Variables, Expressions, Constraints, Objectives, Axioms, Properties) share a **single global namespace**. A Constraint named `"capacity"` collides with a Parameter named `"capacity"`. Use distinct, descriptive names:
- Constraints: `"cap_limit"`, `"demand_coverage"`, `"effort_capacity"`
- Parameters: `"cap"`, `"capacity_hours"`, `"d_min"`

## Fixture data follows document order

Fixture and results blocks run top to bottom, and each validation block is checked against the data as it stands at that point in the document. A name defined only further down falls back to its first definition.

A later fixture that reassigns a name (a scenario or sensitivity section) does not change the data earlier sections were checked against. Earlier constraints and data-linked axioms are re-checked under the new values; violations are reported as warnings beginning "Under the fixture at line N (...)". Validation blocks after the scenario fixture see the new values.

## Lean verification

`mpc prove <file>` checks every Property and Theorem in Lean and records the results in `<paper>.proofs.json`; `mpc lean <file>` prints the generated Lean file. A proof counts only if Lean accepts it and it depends on no axioms beyond `propext`, `Classical.choice` and `Quot.sound` (so `sorry` and `axiom` never count). The report's **Verification Levels** section shows each claim as assumed, stated, Z3-checked or Lean-proved; editing a claim or proof marks its Lean result stale.

Translation notes: Z3 `Real` → `ℝ`, `Int` → `ℤ`; `x**2` → `x ^ 2`; non-integer exponents become `Real.rpow`; division follows Lean's convention `x / 0 = 0`.

## Symbol table

`mpc symbols --json <file>` prints every registered symbol with its kind, index, units, bounds, `latex`, and defining line. Use it instead of tracking symbol names by hand.

