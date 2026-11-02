"""Lean verification tier: translation, statement generation, caching, and
(when a Lean project is available) real proof checking."""

import json
import os

import pytest

z3 = pytest.importorskip("z3")

from meta_compiler.compiler import check_document
from meta_compiler.lean import (
    ProofResult,
    UntranslatableError,
    build_theorems,
    find_lean_env,
    ident,
    proofs_path,
    record_results,
    render_file,
    run_lean,
    validate_theorem_source,
    verification_levels,
    z3_to_lean,
)

H, M, b = z3.Reals("H M beta")
n = z3.Int("n")


class TestTranslation:
    def test_arithmetic_and_comparisons(self):
        assert z3_to_lean(b * (H - M) >= 0) == "(beta * (H - M)) ≥ 0"
        assert z3_to_lean(H / 2 < M) == "(H / 2) < M"
        assert z3_to_lean(-H <= 3) == "(-H) ≤ 3"  # unary minus always wrapped

    def test_rationals_are_exact(self):
        # Z3 itself normalizes this to `3/10 >= H`
        assert z3_to_lean(H <= z3.RealVal("3/10")) == "(3 / 10 : ℝ) ≥ H"
        assert z3_to_lean(H <= 0.75) == "H ≤ (3 / 4 : ℝ)"

    def test_negative_literals(self):
        assert z3_to_lean(H >= -2) == "H ≥ (-2)"

    def test_powers(self):
        assert z3_to_lean(H ** 2 >= 0) == "(H ^ 2) ≥ 0"
        assert "^ (" in z3_to_lean(H ** M >= 0)  # rpow for a real exponent

    def test_logic(self):
        assert z3_to_lean(z3.And(H > 0, M > 0)) == "(H > 0) ∧ (M > 0)"
        assert z3_to_lean(z3.Implies(H > 0, M > 0)) == "(H > 0) → (M > 0)"
        assert z3_to_lean(z3.Not(H > 0)) == "¬(H > 0)"
        assert z3_to_lean(z3.Distinct(H, M)) == "H ≠ M"

    def test_quantifier(self):
        x = z3.Real("x")
        assert z3_to_lean(z3.ForAll([x], x * x >= 0)) == "∀ (x : ℝ), (x * x) ≥ 0"

    def test_int_to_real(self):
        assert z3_to_lean(z3.ToReal(n) <= H) == "((n : ℤ) : ℝ) ≤ H"

    def test_untranslatable(self):
        f = z3.Function("f", z3.RealSort(), z3.RealSort())
        with pytest.raises(UntranslatableError):
            z3_to_lean(f(H) > 0)

    def test_ident_quoting(self):
        assert ident("beta") == "beta"
        assert ident("fun") == "«fun»"
        assert ident("x.y") == "«x.y»"


DOC = '''# Model
```python:fixture
H = 8.0
M = 2.0
beta = 0.75
```
```python:validate
from z3 import Real, And
zH, zM, zb = Real("H"), Real("M"), Real("beta")
Parameter("H", units="hours", description="h")
Parameter("M", units="hours", description="m")
Parameter("beta", description="b")
Axiom("A2", statement="0 <= M <= H", z3_expr=lambda: And(zM >= 0, zM <= zH), description="a")
Axiom("A3", statement="0 < beta <= 1", z3_expr=lambda: And(zb > 0, zb <= 1), description="a")
Property("P1", claim="beta (H - M) >= 0", z3_expr=lambda: zb * (zH - zM) >= 0,
         given=["A2", "A3"], description="p", lean_proof=PROOF)
Property("P2", claim="M <= H", z3_expr=lambda: zM <= zH, given=["A2"], description="p")
Theorem("T1", claim="d/dx (c x) = c", lean=r"""
theorem T1 (c : ℝ) : deriv (fun x : ℝ => c * x) = fun _ => c := by
  funext x
  simp
""", description="t")
```
'''
GOOD = 'r"""\nobtain ⟨hM0, hMH⟩ := A2\nobtain ⟨hb0, hb1⟩ := A3\nexact mul_nonneg hb0.le (by linarith)\n"""'


