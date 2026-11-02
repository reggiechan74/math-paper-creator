"""Z3-based axiom verification for the meta-compiler.

Provides consistency checking (are axioms self-consistent?) and
implication checking (does a property follow from given axioms?).

Requires z3-solver: pip install z3-solver
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class VerificationResult:
    """Result of a Z3 verification check."""
    status: str  # "consistent", "contradictory", "verified", "failed", "skipped", "error"
    counterexample: dict | None = None
    error: str | None = None
    duration_s: float | None = None


def z3_available() -> bool:
    """Check if z3-solver is installed."""
    try:
        import z3
        return True
    except ImportError:
        return False


def check_axiom_consistency(
    axiom_exprs: list[object],
) -> VerificationResult:
    """Check whether a set of axiom Z3 expressions are mutually consistent.

    Returns VerificationResult with status "consistent" or "contradictory".
    """
    try:
        import z3
    except ImportError:
        return VerificationResult(status="skipped", error="z3-solver not installed")

    start = time.monotonic()
    try:
        solver = z3.Solver()
        for expr_fn in axiom_exprs:
            solver.add(expr_fn())

        result = solver.check()
        duration = time.monotonic() - start

        if result == z3.sat:
            return VerificationResult(status="consistent", duration_s=duration)
        elif result == z3.unsat:
            return VerificationResult(status="contradictory", duration_s=duration)
        else:
            return VerificationResult(
                status="error", error="Z3 returned unknown",
                duration_s=duration,
            )
    except Exception as e:
        return VerificationResult(
            status="error", error=str(e),
            duration_s=time.monotonic() - start,
        )


def check_property(
    axiom_exprs: list[object],
    property_expr: object,
) -> VerificationResult:
    """Check whether a property follows from given axioms.

    Uses proof by contradiction: if axioms AND NOT(property) is unsat,
    then the property is implied by the axioms.
    """
    try:
        import z3
    except ImportError:
        return VerificationResult(status="skipped", error="z3-solver not installed")

    start = time.monotonic()
    try:
        solver = z3.Solver()
        for expr_fn in axiom_exprs:
            solver.add(expr_fn())
        solver.add(z3.Not(property_expr()))

        result = solver.check()
        duration = time.monotonic() - start

        if result == z3.unsat:
            # No counterexample exists — property is implied
            return VerificationResult(status="verified", duration_s=duration)
        elif result == z3.sat:
            # Counterexample found — property does NOT follow
            model = solver.model()
            counterexample = {
                str(d): str(model[d]) for d in model.decls()
            }
            return VerificationResult(
                status="failed", counterexample=counterexample,
                duration_s=duration,
            )
        else:
            return VerificationResult(
                status="error", error="Z3 returned unknown",
                duration_s=duration,
            )
    except Exception as e:
        return VerificationResult(
            status="error", error=str(e),
            duration_s=time.monotonic() - start,
        )


def _to_z3_value(z3, const, value):
    """Convert a fixture value to a Z3 value of the constant's sort, or None."""
    from decimal import Decimal, InvalidOperation
    from fractions import Fraction

    sort = const.sort()
    if isinstance(value, bool) or type(value).__name__ == "bool_":
        return z3.BoolVal(bool(value)) if sort == z3.BoolSort() else None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num or num in (float("inf"), float("-inf")):
        return None
    if sort == z3.IntSort():
        return z3.IntVal(int(num)) if num.is_integer() else None
    if sort == z3.RealSort():
        # Exact decimal: 0.1 becomes 1/10, matching how Z3 reads Python literals.
        try:
            frac = Fraction(Decimal(repr(num)))
        except (InvalidOperation, ValueError):
            frac = Fraction(num)
        return z3.RealVal(f"{frac.numerator}/{frac.denominator}")
    return None


