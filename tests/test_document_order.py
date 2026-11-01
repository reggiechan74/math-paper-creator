"""Fixture data follows document order; scenario overrides don't leak backwards."""

from meta_compiler.compiler import check_document


BASE_THEN_SCENARIO = '''# Base
```python:fixture
H = 8.0
```
```python:validate
Parameter("H", units="hours", description="hours")
Constraint("H_cap", expr=lambda: H <= 10, description="cap")
```
# Scenario: long days
```python:fixture
H = 12.0
```
'''


def test_scenario_override_does_not_fail_earlier_section():
    result = check_document(BASE_THEN_SCENARIO)
    assert result.passed, result.errors


def test_scenario_violation_is_reported_as_warning():
    result = check_document(BASE_THEN_SCENARIO)
    assert any(
        "line 10" in w and "H: 8.0 → 12.0" in w and '"H_cap"' in w
        for w in result.warnings
    ), result.warnings


def test_later_section_sees_overridden_value():
    doc = '''# Base
```python:fixture
H = 8.0
```
```python:validate
Parameter("H", units="hours", description="hours")
```
# Scenario
```python:fixture
H = 12.0
```
```python:validate
Constraint("long_day", expr=lambda: H > 10, description="scenario has long days")
```
'''
    result = check_document(doc)
    assert result.passed, result.errors


def test_earlier_section_did_not_see_later_value_before_fix():
    """A base constraint that only holds under the scenario value must fail."""
    doc = '''```python:fixture
H = 8.0
```
```python:validate
Parameter("H", units="hours", description="hours")
Constraint("needs_long", expr=lambda: H > 10, description="c")
```
```python:fixture
H = 12.0
```
'''
    result = check_document(doc)
    assert not result.passed
    assert any('"needs_long" failed' in e for e in result.errors)


def test_fixture_after_validate_still_supplies_data():
    """Back-compat: a name defined only later falls back to its first value."""
    doc = '''```python:validate
Set("W", description="workers")
Parameter("cap", index="W", units="hours", description="cap")
Constraint("pos", expr=lambda w: cap[w] > 0, over="W", description="c")
```
```python:fixture
W = ["a", "b"]
cap = {"a": 1.0, "b": 2.0}
```
'''
    result = check_document(doc)
    assert result.passed, result.errors


def test_indexed_override_rechecks_constraint():
    doc = '''```python:fixture
W = ["a", "b"]
cap = {"a": 5.0, "b": 5.0}
```
```python:validate
Set("W", description="workers")
Parameter("cap", index="W", units="hours", description="cap")
Constraint("cap_ok", expr=lambda w: cap[w] <= 8, over="W", description="c")
```
```python:fixture
cap = {"a": 5.0, "b": 9.0}
```
'''
    result = check_document(doc)
    assert result.passed, result.errors
    assert any('"cap_ok" violated for W="b"' in w for w in result.warnings), result.warnings


def test_results_block_sees_data_at_its_position():
    doc = '''```python:fixture
H = 8.0
```
```python:results
print(H)
```
```python:fixture
H = 12.0
```
```python:results
print(H)
```
'''
    from meta_compiler.compiler.parser import parse_document, ResultsBlock
    from meta_compiler.compiler.executor import execute_blocks

    blocks = parse_document(doc)
    execute_blocks(blocks)
    outputs = [b.output.strip() for b in blocks if isinstance(b, ResultsBlock)]
    assert outputs == ["8.0", "12.0"]


def test_no_override_no_warning():
    doc = '''```python:fixture
H = 8.0
```
```python:validate
Parameter("H", units="hours", description="hours")
Constraint("ok", expr=lambda: H <= 10, description="c")
```
```python:fixture
M = 2.0
```
'''
    result = check_document(doc)
    assert result.passed
    assert not any("Under the fixture" in w for w in result.warnings)


def test_registry_keeps_base_data_after_execution():
    result = check_document(BASE_THEN_SCENARIO)
    assert result.registry.data_store["H"] == 8.0
