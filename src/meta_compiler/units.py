"""Lightweight unit algebra for dimensional consistency checks.

Supports base units (hours, headcount, dollars, points, dimensionless) and
compound units formed by multiplication and division. Not a full physical
units library — a tag system sufficient to catch common errors.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Unit:
    """A unit represented as a fraction: numer / denom (sorted tuples)."""
    numer: tuple[str, ...]
    denom: tuple[str, ...]

    def __str__(self) -> str:
        if not self.numer and not self.denom:
            return "dimensionless"
        n = "*".join(self.numer) if self.numer else "1"
        if not self.denom:
            return n
        d = "*".join(self.denom)
        return f"{n}/{d}"


# Spellings that mean the same unit (matched case-insensitively). Anything
# not listed is kept exactly as written, so "MW" and "mW" stay distinct.
_ALIASES = {
    "seconds": ("s", "sec", "secs", "second", "seconds"),
    "minutes": ("min", "mins", "minute", "minutes"),
    "hours": ("h", "hr", "hrs", "hour", "hours"),
    "days": ("d", "day", "days"),
    "weeks": ("wk", "wks", "week", "weeks"),
    "months": ("mo", "mos", "month", "months"),
    "years": ("y", "yr", "yrs", "year", "years"),
    "dollars": ("$", "usd", "dollar", "dollars"),
    "euros": ("€", "eur", "euro", "euros"),
    "people": ("person", "persons", "people"),
    "items": ("item", "items", "unit", "units"),
    "percent": ("%", "pct", "percent"),
}
_CANONICAL = {alias: canon for canon, aliases in _ALIASES.items() for alias in aliases}
_DIMENSIONLESS = {"", "1", "dimensionless", "none", "unitless"}

# Units of the same dimension and their size in a common base, for
# conversion hints. Months and years use average lengths.
_SCALES = {
    "time": {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400,
             "weeks": 604800, "months": 2629800, "years": 31557600},
}


def _canonical(token: str) -> str:
    token = token.strip()
    return _CANONICAL.get(token.lower(), token)


def _atoms(side: str) -> list[str]:
    out: list[str] = []
    for part in side.split("*"):
        part = part.strip()
        power = 1
        if "^" in part:
            base, _, exp = part.partition("^")
            part = base.strip()
            try:
                power = int(exp)
            except ValueError:
                power = 1
        token = _canonical(part)
        if token.lower() in _DIMENSIONLESS:
            continue
        out.extend([token] * max(power, 1))
    return out


def parse_unit(spec: str) -> Unit:
    """Parse a unit string like 'hours', 'hr/week', 'dollars*h^2' or 'dimensionless'.

    Common spellings are normalized (hr, hrs, hour → hours; $ / usd → dollars),
    so the same unit written two ways compares equal.
    """
    spec = (spec or "").strip()
    if spec.lower() in _DIMENSIONLESS:
        return Unit(numer=(), denom=())
    numer_str, _, denom_str = spec.partition("/")
    numer, denom = _cancel(_atoms(numer_str), _atoms(denom_str))
    return Unit(numer=numer, denom=denom)


def conversion_hint(a: Unit, b: Unit) -> str | None:
    """How to convert ``b`` into ``a`` when both are one unit of the same dimension."""
    if a.denom != b.denom or len(a.numer) != 1 or len(b.numer) != 1:
        return None
    ua, ub = a.numer[0], b.numer[0]
    for dimension, scales in _SCALES.items():
        if ua in scales and ub in scales:
            factor = scales[ub] / scales[ua]
            text = f"{factor:g}" if factor >= 1 else f"1/{1 / factor:g}"
            approx = " (average)" if {"months", "years"} & {ua, ub} else ""
            return (f"both are {dimension}: multiply {b} by {text}{approx} to get {a}, "
                    f'e.g. with a conversion parameter in units "{ua}/{ub}"')
    return None


def units_compatible(a: Unit, b: Unit) -> bool:
    """Check if two units are compatible (i.e., identical after normalization)."""
    return a == b


def _cancel(numer: list[str], denom: list[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Cancel matching terms between numerator and denominator."""
    n = list(numer)
    d = list(denom)
    for term in list(n):
        if term in d:
            n.remove(term)
            d.remove(term)
    return tuple(sorted(n)), tuple(sorted(d))


def units_multiply(a: Unit, b: Unit) -> Unit:
    """Multiply two units: (a.numer * b.numer) / (a.denom * b.denom), with cancellation."""
    numer = list(a.numer) + list(b.numer)
    denom = list(a.denom) + list(b.denom)
    n, d = _cancel(numer, denom)
    return Unit(numer=n, denom=d)


def units_divide(a: Unit, b: Unit) -> Unit:
    """Divide units: a / b = a * (1/b)."""
    flipped = Unit(numer=b.denom, denom=b.numer)
    return units_multiply(a, flipped)