def check_axiom_against_data(
    axiom_expr: object,
    values: dict,
) -> VerificationResult:
    """Check that the fixture data satisfies an axiom.

    Z3 constants are linked to fixture values by name: ``Real('H')`` is bound
    to ``values['H']``. Constants with no value stay free, so the check asks
    whether *some* assignment of them satisfies the axiom given the data.

    Statuses:
      "holds"     — the data satisfies the axiom
      "violated"  — no assignment of the remaining free constants satisfies it
      "unbound"   — no constant in the axiom has a fixture value
      "error"/"skipped" — Z3 failed or is not installed

    ``counterexample`` carries the bound values on "violated".
    """
    try:
        import z3
        from z3.z3util import get_vars
    except ImportError:
        return VerificationResult(status="skipped", error="z3-solver not installed")

    start = time.monotonic()
    try:
        expr = axiom_expr()
        subs = []
        bound: dict[str, str] = {}
        for const in get_vars(expr):
            name = const.decl().name()
            if name not in values:
                continue
            z3_value = _to_z3_value(z3, const, values[name])
            if z3_value is None:
                continue
            subs.append((const, z3_value))
            bound[name] = repr(values[name])

        if not subs:
            return VerificationResult(status="unbound", duration_s=time.monotonic() - start)

        reduced = z3.simplify(z3.substitute(expr, *subs))
        if z3.is_true(reduced):
            status = "holds"
        elif z3.is_false(reduced):
            status = "violated"
        else:
            solver = z3.Solver()
            solver.add(reduced)
            outcome = solver.check()
            if outcome == z3.sat:
                status = "holds"
            elif outcome == z3.unsat:
                status = "violated"
            else:
                return VerificationResult(
                    status="error", error="Z3 returned unknown",
                    duration_s=time.monotonic() - start,
                )
        return VerificationResult(
            status=status,
            counterexample=bound if status == "violated" else None,
            duration_s=time.monotonic() - start,
        )
    except Exception as e:
        return VerificationResult(
            status="error", error=str(e),
            duration_s=time.monotonic() - start,
        )


def falsify_property(
    axiom_exprs: list[object],
    property_expr: object,
    *,
    seeds: dict | None = None,
    samples: int = 2000,
    seed: int = 0,
) -> VerificationResult:
    """Search for a counterexample by random assignment, when Z3 can't decide.

    Every constant gets a concrete value: values near its fixture value (if
    linked by name in ``seeds``), small integers and fractions, and wide
    log-uniform magnitudes of both signs. An assignment is a counterexample
    when all axioms hold and the property is false. Finding none is not a
    proof; the status is then "not_found" and ``error`` says how much was
    searched.
    """
    import math
    import random
    from fractions import Fraction

    try:
        import z3
        from z3.z3util import get_vars
    except ImportError:
        return VerificationResult(status="skipped", error="z3-solver not installed")

    start = time.monotonic()
    rng = random.Random(seed)
    seeds = seeds or {}
    try:
        axioms = [f() for f in axiom_exprs]
        prop = property_expr()
        consts = {c.decl().name(): c for e in [*axioms, prop] for c in get_vars(e)}
    except Exception as e:
        return VerificationResult(status="error", error=str(e))

    def draw(name, const):
        is_int = const.sort() == z3.IntSort()
        base = seeds.get(name)
        roll = rng.random()
        if base is not None and roll < 0.3:
            value = float(base) * math.exp(rng.uniform(-1.5, 1.5))
        elif roll < 0.6:
            value = float(Fraction(rng.randint(-12, 12), rng.choice([1, 1, 2, 3, 4, 10])))
        else:
            value = rng.choice([-1, 1]) * math.exp(rng.uniform(-6, 6))
        if is_int:
            return z3.IntVal(int(round(value)))
        frac = Fraction(value).limit_denominator(10**6)
        return z3.RealVal(f"{frac.numerator}/{frac.denominator}")

    tried = admissible = 0
    for _ in range(samples):
        tried += 1
        subs = [(c, draw(n, c)) for n, c in consts.items()]
        try:
            if not all(z3.is_true(z3.simplify(z3.substitute(a, *subs))) for a in axioms):
                continue
            admissible += 1
            if z3.is_false(z3.simplify(z3.substitute(prop, *subs))):
                ce = {str(c): str(v) for c, v in subs}
                return VerificationResult(status="failed", counterexample=ce,
                                          duration_s=time.monotonic() - start)
        except Exception:
            continue
    return VerificationResult(
        status="not_found",
        error=f"{admissible} admissible random assignments (of {tried} tried) were checked",
        duration_s=time.monotonic() - start,
    )
