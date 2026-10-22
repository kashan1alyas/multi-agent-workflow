import logging
import re
from typing import Iterable

from ..llm import ask_json
from ..schemas import Plan, Section

logger = logging.getLogger(__name__)

_WORD = re.compile(r"\b\w+\b", re.UNICODE)
_MAX_ATTEMPTS = 3


def _question_words(question: str) -> set[str]:
    return {word.lower() for word in _WORD.findall(question)}


def _duplicate_problem(sections: Iterable[Section]) -> str | None:
    questions = list(sections)
    for index, first in enumerate(questions):
        first_words = _question_words(first.question)
        if not first_words:
            return f"Section {index + 1} has an empty question."
        for other_index in range(index + 1, len(questions)):
            second_words = _question_words(questions[other_index].question)
            if not second_words:
                return f"Section {other_index + 1} has an empty question."
            shared_ratio = len(first_words & second_words) / min(
                len(first_words), len(second_words)
            )
            if shared_ratio > 0.7:
                return (
                    f"Questions in sections {index + 1} and {other_index + 1} "
                    "are near-duplicates; each pair must share no more than "
                    "70 percent of its words."
                )
    return None


def _validate_sections(sections: list[Section], n_sections: int) -> str | None:
    if len(sections) != n_sections:
        return f"Return exactly {n_sections} sections; returned {len(sections)}."
    return _duplicate_problem(sections)


def plan(topic: str, n_sections: int) -> Plan:
    """Plan exactly n_sections distinct research angles for a topic."""
    if not 1 <= n_sections <= 20:
        raise ValueError("n_sections must be between 1 and 20")

    system_prompt = (
        "You are a market research planner. Produce exactly "
        f"{n_sections} sections, each covering a clearly different angle. "
        "Each section must include one searchable research question and a short "
        "search_query of 5 to 10 keywords, not a full sentence. Questions must "
        "not be duplicates or near-duplicates.\n\n"
        "If the topic names a country, region, or city, every question's "
        "search_query must include it.\n\n"
        "Respond with valid JSON matching this schema:\n"
        f"{Plan.model_json_schema()}"
    )
    problem = ""
    last_result: Plan | None = None
    last_valid_count = 0

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        user_prompt = f"TOPIC: {topic}"
        if problem:
            user_prompt += (
                f"\n\nThe previous response was invalid: {problem} "
                f"Regenerate exactly {n_sections} valid sections."
            )
        try:
            result: Plan = ask_json(
                system=system_prompt,
                user=user_prompt,
                schema=Plan,
                retries=2,
            )
        except ValueError as exc:
            problem = f"The response did not validate as a Plan: {exc}"
            last_result = None
            last_valid_count = 0
            continue

        last_result = result
        problem = _validate_sections(result.sections, n_sections) or ""
        if not problem:
            logger.info(
                "Plan created successfully: %d sections for topic '%s'",
                len(result.sections),
                topic,
            )
            return result

        valid_sections: list[Section] = []
        for section in result.sections:
            if _duplicate_problem([*valid_sections, section]) is None:
                valid_sections.append(section)
        last_valid_count = len(valid_sections)

    if (
        last_result is not None
        and n_sections >= 4
        and last_valid_count >= 4
        and last_valid_count < n_sections
    ):
        valid_sections = []
        for section in last_result.sections:
            if _duplicate_problem([*valid_sections, section]) is None:
                valid_sections.append(section)
        last_result.sections = valid_sections
        logger.warning(
            "Planner returned %d of %d requested sections; using the valid sections.",
            len(valid_sections),
            n_sections,
        )
        return last_result

    raise ValueError(
        f"Planner could not produce {n_sections} valid sections after "
        f"{_MAX_ATTEMPTS} attempts: {problem}"
    )
