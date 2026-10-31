# Meta-compiler API reference and known constraints

Shared reference for the `author` and `onboard` skills. Every `python:validate` block in a `.model.md` document uses this API; `python:fixture` blocks supply the concrete test data.

```python
from meta_compiler import Set, Parameter, Variable, Expression, Constraint, Objective, S, Axiom, Property, registry

# Sets — fixture data must be a list
Set("W", description="Set of workers")

# Parameters (indexed, with units) — fixture data must be a dict
Parameter("cap", index=["W"], domain="nonneg_real", units="hours",
          description="Capacity per worker")

# Variables (indexed, with bounds) — fixture data must be a dict
Variable("x", index=["W", "T"], domain="continuous", bounds=(0, None),
         units="hours", description="Hours assigned")

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
Axiom("A1", statement="H > 0", z3_expr=lambda: H > 0, description="Positivity")

# Properties — derived claims that follow from axioms
Property("P1", claim="H - M >= 0",
         z3_expr=lambda: H - M >= 0,
         given=["A1", "A2"],
         description="Non-negative effective time")

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
