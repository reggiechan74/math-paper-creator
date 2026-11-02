"""Two-mode executor for .model.md validation blocks.

Structural mode (no fixture): registers symbols, stores expr callables,
runs structural checks only.

Numeric mode (fixture present): loads fixture data, executes expr functions
against real values, checks constraints numerically, then runs structural checks.

Fixture data follows document order
-----------------------------------
Fixture and results blocks run top to bottom. Each validation block is
checked against the fixture data *as it stands at that point in the
document*. A name that is only defined further down falls back to its first
definition, so a fixture placed after its validation block still works.

When a later fixture block redefines a name (typically a scenario or
sensitivity section), earlier sections keep their original values. The
constraints and data-linked axioms registered before that point are then
re-checked under the new values, and violations are reported as warnings:
a scenario may legitimately push the model outside its base assumptions,
but the author should hear about it.
"""

from __future__ import annotations

import copy
import inspect
from dataclasses import dataclass, field
from typing import Any

from meta_compiler.compiler.parser import Block, FixtureBlock, ResultsBlock, ValidationBlock
from meta_compiler.proxy import SymbolProxy
from meta_compiler.registry import Registry, registry
from meta_compiler.symbols import (
    AxiomSymbol,
    ConstraintSymbol,
    ObjectiveSymbol,
    ParameterSymbol,
    PropertySymbol,
    VariableSymbol,
)


def _coerce_bool(value) -> bool:
    """Coerce constraint result to Python bool (handles numpy scalars)."""
    try:
        return bool(value)
    except (ValueError, TypeError):
        return value is True


def _is_numeric(value) -> bool:
    """Check if a value is numeric, including numpy scalar types."""
    if isinstance(value, (int, float)):
        return True
    import numpy as np
    return isinstance(value, (np.integer, np.floating))


@dataclass
class ExecutionResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    registry: Registry | None = None
    # For tools that re-evaluate the model on other data (mpc sweep):
    namespace: dict | None = field(default=None, repr=False)
    base_data: dict | None = field(default=None, repr=False)


# ── Fixture timeline ────────────────────────────────────────────────────────


@dataclass
class Override:
    """A fixture block reassigning a name that an earlier fixture defined."""
    name: str
    old: Any
    new: Any
    first_line: int | None


@dataclass
class OverridePoint:
    """A fixture block that redefines names, and the data after it ran."""
    block_index: int
    line: int
    overrides: list[Override]
    state_after: dict[str, Any]

    def describe(self) -> str:
        changes = ", ".join(
            f"{o.name}: {_short(o.old)} → {_short(o.new)}" for o in self.overrides
        )
        return f"the fixture at line {self.line} ({changes})"


@dataclass
class FixtureTimeline:
    first_values: dict[str, Any]
    state_before: list[dict[str, Any]]  # per block index
    override_points: list[OverridePoint]

    def context_at(self, block_index: int) -> dict[str, Any]:
        """Data visible to the block at ``block_index``."""
        ctx = dict(self.first_values)
        ctx.update(self.state_before[block_index])
        return ctx

    def context_after(self, point: OverridePoint) -> dict[str, Any]:
        ctx = dict(self.first_values)
        ctx.update(point.state_after)
        return ctx


def _short(value: Any, limit: int = 40) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _copy_value(value: Any) -> Any:
    try:
        return copy.deepcopy(value)
    except Exception:
        return value  # modules, generators, etc. — share the reference


def _snapshot(ns: dict) -> dict[str, Any]:
    return {k: _copy_value(v) for k, v in ns.items() if not k.startswith("_")}


def _same(a: Any, b: Any) -> bool:
    if a is b:
        return True
    try:
        result = a == b
        if isinstance(result, bool):
            return result
        import numpy as np
        if isinstance(result, np.bool_):
            return bool(result)
        return bool(np.all(result))
    except Exception:
        try:
            return repr(a) == repr(b)
        except Exception:
            return False


class _FixtureError(Exception):
    pass


def _build_timeline(blocks: list[Block]) -> FixtureTimeline:
    """Run fixture and results blocks in document order, recording snapshots."""
    import contextlib
    import io

    fixture_ns: dict = {}
    state: dict[str, Any] = {}
    first_values: dict[str, Any] = {}
    first_line: dict[str, int] = {}
    state_before: list[dict[str, Any]] = []
    override_points: list[OverridePoint] = []

    for idx, block in enumerate(blocks):
        state_before.append(state)

        if isinstance(block, FixtureBlock):
            try:
                exec(block.code, fixture_ns)
            except Exception as e:
                raise _FixtureError(f"Fixture error (line {block.line_number}): {e}") from e
            new_state = _snapshot(fixture_ns)
            overrides: list[Override] = []
            for name, value in new_state.items():
                if name not in state:
                    if name not in first_values:
                        first_values[name] = value
                        first_line[name] = block.line_number
                elif not _same(state[name], value):
                    overrides.append(Override(
                        name=name, old=state[name], new=value,
                        first_line=first_line.get(name),
                    ))
            state = new_state
            if overrides:
                override_points.append(OverridePoint(
                    block_index=idx, line=block.line_number,
                    overrides=overrides, state_after=state,
                ))

        elif isinstance(block, ResultsBlock):
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    exec(block.code, fixture_ns)
            except Exception as e:
                raise _FixtureError(f"Results error (line {block.line_number}): {e}") from e
            block.output = buf.getvalue()

    return FixtureTimeline(
        first_values=first_values,
        state_before=state_before,
        override_points=override_points,
    )