def _registry(proof=GOOD):
    result = check_document(DOC.replace("PROOF", proof))
    assert result.passed, result.errors
    return result.registry


class TestStatements:
    def test_property_statement_uses_given_axioms(self):
        theorems, problems = build_theorems(_registry())
        assert not problems
        p1 = next(t for t in theorems if t.name == "P1")
        assert p1.origin == "property"
        assert "(H M beta : ℝ)" in p1.statement
        assert "(A2 : (M ≥ 0) ∧ (M ≤ H))" in p1.statement
        assert "A3" in p1.statement and "A1" not in p1.statement
        assert p1.statement.rstrip().endswith("(beta * (H - M)) ≥ 0")
        assert p1.has_proof

    def test_missing_proof_becomes_sorry(self):
        theorems, _ = build_theorems(_registry())
        p2 = next(t for t in theorems if t.name == "P2")
        assert not p2.has_proof
        assert p2.source.rstrip().endswith("sorry")

    def test_theorem_is_hand_written(self):
        theorems, _ = build_theorems(_registry())
        t1 = next(t for t in theorems if t.name == "T1")
        assert t1.origin == "theorem" and t1.has_proof

    def test_rendered_file_prints_axioms(self):
        text, spans = render_file(build_theorems(_registry())[0])
        assert text.startswith("import Mathlib")
        assert "#print axioms MPC.P1" in text and "#print axioms MPC.T1" in text
        lines = text.splitlines()
        first, _ = spans["P1"]
        assert lines[first - 1].startswith("theorem P1")

    def test_theorem_source_validation(self):
        with pytest.raises(ValueError, match="must declare"):
            validate_theorem_source("T1", "theorem T2 : True := trivial")
        with pytest.raises(ValueError, match="import"):
            validate_theorem_source("T1", "import Mathlib\ntheorem T1 : True := trivial")
        validate_theorem_source("T1", "lemma helper : True := trivial\ntheorem T1 : True := trivial")

    def test_theorem_registration_rejects_bad_source(self):
        doc = '```python:validate\nTheorem("T1", claim="c", lean="theorem T9 : True := trivial", description="d")\n```\n'
        result = check_document(doc)
        assert not result.passed
        assert any("must declare" in e for e in result.errors)


class TestCache:
    def test_proofs_path(self, tmp_path):
        assert proofs_path(tmp_path / "paper.model.md").name == "paper.proofs.json"

    def test_levels_and_staleness(self):
        reg = _registry()
        theorems, _ = build_theorems(reg)
        results = {t.name: ProofResult("proved") for t in theorems if t.name != "P2"}
        results["P2"] = ProofResult("sorry")
        cache = record_results({}, theorems, results, "leanprover/lean4:test")

        levels = {v["name"]: v for v in verification_levels(reg, True, cache)}
        assert levels["A2"]["level"] == "assumed"
        assert levels["P1"]["level"] == "Lean-proved"
        assert levels["P2"]["level"] == "Z3-checked" and "sorry" in levels["P2"]["detail"]
        assert levels["T1"]["level"] == "Lean-proved"
        assert "hand-written" in levels["T1"]["detail"]

        # Changing the proof text invalidates the cached result
        edited = _registry(GOOD.replace("by linarith", "by nlinarith"))
        levels = {v["name"]: v for v in verification_levels(edited, True, cache)}
        assert levels["P1"]["level"] == "Z3-checked"
        assert "stale" in levels["P1"]["detail"]

    def test_report_includes_levels(self):
        from meta_compiler.compiler import compile_document

        out = compile_document(DOC.replace("PROOF", GOOD), strict=False)
        assert "## Verification Levels" in out["report_text"]
        assert out["lean"].startswith("import Mathlib")


