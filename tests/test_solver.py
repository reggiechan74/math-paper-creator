"""`mpc solve`: the paper's own lambdas, solved with Pyomo + HiGHS."""

import pytest

pytest.importorskip("pyomo.environ")
pytest.importorskip("highspy")

from meta_compiler.compiler.parser import parse_document
from meta_compiler.solver import format_solution, solve_blocks

ASSIGN = '''```python:fixture
W = ["alice", "bob", "carol"]
T = ["design", "build"]
cap = {"alice": 40.0, "bob": 30.0, "carol": 35.0}
need = {"design": 30.0, "build": 50.0}
value = {("alice", "design"): 3.0, ("alice", "build"): 2.0,
         ("bob", "design"): 1.0, ("bob", "build"): 4.0,
         ("carol", "design"): 2.0, ("carol", "build"): 2.0}
x = {("alice", "design"): 20.0, ("alice", "build"): 20.0,
     ("bob", "design"): 10.0, ("bob", "build"): 20.0,
     ("carol", "design"): 0.0, ("carol", "build"): 10.0}
```
```python:validate
Set("W", description="workers")
Set("T", description="tasks")
Parameter("cap", index="W", units="hours", description="capacity")
Parameter("need", index="T", units="hours", description="demand")
Parameter("value", index=["W", "T"], units="dollars/hours", description="value per hour")
Variable("x", index=["W", "T"], bounds=(0, None), units="hours", description="hours")
Constraint("capacity", expr=lambda w: sum(x[w, t] for t in S("T")) <= cap[w], over="W", description="c")
Constraint("demand", expr=lambda t: sum(x[w, t] for w in S("W")) >= need[t], over="T", description="d")
Constraint("cover", expr=lambda: all(sum(x[w, t] for w in S("W")) <= 2 * need[t] for t in S("T")), description="c")
Objective("total_value", expr=lambda: sum(value[w, t] * x[w, t] for w in S("W") for t in S("T")),
          sense="maximize", description="o")
```
'''


def solve(doc, **kw):
    return solve_blocks(parse_document(doc), **kw)


def test_assignment_lp_reuses_the_papers_lambdas():
    sol = solve(ASSIGN)
    assert sol.status == "optimal"
    assert sol.objective_value == pytest.approx(310)
    assert sol.fixture_objective_value == pytest.approx(210)
    assert sol.variables["x"]["alice, design"] == pytest.approx(40)
    assert set(sol.binding["capacity"]) == {"alice", "bob", "carol"}
    assert set(sol.slack["cover"]) == {"#1", "#2"}  # all(...) became two constraints
    assert "68% of optimal" in format_solution(sol)


def test_check_still_passes_after_solving():
    from meta_compiler.compiler import check_document

    solve(ASSIGN)
    assert check_document(ASSIGN).passed  # translation doesn't leak into the namespace


KNAPSACK = '''```python:fixture
I = ["a", "b", "c", "d"]
w = {"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.0}
v = {"a": 10.0, "b": 7.0, "c": 5.0, "d": 3.0}
W_max = 9.0
pick = {"a": 1, "b": 0, "c": 0, "d": 0}
```
```python:validate
Set("I", description="items")
Parameter("w", index="I", description="weight")
Parameter("v", index="I", description="value")
Parameter("W_max", description="capacity")
Variable("pick", index="I", domain="binary", bounds=(0, 1), description="choose")
Constraint("weight", expr=lambda: sum(w[i] * pick[i] for i in S("I")) <= W_max, description="c")
Objective("value", expr=lambda: sum(v[i] * pick[i] for i in S("I")), sense="maximize", description="o")
```
'''


def test_binary_knapsack_is_a_mip():
    sol = solve(KNAPSACK)
    assert sol.status == "optimal"
    assert sol.objective_value == pytest.approx(17)  # a + b
    assert sol.variables["pick"] == {"a": 1, "b": 1, "c": 0, "d": 0}


SCALAR = '''```python:fixture
q = 1.0
```
```python:validate
Variable("q", bounds=(0, 10), description="quantity")
Constraint("cap", expr=lambda: 2 * q <= 8, description="c")
Objective("profit", expr=lambda: 3 * q, sense="maximize", description="o")
```
'''


def test_scalar_variables():
    sol = solve(SCALAR)
    assert sol.status == "optimal" and sol.variables["q"] == pytest.approx(4)


def test_infeasible_when_example_breaks_bounds():
    # A validated paper is feasible at its own example, unless the example
    # ignores the Variable's bounds — check warns about that, solve reports it.
    from meta_compiler.compiler import check_document

    doc = SCALAR.replace("q = 1.0", "q = 20.0").replace("2 * q <= 8", "q >= 20")
    result = check_document(doc)
    assert result.passed
    assert any('"q" = 20.0 in the example is above its upper bound 10' in w for w in result.warnings)
    assert solve(doc).status in ("infeasible", "infeasible_or_unbounded")


def test_unbounded():
    sol = solve(SCALAR.replace("bounds=(0, 10)", "bounds=(0, None)").replace("2 * q <= 8", "q >= 0"))
    assert sol.status in ("unbounded", "infeasible_or_unbounded")


def test_nonlinear_constraint_suggests_ipopt():
    doc = SCALAR.replace("2 * q <= 8", "q * q * q <= 8")
    sol = solve(doc)
    assert sol.status == "error" and "ipopt" in sol.message


def test_python_logic_on_variables_is_untranslatable():
    sol = solve(SCALAR.replace("2 * q <= 8", "max(q, 1) <= 8"))
    assert sol.status == "error"
    assert "cap" in sol.untranslatable


def test_several_objectives_need_a_choice():
    doc = SCALAR.replace('Objective("profit"', 'Objective("other", expr=lambda: q, sense="minimize", description="o")\nObjective("profit"')
    assert "--objective" in solve(doc).message
    sol = solve(doc, objective="other")
    assert sol.status == "optimal" and sol.objective_value == pytest.approx(0)


def test_nothing_to_optimize():
    doc = '```python:fixture\nx = 1.0\n```\n```python:validate\nParameter("x", description="x")\n```\n'
    assert "nothing to optimize" in solve(doc).message


def test_cli(tmp_path, capsys):
    import json
    from meta_compiler.cli import main

    path = tmp_path / "a.model.md"
    path.write_text(ASSIGN)
    out = tmp_path / "solution.json"
    assert main(["solve", str(path), "--output", str(out)]) == 0
    assert json.loads(out.read_text())["objective_value"] == pytest.approx(310)
    assert "Binding constraints" in capsys.readouterr().out
