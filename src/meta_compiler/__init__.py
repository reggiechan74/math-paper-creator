"""Meta-compiler: Symbol registry and validation engine for mathematical models."""

from meta_compiler.registry import registry


def Set(name: str, *, description: str = "", latex: str | None = None) -> "SymbolProxy":
    """Declare an index set."""
    return registry.register_set(name, description=description, latex=latex)


def Parameter(
    name: str,
    *,
    index=None,
    domain: str = "real",
    units: str = "dimensionless",
    description: str = "",
    latex: str | None = None,
) -> "SymbolProxy":
    """Declare a parameter."""
    return registry.register_parameter(name, index=index, domain=domain, units=units, description=description, latex=latex)


def Variable(
    name: str,
    *,
    index=None,
    domain: str = "continuous",
    bounds: tuple[float | None, float | None] = (None, None),
    units: str = "dimensionless",
    description: str = "",
    latex: str | None = None,
) -> "SymbolProxy":
    """Declare a decision variable."""
    return registry.register_variable(name, index=index, domain=domain, bounds=bounds, units=units, description=description, latex=latex)


def Expression(
    name: str,
    *,
    definition: object,
    index=None,
    units: str = "dimensionless",
    description: str = "",
    latex: str | None = None,
) -> "SymbolProxy":
    """Declare a derived expression."""
    return registry.register_expression(name, definition=definition, index=index, units=units, description=description, latex=latex)


def Constraint(
    name: str,
    *,
    expr: object,
    over=None,
    type: str = "hard",
    description: str = "",
) -> None:
    """Declare a constraint."""
    registry.register_constraint(name, expr=expr, over=over, constraint_type=type, description=description)


def Objective(
    name: str,
    *,
    expr: object,
    sense: str = "maximize",
    description: str = "",
) -> None:
    """Declare an objective."""
    registry.register_objective(name, expr=expr, sense=sense, description=description)


def Axiom(
    name: str,
    *,
    statement: str,
    z3_expr: object | None = None,
    description: str = "",
) -> None:
    """Declare a foundational axiom."""
    registry.register_axiom(name, statement=statement, z3_expr=z3_expr, description=description)


def Property(
    name: str,
    *,
    claim: str,
    z3_expr: object,
    given: list[str] | tuple[str, ...],
    description: str = "",
    lean_proof: str | None = None,
) -> None:
    """Declare a derived property.

    ``lean_proof`` optionally proves it in Lean 4: the theorem statement is
    generated from ``z3_expr`` with the ``given`` axioms as hypotheses, and
    ``lean_proof`` is the tactic proof (e.g. ``"nlinarith [sq_nonneg (H - M)]"``).
    """
    registry.register_property(name, claim=claim, z3_expr=z3_expr, given=given,
                               description=description, lean_proof=lean_proof)


def Theorem(
    name: str,
    *,
    claim: str,
    lean: str,
    description: str = "",
) -> None:
    """Declare a claim stated and proved in Lean 4 (Mathlib is imported).

    ``lean`` must declare ``theorem <name>`` (helper lemmas may precede it).
    Use ``sorry`` for a proof not yet written; ``mpc prove`` reports it.
    """
    registry.register_theorem(name, claim=claim, lean=lean, description=description)


def S(name: str):
    """Return the members of a registered set for iteration."""
    return registry.s(name)
