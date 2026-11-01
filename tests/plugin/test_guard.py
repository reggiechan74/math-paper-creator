"""PreToolUse guard: approved claim statements can't be changed by edits."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("z3")

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts" / "guard.py"

DOC = '''# Model
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
Property("P1", claim="H - M >= 0", z3_expr=lambda: zH - zM >= 0, given=["A2"], description="p")
Theorem("T1", claim="c * x is linear", lean=r"""
theorem T1 (c : ℝ) : deriv (fun x : ℝ => c * x) = fun _ => c := by
  sorry
""", description="t")
```
'''


def guard(payload: dict) -> dict | None:
    proc = subprocess.run(
        [sys.executable, str(GUARD)], input=json.dumps(payload),
        capture_output=True, text=True, timeout=60,
        env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def decision(out):
    return out and out["hookSpecificOutput"]["permissionDecision"]


@pytest.fixture
def paper(tmp_path):
    from meta_compiler.cli import main

    path = tmp_path / "paper.model.md"
    path.write_text(DOC)
    assert main(["approve", str(path), "--name", "T1", "--name", "P1"]) == 0
    return path


def edit(path, old, new):
    return guard({"tool_name": "Edit", "cwd": str(path.parent), "tool_input": {
        "file_path": str(path), "old_string": old, "new_string": new}})


def test_changing_approved_theorem_statement_is_denied(paper):
    out = edit(paper, "fun _ => c := by", "fun _ => c + 0 := by")
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "T1 — approved" in reason and "after this edit" in reason


def test_changing_only_the_proof_is_allowed(paper):
    assert edit(paper, "  sorry\n", "  funext x\n  simp\n") is None


def test_weakening_approved_property_is_denied(paper):
    out = edit(paper, "zH - zM >= 0, given", "zH - zM >= -1, given")
    assert decision(out) == "deny"


def test_changing_an_axiom_behind_an_approved_property_is_denied(paper):
    # The axiom is a hypothesis of P1's statement, so P1's meaning changes
    out = edit(paper, "And(zM >= 0, zM <= zH)", "And(zM >= 0, zM <= zH + 1)")
    assert decision(out) == "deny"


def test_removing_an_approved_claim_is_denied(paper):
    text = paper.read_text()
    start = text.index('Property("P1"')
    end = text.index("\n", start) + 1
    out = guard({"tool_name": "Write", "cwd": str(paper.parent), "tool_input": {
        "file_path": str(paper), "content": text[:start] + text[end:]}})
    assert decision(out) == "deny"


def test_unrelated_edit_is_allowed(paper):
    assert edit(paper, "# Model", "# Model of a working day") is None


def test_no_approvals_means_no_checks(tmp_path):
    path = tmp_path / "p.model.md"
    path.write_text(DOC)
    assert edit(path, "fun _ => c := by", "fun _ => c + 0 := by") is None


def test_direct_sidecar_edit_is_denied(paper):
    out = guard({"tool_name": "Write", "tool_input": {
        "file_path": str(paper.with_name("paper.proofs.json")), "content": "{}"}})
    assert decision(out) == "deny"


def test_approve_command_asks_the_user_and_shows_statement(paper):
    cmd = f'CLAUDE_PLUGIN_DATA="/x" "/plugin/scripts/mpc" approve "{paper}" --name T1'
    out = guard({"tool_name": "Bash", "cwd": str(paper.parent), "tool_input": {"command": cmd}})
    assert decision(out) == "ask"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "YOUR approval" in reason and "theorem T1" in reason


def test_revoke_asks_the_user(paper):
    cmd = f'"/plugin/scripts/mpc" approve "{paper}" --name T1 --revoke'
    out = guard({"tool_name": "Bash", "cwd": str(paper.parent), "tool_input": {"command": cmd}})
    assert decision(out) == "ask"
    assert "withdraw" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_shell_write_to_sidecar_asks(paper):
    out = guard({"tool_name": "Bash", "cwd": str(paper.parent),
                 "tool_input": {"command": "echo '{}' > paper.proofs.json"}})
    assert decision(out) == "ask"
    assert guard({"tool_name": "Bash", "cwd": str(paper.parent),
                  "tool_input": {"command": "cat paper.proofs.json"}}) is None


def test_check_reports_changed_approved_statement(paper, capsys):
    from meta_compiler.cli import main

    paper.write_text(paper.read_text().replace("fun _ => c := by", "fun _ => c + 0 := by"))
    assert main(["check", str(paper)]) == 1
    assert "changed since the author approved it" in capsys.readouterr().out
    assert main(["approvals", str(paper)]) == 1


def test_report_shows_approval_state(paper):
    from meta_compiler.cli import _load_sidecar
    from meta_compiler.compiler import check_document
    from meta_compiler.lean import verification_levels

    reg = check_document(paper.read_text()).registry
    levels = {v["name"]: v for v in verification_levels(reg, True, _load_sidecar(paper))}
    assert "approved by the author" in levels["T1"]["detail"]
