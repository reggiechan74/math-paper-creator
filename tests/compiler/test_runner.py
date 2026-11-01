from meta_compiler.compiler.runner import generate_runner


def test_generate_runner_contains_check_call():
    script = generate_runner([], model_path="my_model.model.md")
    assert "check_document" in script
    assert "my_model.model.md" in script
    assert "strict=True" in script
    assert script.startswith("#!/usr/bin/env python3")


def test_generate_runner_is_valid_python():
    script = generate_runner([], model_path="test.model.md")
    compile(script, "<runner>", "exec")  # should not raise


def test_generate_runner_blocks_first_signature():
    """generate_runner takes blocks as first positional arg, model_path as keyword-only."""
    from meta_compiler.compiler.runner import generate_runner
    from meta_compiler.compiler.parser import parse_document

    source = '''
Some prose.

```python:fixture
W = ["alice", "bob"]
```

```python:validate
Set("W", description="workers")
```
'''
    blocks = parse_document(source)
    script = generate_runner(blocks, model_path="test.model.md")
    assert "test.model.md" in script
    assert "#!/usr/bin/env python3" in script


def test_runner_includes_results_blocks():
    from meta_compiler.compiler.parser import parse_document
    source = '''# Model

```python:fixture
x = 42
```

```python:results
print(f"The answer is {x}")
```

```python:validate
Parameter("x", description="the answer")
```
'''
    blocks = parse_document(source)
    script = generate_runner(blocks, model_path="test.model.md")
    assert 'print(f"The answer is {x}")' in script
    compile(script, "<runner>", "exec")  # valid Python


def test_runner_results_without_fixtures():
    from meta_compiler.compiler.parser import parse_document
    source = '''# Model

```python:results
print("hello")
```
'''
    blocks = parse_document(source)
    script = generate_runner(blocks, model_path="test.model.md")
    assert 'print("hello")' in script
    compile(script, "<runner>", "exec")  # valid Python


# ── Behavioural tests: generated runners must give the same verdict as check ──

import os
import subprocess
import sys
from pathlib import Path

from meta_compiler.compiler.parser import parse_document

SRC = str(Path(__file__).resolve().parents[2] / "src")


def _run_runner(tmp_path, doc: str, *args: str) -> subprocess.CompletedProcess:
    script = tmp_path / "runner.py"
    script.write_text(generate_runner(parse_document(doc), model_path="t.model.md"))
    return subprocess.run(
        [sys.executable, str(script), *args], capture_output=True, text=True,
        cwd=tmp_path, env=dict(os.environ, PYTHONPATH=SRC), timeout=60,
    )


def test_runner_executes_and_passes(tmp_path):
    doc = '''# A
```python:fixture
H = 8.0
```
```python:results
print(f"H is {H}")
```
```python:validate
Parameter("H", units="hours", description="h")
Constraint("cap", expr=lambda: H <= 10, description="c")
registry.run_tests()
```
'''
    result = _run_runner(tmp_path, doc)
    assert result.returncode == 0, result.stderr
    assert "H is 8.0" in result.stdout
    assert "All checks passed." in result.stdout


def test_runner_reports_violated_constraint(tmp_path):
    doc = '''```python:fixture
H = 20.0
```
```python:validate
Parameter("H", units="hours", description="h")
Constraint("cap", expr=lambda: H <= 10, description="c")
```
'''
    result = _run_runner(tmp_path, doc)
    assert result.returncode == 1
    assert 'Constraint "cap" failed' in result.stderr


def test_runner_preserves_backslashes_and_quotes(tmp_path):
    doc = r'''```python:fixture
label = "a\\b"
q = """triple"""
```
```python:validate
Parameter("label", description="has a backslash")
Constraint("ok", expr=lambda: label == "a\\b", description="c")
```
'''
    result = _run_runner(tmp_path, doc)
    assert result.returncode == 0, result.stderr
