from meta_compiler.compiler.paper import generate_paper
from meta_compiler.compiler.parser import parse_document, FixtureBlock, ResultsBlock


def test_paper_strips_validation_blocks():
    """Paper output includes prose and math but not validation blocks."""
    doc = """### 2.1 Worker Capacity

Each worker has a maximum capacity:

$$cap_i \\in \\mathbb{R}^+$$

```python:validate
cap = Parameter("cap", index=["W"], units="hours", description="Capacity")
registry.run_tests()
```

### 2.2 Next Section
"""
    blocks = parse_document(doc)
    paper = generate_paper(blocks)
    assert "Worker Capacity" in paper
    assert "$$cap_i" in paper
    assert "Parameter(" not in paper
    assert "registry.run_tests()" not in paper
    assert "python:validate" not in paper
    assert "Next Section" in paper


def test_paper_depth_executive():
    """Executive depth filter shows only executive content."""
    doc = """<!-- depth:executive -->
# Executive Summary

Key findings.

<!-- depth:technical -->
# Technical Details

$$x = 1$$

The math details.
"""
    blocks = parse_document(doc)
    paper = generate_paper(blocks, depth="executive")
    assert "Executive Summary" in paper
    assert "Key findings" in paper
    assert "Technical Details" not in paper


def test_paper_depth_technical():
    """Technical depth filter shows executive and technical content."""
    doc = """<!-- depth:executive -->
# Executive Summary

Key findings.

<!-- depth:technical -->
# Technical Details

$$x = 1$$

<!-- depth:appendix -->
# Appendix

Proofs and derivations.
"""
    blocks = parse_document(doc)
    paper = generate_paper(blocks, depth="technical")
    assert "Executive Summary" in paper
    assert "Technical Details" in paper
    assert "Appendix" not in paper


def test_paper_no_depth_filter():
    """No depth filter includes everything."""
    doc = """<!-- depth:executive -->
# Executive Summary

<!-- depth:appendix -->
# Appendix
"""
    blocks = parse_document(doc)
    paper = generate_paper(blocks)
    assert "Executive Summary" in paper
    assert "Appendix" in paper


def test_paper_strips_fixture_blocks():
    source = '''# Model

Some prose.

```python:fixture
cap = {"alice": 40}
```

$$x + y$$

```python:validate
Set("W")
```

More prose.
'''
    blocks = parse_document(source)
    paper = generate_paper(blocks)
    assert "python:fixture" not in paper
    assert "cap =" not in paper
    assert "Some prose" in paper
    assert "$$x + y$$" in paper
    assert "More prose" in paper
    assert "python:validate" not in paper


def test_paper_includes_results_output():
    """Results block output appears in paper, code does not."""
    source = '''# Model

Some prose.

```python:fixture
x = 42
```

```python:results
print(f"The answer is {x}.")
```

```python:validate
Parameter("x", description="the answer")
```

More prose.
'''
    from meta_compiler.compiler.executor import execute_blocks
    blocks = parse_document(source)
    execute_blocks(blocks)  # populates ResultsBlock.output
    paper = generate_paper(blocks)
    assert "The answer is 42." in paper
    assert "python:results" not in paper
    assert "python:fixture" not in paper
    assert "python:validate" not in paper
    assert "Some prose" in paper
    assert "More prose" in paper


def test_paper_empty_results_omitted():
    """A results block that prints nothing is silently omitted."""
    source = '''# Model

```python:results
pass  # no output
```

Some prose.
'''
    blocks = parse_document(source)
    from meta_compiler.compiler.executor import execute_blocks
    execute_blocks(blocks)
    rblocks = [b for b in blocks if isinstance(b, ResultsBlock)]
    assert rblocks[0].output == ""
    paper = generate_paper(blocks)
    assert "python:results" not in paper
    assert "Some prose" in paper


def test_paper_results_with_depth_filter():
    """Results blocks respect depth filtering."""
    source = '''<!-- depth:executive -->
# Summary

Key findings.

<!-- depth:appendix -->
# Appendix

```python:results
print("Detailed computation log")
```
'''
    blocks = parse_document(source)
    from meta_compiler.compiler.executor import execute_blocks
    execute_blocks(blocks)
    paper = generate_paper(blocks, depth="executive")
    assert "Key findings" in paper
    assert "Detailed computation log" not in paper


# ── Verification notes in the compiled paper ────────────────────────────────

import pytest

VERIFIED_DOC = '''# Model

## Assumptions

```python:fixture
H = 8.0
M = 2.0
```

```python:validate
from z3 import Real, And
zH, zM = Real("H"), Real("M")
Parameter("H", units="hours", description="h")
Parameter("M", units="hours", description="m")
Axiom("A2", statement="0 <= M <= H", z3_expr=lambda: And(zM >= 0, zM <= zH), description="a")
```

## Results

```python:validate
Property("P1", claim="H - M >= 0", z3_expr=lambda: zH - zM >= 0, given=["A2"], description="p")
Theorem("T1", claim="trivially true", lean="theorem T1 : True := trivial", description="t")
Theorem("T2", claim="also true", lean="theorem T2 : 1 = 1 := rfl", description="t")
```
'''


def _compile(proofs=None, **kw):
    pytest.importorskip("z3")
    from meta_compiler.compiler import compile_document
    return compile_document(VERIFIED_DOC, strict=False, proofs=proofs, **kw)["paper"]


def _proofs(approve=("T1",)):
    pytest.importorskip("z3")
    from meta_compiler.compiler import check_document
    from meta_compiler.lean import ProofResult, build_theorems, record_approvals, record_results

    reg = check_document(VERIFIED_DOC).registry
    theorems, _ = build_theorems(reg)
    results = {t.name: ProofResult("proved") for t in theorems if t.name != "P1"}
    cache = record_results({}, theorems, results, "tc")
    return record_approvals(cache, theorems, list(approve))


def test_inline_notes_replace_claim_blocks():
    paper = _compile(_proofs())
    assumptions, results = paper.split("## Results")
    assert "**A2** 0 <= M <= H — Assumption; consistent with the example data" in assumptions
    assert "**P1** H - M >= 0 — Verified (Z3)" in results
    assert "python:validate" not in paper


def test_summary_table_and_legend():
    paper = _compile(_proofs())
    summary = paper[paper.index("## Verification"):]
    assert "| P1 | H - M >= 0 | Verified (Z3) |" in summary
    assert "*Proved (Lean)*:" in summary


def test_unapproved_theorem_is_not_reported_as_approved():
    paper = _compile(_proofs(approve=("T1",)))
    assert "**T1** trivially true — Proved (Lean); statement approved by the author" in paper
    assert "**T2** also true — Proved (Lean); statement not yet approved by the author" in paper


def test_without_lean_results_theorems_are_not_verified():
    paper = _compile(None)
    assert "**T1** trivially true — Not verified; statement not yet approved" in paper


def test_executive_depth_has_summary_only():
    paper = _compile(_proofs(), depth="executive")
    assert "> **Verification**" not in paper
    assert "## Verification" in paper


def test_opt_out():
    paper = _compile(_proofs(), annotate=False)
    assert "Verification" not in paper


def test_document_without_claims_is_unchanged():
    from meta_compiler.compiler import compile_document

    doc = '```python:fixture\nx = 1.0\n```\n```python:validate\nParameter("x", description="x")\n```\n'
    assert "Verification" not in compile_document(doc, strict=False)["paper"]
