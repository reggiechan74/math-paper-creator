"""LaTeX ↔ symbol linkage checks."""

import json

from meta_compiler.compiler import check_document
from meta_compiler.linkage import extract_identifiers, normalize


def idents(tex):
    return [sorted(o.candidates(), key=len)[0] for o in extract_identifiers(tex)]


class TestExtraction:
    def test_greek_and_latin(self):
        assert idents(r"\beta x + y") == [r"\beta", "x", "y"]

    def test_subscripts_are_indices(self):
        assert idents(r"x_{ij} \le c_i") == ["x", "c"]

    def test_binders_are_skipped(self):
        assert idents(r"x_i \ge 0 \quad \forall i, j \in W") == ["x", "W"]

    def test_decorated_identifiers(self):
        assert idents(r"\bar{c} + \mathbf{w} + \hat{\theta}") == [r"\bar{c}", r"\mathbf{w}", r"\hat{\theta}"]

    def test_text_and_operators_ignored(self):
        assert idents(r"\text{cost} = \sum_{t} \log(p) \cdot \max(q, 0)") == ["p", "q"]

    def test_euler_and_differential(self):
        assert idents(r"\int_0^T e^{-\rho t}\,\mathrm{d}t") == [r"\mathrm{d}"]

    def test_nested_scripts_collected(self):
        nested = []
        extract_identifiers(r"\sum_{t \in T} x_t", nested)
        assert "T" in [o.base for o in nested]

    def test_normalize(self):
        assert normalize(r"x_{i}") == "x_i"
        assert normalize(r"\pi^{*}") == r"\pi^*"
        assert normalize(r"\rho  t") == r"\rho t"
        assert normalize(r"\left( a \right)") == "(a)"


def _doc(math: str, validate: str, fixture: str = "") -> str:
    return f"# Model\n\n$$\n{math}\n$$\n\n{fixture}```python:validate\n{validate}\n```\n"


def test_opt_in_only():
    result = check_document(_doc(r"\gamma x", 'Set("W", description="w")'))
    assert not any("LaTeX" in w or "latex=" in w for w in result.warnings)


def test_fully_linked_document_is_quiet():
    doc = _doc(
        r"\sum_{w \in W} x_w \le \beta",
        'Set("W", description="w", latex="W")\n'
        'Variable("x", index="W", description="x", latex="x")\n'
        'Parameter("beta", description="b", latex=r"\\beta")',
    )
    result = check_document(doc)
    assert not any("latex" in w.lower() for w in result.warnings), result.warnings


def test_undeclared_identifier_warned():
    doc = _doc(r"x \le \gamma", 'Parameter("x", description="x", latex="x")')
    result = check_document(doc)
    assert any(r"uses \gamma" in w for w in result.warnings), result.warnings


def test_declared_but_unused_warned():
    doc = _doc(r"x \ge 0", 'Parameter("x", description="x", latex="x")\n'
                           'Parameter("beta", description="b", latex=r"\\beta")')
    result = check_document(doc)
    assert any('"beta" declares latex' in w for w in result.warnings), result.warnings


def test_missing_latex_declarations_listed():
    doc = _doc(r"x \ge 0", 'Parameter("x", description="x", latex="x")\n'
                           'Parameter("y", description="y")')
    result = check_document(doc)
    assert any("no latex= declaration" in w and "y" in w for w in result.warnings)


def test_decorated_scalar_matches():
    doc = _doc(r"q \le c_{\max}", 'Parameter("q", description="q", latex="q")\n'
                                  'Parameter("cmax", description="c", latex=r"c_{\\max}")')
    result = check_document(doc)
    assert not any("latex" in w.lower() for w in result.warnings), result.warnings


def test_symbols_cli_json(tmp_path, capsys):
    from meta_compiler.cli import main

    path = tmp_path / "m.model.md"
    path.write_text(_doc(r"x \ge 0", 'Parameter("x", units="hours", description="x", latex="x")'))
    assert main(["symbols", str(path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    [sym] = payload["symbols"]
    assert sym["name"] == "x" and sym["kind"] == "parameter"
    assert sym["latex"] == "x" and sym["units"] == "hours" and sym["line"] == 7