def _bind_context(reg: Registry, ns: dict, ctx: dict[str, Any]) -> None:
    """Point the registry and the validation namespace at a data context."""
    reg.data_store = dict(ctx)
    for name in reg.symbols:
        current = ns.get(name)
        if isinstance(current, SymbolProxy):
            current._data = ctx.get(name)
        elif name in reg.scalar_names and name in ctx and reg._is_scalar(current):
            # Only replace plain scalars: a name rebound to something else
            # (e.g. a Z3 constant) belongs to the author.
            ns[name] = ctx[name]


# ── Main entry point ────────────────────────────────────────────────────────


def execute_blocks(
    blocks: list[Block], *, strict: bool = False
) -> ExecutionResult:
    """Execute fixture + validation blocks and run checks."""
    from meta_compiler.checks import collect_scalar_refs

    registry.reset()
    errors: list[str] = []
    warnings: list[str] = []

    has_fixtures = any(isinstance(b, FixtureBlock) for b in blocks)

    # Step 1: fixture + results blocks, in document order
    try:
        timeline = _build_timeline(blocks)
    except _FixtureError as e:
        errors.append(str(e))
        return ExecutionResult(passed=False, errors=errors, warnings=warnings, registry=None)

    # Step 2: Build validation namespace
    from meta_compiler import (
        Set, Parameter, Variable, Expression, Constraint, Objective, S,
        Axiom, Property, Theorem,
    )
    ns = {
        "Set": Set, "Parameter": Parameter, "Variable": Variable,
        "Expression": Expression, "Constraint": Constraint,
        "Objective": Objective, "S": S, "Axiom": Axiom,
        "Property": Property, "Theorem": Theorem, "registry": registry,
    }

    # Step 3: Execute validation blocks, each against its own data context.
    # The DSL surface (Set, Parameter, etc.) does NOT require users to
    # capture return values; the registry auto-injects proxies into `ns`.
    registry._exec_namespace = ns
    symbol_block: dict[str, int] = {}  # symbol name -> block index
    contexts: dict[int, dict[str, Any]] = {}

    for idx, block in enumerate(blocks):
        if not isinstance(block, ValidationBlock):
            continue
        ctx = timeline.context_at(idx) if has_fixtures else {}
        contexts[idx] = ctx
        _bind_context(registry, ns, ctx)
        before = set(registry.symbols)
        try:
            registry._current_block_source = block.code
            registry._current_block_line = block.line_number
            exec(block.code, ns)
            collect_scalar_refs(block.code, registry.scalar_names, registry.access_log)
        except Exception as e:
            errors.append(f"Validation error (line {block.line_number}): {e}")
            registry._exec_namespace = None
            return ExecutionResult(passed=False, errors=errors,
                                   warnings=warnings, registry=registry)
        for name in registry.symbols:
            if name not in before:
                symbol_block[name] = idx

    registry._exec_namespace = None
    registry._current_block_source = None
    registry._current_block_line = None

    def symbols_of(kind):
        return [s for s in registry.symbols.values() if isinstance(s, kind)]

    # Step 4: In numeric mode, evaluate constraints and objectives, each
    # against the data of the block that registered it.
    if has_fixtures:
        for name, sym in registry.symbols.items():
            if isinstance(sym, (ConstraintSymbol, ObjectiveSymbol)) and sym.expr is not None:
                _bind_context(registry, ns, contexts[symbol_block[name]])
            if isinstance(sym, ConstraintSymbol) and sym.expr is not None:
                try:
                    _check_constraint(sym, registry, errors)
                except Exception as e:
                    errors.append(f"Error in constraint \"{sym.name}\": {e}")

            elif isinstance(sym, ObjectiveSymbol) and sym.expr is not None:
                try:
                    result = sym.expr() if _arity(sym.expr) == 0 else None
                    if result is not None and not _is_numeric(result):
                        errors.append(
                            f"Objective \"{sym.name}\" returned {type(result).__name__}, "
                            f"expected numeric value"
                        )
                except Exception as e:
                    errors.append(f"Error in objective \"{sym.name}\": {e}")

        # Step 4-: example decisions must respect each Variable's bounds/domain
        warnings.extend(_check_variable_bounds(registry, contexts, symbol_block))

        # Step 4a: scenario re-checks — constraints registered before a
        # fixture that redefines data are re-evaluated under the new data.
        for point in timeline.override_points:
            earlier = [
                s for s in symbols_of(ConstraintSymbol)
                if s.expr is not None and symbol_block[s.name] < point.block_index
            ]
            if not earlier:
                continue
            _bind_context(registry, ns, timeline.context_after(point))
            for sym in earlier:
                scenario_errors: list[str] = []
                try:
                    _check_constraint(sym, registry, scenario_errors)
                except Exception as e:
                    scenario_errors.append(f'Error in constraint "{sym.name}": {e}')
                for msg in scenario_errors:
                    warnings.append(f"Under {point.describe()}: {msg}")

    # Step 4b: Verify axioms and properties (if Z3 expressions present)
    axiom_syms = [s for s in symbols_of(AxiomSymbol) if s.z3_expr is not None]
    if axiom_syms:
        from meta_compiler.verification import check_axiom_consistency, check_property, z3_available
        if z3_available():
            # Consistency check
            consistency = check_axiom_consistency([s.z3_expr for s in axiom_syms])
            if consistency.status == "contradictory":
                axiom_names = ", ".join(s.name for s in axiom_syms)
                errors.append(
                    f"Axioms are contradictory: {axiom_names} cannot all hold simultaneously"
                )
            elif consistency.status == "error":
                errors.append(f"Axiom consistency check error: {consistency.error}")

            # Property implication checks
            for name, sym in registry.symbols.items():
                if isinstance(sym, PropertySymbol):
                    # Premises: axioms and earlier properties
                    given_exprs = [
                        registry.symbols[premise].z3_expr
                        for premise in sym.given
                        if isinstance(registry.symbols.get(premise), (AxiomSymbol, PropertySymbol))
                        and registry.symbols[premise].z3_expr is not None
                    ]
                    if given_exprs:
                        prop_result = check_property(given_exprs, sym.z3_expr)
                        if prop_result.status == "failed":
                            ce = prop_result.counterexample or {}
                            ce_str = ", ".join(f"{k}={v}" for k, v in ce.items())
                            errors.append(
                                f'Property "{sym.name}" does NOT follow from '
                                f'{", ".join(sym.given)}'
                                f'{" — counterexample: " + ce_str if ce_str else ""}'
                            )
                        elif prop_result.status == "error":
                            _falsify_undecided(sym, given_exprs, prop_result.error,
                                               errors, warnings)

            # Step 4c: the fixture data must satisfy the axioms
            if has_fixtures:
                _check_axioms_against_data(axiom_syms, symbol_block, contexts,
                                           timeline, errors, warnings)
        else:
            warnings.append(
                "z3-solver is not installed: axioms and properties were not verified"
            )

    # Step 5: Run structural checks
    from meta_compiler.checks import run_all_checks
    check_result = run_all_checks(registry, strict=strict)
    errors.extend(check_result.errors)
    warnings.extend(check_result.warnings)

    # Step 6: LaTeX ↔ symbol linkage (warnings only; opt-in via latex=)
    from meta_compiler.linkage import check_latex_linkage
    warnings.extend(check_latex_linkage(blocks, registry))

    # Leave the registry and namespace holding the base data for downstream
    # consumers (reports, reconciliation checks, sweeps).
    if has_fixtures:
        _bind_context(registry, ns, dict(timeline.first_values))

    return ExecutionResult(
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        registry=registry,
        namespace=ns,
        base_data=dict(timeline.first_values) if has_fixtures else {},
    )


