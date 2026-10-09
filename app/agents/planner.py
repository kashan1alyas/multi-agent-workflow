import logging
from typing import List

from pydantic import ValidationError

from ..schemas import Plan, Section
from ..llm import ask_json

logger = logging.getLogger(__name__)


def plan(topic: str, max_questions: int = 5) -> Plan:
    """Turn a topic into up to max_questions sections with searchable questions.

    Each section includes a title, a research question, and a short search query
    optimized for web search engines (5-10 words, keywords not full sentences).

    Args:
        topic: The research topic.

    Returns:
        A Plan containing distinct sections with titles, questions, and search queries.

    Raises:
        ValueError: If max_questions is outside 1-20 or questions are duplicated.
    """
    if not 1 <= max_questions <= 20:
        raise ValueError("max_questions must be between 1 and 20")

    system_prompt = (
        "You are a market research planner. Your task is to break down a topic into "
        f"exactly {max_questions} research questions, each focusing on a different angle. "
        "Questions must be distinct and must not overlap in topic. For each question, "
        "provide a title, a full research question, and a short search query (5-10 words) "
        "optimized for a web search engine (use keywords, not a full sentence).\n\n"
        "If the topic names a country, region, or city, every question's search_query must "
        "include it.\n\n"
        "Cover different angles such as market size, trends, competitors, customers, "
        "risks, and regulation. Do not repeat or overlap questions.\n\n"
        "Respond with valid JSON matching this schema:\n"
        f"{Plan.model_json_schema()}"
    )

    user_prompt = f"TOPIC: {topic}"

    try:
        result: Plan = ask_json(
            system=system_prompt,
            user=user_prompt,
            schema=Plan,
            retries=2,
        )
    except ValidationError as e:
        raise ValueError(
            f"LLM response did not validate as a Plan. Error: {e}"
        )

    returned_count = len(result.sections)
    if returned_count > max_questions:
        logger.warning(
            "Planner returned %d questions; keeping the first %d.",
            returned_count,
            max_questions,
        )
        result.sections = result.sections[:max_questions]
    elif returned_count < max_questions:
        logger.warning(
            "Planner returned %d of %d requested questions for topic '%s'; "
            "using the questions returned.",
            returned_count,
            max_questions,
            topic,
        )

    # Validate no duplicate questions (case-insensitive)
    questions = [s.question.lower().strip() for s in result.sections]
    if len(questions) != len(set(questions)):
        seen = {}
        for s in result.sections:
            q = s.question.lower().strip()
            seen[q] = seen.get(q, 0) + 1
        duplicates = {q: c for q, c in seen.items() if c > 1}
        raise ValueError(
            f"Duplicate questions found in plan: {duplicates}. "
            f"All questions must be unique."
        )

    logger.info(
        "Plan created successfully: %d sections for topic '%s'",
        len(result.sections),
        topic,
    )
    return result