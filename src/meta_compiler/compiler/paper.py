"""Generate clean paper artifact by stripping validation blocks."""

from __future__ import annotations

from meta_compiler.compiler.parser import Block, MathBlock, ProseBlock, ResultsBlock, ValidationBlock, FixtureBlock


def generate_paper(
    blocks: list[Block],
    *,
    depth: str | None = None,
    verification: list[dict] | None = None,
) -> str:
    """Generate a clean paper from parsed blocks.

    Args:
        blocks: Parsed document blocks.
        depth: Optional depth filter ('executive', 'technical', 'appendix').
               If None, include all content.
        verification: Per-claim evidence entries (from
            ``meta_compiler.lean.verification_levels``). When given, each
            validation block that declared claims is replaced by a short
            note of their evidence, and a summary section is appended.
            Executive-depth papers get the summary only.

    Returns:
        Markdown string with validation blocks stripped.
    """
    parts: list[str] = []

    if depth is not None:
        blocks = _filter_by_depth(blocks, depth)

    by_line: dict[int, list[dict]] = {}
    for entry in verification or []:
        if entry.get("line") is not None:
            by_line.setdefault(entry["line"], []).append(entry)
    inline = bool(by_line) and depth != "executive"

    for block in blocks:
        if isinstance(block, ProseBlock):
            parts.append(block.content)
        elif isinstance(block, MathBlock):
            parts.append(block.raw)
            parts.append("")
        elif isinstance(block, ResultsBlock) and block.output:
            parts.append(block.output.rstrip())
        elif isinstance(block, ValidationBlock) and inline and block.line_number in by_line:
            parts.append(_inline_note(by_line[block.line_number]))
            parts.append("")
        # Other ValidationBlocks and FixtureBlocks are silently skipped

    text = "\n".join(parts).strip() + "\n"
    if verification:
        text += "\n" + _summary(verification)
    return text


# ── Verification notes ──────────────────────────────────────────────────────

_LEGEND = (
    "*Assumption*: stated without proof; checked to be consistent with the example data. "
    "*Verified (Z3)*: follows from its assumptions for every value they allow, checked by "
    "the Z3 SMT solver. *Proved (Lean)*: a machine-checked proof in Lean 4 with Mathlib "
    "that relies only on Lean's standard axioms. *Not verified*: stated, but no check has "
    "succeeded yet. A hand-written Lean statement is marked with whether the author "
    "approved it as a faithful rendering of the claim."
)


def _evidence(entry: dict) -> str:
    level, kind, detail = entry["level"], entry["kind"], entry.get("detail", "")
    if kind == "Axiom":
        text = "Assumption"
        if "fixture data" in detail:
            text += "; consistent with the example data"
        return text
    text = {
        "Lean-proved": "Proved (Lean)",
        "Z3-checked": "Verified (Z3)",
    }.get(level, "Not verified")
    if kind == "Theorem":
        text += {
            "approved": "; statement approved by the author",
            "changed": "; statement changed since the author approved it",
        }.get(entry.get("approval"), "; statement not yet approved by the author")
    return text


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _inline_note(entries: list[dict]) -> str:
    lines = ["> **Verification**"]
    for e in entries:
        lines.append(f"> - **{e['name']}** {e['claim']} — {_evidence(e)}")
    return "\n".join(lines)


def _summary(entries: list[dict]) -> str:
    lines = [
        "## Verification",
        "",
        "| Claim | Statement | Evidence |",
        "|---|---|---|",
    ]
    for e in entries:
        lines.append(f"| {e['name']} | {_cell(e['claim'])} | {_evidence(e)} |")
    lines += ["", _LEGEND, ""]
    return "\n".join(lines)


def _filter_by_depth(blocks: list[Block], target_depth: str) -> list[Block]:
    """Filter blocks to only include content at or above the target depth.

    Depth markers are <!-- depth:executive -->, <!-- depth:technical -->,
    <!-- depth:appendix --> found within prose blocks.

    Depth hierarchy: executive < technical < appendix.
    A target of 'technical' includes executive and technical but not appendix.
    """
    depth_order = {"executive": 0, "technical": 1, "appendix": 2}
    target_level = depth_order.get(target_depth, 1)

    # First, split prose blocks at depth markers so each segment can be
    # filtered independently.
    expanded: list[Block] = []
    for block in blocks:
        if isinstance(block, ProseBlock):
            expanded.extend(_split_prose_at_depth_markers(block, depth_order))
        else:
            expanded.append(block)

    result: list[Block] = []
    current_level = 0  # Start with executive (always included)
    include = True

    for block in expanded:
        if isinstance(block, ProseBlock):
            # Check if the first non-empty line is a depth marker
            for line in block.content.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("<!-- depth:") and stripped.endswith("-->"):
                    marker = stripped[len("<!-- depth:"):-len("-->")].strip()
                    if marker in depth_order:
                        current_level = depth_order[marker]
                        include = current_level <= target_level
                break  # Only examine the leading marker line

        if include:
            result.append(block)

    return result


def _split_prose_at_depth_markers(
    block: ProseBlock,
    depth_order: dict[str, int],
) -> list[ProseBlock]:
    """Split a ProseBlock into sub-blocks at each depth marker boundary."""
    lines = block.content.split("\n")
    segments: list[ProseBlock] = []
    current: list[str] = []

    for line in lines:
        stripped = line.strip()
        if (
            stripped.startswith("<!-- depth:")
            and stripped.endswith("-->")
            and stripped[len("<!-- depth:"):-len("-->")].strip() in depth_order
        ):
            # Flush accumulated lines as a segment (even if empty — the marker
            # itself will start the new segment)
            if current:
                text = "\n".join(current)
                if text.strip():
                    segments.append(ProseBlock(content=text + "\n"))
                current = []
            # Start new segment with the marker line
            current.append(line)
        else:
            current.append(line)

    if current:
        text = "\n".join(current)
        if text.strip():
            segments.append(ProseBlock(content=text + "\n"))

    return segments