def _falsify_undecided(sym, given_exprs, z3_error, errors, warnings) -> None:
    """Z3 couldn't decide a Property: look for a counterexample by sampling."""
    from meta_compiler.verification import falsify_property

    seeds = _data_values(registry, registry.data_store)
    found = falsify_property(given_exprs, sym.z3_expr, seeds=seeds)
    if found.status == "failed":
        ce = ", ".join(f"{k}={v}" for k, v in (found.counterexample or {}).items())
        errors.append(
            f'Property "{sym.name}" does NOT follow from {", ".join(sym.given)} '
            f"— counterexample found by random search: {ce}"
        )
    elif found.status == "not_found":
        warnings.append(
            f'Property "{sym.name}": Z3 could not decide it ({z3_error}); '
            f"{found.error} without finding a counterexample. Consider a Lean proof."
        )
    else:
        errors.append(f'Property "{sym.name}" verification error: {z3_error}')


def _check_variable_bounds(reg: Registry, contexts, symbol_block) -> list[str]:
    """Warn when a Variable's fixture value lies outside its bounds or domain."""
    out = []
    for name, sym in reg.symbols.items():
        if not isinstance(sym, VariableSymbol):
            continue
        ctx = contexts.get(symbol_block.get(name), {})
        if name not in ctx:
            continue
        data = ctx[name]
        items = data.items() if isinstance(data, dict) else [(None, data)]
        lo, hi = sym.bounds if sym.bounds else (None, None)
        domain = (sym.domain or "").lower()
        for key, value in items:
            if not _is_numeric(value):
                continue
            where = f"[{key}]" if key is not None else ""
            problem = None
            if lo is not None and value < lo:
                problem = f"below its lower bound {lo}"
            elif hi is not None and value > hi:
                problem = f"above its upper bound {hi}"
            elif domain in ("integer", "binary") and float(value) != int(value):
                problem = f"not an integer (domain {domain})"
            elif domain == "binary" and value not in (0, 1):
                problem = "not 0 or 1 (domain binary)"
            if problem:
                out.append(f'Variable "{name}"{where} = {value!r} in the example is {problem}')
                break  # one warning per variable is enough
    return out


