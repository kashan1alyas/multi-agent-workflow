import logging
import re
from collections import defaultdict

from pydantic import BaseModel, Field

from ..llm import ask_json
from ..report import EMPTY_CONTENT, section_group
from ..schemas import Report
from .reviewer import _extract_numbers

logger = logging.getLogger(__name__)

_NUMBER_TOKEN = re.compile(r"\$?\b\d+(?:\.\d+)?%?\b")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


class EditorResult(BaseModel):
    summary: str = ""
    notes: list[str] = Field(default_factory=list)
    removed_sentences: list[str] = Field(default_factory=list)


class _Contradiction(BaseModel):
    section_a: int
    section_b: int
    description: str


class _EditorOutput(BaseModel):
    summary: str
    contradictions: list[_Contradiction]
    duplicate_sentences: list[str]


def _content_sections(report: Report):
    return [
        (index, section)
        for index, section in enumerate(report.sections, 1)
        if section_group(section) != 2
        and section.draft.content.strip()
        and section.draft.content.strip() != EMPTY_CONTENT
    ]


def _find_obvious_number_conflicts(contents: list[tuple[int, str]]) -> list[str]:
    """Find differing numbers in sentences with otherwise identical wording."""
    sentences_by_skeleton: dict[str, list[tuple[int, str, list[str]]]] = defaultdict(list)
    for section_number, content in contents:
        for sentence in _SENTENCE_BOUNDARY.split(content):
            numbers = _extract_numbers(sentence)
            if not numbers:
                continue
            skeleton = _NUMBER_TOKEN.sub("<number>", sentence.casefold()).strip()
            sentences_by_skeleton[skeleton].append(
                (section_number, sentence.strip(), numbers)
            )

    notes: list[str] = []
    for entries in sentences_by_skeleton.values():
        for index, (section_a, sentence_a, numbers_a) in enumerate(entries):
            for section_b, sentence_b, numbers_b in entries[index + 1:]:
                if section_a != section_b and numbers_a != numbers_b:
                    note = (
                        f"Possible numeric inconsistency between sections "
                        f"{section_a} and {section_b}: {sentence_a!r} / {sentence_b!r}"
                    )
                    if note not in notes:
                        notes.append(note)
    return notes


def _summary_sentence_count(summary: str) -> int:
    return len(
        [part for part in _SENTENCE_BOUNDARY.split(summary.strip()) if part.strip()]
    )


def _summary_numbers_missing(summary: str, section_text: str) -> list[str]:
    return [
        number
        for number in _extract_numbers(summary)
        if not re.search(
            rf"(?<![\w.]){re.escape(number)}(?![\w.])",
            section_text,
            re.IGNORECASE,
        )
    ]


def _has_exact_sentence(content: str, sentence: str) -> bool:
    return sentence in {
        part.strip()
        for part in _SENTENCE_BOUNDARY.split(content)
        if part.strip()
    }


def edit_report(report: Report) -> EditorResult:
    """Create a factual executive summary and report-level editorial notes."""
    content_sections = _content_sections(report)
    if len(content_sections) < 2:
        return EditorResult()

    section_text = "\n\n".join(
        f"SECTION {number}: {section.draft.title}\n{section.draft.content}"
        for number, section in content_sections
    )
    summary_source_text = "\n".join(
        section.draft.content for _, section in content_sections
    )
    content_pairs = [
        (number, section.draft.content)
        for number, section in content_sections
    ]
    numeric_notes = _find_obvious_number_conflicts(content_pairs)
    output: _EditorOutput | None = None
    summary = ""
    for attempt in range(2):
        feedback = ""
        if attempt == 1:
            feedback = (
                "\n\nThe previous summary failed the number check. Regenerate it "
                "without the following unsupported number(s): "
                + ", ".join(_summary_numbers_missing(summary, summary_source_text))
                + "."
            )
        output = ask_json(
            system=(
                "You are an editor of a complete market research report. Use only "
                "facts stated in the supplied section texts. Return a 3 to 5 "
                "sentence executive summary, contradictions or overlaps with the "
                "two section numbers and a one-line description, and exact "
                "sentences duplicated across sections that may be dropped. Do not "
                "introduce facts, implications, or numbers that are not stated."
            ),
            user=(
                f"SECTION TEXTS:\n{section_text}\n\n"
                "Return JSON with: summary (3-5 sentences), contradictions "
                "(array of {section_a, section_b, description}), and "
                "duplicate_sentences (array of exact duplicated sentences)."
                f"{feedback}"
            ),
            schema=_EditorOutput,
        )
        summary = output.summary.strip()
        missing_numbers = _summary_numbers_missing(summary, summary_source_text)
        valid_sentence_count = 3 <= _summary_sentence_count(summary) <= 5
        if not missing_numbers and valid_sentence_count:
            break
        if attempt == 1:
            logger.warning(
                "Editor summary omitted after regeneration failed validation "
                "(missing numbers=%s, sentence count=%d)",
                missing_numbers,
                _summary_sentence_count(summary),
            )
            summary = ""

    duplicate_candidates = dict.fromkeys(output.duplicate_sentences if output else [])
    exact_duplicates = [
        sentence
        for sentence in duplicate_candidates
        if sum(
            _has_exact_sentence(section.draft.content, sentence)
            for _, section in content_sections
        ) >= 2
    ]
    notes = numeric_notes + [
        f"Sections {item.section_a} and {item.section_b}: {item.description}"
        for item in (output.contradictions if output else [])
    ]
    return EditorResult(
        summary=summary,
        notes=notes,
        removed_sentences=exact_duplicates,
    )


def apply_editor_result(report: Report, result: EditorResult) -> None:
    """Store editorial metadata and remove only later exact duplicate sentences."""
    report.editor_summary = result.summary
    report.editor_notes = list(result.notes)
    report.editor_removed_sentences = list(result.removed_sentences)

    duplicate_sentences = set(result.removed_sentences)
    if not duplicate_sentences:
        return

    seen: set[str] = set()
    for _, section in _content_sections(report):
        parts = re.split(r"(?<=[.!?])(\s+)", section.draft.content)
        edited_parts: list[str] = []
        for index in range(0, len(parts), 2):
            sentence = parts[index]
            separator = parts[index + 1] if index + 1 < len(parts) else ""
            stripped = sentence.strip()
            if stripped in duplicate_sentences:
                if stripped in seen:
                    continue
                seen.add(stripped)
            edited_parts.extend([sentence, separator])
        section.draft.content = "".join(edited_parts)
