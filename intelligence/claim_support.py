"""Deterministic claim-to-source checks used by the existing answer guard.

This deliberately handles a narrow, explicit engineering claim vocabulary.
If a material claim is outside that vocabulary, publication fails closed; this
module never asks an LLM to certify evidence.
"""
from __future__ import annotations

import re
from decimal import Decimal


_PROPERTY_PATTERNS = (
    ("design pressure", r"\bdesign\s+pressure\b"),
    ("operating pressure", r"\boperating\s+pressure\b"),
    ("rated load", r"\brated\s+load\b"),
    ("temporary load", r"\btemporary\s+load(?:\s+increase)?\b"),
    ("flow rate", r"\bflow\s+rate\b"),
    ("floor gfa", r"\b(?:floor\s+)?gfa\b|\bfloor\s+gross\s+floor\s+area\b"),
    ("floor bua", r"\b(?:floor\s+)?bua\b|\bfloor\s+built[- ]up\s+area\b"),
    ("area", r"\b(?:plot\s+)?area\b|\barea\s+statement\b"),
    ("pressure", r"\bpressure\b"),
    ("flow", r"\bflow\b"),
    ("width", r"\bwidth\b"),
    ("length", r"\blength\b"),
    ("height", r"\bheight\b|\blevel\b"),
    ("diameter", r"\bdiameter\b"),
    ("thickness", r"\bthickness\b"),
    ("capacity", r"\bcapacity\b"),
    ("temperature", r"\btemperature\b"),
    ("load", r"\bload\b"),
    ("voltage", r"\bvoltage\b"),
    ("power", r"\bpower\b"),
    ("spacing", r"\bspacing\b"),
    ("quantity", r"\bquantity\b|\bcount\b|\bnumber\s+of\b|\bunits?\b|\bracks?\b|\bbuildings?\b|\blifts?\b|\bstoreys?\b|\bstories?\b|\bbays?\b"),
    ("rating", r"\brating\b|\bfire[- ]resistance\b|\bfire\s+door\b|\bassembly\s+rating\b"),
    ("dimension", r"\bdimension\b|\bgrid\b|\bspan\b|\bssl\b"),
)
_UNIT_NUMBER_RE = re.compile(
    r"(?<![\w])([-+]?\d[\d,]*(?:\.\d+)?)(?:\s|\*|-)*(" +
    r"kg/m3|kg/m³|kN/m2|kN/m²|N/mm2|N/mm²|m3/h|m³/h|m3/s|m³/s|L/s|L/min|L/h|gpm|cfm|"
    r"square metres|square meters|square feet|sq\.?\s*ft|sq\.?\s*m|sqm|sqft|MPa|kPa|Pa|psi|bar|"
    r"MW|kW|W|kVA|VA|kV|V|mA|A|Hz|dB|°C|°F|kNm|Nm|kN|N|kg|mm|cm|m²|m2|m³|m3|m|%|"
    r"units?|racks?|buildings?|lifts?|storeys?|stories?|floors?|bays?|hours?|minutes?)(?![A-Za-z0-9])",
    re.I,
)
_IDENTIFIER_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+\b")
_STATE_RE = re.compile(
    r"\b(approved\s+with\s+comments|approved|draft|proposed|superseded|pending|tbc|existing|current)\b",
    re.I,
)
_STATUS_CONTEXT_RE = re.compile(r"\b(?:status|drawing|document|issue|approval|approved|proposed|draft|tbc)\b", re.I)
_NON_STATUS_NOUN_PHRASE_RE = re.compile(
    r'\b(?:proposed|approved)\s+(?:development|building|buildings|gfa|area|units?|parking|racks?|lifts?|levels?|scheme|project|works?|shop\s+drawings?|design|details?|contractor)\b',
    re.I
)
_REVISION_RE = re.compile(r"\b(?:revision|rev(?:\.|\b))\s*(?:(?:is|no\.?|number)\s*)?[:#-]?\s*([A-Z0-9]{1,6})\b", re.I)
_NEG_RE = re.compile(r"\b(?:no|not|never|cannot|can't|must\s+not|prohibited|forbidden|disallowed|unapproved)\b", re.I)
_POLARITY_RE = re.compile(r"\b(?:permitted|allowed|approved|required|prohibited|forbidden|disallowed)\b", re.I)
_QUALIFIER_PATTERNS = (
    re.compile(r"\bsubject\s+to\s+[^.;,\n]+", re.I),
    re.compile(r"\bpending\s+[^.;,\n]+", re.I),
    re.compile(r"\bunless\s+[^.;,\n]+", re.I),
    re.compile(r"\bexcept\s+[^.;,\n]+", re.I),
    re.compile(r"\bprovided\s+that\s+[^.;,\n]+", re.I),
    re.compile(r"\bconditional\s+upon\s+[^.;,\n]+", re.I),
    re.compile(r"\bfor\s+coordination\s+only\b", re.I),
    re.compile(r"\bnot\s+for\s+(?:construction|installation|execution)\b", re.I),
    re.compile(r"\bnot\s+to\s+exceed\s+[^.;,\n]+", re.I),
)
_BOILERPLATE_QUALIFIER_RE = re.compile(
    r'(?:expressly\s+agreed\s+in\s+writing|unless\s+noted|noted\s+otherwise|all\s+rights\s+reserved|reproduced|liability|in\s+whole\s+or\s+in\s+part)',
    re.I
)
_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "for", "to", "of",
    "on", "in", "at", "by", "and", "or", "with", "without", "this", "that", "it", "as",
    "no", "not", "never", "must", "may", "can", "cannot", "permitted", "allowed", "approved",
    "required", "prohibited", "forbidden", "disallowed", "subject", "pending", "unless", "except",
    "provided", "conditional", "upon", "only", "from", "revision", "rev", "status", "drawing",
    "document", "issue", "current", "latest", "value", "states", "state", "shows", "specifies",
}
_ABSTENTION_RE = re.compile(
    r"\b(?:i\s+could\s+not\s+(?:find|verify|establish)|could\s+not\s+be\s+established|"
    r"not\s+stated\b|not\s+available\s+in\s+the\s+evidence|please\s+review|"
    r"conflicting\s+source\s+evidence|ambiguous\s+source\s+evidence|abstain)\b", re.I,
)

