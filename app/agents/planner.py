import logging
from typing import List

from pydantic import ValidationError

from ..schemas import Plan, Section
from ..llm import ask_json

logger = logging.getLogger(__name__)


def plan(topic: str) -> Plan:
    """Turn a topic into 4-6 sections with searchable research questions.

    Each section includes a title, a research question, and a short search query
    optimized for web search engines (5-10 words, keywords not full sentences).

    Args:
        topic: The research topic.

    Returns:
        A Plan containing 4-6 sections with titles, questions, and search queries.

    Raises:
        ValueError: If the LLM produces fewer than 4 or more than 6 sections,
            or if duplicate questions are found.
    """
    system_prompt = (
        "You are a market research planner. Your task is to break down a topic into "
        "4-6 research sections, each focusing on a different angle. For each section, "
        "provide a title, a full research question, and a short search query (5-10 words) "
        "optimized for a web search engine (use keywords, not a full sentence).\n\n"
        "If the topic names a country, region, or city, every section's search_query must "
        "include it.\n\n"
        "The sections must cover different angles such as: market size, trends, competitors, "
        "customers, risks, regulation, etc. No duplicate questions are allowed.\n\n"
        "Respond with valid JSON matching this schema:\n"
        f"{Plan.model_json_schema()}\n\n"
        "Example:\n"
        '{"topic": "Electric scooters in Pakistan", "sections": ['
        '{"title": "Market Size", "question": "What is the current market size of electric scooters in Pakistan?", '
        '"search_query": "electric scooters market size Pakistan 2026"},'
        '{"title": "Trends", "question": "What are the main trends in electric scooters in Pakistan?", '
        '"search_query": "electric scooters trends Pakistan"},'
        '{"title": "Competitors", "question": "Who are the main competitors in the Pakistan electric scooter market?", '
        '"search_query": "electric scooter competitors Pakistan"'
        ']}'
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
            f"LLM response did not validate as Plan with 4-6 sections. Error: {e}"
        )

    # Validate section count
    num_sections = len(result.sections)
    if num_sections < 4 or num_sections > 6:
        raise ValueError(
            f"Expected 4-6 sections, got {num_sections}. "
            f"The LLM produced {num_sections} sections for topic '{topic}'."
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

    logger.info(f"Plan created successfully: {num_sections} sections for topic '{topic}'")
    return result