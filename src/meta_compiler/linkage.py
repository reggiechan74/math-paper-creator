"""LaTeX ↔ symbol linkage checks.

The validation blocks prove things about Python symbols; the paper's
``$$...$$`` blocks are what readers see. This module ties the two together
through the optional ``latex=`` argument on Set, Parameter, Variable and
Expression, and warns when they drift apart:

* an identifier appears in the paper's math but no symbol declares it,
* a symbol declares a LaTeX form that never appears in the math,
* some symbols declare ``latex=`` and others don't.

The checks are opt-in: they run only once at least one symbol declares
``latex=``, so older documents are unaffected. They produce warnings only.

The identifier scanner is deliberately conservative. It looks at the top
level of each formula (not inside subscripts or superscripts, which mostly
hold bound indices and exponents) and treats Greek-letter macros, single
Latin letters and decorated forms (``\\bar{x}``, ``\\mathbf{x}``,
``\\mathrm{cap}``) as identifiers. Indexed symbols should declare their base
(``latex="x"`` for x_{ij}); scalars may declare a decorated form such as
``latex=r"c_{\\max}"``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from meta_compiler.compiler.parser import Block, MathBlock, ProseBlock
from meta_compiler.symbols import (
    ExpressionSymbol,
    ParameterSymbol,
    SetSymbol,
    VariableSymbol,
)

if TYPE_CHECKING:
    from meta_compiler.registry import Registry

LINKABLE = (SetSymbol, ParameterSymbol, VariableSymbol, ExpressionSymbol)

GREEK = {
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta",
    "theta", "vartheta", "iota", "kappa", "lambda", "mu", "nu", "xi", "pi",
    "varpi", "rho", "varrho", "sigma", "varsigma", "tau", "upsilon", "phi",
    "varphi", "chi", "psi", "omega", "Gamma", "Delta", "Theta", "Lambda", "Xi",
    "Pi", "Sigma", "Upsilon", "Phi", "Psi", "Omega",
}
# Wrappers whose argument is part of the identifier: \bar{x} is not x.
DECORATORS = {
    "bar", "hat", "tilde", "dot", "ddot", "vec", "overline", "widehat",
    "widetilde", "mathbf", "boldsymbol", "bm", "mathcal", "mathscr",
    "mathfrak", "mathsf", "mathit",
}
# Wrappers that may name a multi-letter identifier (\mathrm{cap}). Their
# content is only treated as an identifier when declared or subscripted,
# because \mathrm{d} and \operatorname{argmax} are usually notation.
WORD_WRAPPERS = {"mathrm", "operatorname"}
# Wrappers whose argument is never an identifier.
SKIP_ARG = {
    "text", "textrm", "textbf", "textit", "mbox", "mathbb", "label", "tag",
    "begin", "end", "hspace", "vspace", "operatorname*",
}
BINDERS = {"forall", "exists"}

_TOKEN = re.compile(r"\\[A-Za-z]+\*?|\\.|[A-Za-z]|[{}_^]|\s+|.", re.S)


def normalize(tex: str) -> str:
    """Canonical form for comparing LaTeX snippets."""
    tex = re.sub(r"\\(left|right|big|Big|bigg|Bigg)(?![A-Za-z])", "", tex)
    # Drop whitespace, except where it separates a macro from a letter
    # (\rho t must not become \rhot).
    tex = re.sub(r"(\\[A-Za-z]+)\s+(?=[A-Za-z])", "\\1\x00", tex)
    tex = re.sub(r"\s+", "", tex).replace("\x00", " ")
    # x_{i} == x_i for single-token scripts
    tex = re.sub(r"([_^])\{(\\[A-Za-z]+|[A-Za-z0-9*'])\}", r"\1\2", tex)
    return tex


@dataclass
class _Occurrence:
    base: str          # e.g. "x", "\\beta", "\\bar{x}", "\\mathrm{cap}"
    sub: str | None    # raw subscript text
    sup: str | None    # raw superscript text
    word: bool = False # came from \mathrm / \operatorname

    def candidates(self) -> set[str]:
        out = {normalize(self.base)}
        if self.sub is not None:
            out.add(normalize(f"{self.base}_{{{self.sub}}}"))
        if self.sup is not None:
            out.add(normalize(f"{self.base}^{{{self.sup}}}"))
            if self.sub is not None:
                out.add(normalize(f"{self.base}_{{{self.sub}}}^{{{self.sup}}}"))
        return out


def _read_group(tokens: list[str], i: int) -> tuple[str, int]:
    """Read one argument (a {...} group or a single token) starting at i."""
    while i < len(tokens) and tokens[i].isspace():
        i += 1
    if i >= len(tokens):
        return "", i
    if tokens[i] != "{":
        return tokens[i], i + 1
    depth, j, out = 1, i + 1, []
    while j < len(tokens) and depth:
        tok = tokens[j]
        if tok == "{":
            depth += 1
        elif tok == "}":
            depth -= 1
            if depth == 0:
                break
        out.append(tok)
        j += 1
    return "".join(out), j + 1


def _read_scripts(tokens: list[str], i: int) -> tuple[str | None, str | None, int]:
    sub = sup = None
    while i < len(tokens) and tokens[i] in ("_", "^"):
        kind = tokens[i]
        arg, i = _read_group(tokens, i + 1)
        if kind == "_":
            sub = arg
        else:
            sup = arg
    return sub, sup, i


def extract_identifiers(tex: str, nested: list[_Occurrence] | None = None) -> list[_Occurrence]:
    """Top-level identifier occurrences in a LaTeX formula.

    If ``nested`` is given, identifiers found inside subscripts and
    superscripts (``\\sum_{t \\in T}``, ``x_{i}``) are appended to it. They
    count as appearances of declared symbols but are never reported as
    undeclared, since scripts mostly hold bound indices.
    """
    tokens = _TOKEN.findall(tex)
    found: list[_Occurrence] = []

    def scan(script: str | None) -> None:
        if nested is not None and script:
            nested.extend(extract_identifiers(script, nested))

    i = 0
    after_binder = False
    while i < len(tokens):
        tok = tokens[i]
        if tok.isspace():
            i += 1
            continue

        if tok in ("_", "^"):
            # Script on a non-identifier (\sum_{i}, )^2): skip its argument.
            arg, i = _read_group(tokens, i + 1)
            scan(arg)
            continue

        if tok.startswith("\\") and len(tok) > 1 and tok[1].isalpha():
            name = tok[1:]
            if name in BINDERS:
                after_binder = True
                i += 1
                continue
            if name in SKIP_ARG:
                _, i = _read_group(tokens, i + 1)
                continue
            if name in DECORATORS or name in WORD_WRAPPERS:
                arg, j = _read_group(tokens, i + 1)
                sub, sup, j = _read_scripts(tokens, j)
                base = f"\\{name}{{{arg}}}"
                found.append(_Occurrence(base, sub, sup, word=name in WORD_WRAPPERS))
                scan(sub)
                scan(sup)
                i = j
                # \mathrm{d}t: the integration variable is bound
                after_binder = name in WORD_WRAPPERS and arg.strip() == "d"
                continue
            if name in GREEK:
                sub, sup, j = _read_scripts(tokens, i + 1)
                found.append(_Occurrence(tok, sub, sup))
                scan(sub)
                scan(sup)
                i = j
                after_binder = False
                continue
            i += 1  # \sum, \le, \frac, \in, ... — structure, not identifiers
            if name not in {"quad", "qquad", "colon"}:
                after_binder = False
            continue

        if len(tok) == 1 and tok.isalpha():
            sub, sup, j = _read_scripts(tokens, i + 1)
            euler = tok == "e" and sup is not None and sub is None
            if not after_binder and not euler:
                found.append(_Occurrence(tok, sub, sup))
            scan(sub)
            scan(sup)
            i = j
            continue

        if tok in ",":
            i += 1  # keep binder mode across "\forall i, j"
            continue
        after_binder = False
        i += 1
    return found


def _sections(blocks: list[Block]):
    """Yield (section heading, MathBlock) pairs in document order."""
    heading = ""
    for block in blocks:
        if isinstance(block, ProseBlock):
            for line in block.content.splitlines():
                if line.strip().startswith("#"):
                    heading = line.strip().lstrip("#").strip()
        elif isinstance(block, MathBlock):
            yield heading, block


def check_latex_linkage(blocks: list[Block], registry: "Registry") -> list[str]:
    """Warnings about LaTeX identifiers and symbols that don't line up."""
    linkable = {
        name: sym for name, sym in registry.symbols.items()
        if isinstance(sym, LINKABLE)
    }
    declared = {name: sym.latex for name, sym in linkable.items() if sym.latex}
    if not declared:
        return []

    declared_norm = {normalize(tex): name for name, tex in declared.items()}
    seen: set[str] = set()
    undeclared: dict[str, list[str]] = {}

    for heading, math in _sections(blocks):
        nested: list[_Occurrence] = []
        top = extract_identifiers(math.content, nested)
        for occ in nested:
            seen.update(declared_norm[m] for m in occ.candidates() & declared_norm.keys())
        for occ in top:
            matches = occ.candidates() & declared_norm.keys()
            if matches:
                seen.update(declared_norm[m] for m in matches)
                continue
            if occ.word and occ.sub is None:
                continue  # \mathrm{d}, \operatorname{argmax}: notation
            label = sorted(occ.candidates(), key=len)[0]
            bucket = undeclared.setdefault(heading or "(top)", [])
            if label not in bucket:
                bucket.append(label)

    warnings: list[str] = []
    for heading, idents in undeclared.items():
        warnings.append(
            f'LaTeX in section "{heading}" uses {", ".join(idents)} '
            f"but no symbol declares it with latex= — register it, or add "
            f"latex= to the symbol it denotes"
        )
    for name, tex in declared.items():
        if name not in seen:
            warnings.append(
                f'Symbol "{name}" declares latex={tex!r} but it never appears '
                f"in the paper's display math"
            )
    missing = sorted(name for name in linkable if name not in declared)
    if missing:
        warnings.append(
            f"{len(missing)} symbol(s) have no latex= declaration, so their link "
            f"to the paper's math is unchecked: {', '.join(missing)}"
        )
    return warnings