def test_prove_without_lean_exits_3(tmp_path, monkeypatch, capsys):
    from meta_compiler.cli import main

    for var in ("MPC_LEAN_PROJECT", "CLAUDE_PLUGIN_DATA"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "p.model.md"
    path.write_text(DOC.replace("PROOF", GOOD))
    assert main(["prove", str(path)]) == 3
    assert "Lean is not available" in capsys.readouterr().err


# ── Real Lean (opt-in: set MPC_LEAN_PROJECT) ────────────────────────────────

lean_env = find_lean_env() if os.environ.get("MPC_LEAN_PROJECT") else None
needs_lean = pytest.mark.skipif(lean_env is None, reason="set MPC_LEAN_PROJECT to run Lean tests")


@needs_lean
def test_real_lean_statuses():
    theorems, _ = build_theorems(_registry())
    results = run_lean(theorems, lean_env, timeout=600)
    assert results["P1"].status == "proved", results["P1"].messages
    assert results["P2"].status == "sorry"
    assert results["T1"].status == "proved", results["T1"].messages


@needs_lean
def test_real_lean_wrong_proof_fails():
    theorems, _ = build_theorems(_registry('"linarith"'))
    results = run_lean([t for t in theorems if t.name == "P1"], lean_env, timeout=600)
    assert results["P1"].status == "failed"
    assert results["P1"].messages


@needs_lean
def test_real_lean_rejects_smuggled_axiom():
    doc = '''```python:validate
Theorem("T9", claim="anything", lean=r"""
axiom magic : ∀ p : Prop, p
theorem T9 : (1 : ℕ) = 2 := magic _
""", description="cheat")
```
'''
    result = check_document(doc)
    theorems, _ = build_theorems(result.registry)
    results = run_lean(theorems, lean_env, timeout=600)
    assert results["T9"].status == "failed"
    assert any("non-standard axioms" in m for m in results["T9"].messages)


@needs_lean
def test_real_prove_cli_writes_sidecar(tmp_path, capsys):
    from meta_compiler.cli import main

    path = tmp_path / "paper.model.md"
    path.write_text(DOC.replace("PROOF", GOOD))
    rc = main(["prove", str(path), "--json"])
    assert rc == 2  # P2 has no proof yet
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"]["P1"]["status"] == "proved"
    sidecar = json.loads((tmp_path / "paper.proofs.json").read_text())
    assert sidecar["results"]["P1"]["status"] == "proved"
    assert sidecar["toolchain"] == lean_env.toolchain


# ── Theorems vs. example data ───────────────────────────────────────────────

from meta_compiler.lean import DataCheck, LeanTheorem, build_data_check, split_statement


def _th(stmt):
    return LeanTheorem(name="T", origin="theorem", source=stmt + " := sorry",
                       statement=stmt, has_proof=False)


class TestDataCheck:
    def test_split_statement(self):
        binders, concl = split_statement("theorem T (H M : ℝ) {k : ℕ} [Fact (0 < 1)] (h : 0 < M) : H - M < H")
        assert [(b.names, b.type, b.explicit) for b in binders] == [
            (["H", "M"], "ℝ", True), (["k"], "ℕ", False), (["h"], "0 < M", True)]
        assert concl == "H - M < H"

    def test_instances_use_exact_values(self):
        check = build_data_check(_th("theorem T (H M : ℝ) (h : 0 < M) : H - M < H"),
                                 {"H": 8.0, "M": 0.75})
        hyp = check.items[0]
        assert hyp["part"] == "hypothesis" and hyp["name"] == "h"
        assert hyp["lean"] == "(fun (H : ℝ) (M : ℝ) => (0 < M)) (8 : ℝ) ((3 : ℝ) / 4)"

    def test_unbound_binders_make_items_undecidable(self):
        check = build_data_check(_th("theorem T (f : ℝ → ℝ) (H : ℝ) (hf : f H > 0) : f H ≥ 0"),
                                 {"H": 8.0})
        assert all(i["lean"] is None for i in check.items)

    def test_no_data_names_means_no_check(self):
        assert build_data_check(_th("theorem T (x : ℝ) : x ^ 2 ≥ 0"), {"H": 8.0}) is None

    def test_integer_binders_need_integral_values(self):
        check = build_data_check(_th("theorem T (n : ℕ) (h : 0 < n) : n ≥ 1"), {"n": 2.5})
        assert check is None

    def test_summary(self):
        def mk(*statuses):
            items = [{"part": "hypothesis", "status": s} for s in statuses[:-1]]
            items.append({"part": "conclusion", "status": statuses[-1]})
            return DataCheck("T", {}, items).summary()
        assert mk("holds", "holds") == "applies"
        assert mk("fails", "holds") == "not_applicable"
        assert mk("holds", "fails") == "refuted"
        assert mk("undetermined", "holds") == "undetermined"


@needs_lean
def test_real_lean_data_check():
    from meta_compiler.lean import run_data_checks

    checks = [build_data_check(_th("theorem T (H M : ℝ) (h : 0 < M) : H - M < H"), {"H": 8.0, "M": 0.0}),
              build_data_check(_th("theorem T (H M : ℝ) (h : 0 ≤ M) : H - M < 1"), {"H": 8.0, "M": 0.0})]
    run_data_checks(checks, lean_env)
    assert [c.summary() for c in checks] == ["not_applicable", "refuted"]


# ── Properties built on Properties ──────────────────────────────────────────

CHAIN = '''```python:fixture
H = 8.0
M = 2.0
```
```python:validate
from z3 import Real, And
zH, zM = Real("H"), Real("M")
Parameter("H", units="hours", description="h")
Parameter("M", units="hours", description="m")
Axiom("A1", statement="0 <= M <= H", z3_expr=lambda: And(zM >= 0, zM <= zH), description="a")
Property("P1", claim="H - M >= 0", z3_expr=lambda: zH - zM >= 0, given=["A1"], description="p",
         lean_proof="linarith [A1.2]")
Property("P2", claim="2 (H - M) >= 0", z3_expr=lambda: 2 * (zH - zM) >= 0, given=["P1"], description="p",
         lean_proof="linarith [P1]")
```
'''


class TestChains:
    def test_property_may_build_on_property(self):
        result = check_document(CHAIN)
        assert result.passed, result.errors

    def test_false_step_is_caught(self):
        bad = CHAIN.replace("2 * (zH - zM) >= 0", "2 * (zH - zM) >= 1")
        result = check_document(bad)
        assert any('"P2" does NOT follow from P1' in e for e in result.errors)

    def test_lean_statement_uses_property_as_hypothesis(self):
        theorems, _ = build_theorems(check_document(CHAIN).registry)
        p2 = next(t for t in theorems if t.name == "P2")
        assert "(P1 : (H - M) ≥ 0)" in p2.statement

    def test_weakest_premise_caps_the_level(self):
        reg = check_document(CHAIN).registry
        theorems, _ = build_theorems(reg)
        # P2 Lean-proved, P1 only Z3-checked
        cache = record_results({}, theorems, {"P2": ProofResult("proved")}, "tc")
        levels = {v["name"]: v for v in verification_levels(reg, True, cache)}
        assert levels["P1"]["level"] == "Z3-checked"
        assert levels["P2"]["level"] == "Z3-checked"
        assert "relies on P1 (Z3-checked)" in levels["P2"]["detail"]
        cache = record_results(cache, theorems, {"P1": ProofResult("proved")}, "tc")
        levels = {v["name"]: v for v in verification_levels(reg, True, cache)}
        assert levels["P2"]["level"] == "Lean-proved"

    def test_premise_must_be_declared_first(self):
        doc = CHAIN.replace('given=["A1"], description="p",\n         lean_proof="linarith [A1.2]")',
                            'given=["P2"], description="p")')
        result = check_document(doc)
        assert not result.passed and any("premises must be declared first" in e for e in result.errors)


@needs_lean
def test_real_lean_chain():
    theorems, _ = build_theorems(check_document(CHAIN).registry)
    results = run_lean(theorems, lean_env, timeout=600)
    assert results["P1"].status == "proved", results["P1"].messages
    assert results["P2"].status == "proved", results["P2"].messages
