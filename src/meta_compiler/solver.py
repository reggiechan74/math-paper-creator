"""Solve a .model.md's optimization model with Pyomo (`mpc solve`).

`check` verifies that the fixture's decision is feasible; it never asks what
the *best* decision is. This module answers that by reusing the paper's own
validation lambdas: the registry's Variables become Pyomo `Var` components
bound into the validation namespace under the same names, while Parameters
keep their fixture data. The lambdas `x[i, t]`, `sum(...)`, `<=` then build
Pyomo expressions instead of numbers — no second, Pyomo-specific copy of the
model to keep in sync.

Constraint forms the translation supports: arity-0 constraints, constraints
`over` one set, and `all(...)` inside a constraint (each item becomes its own
constraint). Python control flow on variables (`if x > 0`, `max(x, y)`,
`abs(x)`) can't become solver constraints; such constraints are reported as
untranslatable rather than guessed at.

The default solver is HiGHS (pip-installed `highspy`), for linear and
mixed-integer models. For nonlinear models, `--solver ipopt` uses Ipopt if
installed.
"""

from __future__ import annotations

import builtins
import math
from dataclasses import dataclass, field
from typing import Any

from meta_compiler.symbols import ConstraintSymbol, ObjectiveSymbol, VariableSymbol


class _Many(list):
    """What `all(...)` returns during translation: every item is a constraint."""

    def __bool__(self):  # pragma: no cover — guards against accidental truth tests
        raise TypeError("all(...) over decision variables can't be used as a truth value")


def _collect_all(iterable):
    items = list(iterable)
    try:
        import pyomo.core.expr.relational_expr as rel
        relational = tuple(
            getattr(rel, n) for n in ("InequalityExpression", "EqualityExpression",
                                      "RangedExpression") if hasattr(rel, n))
    except ImportError:  # pragma: no cover
        relational = ()
    if relational and any(isinstance(i, relational) for i in items):
        return _Many(items)
    return builtins.all(items)


