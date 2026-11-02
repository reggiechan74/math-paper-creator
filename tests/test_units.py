from meta_compiler.units import Unit, parse_unit, units_compatible, units_multiply, units_divide


def test_base_unit():
    u = parse_unit("hours")
    assert u == Unit(numer=("hours",), denom=())


def test_compound_unit():
    u = parse_unit("hours/headcount")
    assert u == Unit(numer=("hours",), denom=("headcount",))


def test_dimensionless():
    u = parse_unit("dimensionless")
    assert u == Unit(numer=(), denom=())


def test_compatible_same():
    assert units_compatible(parse_unit("hours"), parse_unit("hours"))


def test_incompatible():
    assert not units_compatible(parse_unit("hours"), parse_unit("headcount"))


def test_dimensionless_compatible_with_self():
    assert units_compatible(parse_unit("dimensionless"), parse_unit("dimensionless"))


def test_multiply_units():
    # dimensionless * hours = hours
    result = units_multiply(parse_unit("dimensionless"), parse_unit("hours"))
    assert result == parse_unit("hours")


def test_multiply_compound():
    # hours/headcount * headcount = hours
    result = units_multiply(parse_unit("hours/headcount"), parse_unit("headcount"))
    assert result == parse_unit("hours")


def test_multiply_two_base():
    # hours * dollars = hours*dollars (compound numer)
    result = units_multiply(parse_unit("hours"), parse_unit("dollars"))
    assert units_compatible(result, Unit(numer=("dollars", "hours"), denom=()))


def test_divide_units():
    # hours / headcount = hours/headcount
    result = units_divide(parse_unit("hours"), parse_unit("headcount"))
    assert result == parse_unit("hours/headcount")


def test_divide_cancel():
    # hours / hours = dimensionless
    result = units_divide(parse_unit("hours"), parse_unit("hours"))
    assert result == parse_unit("dimensionless")


def test_unit_str():
    assert str(parse_unit("hours")) == "hours"
    assert str(parse_unit("dimensionless")) == "dimensionless"
    assert str(parse_unit("hours/headcount")) == "hours/headcount"


# ── Aliases, powers and conversion hints ────────────────────────────────────

import pytest

from meta_compiler.units import conversion_hint


@pytest.mark.parametrize("a,b", [
    ("hours", "hr"), ("hours", "Hrs"), ("hours/week", "hr/wk"),
    ("dollars", "$"), ("dollars/hour", "USD/h"), ("people", "persons"),
    ("dimensionless", "1"), ("dimensionless", ""), ("hours*hours", "h^2"),
    ("hours * headcount / week", "headcount*hr/wk"),
])
def test_spellings_are_equivalent(a, b):
    assert parse_unit(a) == parse_unit(b)


def test_unknown_units_keep_their_case():
    assert parse_unit("MW") != parse_unit("mW")


def test_parse_cancels():
    assert parse_unit("hours*dollars/hours") == parse_unit("dollars")


def test_conversion_hint_same_dimension():
    hint = conversion_hint(parse_unit("minutes"), parse_unit("hours"))
    assert "multiply hours by 60 to get minutes" in hint
    assert conversion_hint(parse_unit("hours"), parse_unit("dollars")) is None


def _doc(units_a, units_b, extra=""):
    return f'''```python:fixture
a = 30.0
b = 1.0
k = 60.0
```
```python:validate
Parameter("a", units="{units_a}", description="a")
Parameter("b", units="{units_b}", description="b")
Parameter("k", units="minutes/hour", description="minutes per hour")
Constraint("c", expr=lambda: {extra or "a <= b * 100"}, description="c")
```
'''


def test_alias_spellings_pass_in_documents():
    from meta_compiler.compiler import check_document
    assert check_document(_doc("hr", "hours")).passed


def test_mixed_time_units_fail_with_hint():
    from meta_compiler.compiler import check_document
    result = check_document(_doc("minutes", "hours"))
    assert not result.passed
    assert any("multiply hours by 60 to get minutes" in e for e in result.errors), result.errors


def test_explicit_conversion_passes():
    from meta_compiler.compiler import check_document
    assert check_document(_doc("minutes", "hours", "a <= b * k")).passed
