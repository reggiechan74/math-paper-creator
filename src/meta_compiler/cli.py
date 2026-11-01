"""CLI entry point for the meta-compiler.

Usage:
    python -m meta_compiler.cli check <file.model.md>
    python -m meta_compiler.cli paper <file.model.md> [--depth executive|technical|appendix]
    python -m meta_compiler.cli report <file.model.md>
    python -m meta_compiler.cli compile <file.model.md> [--output <dir>]
    python -m meta_compiler.cli reconcile <file.model.md> [--section "<heading>"]
    python -m meta_compiler.cli verify <file.model.md>
    python -m meta_compiler.cli symbols <file.model.md> [--json]
    python -m meta_compiler.cli lean <file.model.md> [--name NAME]
    python -m meta_compiler.cli prove <file.model.md> [--name NAME] [--json]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="meta-compiler",
        description="Validated mathematical model compiler",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # check
    check_parser = subparsers.add_parser("check", help="Validate a .model.md document")
    check_parser.add_argument("file", type=Path, help="Path to .model.md file")
    check_parser.add_argument("--strict", action="store_true",
                              help="Treat orphans as errors")

    # paper
    paper_parser = subparsers.add_parser("paper", help="Generate paper artifact")
    paper_parser.add_argument("file", type=Path, help="Path to .model.md file")
    paper_parser.add_argument("--depth", choices=["executive", "technical", "appendix"],
                              help="Depth filter for paper output")
    paper_parser.add_argument("--output", type=Path, help="Output file path")
    paper_parser.add_argument(
        "--no-strict", action="store_true",
        help="Treat orphan symbols as warnings instead of errors",
    )
    paper_parser.add_argument(
        "--skip-validation", action="store_true",
        help="Generate paper without running validation",
    )

    # report
    report_parser = subparsers.add_parser("report", help="Generate validation report")
    report_parser.add_argument("file", type=Path, help="Path to .model.md file")
    report_parser.add_argument("--output", type=Path, help="Output file path")
    report_parser.add_argument(
        "--no-strict", action="store_true",
        help="Treat orphan symbols as warnings instead of errors",
    )

    # compile
    compile_parser = subparsers.add_parser("compile", help="Generate all artifacts")
    compile_parser.add_argument("file", type=Path, help="Path to .model.md file")
    compile_parser.add_argument("--output", type=Path, default=Path("output"),
                                help="Output directory (default: output/)")
    compile_parser.add_argument("--depth", choices=["executive", "technical", "appendix"],
                                help="Depth filter for paper output")
    compile_parser.add_argument(
        "--no-strict", action="store_true",
        help="Treat orphan symbols as warnings instead of errors",
    )

    # reconcile
    reconcile_parser = subparsers.add_parser(
        "reconcile", help="Run prose-math reconciliation checks"
    )
    reconcile_parser.add_argument("file", type=Path, help="Path to .model.md file")
    reconcile_parser.add_argument(
        "--section", type=str, default=None,
        help="Scope checks to a specific section heading"
    )

    # verify
    verify_parser = subparsers.add_parser("verify", help="Run Z3 axiom verification")
    verify_parser.add_argument("file", type=Path, help="Path to .model.md file")

    # symbols
    symbols_parser = subparsers.add_parser(
        "symbols", help="List registered symbols (the document's symbol table)"
    )
    symbols_parser.add_argument("file", type=Path, help="Path to .model.md file")
    symbols_parser.add_argument("--json", action="store_true",
                                help="Emit machine-readable JSON")

    # lean
    lean_parser = subparsers.add_parser(
        "lean", help="Print the Lean 4 file generated for Properties and Theorems"
    )
    lean_parser.add_argument("file", type=Path, help="Path to .model.md file")
    lean_parser.add_argument("--name", action="append",
                             help="Only this claim (repeatable)")

    # prove
    prove_parser = subparsers.add_parser(
        "prove", help="Check Lean proofs and record results in <paper>.proofs.json"
    )
    prove_parser.add_argument("file", type=Path, help="Path to .model.md file")
    prove_parser.add_argument("--name", action="append",
                              help="Only this claim (repeatable)")
    prove_parser.add_argument("--timeout", type=int, default=600,
                              help="Seconds before Lean is stopped (default 600)")
    prove_parser.add_argument("--json", action="store_true",
                              help="Emit machine-readable JSON")

    args = parser.parse_args(argv)
    source = args.file.read_text()

    if args.command == "check":
        return _cmd_check(source, strict=args.strict)
    elif args.command == "paper":
        return _cmd_paper(source, depth=args.depth, output=args.output,
                          strict=not args.no_strict,
                          skip_validation=args.skip_validation)
    elif args.command == "report":
        return _cmd_report(source, output=args.output, strict=not args.no_strict,
                           proofs=_load_sidecar(args.file))
    elif args.command == "compile":
        return _cmd_compile(source, output=args.output, depth=args.depth,
                            strict=not args.no_strict, proofs=_load_sidecar(args.file))
    elif args.command == "reconcile":
        return _cmd_reconcile(source, section=args.section)
    elif args.command == "verify":
        return _cmd_verify(source)
    elif args.command == "symbols":
        return _cmd_symbols(source, as_json=args.json)
    elif args.command == "lean":
        return _cmd_lean(source, names=args.name)
    elif args.command == "prove":
        return _cmd_prove(source, path=args.file, names=args.name,
                          timeout=args.timeout, as_json=args.json)
    return 1


def _cmd_check(source: str, *, strict: bool = False) -> int:
    from meta_compiler.compiler import check_document

    result = check_document(source, strict=strict)
    if result.passed:
        print("PASSED")
        for w in result.warnings:
            print(f"  WARNING: {w}")
        return 0
    else:
        print("FAILED")
        for e in result.errors:
            print(f"  ERROR: {e}")
        for w in result.warnings:
            print(f"  WARNING: {w}")
        return 1


def _cmd_paper(source: str, *, depth: str | None, output: Path | None,
               strict: bool = True, skip_validation: bool = False) -> int:
    from meta_compiler.compiler import compile_document

    try:
        artifacts = compile_document(source, depth=depth, strict=strict,
                                     skip_validation=skip_validation)
    except (ValueError, RuntimeError) as e:
        print(str(e), file=sys.stderr)
        return 1

    paper = artifacts["paper"]
    if output:
        output.write_text(paper)
        print(f"Paper written to {output}")
    else:
        print(paper)
    return 0


def _load_sidecar(path: Path) -> dict | None:
    from meta_compiler.lean import load_proofs, proofs_path

    return load_proofs(proofs_path(path)) or None


def _cmd_report(source: str, *, output: Path | None, strict: bool = True,
                proofs: dict | None = None) -> int:
    from meta_compiler.compiler import compile_document

    try:
        artifacts = compile_document(source, strict=strict, proofs=proofs)
    except (ValueError, RuntimeError) as e:
        print(str(e), file=sys.stderr)
        return 1

    text = artifacts["report_text"]
    if output:
        output.write_text(text)
        print(f"Report written to {output}")
    else:
        print(text)
    return 0


def _cmd_compile(source: str, *, output: Path, depth: str | None,
                 strict: bool = True, proofs: dict | None = None) -> int:
    from meta_compiler.compiler import compile_document

    try:
        artifacts = compile_document(source, depth=depth, strict=strict, proofs=proofs)
    except (ValueError, RuntimeError) as e:
        print(str(e), file=sys.stderr)
        return 1

    output.mkdir(parents=True, exist_ok=True)
    (output / "paper.md").write_text(artifacts["paper"])
    (output / "runner.py").write_text(artifacts["runner"])
    (output / "report.txt").write_text(artifacts["report_text"])
    if artifacts.get("lean"):
        (output / "Proofs.lean").write_text(artifacts["lean"])

    print(f"Artifacts written to {output}/")
    print("  paper.md")
    print("  runner.py")
    print("  report.txt")
    if artifacts.get("lean"):
        print("  Proofs.lean")
    return 0


def _cmd_reconcile(source: str, *, section: str | None) -> int:
    from meta_compiler.compiler import reconcile_document

    warnings, _ = reconcile_document(source, section=section)
    if warnings:
        print("Reconciliation warnings:")
        for w in warnings:
            print(f"  WARNING: {w}")
        return 2
    else:
        print("Reconciliation: OK")
        return 0


def _cmd_verify(source: str) -> int:
    from meta_compiler.compiler.parser import parse_document
    from meta_compiler.compiler.executor import execute_blocks
    from meta_compiler.verification import z3_available

    if not z3_available():
        print("z3-solver is not installed. Install with: pip install z3-solver",
              file=sys.stderr)
        return 1

    blocks = parse_document(source)
    result = execute_blocks(blocks)

    # Extract axiom/property info from registry
    from meta_compiler.symbols import AxiomSymbol, PropertySymbol
    reg = result.registry
    if reg is None:
        print("FAILED — could not build registry", file=sys.stderr)
        return 1

    axioms = [s for s in reg.symbols.values() if isinstance(s, AxiomSymbol)]
    properties = [s for s in reg.symbols.values() if isinstance(s, PropertySymbol)]
    z3_axioms = [a for a in axioms if a.z3_expr is not None]

    if not z3_axioms:
        print("No axioms with Z3 expressions found.")
        return 0

    print(f"Axiom verification (Z3):")
    print(f"  Axioms: {len(z3_axioms)}, Properties: {len(properties)}")

    if result.passed:
        print(f"  PASSED")
        for w in result.warnings:
            print(f"  WARNING: {w}")
        return 0
    else:
        print(f"  FAILED")
        for e in result.errors:
            print(f"  ERROR: {e}")
        return 1


def symbol_table(registry) -> list[dict]:
    """Registered symbols as plain dicts, in registration order."""
    from dataclasses import fields

    kinds = {
        "SetSymbol": "set", "ParameterSymbol": "parameter",
        "VariableSymbol": "variable", "ExpressionSymbol": "expression",
        "ConstraintSymbol": "constraint", "ObjectiveSymbol": "objective",
        "AxiomSymbol": "axiom", "PropertySymbol": "property",
        "TheoremSymbol": "theorem",
    }
    skip = {"expr", "z3_expr", "name", "lean"}
    table = []
    for name in registry._registration_order:
        sym = registry.symbols[name]
        entry = {"name": name, "kind": kinds.get(type(sym).__name__, type(sym).__name__)}
        for f in fields(sym):
            if f.name in skip:
                continue
            value = getattr(sym, f.name)
            if isinstance(value, tuple):
                value = list(value)
            if value is not None:
                entry[f.name] = value
        if any(f.name == "z3_expr" for f in fields(sym)):
            entry["z3"] = sym.z3_expr is not None
        entry["line"] = registry.defined_at.get(name)
        table.append(entry)
    return table


def _cmd_symbols(source: str, *, as_json: bool) -> int:
    import json

    from meta_compiler.compiler import check_document

    result = check_document(source, strict=False)
    if result.registry is None:
        print("Could not build the symbol table:", file=sys.stderr)
        for e in result.errors:
            print(f"  ERROR: {e}", file=sys.stderr)
        return 1

    table = symbol_table(result.registry)
    if as_json:
        print(json.dumps({"passed": result.passed, "symbols": table}, indent=2, default=str))
    else:
        for entry in table:
            extra = f" [{', '.join(entry['index'])}]" if entry.get("index") else ""
            latex = f"  latex={entry['latex']}" if entry.get("latex") else ""
            print(f"{entry['kind']:<11} {entry['name']}{extra}  (line {entry['line']}){latex}")
        if not result.passed:
            print(f"\n{len(result.errors)} validation error(s); run check for details.")
    return 0 if result.passed else 1


def _registry_or_errors(source: str):
    from meta_compiler.compiler import check_document

    result = check_document(source, strict=False)
    if result.registry is None or (not result.passed and not result.registry.symbols):
        print("The document does not validate; fix it first:", file=sys.stderr)
        for e in result.errors:
            print(f"  ERROR: {e}", file=sys.stderr)
        return None, result
    return result.registry, result


def _select(theorems, names):
    if not names:
        return theorems
    wanted = set(names)
    return [t for t in theorems if t.name in wanted]


def _cmd_lean(source: str, *, names: list[str] | None) -> int:
    from meta_compiler.lean import build_theorems, render_file

    registry, _ = _registry_or_errors(source)
    if registry is None:
        return 1
    theorems, problems = build_theorems(registry)
    for name, problem in problems.items():
        print(f"-- {name}: not translatable to Lean: {problem}", file=sys.stderr)
    selected = _select(theorems, names)
    if not selected:
        print("No Properties or Theorems to translate.", file=sys.stderr)
        return 1
    print(render_file(selected)[0], end="")
    return 0


def _cmd_prove(source: str, *, path: Path, names: list[str] | None,
               timeout: int, as_json: bool) -> int:
    import json

    from meta_compiler.lean import (
        ProofResult, build_theorems, find_lean_env, load_proofs, proofs_path,
        record_results, run_lean, save_proofs,
    )

    registry, check = _registry_or_errors(source)
    if registry is None:
        return 1
    theorems, problems = build_theorems(registry)
    selected = _select(theorems, names)
    if names:
        problems = {k: v for k, v in problems.items() if k in set(names)}
    if not selected and not problems:
        print("No Properties or Theorems to prove.")
        return 0

    lean_env = find_lean_env()
    if lean_env is None:
        print(
            "Lean is not available. Enable the plugin's `enable_lean` option "
            "(/plugin → math-paper-creator → configure) and start a new session, "
            "or set MPC_LEAN_PROJECT to a Lake project that requires Mathlib.",
            file=sys.stderr,
        )
        return 3

    results = run_lean(selected, lean_env, timeout=timeout)
    for name, problem in problems.items():
        results[name] = ProofResult("untranslatable", [problem])

    sidecar = proofs_path(path)
    cache = record_results(load_proofs(sidecar), selected, results, lean_env.toolchain)
    save_proofs(sidecar, cache)

    origin = {t.name: t.origin for t in selected}
    if as_json:
        print(json.dumps({
            "toolchain": lean_env.toolchain,
            "sidecar": str(sidecar),
            "results": {n: {**r.to_json(), "origin": origin.get(n)} for n, r in results.items()},
        }, indent=2, ensure_ascii=False))
    else:
        marks = {"proved": "✓", "sorry": "…", "failed": "✗", "error": "!", "untranslatable": "?"}
        for name, r in results.items():
            label = " (hand-written statement)" if origin.get(name) == "theorem" else ""
            print(f"{marks.get(r.status, '?')} {name}: {r.status}{label}")
            for msg in r.messages:
                print("    " + msg.replace("\n", "\n    "))
        print(f"\nResults recorded in {sidecar}")
    return 0 if all(r.status == "proved" for r in results.values()) else 2


if __name__ == "__main__":
    sys.exit(main())
