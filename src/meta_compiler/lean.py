"""Lean 4 verification tier.

Three levels of evidence exist for a claim in a .model.md paper:

  tested      — holds on the fixture data (Python)
  Z3-checked  — follows from the axioms for all real values (SMT)
  Lean-proved — a machine-checked proof in Lean 4 + Mathlib

This module builds the Lean side:

* ``Property(..., lean_proof=...)`` — the Lean *statement* is generated from
  the property's ``z3_expr`` with its ``given`` axioms as hypotheses, so what
  Lean proves is exactly what Z3 checked and the data was tested against.
  Only the proof is written by hand (or by Claude).
* ``Theorem(name, claim=..., lean=...)`` — a hand-written Lean statement and
  proof, for claims Z3 cannot express. Reports label these as hand-written.

A proof counts as proved only if Lean accepts it *and* ``#print axioms``
shows no axioms beyond Lean's standard three. That rules out ``sorry`` and
any ``axiom`` smuggled in through proof text.

Results are cached in a sidecar ``<paper>.proofs.json`` keyed by a hash of
the exact Lean source and toolchain, so editing a claim or its proof makes
the old result stale instead of silently reusing it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meta_compiler.registry import Registry

NAMESPACE = "MPC"
STANDARD_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
HEADER = (
    "import Mathlib\n\n"
    "set_option linter.unusedVariables false\n"
    "set_option linter.style.longLine false\n\n"
    "open Real\n\n"
    f"namespace {NAMESPACE}\n"
)

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*$")
_RESERVED = {
    "at", "by", "do", "else", "end", "from", "fun", "have", "if", "import",
    "in", "let", "match", "namespace", "open", "show", "then", "theorem",
    "lemma", "def", "where", "with", "variable", "section", "Type", "Prop",
    "Sort", "calc", "suffices", "obtain", "instance", "structure", "class",
    "axiom", "example", "abbrev", "deriving", "mutual", "private", "protected",
    "λ", "Π", "Σ",
}


class UntranslatableError(ValueError):
    """A Z3 expression uses something with no faithful Lean counterpart."""


def ident(name: str) -> str:
    """A Lean identifier for ``name``, «quoted» when needed."""
    if _IDENT.match(name) and name not in _RESERVED:
        return name
    if "»" in name or "«" in name:
        raise UntranslatableError(f"name {name!r} cannot be a Lean identifier")
    return f"«{name}»"


# ── Z3 → Lean ───────────────────────────────────────────────────────────────


def _lean_type(sort) -> str:
    import z3

    if sort == z3.RealSort():
        return "ℝ"
    if sort == z3.IntSort():
        return "ℤ"
    if sort == z3.BoolSort():
        return "Prop"
    raise UntranslatableError(f"Z3 sort {sort} has no Lean counterpart here")


def _enclosed(text: str) -> bool:
    """True if ``text`` is one parenthesized group, like ``(a + (b))``."""
    if not (text.startswith("(") and text.endswith(")")):
        return False
    depth = 0
    for i, ch in enumerate(text):
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and i < len(text) - 1:
            return False
    return True


def z3_to_lean(expr, _bound: list[str] | None = None) -> str:
    """Translate a Z3 arithmetic/boolean expression to Lean 4 syntax."""
    import z3

    bound = _bound or []
    tr = lambda e: z3_to_lean(e, bound)  # noqa: E731

    def paren(e) -> str:
        text = tr(e)
        atomic = (_IDENT.match(text) or re.fullmatch(r"«[^»]*»", text)
                  or re.fullmatch(r"\d+", text) or _enclosed(text))
        return text if atomic else f"({text})"

    if z3.is_var(expr):
        return bound[len(bound) - 1 - z3.get_var_index(expr)]
    if z3.is_true(expr):
        return "True"
    if z3.is_false(expr):
        return "False"
    if z3.is_int_value(expr):
        value = expr.as_long()
        return str(value) if value >= 0 else f"({value})"
    if z3.is_rational_value(expr):
        num, den = expr.numerator_as_long(), expr.denominator_as_long()
        if den == 1:
            return str(num) if num >= 0 else f"({num})"
        return f"({num} / {den} : ℝ)"
    if z3.is_algebraic_value(expr):
        raise UntranslatableError(f"algebraic number {expr} (use a rational)")
    if z3.is_quantifier(expr):
        if expr.is_lambda():
            raise UntranslatableError("lambda expressions are not supported")
        names = [ident(expr.var_name(i)) for i in range(expr.num_vars())]
        sorts = [_lean_type(expr.var_sort(i)) for i in range(expr.num_vars())]
        binder = "∀" if expr.is_forall() else "∃"
        body = z3_to_lean(expr.body(), bound + names)
        params = " ".join(f"({n} : {s})" for n, s in zip(names, sorts))
        return f"{binder} {params}, {body}"

    kind = expr.decl().kind()
    args = expr.children()

    if kind == z3.Z3_OP_UNINTERPRETED:
        if args:
            raise UntranslatableError(f"uninterpreted function {expr.decl().name()}")
        _lean_type(expr.sort())  # reject unsupported sorts early
        return ident(expr.decl().name())

    infix = {
        z3.Z3_OP_ADD: "+", z3.Z3_OP_SUB: "-", z3.Z3_OP_MUL: "*",
        z3.Z3_OP_DIV: "/", z3.Z3_OP_IDIV: "/", z3.Z3_OP_MOD: "%",
        z3.Z3_OP_LE: "≤", z3.Z3_OP_LT: "<", z3.Z3_OP_GE: "≥", z3.Z3_OP_GT: ">",
        z3.Z3_OP_EQ: "=", z3.Z3_OP_AND: "∧", z3.Z3_OP_OR: "∨",
        z3.Z3_OP_IMPLIES: "→", z3.Z3_OP_IFF: "↔",
    }
    if kind in infix:
        if kind == z3.Z3_OP_EQ and args[0].sort() == z3.BoolSort():
            return f"{paren(args[0])} ↔ {paren(args[1])}"
        if len(args) == 1:
            return tr(args[0])
        return f" {infix[kind]} ".join(paren(a) for a in args)
    if kind == z3.Z3_OP_UMINUS:
        return f"-{paren(args[0])}"
    if kind == z3.Z3_OP_NOT:
        return f"¬{paren(args[0])}"
    if kind == z3.Z3_OP_DISTINCT:
        pairs = [
            f"{paren(a)} ≠ {paren(b)}"
            for i, a in enumerate(args) for b in args[i + 1:]
        ]
        return " ∧ ".join(pairs)
    if kind == z3.Z3_OP_POWER:
        base, exp = args
        if z3.is_rational_value(exp) or z3.is_int_value(exp):
            value = exp.as_fraction() if z3.is_rational_value(exp) else exp.as_long()
            if value == int(value) and value >= 0:
                return f"{paren(base)} ^ {int(value)}"
        return f"{paren(base)} ^ ({tr(exp)} : ℝ)"  # Real.rpow
    if kind == z3.Z3_OP_TO_REAL:
        return f"(({tr(args[0])} : ℤ) : ℝ)"
    if kind == z3.Z3_OP_ITE:
        return f"if {tr(args[0])} then {tr(args[1])} else {tr(args[2])}"
    raise UntranslatableError(f"Z3 operator {expr.decl().name()!r} is not supported")


def _free_constants(exprs) -> list:
    from z3.z3util import get_vars

    seen: dict[str, object] = {}
    for e in exprs:
        for const in get_vars(e):
            seen.setdefault(const.decl().name(), const)
    return [seen[k] for k in sorted(seen)]


# ── Theorems ────────────────────────────────────────────────────────────────


@dataclass
class LeanTheorem:
    name: str
    origin: str        # "property" (generated statement) or "theorem" (hand-written)
    source: str        # Lean declaration(s), proof included
    statement: str     # the statement only, for display
    has_proof: bool    # False when no proof was supplied (a `sorry` is inserted)
    locked: str = ""   # what an approval pins: everything that fixes the meaning

    def statement_digest(self) -> str:
        text = re.sub(r"\s+", " ", self.locked or self.statement).strip()
        return hashlib.sha256(text.encode()).hexdigest()

    def digest(self, toolchain: str) -> str:
        return hashlib.sha256(f"{toolchain}\n{self.source}".encode()).hexdigest()


def _format_proof(proof: str) -> str:
    text = proof.strip("\n")
    if text.lstrip().startswith("by"):
        return " " + text.strip()
    lines = text.splitlines() or ["sorry"]
    indent = min((len(l) - len(l.lstrip()) for l in lines if l.strip()), default=0)
    body = "\n".join("  " + l[indent:] if l.strip() else "" for l in lines)
    return " by\n" + body


def property_theorem(sym, registry: "Registry") -> LeanTheorem:
    """Generate the Lean theorem for a Property from its Z3 expressions."""
    from meta_compiler.symbols import AxiomSymbol

    hypotheses = []
    exprs = []
    for axiom_name in sym.given:
        ax = registry.symbols.get(axiom_name)
        if not isinstance(ax, AxiomSymbol) or ax.z3_expr is None:
            raise UntranslatableError(f'given axiom "{axiom_name}" has no z3_expr')
        e = ax.z3_expr()
        exprs.append(e)
        hypotheses.append((axiom_name, e))
    goal = sym.z3_expr()
    exprs.append(goal)

    binders: dict[str, list[str]] = {}
    for const in _free_constants(exprs):
        binders.setdefault(_lean_type(const.sort()), []).append(ident(const.decl().name()))
    params = [f"({' '.join(names)} : {typ})" for typ, names in binders.items()]
    params += [f"({ident(n)} : {z3_to_lean(e)})" for n, e in hypotheses]

    signature = f"theorem {ident(sym.name)}"
    if params:
        signature += "\n    " + "\n    ".join(params)
    statement = f"{signature} :\n    {z3_to_lean(goal)} :="
    proof = sym.lean_proof if sym.lean_proof and sym.lean_proof.strip() else "sorry"
    return LeanTheorem(
        name=sym.name, origin="property",
        source=statement + _format_proof(proof),
        statement=statement[:-3].rstrip(),
        has_proof=bool(sym.lean_proof and sym.lean_proof.strip()),
        locked=statement[:-3].rstrip(),
    )


_DECL = r"(?:theorem|lemma)\s+(?:«{name}»|{name})(?=[\s:(\[{{])"


def validate_theorem_source(name: str, lean: str) -> None:
    """Static checks on a Theorem's Lean source (raises ValueError)."""
    if not re.search(_DECL.format(name=re.escape(name)), lean):
        raise ValueError(
            f'Theorem "{name}": its lean= source must declare `theorem {name}`'
        )
    if re.search(r"^\s*import\s", lean, re.M):
        raise ValueError(
            f'Theorem "{name}": remove `import` lines — Mathlib is already imported'
        )
    if re.search(r"^\s*(namespace|end|section)\b", lean, re.M):
        raise ValueError(f'Theorem "{name}": namespace/section commands are not allowed')


