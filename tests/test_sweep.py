"""Random testing: `mpc sweep` and Z3-unknown property falsification."""

import random

import pytest

from meta_compiler.compiler.parser import parse_document
from meta_compiler.sweep import Spec, draw, run_sweep, spec_for

FRAGILE = '''```python:fixture
W = ["a", "b"]
H = 8.0
M = 2.0
load = {"a": 3.0, "b": 5.0}
```
```python:validate
import math
Set("W", description="workers")
Parameter("H", domain="positive", units="hours", description="h")
Parameter("M", domain="nonneg_real", units="hours", description="m")
Parameter("load", index="W", domain="nonneg_real", units="hours", description="l")
Expression("util", definition=lambda w: load[w] / (H - M), index=["W"], description="u")
Constraint("fits", expr=lambda w: load[w] <= H - M, over="W", description="c")
Objective("share", expr=lambda: sum(load[w] for w in S("W")) / H, sense="minimize", description="o")
```
'''

ROBUST = '''```python:fixture
H = 8.0
M = 2.0
```
```python:validate
Parameter("H", domain="positive", units="hours", description="h")
Parameter("M", domain="nonneg_real", units="hours", description="m")
Expression("free", definition=lambda: H - M, description="f")
Objective("o", expr=lambda: H + M, sense="maximize", description="o")
```
'''


def test_finds_division_by_zero_at_equal_values():
    report = run_sweep(parse_document(FRAGILE), samples=200, seed=0)
    assert "util" in report.problems
    p = report.problems["util"]
    assert "ZeroDivisionError" in p.message
    assert p.example["H"] == p.example["M"]


def test_respects_strict_positive_domain():
    # share divides by H, which is declared positive: never a defect
    for seed in range(5):
        report = run_sweep(parse_document(FRAGILE), samples=200, seed=seed)
        assert "share" not in report.problems


def test_robust_model_is_clean_and_reproducible():
    a = run_sweep(parse_document(ROBUST), samples=100, seed=7)
    b = run_sweep(parse_document(ROBUST), samples=100, seed=7)
    assert a.ok and a.samples == 100
    assert a.to_json() == b.to_json()


def test_constraint_tally_is_informational():
    report = run_sweep(parse_document(FRAGILE), samples=200, seed=0)
    assert 0 < report.constraint_holds["fits"] < 200
    assert "fits" not in report.problems


def test_axioms_filter_samples():
    pytest.importorskip("z3")
    doc = FRAGILE.replace(
        "import math",
        'import math\nfrom z3 import Real\nAxiom("A1", statement="M < H", '
        'z3_expr=lambda: Real("M") < Real("H"), description="a")',
    )
    report = run_sweep(parse_document(doc), samples=200, seed=0)
    assert report.rejected_by_axioms > 0
    # M < H strictly: H - M is never zero, so util can't divide by zero
    assert "util" not in report.problems


def test_invalid_document_is_not_swept():
    report = run_sweep(parse_document('```python:validate\nParameter("x", index=["NOPE"])\n```\n'))
    assert report.error and "does not validate" in report.error


@pytest.mark.parametrize("domain,check", [
    ("nonneg_real", lambda v: v >= 0),
    ("positive", lambda v: v > 0),
    ("integer", lambda v: float(v).is_integer()),
    ("binary", lambda v: v in (0, 1)),
    ("probability", lambda v: 0 <= v <= 1),
])
def test_draw_respects_domain(domain, check):
    class Sym:
        pass
    sym = Sym()
    sym.domain = domain
    spec = spec_for(sym)
    rng = random.Random(0)
    assert all(check(draw(rng, 3.0, spec)) for _ in range(500))


def test_draw_respects_variable_bounds():
    from meta_compiler.symbols import VariableSymbol

    sym = VariableSymbol("x", None, "continuous", (2.0, 5.0), "u", "d")
    rng = random.Random(1)
    values = [draw(rng, 3.0, spec_for(sym)) for _ in range(500)]
    assert min(values) >= 2.0 and max(values) <= 5.0
    assert 2.0 in values and 5.0 in values  # bounds are probed


def test_cli_exit_codes(tmp_path, capsys):
    from meta_compiler.cli import main

    bad, good = tmp_path / "bad.model.md", tmp_path / "good.model.md"
    bad.write_text(FRAGILE)
    good.write_text(ROBUST)
    assert main(["sweep", str(bad)]) == 2
    assert "util" in capsys.readouterr().out
    assert main(["sweep", str(good), "--samples", "50"]) == 0


class TestFalsify:
    def test_counterexample_when_z3_is_unknown(self):
        pytest.importorskip("z3")
        from meta_compiler.compiler import check_document

        doc = '''```python:validate
from z3 import Real, And
zx, zy = Real("x"), Real("y")
Axiom("A1", statement="x > 1, y > 0", z3_expr=lambda: And(zx > 1, zy > 0), description="a")
Property("P1", claim="x^y < 100", z3_expr=lambda: zx ** zy < 100, given=["A1"], description="false")
Property("P2", claim="x^y > 0", z3_expr=lambda: zx ** zy > 0, given=["A1"], description="true")
```
'''
        result = check_document(doc)
        assert not result.passed
        assert any('"P1" does NOT follow' in e and "random search" in e for e in result.errors)
        assert not any('"P2"' in e for e in result.errors)
        assert any('"P2"' in w and "could not decide" in w for w in result.warnings)