# A stage is a qualitative field, not permission to reuse arbitrary words
# from a cited page. These native cover headings have a narrow conventional
# meaning even when the PDF omits an explicit "Stage:" label.
_COVER_STAGES = frozenset({
    "concept design", "schematic design", "developed design", "detailed design",
})
_STAGE_LABEL = r"(?:(?:design|project)\s+)?stage"
_STAGE_ASSERTION_RE = re.compile(
    r"\b" + _STAGE_LABEL + r"\s*(?::|=|\bis\b)\s*(.+)", re.I)


def _metadata_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*_`]+", "", value)).strip(" \t\r\n.\"'").casefold()


def _source_stages(body: str) -> set[str]:
    """Read a complete labelled field or a standalone conventional heading.

    Never derive a stage from a mention inside another field or prose, and
    never discard a qualification attached to a field's value.
    """
    lines = [re.sub(r"[*_`]+", "", line).strip() for line in body.splitlines() if line.strip()]
    explicit = set()
    for index, line in enumerate(lines):
        field = re.fullmatch(_STAGE_LABEL + r"\s*[:=]\s*(.+)", line, re.I)
        if field:
            explicit.add(_metadata_text(field.group(1)))
        elif re.fullmatch(_STAGE_LABEL + r"\s*[:=]?", line, re.I) and index + 1 < len(lines):
            explicit.add(_metadata_text(lines[index + 1]))
    if explicit:
        return explicit
    return {
        _metadata_text(line) for index, line in enumerate(lines)
        if _metadata_text(line) in _COVER_STAGES
        and not (index and re.fullmatch(
            r"(?:project(?:\s+name|\s+title)?|document\s+title|title|client|consultant|engineer|report\s+title)\s*[:=]?",
            lines[index - 1], re.I))
    }


def _property_matches(text: str):
    hits = []
    for label, pattern in _PROPERTY_PATTERNS:
        for match in re.finditer(pattern, text, re.I):
            hits.append((match.start(), match.end(), label))
    # Prefer the longest phrase at the same location (e.g. design pressure).
    hits.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    out = []
    for hit in hits:
        if any(hit[0] >= old[0] and hit[0] < old[1] for old in out):
            continue
        out.append(hit)
    return out