def theorem_theorem(sym) -> LeanTheorem:
    source = sym.lean.strip("\n")
    m = re.search(_DECL.format(name=re.escape(sym.name)), source)
    stmt_start = m.start() if m else 0
    stmt = source[stmt_start:]
    cut = stmt.find(":=")
    statement = stmt[:cut].rstrip() if cut >= 0 else stmt
    # Helper definitions/lemmas before the theorem can change what its
    # statement means, so an approval pins them too; only the main proof
    # (after its `:=`) may change freely.
    locked = source[: stmt_start + cut].rstrip() if cut >= 0 else source
    return LeanTheorem(
        name=sym.name, origin="theorem", source=source, statement=statement,
        has_proof=not re.search(r"\bsorry\b", source), locked=locked,
    )


def build_theorems(registry: "Registry", *, all_properties: bool = True):
    """Lean theorems for the registry's Properties and Theorems.

    Returns (theorems, problems). Properties whose Z3 expressions can't be
    translated are reported in ``problems`` rather than raising.
    """
    from meta_compiler.symbols import PropertySymbol, TheoremSymbol

    theorems: list[LeanTheorem] = []
    problems: dict[str, str] = {}
    for name in registry._registration_order:
        sym = registry.symbols[name]
        if isinstance(sym, PropertySymbol):
            if not all_properties and not sym.lean_proof:
                continue
            try:
                theorems.append(property_theorem(sym, registry))
            except UntranslatableError as e:
                problems[name] = str(e)
            except Exception as e:  # z3 missing, broken lambda, ...
                problems[name] = f"could not build the Lean statement: {e}"
        elif isinstance(sym, TheoremSymbol):
            theorems.append(theorem_theorem(sym))
    return theorems, problems