def _data_values(reg: Registry, ctx: dict[str, Any]) -> dict[str, Any]:
    """Scalar fixture values of registered Parameters/Variables, by name."""
    return {
        name: ctx[name]
        for name, sym in reg.symbols.items()
        if isinstance(sym, (ParameterSymbol, VariableSymbol))
        and name in ctx and reg._is_scalar(ctx[name])
    }


def _check_axioms_against_data(axiom_syms, symbol_block, contexts, timeline,
                               errors, warnings) -> None:
    from meta_compiler.verification import check_axiom_against_data

    def fmt(values: dict) -> str:
        return ", ".join(f"{k}={v}" for k, v in values.items())

    for sym in axiom_syms:
        idx = symbol_block[sym.name]
        result = check_axiom_against_data(sym.z3_expr, _data_values(registry, contexts[idx]))
        if result.status == "violated":
            errors.append(
                f'Axiom "{sym.name}" ({sym.statement}) is violated by the fixture data: '
                f"{fmt(result.counterexample or {})}"
            )
        elif result.status == "error":
            warnings.append(f'Axiom "{sym.name}" could not be checked against the data: {result.error}')

        for point in timeline.override_points:
            if point.block_index <= idx:
                continue
            values = _data_values(registry, timeline.context_after(point))
            scenario = check_axiom_against_data(sym.z3_expr, values)
            if scenario.status == "violated":
                warnings.append(
                    f'Under {point.describe()}: axiom "{sym.name}" ({sym.statement}) '
                    f"no longer holds ({fmt(scenario.counterexample or {})})"
                )


def _check_constraint(sym: ConstraintSymbol, reg: Registry, errors: list[str]):
    """Evaluate a constraint against fixture data."""
    arity = _arity(sym.expr)

    if arity == 0:
        try:
            result = sym.expr()
        except NameError as e:
            missing = str(e).split("'")[1]
            if missing in reg.data_store:
                errors.append(
                    f'Constraint "{sym.name}": "{missing}" is computed in fixture '
                    f'but not registered as a Parameter — add Parameter("{missing}", ...) '
                    f'to the validate block to use it in constraints'
                )
            else:
                errors.append(f'Error in constraint "{sym.name}": {e}')
            return
        if not _coerce_bool(result):
            errors.append(
                f"Constraint \"{sym.name}\" failed (returned {result!r})"
            )
    else:
        if sym.over is None:
            errors.append(
                f"Constraint \"{sym.name}\" has positional args but no 'over' set"
            )
            return

        if sym.over not in reg.data_store:
            errors.append(
                f"Constraint \"{sym.name}\": set \"{sym.over}\" has no fixture data"
            )
            return

        members = reg.data_store[sym.over]
        if not isinstance(members, list):
            errors.append(
                f"Constraint \"{sym.name}\": fixture data for set \"{sym.over}\" "
                f"must be a list"
            )
            return

        for member in members:
            try:
                result = sym.expr(member)
            except NameError as e:
                missing = str(e).split("'")[1]
                if missing in reg.data_store:
                    errors.append(
                        f'Constraint "{sym.name}": "{missing}" is computed in fixture '
                        f'but not registered as a Parameter — add Parameter("{missing}", ...) '
                        f'to the validate block to use it in constraints'
                    )
                else:
                    errors.append(f'Error in constraint "{sym.name}": {e}')
                return
            if not _coerce_bool(result):
                errors.append(
                    f"Constraint \"{sym.name}\" violated for "
                    f"{sym.over}=\"{member}\": result is {result!r}"
                )


def _arity(fn) -> int:
    """Return the number of positional parameters of a function."""
    sig = inspect.signature(fn)
    return sum(
        1 for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    )