@dataclass
class Solution:
    status: str                       # optimal | infeasible | unbounded | error | ...
    objective: str | None = None
    sense: str | None = None
    objective_value: float | None = None
    fixture_objective_value: float | None = None
    variables: dict[str, Any] = field(default_factory=dict)
    binding: dict[str, list] = field(default_factory=dict)
    slack: dict[str, Any] = field(default_factory=dict)
    untranslatable: dict[str, str] = field(default_factory=dict)
    message: str = ""

    def to_json(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _value(v):
    import pyomo.environ as pyo
    try:
        x = pyo.value(v, exception=False)
    except TypeError:
        x = pyo.value(v)
    if x is None:
        return None
    x = float(x)
    return round(x) if abs(x - round(x)) < 1e-9 else x


def _members(name: str, data: dict) -> list:
    members = data.get(name)
    if not isinstance(members, list):
        raise ValueError(f'set "{name}" has no fixture members')
    return members


def solve_blocks(blocks, *, objective: str | None = None, solver: str = "highs",
                 time_limit: float | None = 60) -> Solution:
    try:
        import pyomo.environ as pyo
    except ImportError:
        return Solution("error", message="Pyomo is not installed (pip install pyomo highspy)")

    from meta_compiler.compiler.executor import _arity, _bind_context, execute_blocks

    result = execute_blocks(blocks)
    if not result.passed or result.registry is None:
        return Solution("error", message="the document does not validate; fix it before solving")
    reg, ns, base = result.registry, result.namespace, dict(result.base_data or {})

    objectives = [s for s in reg.symbols.values() if isinstance(s, ObjectiveSymbol)]
    variables = [s for s in reg.symbols.values() if isinstance(s, VariableSymbol)]
    if not objectives or not variables:
        return Solution("error", message="nothing to optimize: the model needs at least one "
                                         "Variable and one Objective")
    if objective is None:
        if len(objectives) > 1:
            names = ", ".join(o.name for o in objectives)
            return Solution("error", message=f"several objectives ({names}); choose one with --objective")
        obj = objectives[0]
    else:
        obj = next((o for o in objectives if o.name == objective), None)
        if obj is None:
            return Solution("error", message=f'no Objective named "{objective}"')

    # Fixture decision's objective value, for comparison
    _bind_context(reg, ns, base)
    fixture_value = None
    try:
        fixture_value = float(obj.expr())
    except Exception:
        pass

    model = pyo.ConcreteModel()
    domains = {"binary": pyo.Binary, "integer": pyo.Integers}
    pyomo_vars = {}
    try:
        for var in variables:
            domain = domains.get((var.domain or "").lower(), pyo.Reals)
            lo, hi = var.bounds if var.bounds else (None, None)
            if var.index:
                sets = [_members(s, base) for s in var.index]
                if len(sets) == 1:
                    keys = list(sets[0])
                else:
                    import itertools
                    keys = list(itertools.product(*sets))
                component = pyo.Var(keys, domain=domain, bounds=(lo, hi), dense=True)
            else:
                component = pyo.Var(domain=domain, bounds=(lo, hi))
            model.add_component(f"v_{var.name}", component)
            pyomo_vars[var.name] = component
            # Start from the fixture decision, when there is one
            start = base.get(var.name)
            if isinstance(start, dict):
                for key, val in start.items():
                    if key in component:
                        component[key].set_value(val, skip_validation=True)
            elif start is not None and not var.index:
                component.set_value(start, skip_validation=True)
    except ValueError as e:
        return Solution("error", message=str(e))

    # Bind Pyomo variables into the namespace; parameters keep fixture data.
    saved = {name: ns.get(name) for name in pyomo_vars}
    saved_all = ns.get("all", None)
    ns.update(pyomo_vars)
    ns["all"] = _collect_all

    solution = Solution("unknown", objective=obj.name, sense=obj.sense,
                        fixture_objective_value=fixture_value)
    constraint_index: dict[str, list] = {}
    try:
        model.cons = pyo.ConstraintList()

        def add(name, expr, label):
            many = isinstance(expr, _Many)
            items = expr if many else [expr]
            for k, item in enumerate(items, start=1):
                if isinstance(item, bool):
                    if not item:
                        raise ValueError("is always false for these parameters")
                    continue
                con = model.cons.add(item)
                where = label
                if many:  # one constraint per item of all(...)
                    where = f"{label} #{k}" if label is not None else f"#{k}"
                constraint_index.setdefault(name, []).append((where, con))

        for sym in reg.symbols.values():
            if not isinstance(sym, ConstraintSymbol) or sym.expr is None:
                continue
            try:
                if _arity(sym.expr) == 0:
                    add(sym.name, sym.expr(), None)
                else:
                    for member in _members(sym.over, base):
                        add(sym.name, sym.expr(member), member)
            except Exception as e:  # noqa: BLE001
                solution.untranslatable[sym.name] = f"{type(e).__name__}: {e}"

        try:
            model.obj = pyo.Objective(
                expr=obj.expr(),
                sense=pyo.maximize if obj.sense == "maximize" else pyo.minimize,
            )
        except Exception as e:  # noqa: BLE001
            return Solution("error", message=f'objective "{obj.name}" could not be translated: '
                                             f"{type(e).__name__}: {e}")
    finally:
        for name, value in saved.items():
            ns[name] = value
        if saved_all is None:
            ns.pop("all", None)
        else:
            ns["all"] = saved_all
        _bind_context(reg, ns, base)

    if solution.untranslatable:
        solution.status = "error"
        solution.message = ("some constraints use Python logic on decision variables "
                            "(if/max/min/abs/bool) and can't be passed to a solver; "
                            "rewrite them as (in)equalities")
        return solution

    name = {"highs": "appsi_highs"}.get(solver, solver)
    opt = pyo.SolverFactory(name)
    if opt is None or not opt.available(exception_flag=False):
        hint = "pip install highspy" if solver == "highs" else f"install the {solver} solver"
        return Solution("error", message=f"solver {solver!r} is not available ({hint})")
    if time_limit and hasattr(opt, "config") and hasattr(opt.config, "time_limit"):
        opt.config.time_limit = time_limit
    try:
        res = opt.solve(model, load_solutions=False)
    except Exception as e:  # noqa: BLE001 — e.g. HiGHS rejecting a nonlinear model
        msg = str(e).splitlines()[0] if str(e) else type(e).__name__
        if any(w in msg.lower() for w in ("nonlinear", "quadratic", "polynomial", "degree")):
            msg += " — the model is nonlinear; try --solver ipopt"
        return Solution("error", objective=obj.name, message=msg)

    tc = str(res.solver.termination_condition).split(".")[-1]
    if tc in ("optimal", "locallyOptimal", "globallyOptimal"):
        model.solutions.load_from(res)
        tc = "optimal"
    solution.status = {"optimal": "optimal", "infeasible": "infeasible",
                       "unbounded": "unbounded",
                       "infeasibleOrUnbounded": "infeasible_or_unbounded",
                       "maxTimeLimit": "time_limit"}.get(tc, tc)
    if solution.status != "optimal":
        solution.message = {
            "infeasible": "no decision satisfies all constraints for these parameters",
            "unbounded": "the objective can improve without limit; a bound or constraint is missing",
        }.get(solution.status, "")
        return solution

    solution.objective_value = _value(model.obj)
    for vname, component in pyomo_vars.items():
        if component.is_indexed():
            solution.variables[vname] = {
                (", ".join(map(str, k)) if isinstance(k, tuple) else str(k)): _value(component[k])
                for k in component
            }
        else:
            solution.variables[vname] = _value(component)
    for cname, entries in constraint_index.items():
        rows = []
        for label, con in entries:
            slack = min(
                (s for s in (con.uslack(), con.lslack())
                 if s is not None and math.isfinite(s)),
                default=None,
            )
            rows.append((label, None if slack is None else round(float(slack), 9)))
        solution.slack[cname] = {str(l) if l is not None else "": s for l, s in rows}
        tight = [l for l, s in rows if s is not None and abs(s) <= 1e-7]
        if tight:
            solution.binding[cname] = [str(l) if l is not None else "" for l in tight]
    return solution


def format_solution(sol: Solution) -> str:
    if sol.status == "error":
        lines = [f"Not solved: {sol.message}"]
        for name, why in sol.untranslatable.items():
            lines.append(f"  ✗ constraint \"{name}\": {why}")
        return "\n".join(lines)
    if sol.status != "optimal":
        return f"Solver status: {sol.status}" + (f" — {sol.message}" if sol.message else "")
    lines = [f"Optimal {sol.sense} of \"{sol.objective}\": {sol.objective_value:g}"]
    if sol.fixture_objective_value is not None and sol.objective_value not in (None, 0):
        share = sol.fixture_objective_value / sol.objective_value
        lines.append(f"  The paper's example decision scores {sol.fixture_objective_value:g} "
                     f"({share:.0%} of optimal)" if sol.sense == "maximize" else
                     f"  The paper's example decision scores {sol.fixture_objective_value:g} "
                     f"(optimal is {sol.objective_value:g})")
    lines.append("")
    lines.append("Decision:")
    for name, value in sol.variables.items():
        if isinstance(value, dict):
            nonzero = {k: v for k, v in value.items() if v}
            shown = ", ".join(f"{name}[{k}]={v:g}" for k, v in nonzero.items()) or "all zero"
            lines.append(f"  {shown}")
        else:
            lines.append(f"  {name} = {value:g}")
    if sol.binding:
        lines.append("")
        lines.append("Binding constraints (no slack at the optimum):")
        for name, where in sol.binding.items():
            at = f" at {', '.join(w for w in where if w)}" if any(where) else ""
            lines.append(f"  {name}{at}")
    return "\n".join(lines)