def render_file(theorems: list[LeanTheorem]) -> tuple[str, dict[str, tuple[int, int]]]:
    """The Lean file for ``theorems`` and each theorem's (first, last) line."""
    lines = HEADER.splitlines()
    spans: dict[str, tuple[int, int]] = {}
    for th in theorems:
        lines.append("")
        start = len(lines) + 1
        lines.extend(th.source.splitlines())
        spans[th.name] = (start, len(lines))
    lines.append("")
    lines.append(f"end {NAMESPACE}")
    lines.append("")
    for th in theorems:
        lines.append(f"#print axioms {NAMESPACE}.{ident(th.name)}")
    return "\n".join(lines) + "\n", spans


# ── Running Lean ────────────────────────────────────────────────────────────


@dataclass
class LeanEnv:
    project: Path
    lake: str
    env: dict[str, str]
    toolchain: str


def find_lean_env() -> LeanEnv | None:
    """Locate a Lean project with Mathlib and the `lake` that drives it.

    Looks at $MPC_LEAN_PROJECT, then ${CLAUDE_PLUGIN_DATA}/lean/project (the
    plugin's managed install, ready once `.ready` exists).
    """
    project = None
    explicit = os.environ.get("MPC_LEAN_PROJECT")
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    elan_home = os.environ.get("ELAN_HOME")
    if explicit:
        project = Path(explicit)
    elif data and (Path(data) / "lean" / ".ready").exists():
        project = Path(data) / "lean" / "project"
        private = Path(data) / "lean" / "elan"
        if not elan_home and (private / "bin" / "lake").exists():
            elan_home = str(private)
    if project is None or not (project / "lean-toolchain").exists():
        return None

    candidates = []
    if elan_home:
        candidates.append(Path(elan_home) / "bin" / "lake")
    candidates.append(Path.home() / ".elan" / "bin" / "lake")
    lake = next((str(c) for c in candidates if c.exists()), None) or shutil.which("lake")
    if lake is None:
        return None

    env = dict(os.environ)
    if elan_home:
        env["ELAN_HOME"] = elan_home
    elif lake.startswith(str(Path.home() / ".elan")):
        env["ELAN_HOME"] = str(Path.home() / ".elan")
    env["PATH"] = str(Path(lake).parent) + os.pathsep + env.get("PATH", "")
    toolchain = (project / "lean-toolchain").read_text().strip()
    return LeanEnv(project=project, lake=lake, env=env, toolchain=toolchain)