def _state_name(value: str) -> str:
    return "APPROVED_WITH_COMMENTS" if re.sub(r"\s+", " ", value.strip()).casefold() == "approved with comments" else value.upper()


def _answer_segments(answer: str):
    """Return text segments and their citation handles without losing offsets."""
    from intelligence.answer_guard import MARKER

    clean = list(answer)
    citations = []
    for match in MARKER.finditer(answer):
        citations.append((match.start(), (match.group(1).strip(), match.group(2).upper())))
        for i in range(match.start(), match.end()):
            clean[i] = " "
    text = "".join(clean)
    # Server-appended metadata is disclosure, not an LLM claim; it is still
    # checked by the final gate for citation validity and source membership.
    metadata_at = re.search(r"(?im)^\s*(?:Source qualifications|Source disposition):", text)
    if metadata_at:
        text = text[:metadata_at.start()] + " " * (len(text) - metadata_at.start())
    for match in re.finditer(r"(?im)^\s*Scope:", text):
        text = text[:match.start()] + " " * (len(text) - match.start())

    # Protect decimal points and common engineering abbreviations while splitting prose
    text = re.sub(r"(?<=\d)\.(?=\d)", "\uE000", text)
    text = re.sub(r"\b(sq|no|rev)\.(?=[a-z])", lambda m: m.group(1) + "\uE001", text, flags=re.I)
    text = re.sub(r"\b(sq\uE001m|sq\uE001ft)\.(?=\s|\b|[.,;])", lambda m: m.group(1) + "\uE002", text, flags=re.I)
    segments = []
    for match in re.finditer(r"[^.!?\n]+(?:[.!?]+|$)", text):
        body = match.group().replace("\uE000", ".").replace("\uE001", ".").replace("\uE002", ".").strip()
        if body:
            segments.append((match.start(), match.end(), body))
    attached = []
    unique_keys = list(dict.fromkeys(key for _, key in citations))
    for index, (start, end, body) in enumerate(segments):
        next_start = segments[index + 1][0] if index + 1 < len(segments) else len(text)
        keys = [key for pos, key in citations if start <= pos <= end or end <= pos < next_start]
        if not keys and len(unique_keys) == 1:
            keys = [unique_keys[0]]
        elif not keys:
            next_cites = [key for pos, key in citations if pos >= end]
            if next_cites:
                keys = [next_cites[0]]
        attached.append((body, keys))
    return attached


def _material(text: str) -> bool:
    if re.fullmatch(r"\s*\d+[.)]?\s*", text):
        return False  # Markdown/list numbering is not an engineering claim.
    if _ABSTENTION_RE.search(text):
        return False
    return bool(
        re.search(r"\d", text)
        or _STATE_RE.search(text)
        or _NEG_RE.search(text)
        or _POLARITY_RE.search(text)
        or _property_matches(text)
        or _STAGE_ASSERTION_RE.search(re.sub(r"[*_`]+", "", text))
        or re.search(r"\b(?:drawing|document|revision|approval|status|equipment|foundation|beam|column|slab|design|specification|construction)\b", text, re.I)
    )


def _span_lines(body: str):
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if any(line.startswith("|") for line in lines):
        try:
            from intelligence.table_evidence import table_row_units
            lines.extend(table_row_units(body))
        except Exception:
            pass
    return lines


def _contains_phrase(text: str, phrase: str) -> bool:
    return bool(re.search(r"(?<![\w-])" + re.escape(phrase) + r"(?![\w-])", text, re.I))


