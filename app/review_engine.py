"""Heuristic parsing and academic QA checks for question papers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

# Primary verb -> Bloom level (L1–L6) per reviewer specification
VERB_TO_LEVEL: dict[str, int] = {}
for _verbs, _lvl in [
    (
        "define list state recall name identify what is",
        1,
    ),
    (
        "explain describe summarize compare classify",
        2,
    ),
    (
        "demonstrate use solve implement show calculate apply",
        3,
    ),
    (
        "analyze differentiate examine break down contrast",
        4,
    ),
    (
        "evaluate justify critique assess judge defend",
        5,
    ),
    (
        "design build construct create develop formulate",
        6,
    ),
]:
    for v in _verbs.split():
        VERB_TO_LEVEL[v.lower()] = _lvl


def level_label(n: int) -> str:
    labels = {1: "L1 Remember", 2: "L2 Understand", 3: "L3 Apply", 4: "L4 Analyze", 5: "L5 Evaluate", 6: "L6 Create"}
    return labels.get(n, f"L{n}")


def _bloom_mismatch_severity(verb: str | None, tagged: int, inferred: int) -> str:
    v = verb or ""
    if v in VERB_TO_LEVEL and VERB_TO_LEVEL[v] >= 5 and tagged <= 3:
        return "HIGH"
    if v in {"analyze", "differentiate", "examine"} and tagged <= 2:
        return "MEDIUM"
    if v in {"explain", "describe"} and tagged == 1:
        return "LOW"
    return "MEDIUM"


@dataclass
class ParsedQuestion:
    qid: str
    text: str
    marks: int | None
    tagged_bloom: int | None
    tagged_co: int | None
    is_or_option: bool
    primary_verb: str | None
    inferred_bloom: int | None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _extract_marks(text: str) -> int | None:
    patterns = [
        r"\[(\d{1,2})\s*(?:marks?|m)?\s*\]",
        r"\((\d{1,2})\s*(?:marks?|m)\)",
        r"(\d{1,2})\s*marks?",
        r"(?:max\.?|maximum)\s*(\d{1,2})\s*marks?",
    ]
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def _extract_tagged_bloom(text: str) -> int | None:
    # University papers: KL2, BL3, BTL1, K4, etc.
    m = re.search(r"\b(?:KL|BL|BTL|BT|K)\s*([1-6])\b", text, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"(?:bloom|bl)\s*[:#]?\s*L?\s*([1-6])\b", text, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"\bL\s*([1-6])\b", text, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _extract_tagged_co(text: str) -> int | None:
    m = re.search(r"C\.?\s*O\.?\s*(\d+)", text, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"\bCO\s*(\d+)\b", text, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _primary_verb(text: str) -> str | None:
    # Strip common boilerplate
    core = re.sub(r"^(?:\d+[\).]\s*)+[a-z][\).]\s*", "", text, flags=re.IGNORECASE)
    core = re.sub(r"^Q\d+[a-z]?\s*[\).:]?\s*", "", core, flags=re.IGNORECASE)
    words = re.findall(r"[A-Za-z]+", core.lower())
    stop = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "for",
        "with",
        "any",
        "one",
        "two",
        "following",
        "given",
        "assume",
        "suitable",
        "data",
        "marks",
        "mark",
        "co",
        "bloom",
    }
    for w in words:
        if w in stop or len(w) < 3:
            continue
        if w in VERB_TO_LEVEL:
            return w
    return None


def _infer_bloom_from_verb(verb: str | None) -> int | None:
    if not verb:
        return None
    return VERB_TO_LEVEL.get(verb)


def split_into_questions(raw: str) -> list[tuple[str, str]]:
    """
    Split document into (qid, block) using common numbering patterns.

    Handles:
      Q1  Q1a  Q.1  Q.1a  Q.1 a)   <- standard + dotted university format
      1. a)  1) a  1a)              <- numeric sub-parts
      (a)                           <- standalone sub-part

    Also handles mid-line question starts (e.g. PDFs where
    "...10  1  5  Q.2  Attempt..." appears on one line) by inserting
    a newline before every Q.<digit> or Q<digit> that is not already
    at the start of a line.
    """
    text = raw.replace("\r\n", "\n")

    # Insert newline before any mid-line Q-number so the splitter sees it
    # as a block boundary.  Use a non-greedy look-behind to avoid double-newlines.
    text = re.sub(r"(?<!\n)(?=\s*Q\s*\.?\s*\d)", "\n", text)

    # Normalize standalone OR lines so they don't fragment blocks
    text = re.sub(r"(?i)^\s*OR\s*$", "\nOR\n", text, flags=re.MULTILINE)

    pattern = re.compile(
        r"(?:^|\n)\s*("
        r"Q\s*\.?\s*\d+\s*\.?\s*[a-z]?"    # Q1, Q.1, Q1a, Q.1a
        r"|\d+\s*[.)]\s*\(?\s*[a-z]\s*\)?" # 1. a)  1) a  1a)
        r"|\(\s*[a-z]\s*\)"                 # (a)
        r")\s*[:.)]?\s*",
        flags=re.IGNORECASE | re.MULTILINE,
    )

    matches = list(pattern.finditer(text))
    if not matches:
        return [("Q1", text.strip())]

    chunks: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        # Skip tiny footer/page-number artifacts
        if len(block) < 25 and re.fullmatch(
            r"[\d.\s]*(?:page\s*\d+\s*of\s*\d+)?", block, re.IGNORECASE
        ):
            continue
        # Normalise QID: remove dots and spaces, ensure Q prefix
        header = re.sub(r"\s+", "", m.group(1).strip()).replace(".", "")
        qid = header.upper() if header.upper().startswith("Q") else "Q" + header
        chunks.append((qid, block))

    return chunks if chunks else [("Q1", text.strip())]


def parse_questions(raw: str) -> list[ParsedQuestion]:
    out: list[ParsedQuestion] = []
    for qid, block in split_into_questions(raw):
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        joined = " ".join(lines)
        marks = _extract_marks(joined)
        tb = _extract_tagged_bloom(joined)
        tco = _extract_tagged_co(joined)
        verb = _primary_verb(joined)
        ib = _infer_bloom_from_verb(verb)
        is_or = bool(re.search(r"(?i)\bOR\b", block))
        out.append(
            ParsedQuestion(
                qid=qid,
                text=joined[:2000],
                marks=marks,
                tagged_bloom=tb,
                tagged_co=tco,
                is_or_option=is_or,
                primary_verb=verb,
                inferred_bloom=ib,
            )
        )
    return out


def parse_co_list(cos_raw: str) -> dict[int, str]:
    """Parse lines like CO1: Apply ... or CO 1 - ..."""
    cos: dict[int, str] = {}
    for line in cos_raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^C\.?\s*O\.?\s*(\d+)\s*[:.\-–]\s*(.+)$", line, flags=re.IGNORECASE)
        if m:
            cos[int(m.group(1))] = m.group(2).strip()
    return cos


def parse_units(syllabus_raw: str) -> list[str]:
    units = []
    for line in syllabus_raw.splitlines():
        s = line.strip()
        if s:
            units.append(s)
    return units


def _best_unit(question_text: str, units: list[str]) -> tuple[str | None, float]:
    if not units:
        return None, 0.0
    qn = _normalize(question_text)
    best_u = None
    best_score = 0.0
    for u in units:
        un = _normalize(u)
        # token overlap score
        utoks = set(re.findall(r"[a-z0-9]+", un))
        qtoks = set(re.findall(r"[a-z0-9]+", qn))
        if not utoks:
            continue
        inter = len(utoks & qtoks)
        score = inter / max(1, len(utoks))
        if score > best_score:
            best_score = score
            best_u = u
    if best_score < 0.15:
        return None, best_score
    return best_u, best_score


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def find_within_set_duplicates(
    sets: list[tuple[str, str, list[ParsedQuestion]]],
) -> list[dict[str, Any]]:
    """Pairs in the same set with text similarity >= 78% (same threshold as cross-set)."""
    out: list[dict[str, Any]] = []
    for set_label, _raw, qs in sets:
        for i in range(len(qs)):
            for j in range(i + 1, len(qs)):
                sim = _similarity(qs[i].text, qs[j].text)
                if sim >= 0.78:
                    rtype = "EXACT" if sim >= 0.92 else "NEAR-IDENTICAL"
                    out.append(
                        {
                            "kind": "within_set",
                            "set": set_label,
                            "qa": f"{set_label} {qs[i].qid}",
                            "qb": f"{set_label} {qs[j].qid}",
                            "snippet_a": qs[i].text[:200] + ("…" if len(qs[i].text) > 200 else ""),
                            "snippet_b": qs[j].text[:200] + ("…" if len(qs[j].text) > 200 else ""),
                            "similarity": f"{sim:.0%}",
                            "type": rtype,
                        }
                    )
    return out


def run_checks(
    *,
    sets: list[tuple[str, str, list[ParsedQuestion]]],
    units: list[str],
    cos_map: dict[int, str],
    co_required: bool,
    bloom_in_paper: bool,
) -> dict[str, Any]:
    """sets: list of (set_label, raw_text, parsed_questions)."""

    bloom_issues: list[dict[str, Any]] = []
    co_issues: list[dict[str, Any]] = []
    syllabus_rows: list[dict[str, Any]] = []
    repetition: list[dict[str, Any]] = []
    marks_issues: list[dict[str, Any]] = []
    quality: list[dict[str, Any]] = []

    unit_marks: dict[str, float] = {u: 0.0 for u in units}
    questions_by_unit: dict[str, int] = {u: 0 for u in units}

    co_counts: dict[int, int] = {}
    all_parsed: list[tuple[str, ParsedQuestion]] = []

    for set_label, _raw, qs in sets:
        for pq in qs:
            all_parsed.append((set_label, pq))

    # Per-question checks
    for set_label, pq in all_parsed:
        qref = f"{set_label} {pq.qid}"
        if pq.tagged_co is not None:
            co_counts[pq.tagged_co] = co_counts.get(pq.tagged_co, 0) + 1

        # CHECK A — Bloom
        if bloom_in_paper and pq.tagged_bloom is not None and pq.inferred_bloom is not None:
            if pq.tagged_bloom != pq.inferred_bloom:
                direction = "under-tagged" if pq.tagged_bloom < pq.inferred_bloom else "over-tagged"
                sev = "MEDIUM"
                verb = pq.primary_verb or ""
                if verb in VERB_TO_LEVEL and VERB_TO_LEVEL[verb] >= 5 and pq.tagged_bloom <= 3:
                    sev = "HIGH"
                elif verb in {"analyze", "differentiate", "examine"} and pq.tagged_bloom <= 2:
                    sev = "MEDIUM"
                elif verb in {"explain", "describe"} and pq.tagged_bloom == 1:
                    sev = "LOW"
                bloom_issues.append(
                    {
                        "q": qref,
                        "summary": pq.text[:120] + ("…" if len(pq.text) > 120 else ""),
                        "tagged": f"L{pq.tagged_bloom}",
                        "correct": f"L{pq.inferred_bloom}",
                        "direction": direction,
                        "severity": sev,
                        "fix": f"Retag Bloom level to {level_label(pq.inferred_bloom)} based on primary verb "
                        f"‘{pq.primary_verb}’.",
                    }
                )
        elif bloom_in_paper and pq.tagged_bloom is None and pq.inferred_bloom is not None:
            quality.append(
                {
                    "q": qref,
                    "issue": "Bloom tag missing",
                    "details": "Bloom validation requested but no L1–L6 tag detected in this block.",
                }
            )

        # CHECK C — Syllabus
        unit, score = _best_unit(pq.text, units)
        if units:
            if unit is None:
                syllabus_rows.append(
                    {
                        "q": qref,
                        "topic": pq.text[:220] + ("…" if len(pq.text) > 220 else ""),
                        "unit": "—",
                        "status": "Unclear / not matched to a unit (LOW confidence)",
                    }
                )
            else:
                syllabus_rows.append(
                    {
                        "q": qref,
                        "topic": pq.text[:220] + ("…" if len(pq.text) > 220 else ""),
                        "unit": unit,
                        "status": "Aligned (heuristic keyword overlap)",
                    }
                )
                if pq.marks:
                    unit_marks[unit] = unit_marks.get(unit, 0) + pq.marks
                questions_by_unit[unit] = questions_by_unit.get(unit, 0) + 1

        # CHECK F — Quality
        if re.search(r"(?i)assume\s+suitable\s+data", pq.text) and len(pq.text) < 120:
            quality.append(
                {
                    "q": qref,
                    "issue": "Thin numerical specification",
                    "details": "‘Assume suitable data’ with little context may be ambiguous for examinees.",
                }
            )
        if pq.text.count("?") > 3 and len(pq.text) < 80:
            quality.append(
                {
                    "q": qref,
                    "issue": "Possibly incomplete stem",
                    "details": "Very short block with multiple question marks — verify wording is complete.",
                }
            )

    # CO coverage
    for coid in cos_map:
        if co_required and co_counts.get(coid, 0) == 0:
            co_issues.append(
                {
                    "q": "—",
                    "topic": "Coverage",
                    "tagged": f"CO{coid}",
                    "correct": "—",
                    "type": "No questions mapped",
                    "fix": f"Include at least one question mapped to CO{coid}, or document exemption.",
                }
            )

    # CHECK D — Repetition across sets
    if len(sets) > 1:
        for i, (la, _ra, qsa) in enumerate(sets):
            for j, (lb, _rb, qsb) in enumerate(sets):
                if j <= i:
                    continue
                for a in qsa:
                    for b in qsb:
                        sim = _similarity(a.text, b.text)
                        if sim >= 0.92:
                            rtype = "EXACT"
                        elif sim >= 0.78:
                            rtype = "NEAR-IDENTICAL"
                        elif sim >= 0.55 and (a.tagged_co == b.tagged_co and a.tagged_bloom == b.tagged_bloom):
                            rtype = "TOPICALLY_REPEATED"
                        else:
                            continue
                        repetition.append(
                            {
                                "qa": f"{la} {a.qid}",
                                "qb": f"{lb} {b.qid}",
                                "topic": a.text[:60] + "…",
                                "type": rtype,
                                "similarity": f"{sim:.0%}",
                            }
                        )

    # CHECK E — Marks
    total_marks = sum(p.marks or 0 for _, p in all_parsed)

    # OR parity within same parent block heuristic: consecutive questions with OR
    for set_label, _raw, qs in sets:
        for k in range(len(qs) - 1):
            if qs[k].is_or_option or " OR " in qs[k].text.upper():
                m1, m2 = qs[k].marks, qs[k + 1].marks
                if m1 is not None and m2 is not None and m1 != m2:
                    marks_issues.append(
                        {
                            "issue": "OR option marks imbalance",
                            "details": f"{set_label}: {qs[k].qid} ({m1}m) vs {qs[k+1].qid} ({m2}m).",
                            "severity": "MEDIUM",
                        }
                    )

    # Unit over-representation
    if unit_marks and total_marks > 0:
        for u, m in unit_marks.items():
            pct = 100.0 * m / total_marks
            if pct > 40:
                marks_issues.append(
                    {
                        "issue": "Unit mark concentration",
                        "details": f"Unit ‘{u}’ accounts for ~{pct:.0f}% of parsed marks.",
                        "severity": "LOW",
                    }
                )

    under_units = [u for u in units if questions_by_unit.get(u, 0) == 0]
    over_units = [u for u, m in unit_marks.items() if total_marks and m / total_marks > 0.4]

    # Higher-order vs lower-order marks (only if bloom tags exist)
    if bloom_in_paper:
        ho = sum(p.marks or 0 for _, p in all_parsed if p.tagged_bloom and p.tagged_bloom >= 4)
        lo = sum(p.marks or 0 for _, p in all_parsed if p.tagged_bloom and p.tagged_bloom <= 2)
        if ho and lo and ho < lo * 0.5:
            marks_issues.append(
                {
                    "issue": "Higher-order Bloom marks lower than recall-heavy items",
                    "details": "Tagged L4–L6 marks sum lower than L1–L2; confirm this matches assessment design.",
                    "severity": "LOW",
                }
            )

    # --- Per-question Bloom / CO alignment (full list for report) ---
    def _best_co_for_text(text: str) -> tuple[int | None, float]:
        best_co: int | None = None
        best_score = -1.0
        for coid, codesc in cos_map.items():
            s = _similarity(text, codesc)
            if s > best_score:
                best_score = s
                best_co = coid
        return best_co, best_score

    bloom_order = {"NOT_ALIGNED": 0, "VERIFY": 1, "ALIGNED": 2, "SKIPPED": 3}
    bloom_per_question: list[dict[str, Any]] = []
    for set_label, pq in all_parsed:
        qref = f"{set_label} {pq.qid}"
        summ = pq.text[:220] + ("…" if len(pq.text) > 220 else "")
        verb = pq.primary_verb or "—"
        tb, ib = pq.tagged_bloom, pq.inferred_bloom
        tagged_s = f"L{tb}" if tb is not None else "—"
        inferred_s = f"L{ib}" if ib is not None else "—"

        if not bloom_in_paper:
            bloom_per_question.append(
                {
                    "q": qref,
                    "summary": summ,
                    "verb": verb,
                    "tagged": tagged_s,
                    "verb_based": inferred_s,
                    "alignment": "SKIPPED",
                    "severity": "—",
                    "notes": "Bloom validation not requested for this review.",
                }
            )
        elif tb is None:
            bloom_per_question.append(
                {
                    "q": qref,
                    "summary": summ,
                    "verb": verb,
                    "tagged": "—",
                    "verb_based": inferred_s,
                    "alignment": "NOT_ALIGNED",
                    "severity": "MEDIUM",
                    "notes": "No L1–L6 Bloom tag detected in this parsed block.",
                }
            )
        elif ib is None:
            bloom_per_question.append(
                {
                    "q": qref,
                    "summary": summ,
                    "verb": verb,
                    "tagged": tagged_s,
                    "verb_based": "—",
                    "alignment": "VERIFY",
                    "severity": "—",
                    "notes": "Tag present; primary verb not mapped to Bloom table (or stem unclear).",
                }
            )
        elif tb == ib:
            bloom_per_question.append(
                {
                    "q": qref,
                    "summary": summ,
                    "verb": verb,
                    "tagged": tagged_s,
                    "verb_based": inferred_s,
                    "alignment": "ALIGNED",
                    "severity": "—",
                    "notes": "Tagged level matches verb-based level.",
                }
            )
        else:
            direction = "under-tagged" if tb < ib else "over-tagged"
            bloom_per_question.append(
                {
                    "q": qref,
                    "summary": summ,
                    "verb": verb,
                    "tagged": tagged_s,
                    "verb_based": inferred_s,
                    "alignment": "NOT_ALIGNED",
                    "severity": _bloom_mismatch_severity(pq.primary_verb, tb, ib),
                    "notes": f"Mismatch ({direction}): paper tag {tagged_s}, verb suggests {inferred_s}.",
                }
            )

    bloom_per_question.sort(key=lambda r: (bloom_order.get(str(r.get("alignment")), 9), r["q"]))

    co_per_question: list[dict[str, Any]] = []
    if cos_map:
        co_order = {"NOT_ALIGNED": 0, "VERIFY": 1, "ALIGNED": 2}
        for set_label, pq in all_parsed:
            qref = f"{set_label} {pq.qid}"
            summ = pq.text[:220] + ("…" if len(pq.text) > 220 else "")
            best_co, best_score = _best_co_for_text(pq.text)
            tagged = pq.tagged_co
            tagged_s = f"CO{tagged}" if tagged is not None else "—"
            best_s = f"CO{best_co}" if best_co is not None else "—"
            score_s = f"{best_score:.2f}" if best_score >= 0 else "—"

            if tagged is None:
                co_per_question.append(
                    {
                        "q": qref,
                        "topic": summ,
                        "tagged_co": tagged_s,
                        "heuristic_co": best_s,
                        "score": score_s,
                        "alignment": "NOT_ALIGNED",
                        "severity": "HIGH",
                        "notes": "No CO tag on this question.",
                    }
                )
            elif best_co is None:
                co_per_question.append(
                    {
                        "q": qref,
                        "topic": summ,
                        "tagged_co": tagged_s,
                        "heuristic_co": "—",
                        "score": score_s,
                        "alignment": "VERIFY",
                        "severity": "—",
                        "notes": "Could not rank COs from pasted descriptions.",
                    }
                )
            elif tagged == best_co:
                co_per_question.append(
                    {
                        "q": qref,
                        "topic": summ,
                        "tagged_co": tagged_s,
                        "heuristic_co": tagged_s,
                        "score": score_s,
                        "alignment": "ALIGNED",
                        "severity": "—",
                        "notes": "Tagged CO matches best text-similarity match to your CO list.",
                    }
                )
            else:
                # Tagged CO differs from raw "best" CO — avoid false MISMATCH when the
                # paper explicitly prints a CO and that CO's description still fits.
                sim_tagged = (
                    _similarity(pq.text, cos_map[tagged])
                    if tagged is not None and tagged in cos_map
                    else -1.0
                )
                margin = best_score - sim_tagged
                explicit_tag = False
                if tagged is not None:
                    for m in re.finditer(r"\bCO\s*(\d+)\b", pq.text, re.IGNORECASE):
                        if int(m.group(1)) == tagged:
                            explicit_tag = True
                            break
                weak_overall = best_score < 0.22 and sim_tagged < 0.22
                close_scores = margin <= 0.09
                tagged_plausible = sim_tagged >= 0.10
                trust_explicit = explicit_tag and (sim_tagged >= 0.06 or margin < 0.16)
                trust_margin = tagged_plausible and (sim_tagged >= best_score - 0.06 or close_scores)

                if trust_explicit or weak_overall or trust_margin:
                    co_per_question.append(
                        {
                            "q": qref,
                            "topic": summ,
                            "tagged_co": tagged_s,
                            "heuristic_co": tagged_s,
                            "score": score_s,
                            "alignment": "ALIGNED",
                            "severity": "—",
                            "notes": (
                                "Tagged CO accepted: explicit paper label and/or similar fit to "
                                f"your CO{tagged} text vs heuristic best {best_s} (Δ={margin:.2f})."
                                if explicit_tag
                                else "Tagged CO accepted: similarity to your CO text is close to the best alternative."
                            ),
                        }
                    )
                elif best_score > 0.28 and margin > 0.12:
                    co_per_question.append(
                        {
                            "q": qref,
                            "topic": summ,
                            "tagged_co": tagged_s,
                            "heuristic_co": best_s,
                            "score": score_s,
                            "alignment": "NOT_ALIGNED",
                            "severity": "MEDIUM",
                            "notes": f"Heuristic strongly prefers {best_s} over tagged {tagged_s}.",
                        }
                    )
                else:
                    co_per_question.append(
                        {
                            "q": qref,
                            "topic": summ,
                            "tagged_co": tagged_s,
                            "heuristic_co": tagged_s,
                            "score": score_s,
                            "alignment": "ALIGNED",
                            "severity": "—",
                            "notes": "Tagged CO kept; best alternative is not clearly stronger.",
                        }
                    )
        co_per_question.sort(key=lambda r: (co_order.get(str(r.get("alignment")), 9), r["q"]))

    bloom_alignment_counts: dict[str, int] = {"ALIGNED": 0, "NOT_ALIGNED": 0, "VERIFY": 0, "SKIPPED": 0}
    for row in bloom_per_question:
        key = str(row.get("alignment", "VERIFY"))
        bloom_alignment_counts[key] = bloom_alignment_counts.get(key, 0) + 1

    co_alignment_counts: dict[str, int] = {"ALIGNED": 0, "NOT_ALIGNED": 0, "VERIFY": 0}
    for row in co_per_question:
        key = str(row.get("alignment", "VERIFY"))
        co_alignment_counts[key] = co_alignment_counts.get(key, 0) + 1

    repetition_summary: dict[str, Any] = {
        "total_pairs": len(repetition),
        "exact": sum(1 for r in repetition if r.get("type") == "EXACT"),
        "near_identical": sum(1 for r in repetition if r.get("type") == "NEAR-IDENTICAL"),
        "topically_repeated": sum(1 for r in repetition if r.get("type") == "TOPICALLY_REPEATED"),
    }

    return {
        "within_set_duplicates": find_within_set_duplicates(sets),
        "bloom_issues": bloom_issues,
        "bloom_per_question": bloom_per_question,
        "bloom_alignment_counts": bloom_alignment_counts,
        "co_per_question": co_per_question,
        "co_alignment_counts": co_alignment_counts,
        "co_issues": co_issues,
        "syllabus_rows": syllabus_rows,
        "under_units": under_units,
        "over_units": over_units,
        "unit_marks": unit_marks,
        "repetition": repetition,
        "repetition_summary": repetition_summary,
        "marks_issues": marks_issues,
        "quality": quality,
        "co_counts": co_counts,
        "cos_map": cos_map,
        "total_parsed_marks": total_marks,
        "question_count": len(all_parsed),
    }


def build_report_tables(
    *,
    course_name: str,
    sets_count: int,
    checks_run: list[str],
    result: dict[str, Any],
) -> dict[str, Any]:
    bloom = result.get("bloom_issues", [])
    co = result.get("co_issues", [])
    syl = [r for r in result.get("syllabus_rows", []) if "Unclear" in r.get("status", "")]
    rep = result.get("repetition", [])
    marks = result.get("marks_issues", [])
    qual = result.get("quality", [])

    def sev_bucket(items: list, key: str = "severity") -> str:
        highs = sum(1 for x in items if x.get(key) == "HIGH")
        meds = sum(1 for x in items if x.get(key) == "MEDIUM")
        if highs:
            return "HIGH"
        if meds:
            return "MEDIUM"
        return "LOW" if items else "—"

    bac = result.get("bloom_alignment_counts") or {}
    cac = result.get("co_alignment_counts") or {}
    bloom_align_problems = int(bac.get("NOT_ALIGNED", 0)) + int(bac.get("VERIFY", 0))
    co_align_problems = int(cac.get("NOT_ALIGNED", 0)) + int(cac.get("VERIFY", 0))

    bloom_high = sum(1 for x in bloom if x.get("severity") == "HIGH")
    marks_high = sum(1 for x in marks if x.get("severity") == "HIGH")
    qcount = max(1, int(result.get("question_count") or 0))

    if bloom_high or marks_high or len(syl) >= max(3, qcount // 3):
        recommendation = "MAJOR REVISION REQUIRED"
    elif (
        marks
        or len(syl) >= 2
        or rep
        or bloom_align_problems > 0
        or co_align_problems > 0
        or len(co) > 0
    ):
        recommendation = "NEEDS REVISION"
    else:
        recommendation = "APPROVED"

    summary_paragraph = (
        f"This automated pass reviewed {result.get('question_count', 0)} parsed question blocks across "
        f"{sets_count} set(s). Heuristic parsing may miss marks or CO/Bloom tags embedded in tables or images. "
        f"Recommendation: {recommendation}. Please verify every flagged row against the original PDF/DOCX "
        "and your board’s regulations before finalizing the paper."
    )

    co_sev = "—"
    if len(co) or co_align_problems:
        if len(co):
            co_sev = "HIGH"
        elif co_align_problems:
            co_sev = "MEDIUM"
    if any(row.get("severity") == "HIGH" for row in result.get("co_per_question", [])):
        co_sev = "HIGH"

    if bloom:
        bloom_sev = sev_bucket(bloom)
    elif bloom_align_problems:
        bloom_sev = "MEDIUM"
    else:
        bloom_sev = "—"

    overview = {
        "bloom": {"n": bloom_align_problems, "sev": bloom_sev},
        "co": {"n": co_align_problems + len(co), "sev": co_sev},
        "syllabus": {"n": len(syl), "sev": "MEDIUM" if len(syl) > 1 else ("LOW" if syl else "—")},
        "repetition": {"n": len(rep), "sev": "MEDIUM" if rep else "—"},
        "marks": {"n": len(marks), "sev": sev_bucket(marks)},
        "quality": {"n": len(qual), "sev": "LOW" if qual else "—"},
    }

    return {
        "course_name": course_name,
        "sets_count": sets_count,
        "checks_run": checks_run,
        "recommendation": recommendation,
        "summary_paragraph": summary_paragraph,
        "overview": overview,
        **result,
    }