def workspace_file(lean_env: LeanEnv, model_path: Path) -> Path:
    """A scratch .lean file inside the Lean project, one per paper.

    The Lean MCP tools (lean_goal, lean_diagnostic_messages, ...) work on
    files inside the project. `mpc prove` remains the authority; this file is
    only for interactive proof search.
    """
    name = model_path.name
    stem = name[: -len(".model.md")] if name.endswith(".model.md") else model_path.stem
    stem = re.sub(r"[^A-Za-z0-9_]", "_", stem) or "Paper"
    digest = hashlib.sha256(str(model_path.resolve()).encode()).hexdigest()[:8]
    folder = lean_env.project / "MPCWorkspace"
    folder.mkdir(exist_ok=True)
    return folder / f"{stem}_{digest}.lean"


@dataclass
class ProofResult:
    status: str  # proved | sorry | failed | error | untranslatable
    messages: list[str] = field(default_factory=list)
    axioms: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"status": self.status, "messages": self.messages, "axioms": self.axioms}


_AXIOMS = re.compile(r"'(?P<name>[^']+)' (?:depends on axioms: \[(?P<axioms>[^\]]*)\]|does not depend on any axioms)")


def run_lean(theorems: list[LeanTheorem], lean_env: LeanEnv, *,
             timeout: int = 600) -> dict[str, ProofResult]:
    """Check ``theorems`` with Lean; one result per theorem name."""
    if not theorems:
        return {}
    text, spans = render_file(theorems)
    with tempfile.TemporaryDirectory(prefix="mpc-lean-") as tmp:
        path = Path(tmp) / "Proofs.lean"
        path.write_text(text)
        try:
            proc = subprocess.run(
                [lean_env.lake, "env", "lean", "--json", str(path)],
                cwd=lean_env.project, env=lean_env.env,
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {t.name: ProofResult("error", [f"Lean timed out after {timeout}s"]) for t in theorems}

    messages = []
    for line in proc.stdout.splitlines():
        try:
            messages.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if proc.returncode != 0 and not messages:
        err = (proc.stderr or proc.stdout).strip()[:2000]
        return {t.name: ProofResult("error", [err or "Lean failed to run"]) for t in theorems}

    results = {t.name: ProofResult("proved") for t in theorems}
    by_qualified = {f"{NAMESPACE}.{t.name}": t.name for t in theorems}
    seen_axioms: set[str] = set()
    stray: list[str] = []

    for msg in messages:
        line = msg.get("pos", {}).get("line", 0)
        data = msg.get("data", "")
        severity = msg.get("severity")
        m = _AXIOMS.search(data) if severity == "information" else None
        if m and m.group("name") in by_qualified:
            name = by_qualified[m.group("name")]
            axioms = [a.strip() for a in (m.group("axioms") or "").split(",") if a.strip()]
            results[name].axioms = axioms
            seen_axioms.add(name)
            continue
        owner = next((n for n, (a, b) in spans.items() if a <= line <= b), None)
        if severity == "error":
            if owner:
                results[owner].status = "failed"
                results[owner].messages.append(f"line {line - spans[owner][0] + 1}: {data}")
            else:
                stray.append(data)

    for name, result in results.items():
        if result.status == "failed":
            continue
        if name not in seen_axioms:
            result.status = "failed"
            result.messages.append("Lean did not accept the declaration")
        elif "sorryAx" in result.axioms:
            result.status = "sorry"
        else:
            extra = sorted(set(result.axioms) - STANDARD_AXIOMS)
            if extra:
                result.status = "failed"
                result.messages.append(f"depends on non-standard axioms: {', '.join(extra)}")
    if stray:
        for result in results.values():
            if result.status == "proved":
                continue
            result.messages.extend(stray[:3])
    return results


# ── Sidecar cache ───────────────────────────────────────────────────────────


def proofs_path(model_path: Path) -> Path:
    name = model_path.name
    stem = name[: -len(".model.md")] if name.endswith(".model.md") else model_path.stem
    return model_path.with_name(f"{stem}.proofs.json")


def load_proofs(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_proofs(path: Path, cache: dict) -> None:
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n")


def record_results(cache: dict, theorems: list[LeanTheorem], results: dict[str, ProofResult],
                   toolchain: str) -> dict:
    cache = dict(cache)
    cache["toolchain"] = toolchain
    entries = dict(cache.get("results", {}))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for th in theorems:
        if th.name in results:
            entries[th.name] = {
                **results[th.name].to_json(),
                "origin": th.origin,
                "hash": th.digest(toolchain),
                "checked_at": now,
            }
    cache["results"] = entries
    return cache


def verification_levels(registry: "Registry", passed: bool, cache: dict | None) -> list[dict]:
    """Per-claim evidence level, for reports.

    Each entry: name, kind, claim, level, detail.
    """
    from meta_compiler.symbols import AxiomSymbol, PropertySymbol, TheoremSymbol
    from meta_compiler.verification import z3_available

    cache = cache or {}
    toolchain = cache.get("toolchain", "")
    entries = cache.get("results", {})
    theorems, problems = build_theorems(registry)
    by_name = {t.name: t for t in theorems}
    approvals = approval_status(theorems, cache)
    out = []

    def lean_level(name: str) -> tuple[str | None, str]:
        th = by_name.get(name)
        if th is None:
            return None, problems.get(name, "")
        entry = entries.get(name)
        if entry is None:
            return None, "not yet checked with Lean" if th.has_proof else "no Lean proof"
        if entry.get("hash") != th.digest(toolchain):
            return None, "Lean result is stale (claim or proof changed since `mpc prove`)"
        status = entry.get("status")
        if status == "proved":
            return "Lean-proved", ""
        return None, f"Lean: {status}"

    for name in registry._registration_order:
        sym = registry.symbols[name]
        if isinstance(sym, AxiomSymbol):
            out.append({"name": name, "kind": "Axiom", "claim": sym.statement,
                        "level": "assumed", "detail": "checked against fixture data"
                        if sym.z3_expr is not None and z3_available() else ""})
        elif isinstance(sym, PropertySymbol):
            level, detail = lean_level(name)
            if level is None:
                level = "Z3-checked" if passed and z3_available() else "stated"
            out.append({"name": name, "kind": "Property", "claim": sym.claim,
                        "level": level, "detail": detail})
        elif isinstance(sym, TheoremSymbol):
            level, detail = lean_level(name)
            note = {
                "approved": "hand-written statement, approved by the author",
                "changed": "hand-written statement CHANGED since the author approved it",
            }.get(approvals.get(name), "hand-written statement, NOT yet approved by the author")
            detail = "; ".join(x for x in (detail, note) if x)
            out.append({"name": name, "kind": "Theorem", "claim": sym.claim,
                        "level": level or "stated", "detail": detail})
    return out


# ── Statement approvals ─────────────────────────────────────────────────────
#
# The author approves that a claim's Lean statement says what the paper
# means. Approvals live in the sidecar under "approved" and pin a digest of
# the statement (see LeanTheorem.locked). The plugin's PreToolUse guard
# refuses edits that would change an approved statement, and `check` reports
# any that changed anyway.


def approval_status(theorems: list[LeanTheorem], cache: dict | None) -> dict[str, str]:
    """name -> approved | changed | unapproved | removed."""
    approved = (cache or {}).get("approved", {})
    status = {}
    names = set()
    for th in theorems:
        names.add(th.name)
        entry = approved.get(th.name)
        if entry is None:
            status[th.name] = "unapproved"
        elif entry.get("digest") == th.statement_digest():
            status[th.name] = "approved"
        else:
            status[th.name] = "changed"
    for name in approved:
        if name not in names:
            status[name] = "removed"
    return status


def approval_problems(theorems: list[LeanTheorem], cache: dict | None) -> list[str]:
    """Errors for approved statements that no longer match the document."""
    approved = (cache or {}).get("approved", {})
    problems = []
    for name, state in approval_status(theorems, cache).items():
        if state == "changed":
            problems.append(
                f'Statement of "{name}" changed since the author approved it. '
                f"Approved:\n{approved[name].get('statement', '')}\n"
                "Restore it, or have the author revoke the approval first "
                "(mpc approve --revoke)."
            )
        elif state == "removed":
            problems.append(
                f'"{name}" was removed, but the author had approved its statement. '
                "Restore it, or have the author revoke the approval (mpc approve --revoke)."
            )
    return problems


def record_approvals(cache: dict, theorems: list[LeanTheorem], names: list[str],
                     *, revoke: bool = False) -> dict:
    cache = dict(cache)
    approved = dict(cache.get("approved", {}))
    by_name = {t.name: t for t in theorems}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for name in names:
        if revoke:
            approved.pop(name, None)
            continue
        th = by_name[name]
        approved[name] = {
            "digest": th.statement_digest(),
            "statement": th.statement,
            "origin": th.origin,
            "approved_at": now,
        }
    cache["approved"] = approved
    return cache
