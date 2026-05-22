"""Structured report: CO alignment, Bloom, duplicates, and syllabus alignment.

Output is markdown (GFM tables). User text is wrapped in inline code so characters
like `[CO2]` do not break the markdown parser in the browser.
"""

from __future__ import annotations

from app.review_engine import ParsedQuestion, parse_co_list, parse_questions, parse_units, run_checks


def _cell(text: str, max_len: int = 100) -> str:
    s = " ".join(str(text).split())
    s = s.replace("|", "/")
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def _md_cell(text: str, max_len: int = 100) -> str:
    """Safe inside GFM tables — avoids `[CO2]` being parsed as a link."""
    s = _cell(text, max_len)
    s = s.replace("\\", "\\\\").replace("`", "′")
    return "`" + s + "`"


def _co_status(alignment: str) -> str:
    return "MATCH" if alignment == "ALIGNED" else "MISMATCH"


def _bloom_status(alignment: str, bloom_enabled: bool) -> str:
    if not bloom_enabled or alignment == "SKIPPED":
        return "—"
    return "MATCH" if alignment == "ALIGNED" else "MISMATCH"


def _syllabus_status(row: dict) -> str:
    unit = str(row.get("unit") or "").strip()
    st = str(row.get("status", ""))
    if unit in {"", "—"} or "Unclear" in st or "not matched" in st.lower():
        return "MISMATCH"
    return "MATCH"


def build_three_step_review_markdown(
    *,
    extracted_texts: list[tuple[str, str]],
    cos_text: str,
    syllabus_units: str,
    bloom_in_paper: bool,
    co_required: bool,
) -> str:
    cos_map = parse_co_list(cos_text)
    units = parse_units(syllabus_units)
    sets_data: list[tuple[str, str, list[ParsedQuestion]]] = [
        (label, raw, parse_questions(raw)) for label, raw in extracted_texts
    ]

    result = run_checks(
        sets=sets_data,
        units=units,
        cos_map=cos_map,
        co_required=co_required,
        bloom_in_paper=bloom_in_paper,
    )

    lines: list[str] = []

    # ── Step 1 ───────────────────────────────────────────────────────────
    lines.append("## Step 1 - Course outcomes (CO) alignment\n\n")
    if not cos_map:
        lines.append(
            "*No course outcomes were provided. Paste CO lines (e.g. `CO1: …`) to run this step.*\n\n"
        )
    else:
        lines.append(
            "| Question ref | Question (excerpt) | Current CO | Expected CO | Status |\n"
            "|---|---|---|---|---|\n"
        )
        for row in result.get("co_per_question") or []:
            lines.append(
                "| "
                + _md_cell(row.get("q", ""), 32)
                + " | "
                + _md_cell(row.get("topic", ""), 240)
                + " | "
                + _cell(str(row.get("tagged_co", "—")), 12)
                + " | "
                + _cell(str(row.get("heuristic_co", "—")), 12)
                + " | "
                + _co_status(str(row.get("alignment", "")))
                + " |\n"
            )
        lines.append("\n")

    # ── Step 2 ───────────────────────────────────────────────────────────
    lines.append("## Step 2 - Bloom's taxonomy level\n\n")
    if not bloom_in_paper:
        lines.append(
            "*Bloom check was turned off (checkbox). Turn on “Paper tags Bloom's / KL / BTL” to run this step.*\n\n"
        )
    else:
        lines.append(
            "| Question ref | Question (excerpt) | Current level | Expected level | Status |\n"
            "|---|---|---|---|---|\n"
        )
        for row in result.get("bloom_per_question") or []:
            if str(row.get("alignment")) == "SKIPPED":
                continue
            lines.append(
                "| "
                + _md_cell(row.get("q", ""), 32)
                + " | "
                + _md_cell(row.get("summary", ""), 240)
                + " | "
                + _cell(str(row.get("tagged", "—")), 10)
                + " | "
                + _cell(str(row.get("verb_based", "—")), 14)
                + " | "
                + _bloom_status(str(row.get("alignment", "")), True)
                + " |\n"
            )
        lines.append("\n")

    # ── Step 3 ───────────────────────────────────────────────────────────
    lines.append("## Step 3 - Repeated questions\n\n")
    within = result.get("within_set_duplicates") or []
    across = result.get("repetition") or []

    if not within and not across:
        lines.append(
            "*No repeated questions detected (>=78% text similarity within or across sets).*\n"
        )
    else:
        if within:
            lines.append("### Within the same set\n\n")
            lines.append("| Set | Question A | Question B | Similarity |\n|---|---|---|---|\n")
            for d in within:
                lines.append(
                    "| "
                    + _md_cell(d.get("set", ""), 20)
                    + " | "
                    + _md_cell(d.get("snippet_a", ""), 220)
                    + " | "
                    + _md_cell(d.get("snippet_b", ""), 220)
                    + " | "
                    + _cell(str(d.get("similarity", "")), 8)
                    + " |\n"
                )
            lines.append("\n")
        if across:
            lines.append("### Across different sets\n\n")
            lines.append(
                "| Question A | Question B | Sample (truncated) | Similarity | Type |\n"
                "|---|---|---|---|---|\n"
            )
            for d in across:
                lines.append(
                    "| "
                    + _md_cell(d.get("qa", ""), 40)
                    + " | "
                    + _md_cell(d.get("qb", ""), 40)
                    + " | "
                    + _md_cell(d.get("topic", ""), 200)
                    + " | "
                    + _cell(str(d.get("similarity", "")), 8)
                    + " | "
                    + _cell(str(d.get("type", "")), 20)
                    + " |\n"
                )

    # ── Step 4 - Syllabus alignment ─────────────────────────────────────
    lines.append("\n## Step 4 - Syllabus alignment\n\n")
    if not units:
        lines.append(
            "*No syllabus lines were provided. Paste your syllabus (one unit or topic per line) "
            "in section 5 of the form to run this step.*\n"
        )
    else:
        lines.append(
            "| Question ref | Question (excerpt) | Best-matching syllabus line | Status |\n"
            "|---|---|---|---|\n"
        )
        for row in result.get("syllabus_rows") or []:
            lines.append(
                "| "
                + _md_cell(row.get("q", ""), 32)
                + " | "
                + _md_cell(row.get("topic", ""), 240)
                + " | "
                + _md_cell(str(row.get("unit", "—")), 200)
                + " | "
                + _syllabus_status(row)
                + " |\n"
            )
        under = result.get("under_units") or []
        if under:
            plain = "; ".join(_cell(u, 160) for u in under)
            lines.append(
                f"\n*Syllabus lines with no question matched to them (by keyword overlap):* {plain}\n"
            )

    return "".join(lines).strip() + "\n"