def claim_support_issues(answer: str, evidence: str, sources, question: str = ""):
    """Return deterministic claim-support issues in addition to numeric gates.

    Every parsed engineering relationship must be supported by one cited span
    (a reconstructed table row counts as one span). Unknown material claims,
    omitted source units/qualifiers, polarity flips, status/revision mismatch,
    or unresolved cited conflicts fail closed.
    """
    from intelligence.answer_guard import MARKER, _excerpts_by_page, numbers, quantity_pairs
    from intelligence.source_semantics import explicit_states, native_revision, requested_authority

    excerpts = _excerpts_by_page(evidence)
    allowed = {
        (str(s.get("source") or s.get("filename") or ""),
         str(s.get("page") if s.get("page") is not None else "UNPAGINATED").upper())
        for s in sources if isinstance(s, dict)
    }
    issues = []
    segments = _answer_segments(answer)
    answer_without_server_notes = re.split(r"(?im)^\s*Source qualifications:", answer, maxsplit=1)[0]
    answer_revisions = {m.group(1).upper() for m in _REVISION_RE.finditer(answer_without_server_notes)}

    query_entities = {m.group().casefold() for m in _IDENTIFIER_RE.finditer(question or "") if re.search(r'\d', m.group())}
    if not query_entities:
        query_entities = set()

    for segment, cited_keys in segments:
        if not _material(segment):
            continue
        valid_keys = [key for key in cited_keys if key in allowed and key in excerpts]
        if not valid_keys:
            issues.append("Material claim lacks a valid source/page citation")
            continue
        bodies = [(key, excerpts[key]) for key in valid_keys]
        lines = [(key, line) for key, body in bodies for line in _span_lines(body)]
        stage_segment = re.sub(r"[*_`]+", "", segment)
        stage_claim = _STAGE_ASSERTION_RE.search(stage_segment)
        if stage_claim or re.search(r"\bdesign\s+stage\b", stage_segment, re.I):
            stage_values = set().union(*(_source_stages(body) for _, body in bodies))
            if len(stage_values) > 1:
                issues.append("AMBIGUOUS: cited sources contain conflicting design-stage values")
            if not stage_claim or _metadata_text(stage_claim.group(1)) not in stage_values:
                issues.append("Claimed design stage is not bound to a supported cited source field")
        props = _property_matches(segment)
        entities = [m.group() for m in _IDENTIFIER_RE.finditer(segment)]
        if not entities and len(query_entities) > 1 and _UNIT_NUMBER_RE.search(segment):
            issues.append("Quantified answer omits the requested equipment/entity identifier")

        answer_quantities = []
        for match in _UNIT_NUMBER_RE.finditer(segment):
            answer_quantities.append((Decimal(match.group(1).replace(",", "")), match.group(2), match.start()))
        answer_pairs = quantity_pairs(segment)
        answer_numbers = numbers(segment)

        # Preserve a unit from native evidence whenever the same property and
        # value are reported with that unit. A bare number cannot erase it.
        for _, _, prop in props:
            for key, line in lines:
                if not re.search(_property_pattern(prop), line, re.I):
                    continue
                source_pairs = quantity_pairs(line)
                for value, unit in source_pairs:
                    if value in answer_numbers and not any(pair_value == value for pair_value, _ in answer_pairs):
                        issues.append("Answer omits a unit specified for the cited property/value")
                        break
                if "Answer omits a unit specified for the cited property/value" in issues:
                    break

        # Keep entity + property + value/unit in one native sentence or one
        # reconstructed table row. A union of pages/rows cannot prove it.
        if answer_quantities and props:
            for value, unit, number_pos in answer_quantities:
                preceding_props = [p for p in props if p[1] <= number_pos]
                prop = preceding_props[-1][2] if preceding_props else (props[0][2] if len(props) == 1 else None)
                preceding_entities = [m.group() for m in _IDENTIFIER_RE.finditer(segment[:number_pos])]
                entity = preceding_entities[-1] if preceding_entities else (entities[0] if len(entities) == 1 else None)
                if entity is None and query_entities:
                    entity = next(iter(query_entities)) if len(query_entities) == 1 else None
                supported = False
                entity_pages = set()
                value_property_pages = set()
                for key, line in lines:
                    if entity and _contains_phrase(line, entity):
                        entity_pages.add(key)
                    if prop and not re.search(_property_pattern(prop), line, re.I):
                        continue
                    value_unit_matches = any(
                        v == value and _unit_equal(u, unit)
                        for v, u in quantity_pairs(line))
                    if value_unit_matches and key:
                        value_property_pages.add(key)
                    if value_unit_matches and (not entity or _contains_phrase(line, entity)):
                        supported = True
                        break
                if not supported:
                    if entity and entity_pages and value_property_pages and not (entity_pages & value_property_pages):
                        issues.append("AMBIGUOUS: entity and property/value evidence occur on separate cited pages")
                    else:
                        issues.append("Entity/property/value relationship is not supported by one cited source span")

        # Explicit dispositions are compared as exact states, including
        # conditional approvals; no filename or inferred authority is used.
        status_probe=segment
        # A PROPOSED column is a value category in engineering schedules, not
        # a document disposition. Remove only that explicit tabular label from
        # status interpretation; prose and labeled approval/status assertions
        # continue through the unchanged authority comparison below.
        status_probe=re.sub(
            r"(?im)^\s*\|\s*ITEM\s*\|\s*NO\.?\s*\|\s*REQUIRED\s*\|\s*PROPOSED\s*\|\s*$",
            " ",status_probe)
        if re.search(r"(?i)\bITEM\s*:\s*[^;]+;\s*(?:NO\.?\s*:\s*[^;]*;\s*)?REQUIRED\s*:",status_probe):
            status_probe=re.sub(r"(?i)(;\s*)PROPOSED\s*:",r"\1COLUMN:",status_probe)
        status_probe = _NON_STATUS_NOUN_PHRASE_RE.sub(" ", status_probe)
        is_status_assertion = bool(
            re.search(r'\b(?:status\s*(?:is|:)|(?:drawing|document|submission|submittal|issue)\s+(?:is|was|status\s+is)\s+(?:approved|draft|pending|superseded|tbc|current|proposed)|(?:approval|document|drawing|issue)\s+status\b|\bstatus\s*:\s*[A-Za-z]+|\bcode\s+[A-Z]\b)', segment, re.I)
            or re.search(r'\b(?:is|was)\s+(?:approved|draft|superseded|pending|tbc|proposed)\b', segment, re.I)
        )
        state_matches = [_state_name(m.group(1)) for m in _STATE_RE.finditer(status_probe)]
        if state_matches and _STATUS_CONTEXT_RE.search(status_probe) and is_status_assertion:
            source_states = set()
            for _, body in bodies:
                source_states.update(explicit_states(body))
            for state in state_matches:
                if state not in source_states:
                    issues.append("Claimed document status is not explicitly supported by the cited source")
                    break

        requested = requested_authority(question or "")
        if requested == "CURRENT" and re.search(r"\b(?:current|latest)\b", segment, re.I):
            source_states = set()
            for _, body in bodies:
                source_states.update(explicit_states(body))
            if "CURRENT" not in source_states:
                issues.append("AMBIGUOUS: cited evidence does not establish a current authorized issue")

        # A claimed native revision must be present on the cited page(s).
        if answer_revisions:
            cited_revisions = set()
            for _, body in bodies:
                revision = native_revision({"pages": [{"text": body}]})
                if revision:
                    cited_revisions.add(revision)
            if cited_revisions and not answer_revisions.issubset(cited_revisions):
                issues.append("Claimed revision does not match the cited native revision")
            elif answer_revisions and not cited_revisions:
                issues.append("Claimed revision is not established by the cited source")

        # Preserve source qualifiers. This uses explicit lexical cues; unknown
        # material clauses are handled below as unparsed and fail closed.
        for _, body in bodies:
            for pattern in _QUALIFIER_PATTERNS:
                for match in pattern.finditer(body):
                    if _BOILERPLATE_QUALIFIER_RE.search(match.group()):
                        continue
                    core = [w.casefold() for w in re.findall(r"[A-Za-z]{3,}", match.group())
                            if w.casefold() not in _STOP_WORDS]
                    if not core:
                        continue
                    match_pos = match.start()
                    line_start = body.rfind('\n', 0, match_pos)
                    line_end = body.find('\n', match.end())
                    qual_sentence = body[line_start if line_start != -1 else 0 : line_end if line_end != -1 else len(body)]
                    qual_context_words = {w.casefold() for w in re.findall(r"[A-Za-z]{3,}", qual_sentence)} - _STOP_WORDS - set(core)
                    segment_words = {w.casefold() for w in re.findall(r"[A-Za-z]{3,}", segment)} - _STOP_WORDS
                    if qual_context_words and not (qual_context_words & segment_words):
                        continue
                    if not all(re.search(r"\b" + re.escape(word) + r"\b", segment, re.I) for word in core):
                        issues.append("Answer omits or changes a source qualification")
                        break

        # Preserve polarity for matching source/candidate propositions.
        if _POLARITY_RE.search(segment) or _NEG_RE.search(segment):
            candidate_words = {w.casefold() for w in re.findall(r"[A-Za-z]{3,}", segment)} - _STOP_WORDS
            candidate_polarity = bool(_NEG_RE.search(segment))
            source_lines=[line for _,body in bodies for line in _span_lines(body)]
            normalize_span=lambda value:re.sub(r"\W+"," ",value.casefold()).strip()
            normalized_segment=normalize_span(segment)
            verbatim_table_row=any(
                normalize_span(line)==normalized_segment
                or (line.startswith('[TABLE ROW]') and
                    normalize_span(line).endswith(normalized_segment))
                or normalized_segment in normalize_span(line)
                for line in source_lines)
            if not verbatim_table_row and not _ABSTENTION_RE.search(segment):
                source_sentences = [s.strip() for line in source_lines for s in re.split(r'\. |\n+|(?<=[.;])\s+', line) if s.strip()]
                for line in source_sentences:
                    if not _POLARITY_RE.search(line):
                        continue
                    source_words = {w.casefold() for w in re.findall(r"[A-Za-z]{3,}", line)} - _STOP_WORDS
                    overlap = candidate_words & source_words
                    if len(overlap) >= 3 and candidate_polarity != bool(_NEG_RE.search(line)):
                        issues.append("Answer reverses or drops source negation/polarity")
                        break

        # Conflicting values for the same unqualified property across cited
        # revisions/pages are ambiguity, not permission to select one value.
        if re.search(r"\b(?:current|latest)\b", segment, re.I):
            for _, _, prop in props:
                values = set()
                for _, line in lines:
                    if re.search(_property_pattern(prop), line, re.I):
                        values.update(quantity_pairs(line))
                if len(values) > 1 and not answer_revisions:
                    issues.append("AMBIGUOUS: conflicting source values; no unique current value is established")
                    break

        # Do not silently publish domain-specific material prose that this
        # deterministic parser does not understand. Positive supported forms
        # above are validated; other forms require review until modeled.
        structured = bool(answer_quantities or (answer_numbers and props)
                          or (state_matches and _STATUS_CONTEXT_RE.search(segment))
                          or _NEG_RE.search(segment) or _POLARITY_RE.search(segment)
                          or any(p.search(segment) for p in _QUALIFIER_PATTERNS)
                          or _ABSTENTION_RE.search(segment)
                          or re.search(r'\b(?:report|title|stage|code|standard|guidelines?|supplementary|jurisdiction|authority|coordination|deliverables?|review|limited|separate|submitted|revision|date)\b', segment, re.I))
        domain_words = re.search(
            r"\b(?:drawing|document|revision|approval|status|equipment|foundation|beam|column|slab|"
            r"design|specification|construction|pressure|flow|load|capacity|voltage|power|level|spacing|area)\b",
            segment, re.I)
        if domain_words and not structured:
            # A sentence whose content words are (almost) all present in the
            # cited page is a close restatement of the source, not new
            # engineering prose -- e.g. "Based on the current design, the
            # Acoustic Performance credit would most practically be achieved
            # through ..." (2026-10-14 pipeline audit: correct, cited answers
            # were withheld by this rule alone). Numbers/units/polarity are
            # still checked by the rules above.
            _seg_words = {w.casefold() for w in re.findall(r"[A-Za-z]{3,}", segment)} - _STOP_WORDS
            _src_words = {w.casefold() for _, body in bodies for w in re.findall(r"[A-Za-z]{3,}", body)}
            if len(_seg_words) >= 4 and len(_seg_words & _src_words) / len(_seg_words) >= 0.8:
                structured = True
        if domain_words and not structured:
            issues.append("Unparsed material engineering claim requires review")

    # De-duplicate to keep repair prompts and logs concise/deterministic.
    return list(dict.fromkeys(issues))


def _property_pattern(label: str) -> str:
    for name, pattern in _PROPERTY_PATTERNS:
        if name == label:
            return pattern
    return r"(?!)"


def _unit_equal(left: str, right: str) -> bool:
    from intelligence.answer_guard import _normalize_unit
    return _normalize_unit(left) == _normalize_unit(right)
