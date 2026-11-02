"""Random testing of a model across its admissible inputs (`mpc sweep`).

`check` evaluates the model at one hand-picked point: the fixture data. A
formula can work there and break elsewhere — divide by H − M when meetings
fill the day, take the log of something that can go negative — and the paper
would still pass. The sweep re-evaluates every Expression, Objective and
Constraint at many random inputs the paper itself allows:

* numeric Parameters and Variables (scalars and indexed dicts) are varied;
  Sets keep their fixture members;
* values respect each symbol's domain (nonneg / positive / integer /
  binary / probability) and each Variable's bounds;
* samples that violate a declared axiom (Z3 constants linked by name) are
  rejected, so only inputs the model's assumptions admit are tested.

Reported as defects: exceptions and non-finite numeric results (NaN, ±inf),
each with a concrete input that triggers it. Reported as information: how
often each constraint holds across the samples. Constraints restrict the
decision for given data, so failing on random data is expected; a constraint
that holds everywhere, or only at the fixture, is still worth knowing.
"""

from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, field
from typing import Any

from meta_compiler.symbols import (
    AxiomSymbol,
    ConstraintSymbol,
    ExpressionSymbol,
    ObjectiveSymbol,
    ParameterSymbol,
    VariableSymbol,
)

MAX_INDEX_TUPLES = 200


@dataclass
class Spec:
    lo: float | None = None
    hi: float | None = None
    integer: bool = False
    strict_lo: bool = False  # lo excluded (positive domains)


def spec_for(sym) -> Spec:
    domain = (getattr(sym, "domain", "") or "").lower()
    spec = Spec()
    if "binary" in domain or domain == "bool":
        return Spec(lo=0, hi=1, integer=True)
    if "int" in domain:
        spec.integer = True
    if "nonneg" in domain or "non_neg" in domain:
        spec.lo = 0
    elif "pos" in domain:
        spec.lo, spec.strict_lo = 0, True
    if "prob" in domain or "unit" in domain or "fraction" in domain:
        spec.lo, spec.hi = 0, 1
    if isinstance(sym, VariableSymbol) and sym.bounds:
        lo, hi = sym.bounds
        if lo is not None:
            spec.lo = lo if spec.lo is None else max(spec.lo, lo)
        if hi is not None:
            spec.hi = hi if spec.hi is None else min(spec.hi, hi)
    return spec


