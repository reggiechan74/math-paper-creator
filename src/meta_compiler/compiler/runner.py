"""Generate a standalone runner script from .model.md fixture, results, and validate blocks.

The runner embeds every fixture, results and validate block from the
document, in document order, and runs them through the same engine as
``meta-compiler check`` (``execute_blocks``). It does not need the .model.md
file, only the ``meta_compiler`` package, so it gives exactly the same verdict
as checking the paper: constraints, objectives, axioms and structural checks.
"""

from __future__ import annotations

from meta_compiler.compiler.parser import Block, FixtureBlock, ResultsBlock, ValidationBlock

_KINDS = {FixtureBlock: "fixture", ResultsBlock: "results", ValidationBlock: "validate"}


def _literal(code: str) -> str:
    """A readable Python literal for a code block."""
    triple = "'" * 3
    if triple not in code and not code.endswith("\\"):
        return "r" + triple + code + triple
    return repr(code)


def generate_runner(blocks: list[Block], *, model_path: str = "model.model.md") -> str:
    """Generate a standalone Python script from extracted blocks.

    If no executable blocks are provided (backward compat), falls back to a
    thin wrapper that re-parses the .model.md file.
    """
    code_blocks = [b for b in blocks if type(b) in _KINDS]
    if not code_blocks:
        return _generate_legacy_runner(model_path)

    parts: list[str] = [
        "#!/usr/bin/env python3",
        f'"""Standalone validation runner extracted from {model_path}.',
        "",
        "Contains every fixture, results and validate block from the document, in",
        "document order, and runs them through the meta-compiler engine. It does",
        "not need the paper itself.",
        "",
        "Usage:",
        "    python3 runner.py",
        "    python3 runner.py --strict   # treat orphans as errors",
        '"""',
        "",
        "import sys",
        "",
        "from meta_compiler.compiler.executor import execute_blocks",
        "from meta_compiler.compiler.parser import FixtureBlock, ResultsBlock, ValidationBlock",
        "",
        "_KINDS = {\"fixture\": FixtureBlock, \"results\": ResultsBlock, \"validate\": ValidationBlock}",
        "",
        "# (kind, source line, code)",
        "BLOCKS = [",
    ]
    for block in code_blocks:
        parts.append(f"    ({_KINDS[type(block)]!r}, {block.line_number}, {_literal(block.code)}),")
    parts += [
        "]",
        "",
        "",
        "def main():",
        "    strict = \"--strict\" in sys.argv",
        "    blocks = [_KINDS[kind](code=code, line_number=line) for kind, line, code in BLOCKS]",
        "    result = execute_blocks(blocks, strict=strict)",
        "",
        "    for block in blocks:",
        "        if isinstance(block, ResultsBlock) and block.output:",
        "            print(block.output, end=\"\")",
        "",
        "    for error in result.errors:",
        "        print(f\"ERROR: {error}\", file=sys.stderr)",
        "    for warning in result.warnings:",
        "        print(f\"WARNING: {warning}\", file=sys.stderr)",
        "",
        "    if result.passed:",
        "        print(\"All checks passed.\")",
        "    else:",
        "        print(f\"{len(result.errors)} error(s) found.\", file=sys.stderr)",
        "        sys.exit(1)",
        "",
        "",
        "if __name__ == \"__main__\":",
        "    main()",
        "",
    ]
    return "\n".join(parts)


def _generate_legacy_runner(model_path: str) -> str:
    """Fallback: thin wrapper that re-parses .model.md at runtime."""
    return f'''#!/usr/bin/env python3
"""Auto-generated runner for {model_path}."""

import sys
from pathlib import Path

from meta_compiler.compiler import check_document


def main():
    path = Path(__file__).parent / "{model_path}"
    if not path.exists():
        print(f"Error: {{path}} not found", file=sys.stderr)
        sys.exit(1)

    result = check_document(path.read_text(), strict=True)

    if result.errors:
        for error in result.errors:
            print(f"ERROR: {{error}}", file=sys.stderr)
    for warning in result.warnings:
        print(f"WARNING: {{warning}}", file=sys.stderr)

    if result.passed:
        print("All checks passed.")
    else:
        print(f"{{len(result.errors)}} error(s) found.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
'''
