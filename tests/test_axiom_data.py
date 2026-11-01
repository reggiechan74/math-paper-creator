"""Axioms are checked against the fixture data (Z3 constants linked by name)."""

import pytest

pytest.importorskip("z3")

from meta_compiler.compiler import check_document
from meta_compiler.verification import check_axiom_against_data


def _doc(h_value: str, axiom: str, extra_fixture: str = "") -> str:
    return f'''# A
```python:fixture
H = {h_value}
```
```python:validate
from z3 import Real
Parameter("H", units="hours", description="hours")
zH = Real("H")
Axiom("A1", statement="axiom", z3_expr=lambda: {axiom}, description="d")
```
{extra_fixture}'''


def test_axiom_violated_by_data_is_error():
    result = check_document(_doc("-5.0", "zH > 0"))
    assert not result.passed
    assert any('Axiom "A1"' in e and "H=-5.0" in e for e in result.errors), result.errors


def test_axiom_satisfied_by_data_passes():
    result = check_document(_doc("8.0", "zH > 0"))
    assert result.passed, result.errors


def test_decimal_values_are_exact():
    # 0.1 must equal the Z3 literal 0.1, not its binary approximation
    result = check_document(_doc("0.1", "zH == 0.1"))
    assert result.passed, result.errors


def test_axiom_violated_only_in_scenario_is_warning():
    scenario = "# Scenario\n```python:fixture\nH = 12.0\n```\n"
    result = check_document(_doc("8.0", "zH <= 10", scenario))
    assert result.passed, result.errors
    assert any('axiom "A1"' in w and "no longer holds" in w for w in result.warnings)


def test_unlinked_constants_stay_free():
    # M has no fixture value: H=8 is consistent with "H > M" for some M
    result = check_document(_doc("8.0", "zH > Real('M')"))
    assert result.passed, result.errors


def test_partially_bound_axiom_can_still_be_violated():
    # No M satisfies H > M and M > 10 when H = 8
    result = check_document(_doc("8.0", "And(zH > Real('M'), Real('M') > 10)").replace(
        "from z3 import Real", "from z3 import Real, And"))
    assert not result.passed


def test_unit_check_unbound():
    import z3
    r = check_axiom_against_data(lambda: z3.Real("Q") > 0, {"H": 1.0})
    assert r.status == "unbound"


def test_int_sort_binding():
    import z3
    n = z3.Int("n")
    assert check_axiom_against_data(lambda: n >= 3, {"n": 4}).status == "holds"
    assert check_axiom_against_data(lambda: n >= 3, {"n": 2}).status == "violated"
    # Non-integral value can't bind to an Int constant: left free
    assert check_axiom_against_data(lambda: n >= 3, {"n": 2.5}).status == "unbound"