def _is_number(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    try:
        import numpy as np
        return isinstance(v, (np.integer, np.floating))
    except ImportError:
        return False


def draw(rng: random.Random, base: float, spec: Spec) -> float:
    """One random value around ``base`` that satisfies ``spec``."""
    edges = [base]
    if spec.lo is not None and not spec.strict_lo:
        edges.append(spec.lo)
    if spec.hi is not None:
        edges.append(spec.hi)
    zero_allowed = (
        (spec.lo is None or spec.lo < 0 or (spec.lo == 0 and not spec.strict_lo))
        and (spec.hi is None or spec.hi >= 0)
    )
    if zero_allowed:
        edges.append(0.0)

    roll = rng.random()
    if roll < 0.2:
        value = rng.choice(edges)
    elif spec.lo is not None and spec.hi is not None:
        value = rng.uniform(spec.lo, spec.hi)
    else:
        scale = abs(base) if base else 1.0
        value = scale * math.exp(rng.uniform(-math.log(20), math.log(20)))
        negative_ok = spec.lo is None or spec.lo < 0
        if negative_ok and rng.random() < 0.3:
            value = -value
    if spec.lo is not None:
        value = max(value, spec.lo)
        if spec.strict_lo and value <= spec.lo:
            value = spec.lo + max(abs(base), 1.0) * 1e-6
    if spec.hi is not None:
        value = min(value, spec.hi)
    if spec.integer:
        value = round(value)
        if spec.strict_lo and spec.lo is not None and value <= spec.lo:
            value = math.floor(spec.lo) + 1
    return value


@dataclass
class Problem:
    symbol: str
    kind: str          # Expression | Objective | Constraint
    message: str
    example: dict[str, Any]
    count: int = 1


@dataclass
class SweepReport:
    samples: int
    seed: int
    varied: list[str]
    rejected_by_axioms: int = 0
    axioms_unchecked: bool = False
    problems: dict[str, Problem] = field(default_factory=dict)
    constraint_holds: dict[str, int] = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and not self.problems

    def to_json(self) -> dict:
        return {
            "ok": self.ok, "samples": self.samples, "seed": self.seed,
            "varied": self.varied, "rejected_by_axioms": self.rejected_by_axioms,
            "axioms_unchecked": self.axioms_unchecked, "error": self.error,
            "problems": [vars(p) for p in self.problems.values()],
            "constraint_holds": self.constraint_holds,
        }


def _finite(value: Any) -> bool:
    try:
        import numpy as np
        arr = np.asarray(value, dtype=float)
        return bool(np.all(np.isfinite(arr)))
    except (TypeError, ValueError):
        return True  # non-numeric results aren't this check's business


def _index_tuples(sym, ctx) -> list[tuple]:
    sets = []
    for name in sym.index or ():
        members = ctx.get(name)
        if not isinstance(members, list):
            return []
        sets.append(members)
    return list(itertools.islice(itertools.product(*sets), MAX_INDEX_TUPLES))


def run_sweep(blocks, *, samples: int = 200, seed: int = 0) -> SweepReport:
    import numpy as np

    from meta_compiler.compiler.executor import _arity, _bind_context, _coerce_bool, execute_blocks

    result = execute_blocks(blocks)
    report = SweepReport(samples=0, seed=seed, varied=[])
    if not result.passed or result.registry is None:
        report.error = "the document does not validate; fix it before sweeping"
        return report
    if not result.base_data:
        report.error = "the document has no fixture data to vary"
        return report

    reg, ns, base = result.registry, result.namespace, result.base_data
    rng = random.Random(seed)

    targets: dict[str, tuple[Any, Spec]] = {}
    for name, sym in reg.symbols.items():
        if not isinstance(sym, (ParameterSymbol, VariableSymbol)) or name not in base:
            continue
        value = base[name]
        if _is_number(value) or (isinstance(value, dict) and value
                                 and all(_is_number(v) for v in value.values())):
            targets[name] = (value, spec_for(sym))
    report.varied = sorted(targets)
    if not targets:
        report.error = "no numeric Parameters or Variables to vary"
        return report

    axioms = [s for s in reg.symbols.values() if isinstance(s, AxiomSymbol) and s.z3_expr]
    check_axiom = None
    if axioms:
        from meta_compiler.verification import check_axiom_against_data, z3_available
        if z3_available():
            check_axiom = check_axiom_against_data
        else:
            report.axioms_unchecked = True

    # Scalars with the same units can meet (M = H): the boundary where
    # differences vanish and formulas like x / (H - M) break.
    scalars = [n for n, (v, _) in targets.items() if not isinstance(v, dict)]
    units = {n: getattr(reg.symbols[n], "units", None) for n in scalars}
    pairs = [(a, b) for a in scalars for b in scalars
             if a != b and units[a] == units[b]]

    def sample() -> tuple[dict, dict]:
        data, shown = {}, {}
        for name, (value, spec) in targets.items():
            if isinstance(value, dict):
                data[name] = {k: draw(rng, float(v), spec) for k, v in value.items()}
            else:
                data[name] = draw(rng, float(value), spec)
        if pairs and rng.random() < 0.15:
            a, b = rng.choice(pairs)
            spec = targets[a][1]
            value = data[b]
            above = spec.lo is None or value > spec.lo or (value == spec.lo and not spec.strict_lo)
            if above and (spec.hi is None or value <= spec.hi):
                data[a] = round(value) if spec.integer else value
        for name in scalars:
            shown[name] = round(data[name], 6)
        return data, shown

    evaluate = [s for s in reg.symbols.values()
                if isinstance(s, (ExpressionSymbol, ObjectiveSymbol, ConstraintSymbol))
                and getattr(s, "expr", None) is not None]
    for s in evaluate:
        if isinstance(s, ConstraintSymbol):
            report.constraint_holds[s.name] = 0

    def record(sym, message, shown):
        if sym.name in report.problems:
            report.problems[sym.name].count += 1
        else:
            kind = type(sym).__name__.replace("Symbol", "")
            report.problems[sym.name] = Problem(sym.name, kind, message, shown)

    attempts = 0
    with np.errstate(all="ignore"):
        while report.samples < samples and attempts < samples * 20:
            attempts += 1
            data, shown = sample()
            ctx = {**base, **data}
            if check_axiom is not None:
                values = {k: v for k, v in ctx.items() if _is_number(v)}
                if any(check_axiom(a.z3_expr, values).status == "violated" for a in axioms):
                    report.rejected_by_axioms += 1
                    continue
            report.samples += 1
            _bind_context(reg, ns, ctx)

            for sym in evaluate:
                try:
                    if isinstance(sym, ConstraintSymbol):
                        if _arity(sym.expr) == 0:
                            holds = _coerce_bool(sym.expr())
                        else:
                            members = ctx.get(sym.over) or []
                            holds = all(_coerce_bool(sym.expr(m)) for m in members)
                        report.constraint_holds[sym.name] += int(holds)
                        continue
                    if _arity(sym.expr) == 0:
                        outputs = [sym.expr()]
                    else:
                        tuples = _index_tuples(sym, ctx)
                        outputs = [sym.expr(*t) for t in tuples]
                    bad = next((o for o in outputs if not _finite(o)), None)
                    if bad is not None:
                        record(sym, f"non-finite value ({bad!r})", shown)
                except Exception as e:  # noqa: BLE001 — any crash is the finding
                    record(sym, f"{type(e).__name__}: {e}", shown)

    _bind_context(reg, ns, dict(base))
    if report.samples == 0:
        report.error = ("every random sample violated an axiom; the axioms may be "
                        "too tight for this sampler")
    return report


def format_report(report: SweepReport) -> str:
    if report.error:
        return f"Sweep not run: {report.error}"
    lines = [
        f"Sweep: {report.samples} random inputs (seed {report.seed}), varying "
        f"{', '.join(report.varied)} within their domains, bounds and axioms"
        + (f" ({report.rejected_by_axioms} samples rejected by axioms)"
           if report.rejected_by_axioms else "")
    ]
    if report.axioms_unchecked:
        lines.append("  Note: z3-solver is not installed, so samples were not filtered by the axioms")
    if report.problems:
        lines.append("")
        lines.append("Defects (the model breaks on inputs it allows):")
        for p in report.problems.values():
            example = ", ".join(f"{k}={v}" for k, v in p.example.items()) or "indexed values varied"
            lines.append(f"  ✗ {p.kind} \"{p.symbol}\": {p.message} — "
                         f"in {p.count}/{report.samples} samples, e.g. {example}")
    else:
        lines.append("No crashes or non-finite values.")
    if report.constraint_holds:
        lines.append("")
        lines.append("Constraints (informational — they restrict the decision for given data):")
        for name, n in report.constraint_holds.items():
            lines.append(f"  {name}: holds in {n}/{report.samples} samples")
    return "\n".join(lines)
