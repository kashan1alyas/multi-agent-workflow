import logging
from typing import List, Optional

from ..schemas import SectionDraft, Fact
from ..llm import ask_json

logger = logging.getLogger(__name__)


def write_section(question: str, facts: List[Fact], feedback: Optional[str] = None) -> SectionDraft:
    """Draft a section from verified facts, using only the provided evidence.

    - Writes 1-3 short paragraphs using ONLY the provided facts.
    - No outside knowledge or numbers (numbers from facts are kept as-is).
    - If facts are thin (few facts or sparse content), indicates that.
    - Drops any source_urls not present in the input facts.
    - If zero facts are provided, returns "Not enough verified information found."
    - When feedback is given, includes the reviewer's issues in the prompt
      and instructs the model to fix them using only the provided facts.

    Args:
        question: The research question to answer.
        facts: List of verified Fact objects with claims and source URLs.
        feedback: Optional string of reviewer issues to fix (from review_section).

    Returns:
        A SectionDraft with title, content paragraphs, and filtered source URLs,
        or a string message if there are no facts.
    """
    if not facts:
        return "Not enough verified information found."

    # Build facts summary for the prompt
    facts_summary = "\n".join(
        f"{i+1}. {f.claim} (source: {f.source_url})" for i, f in enumerate(facts)
    )

    # Base system prompt
    system_prompt = (
        "You are a market research writer. Your task is to draft a short section "
        "(1-3 paragraphs) answering the research question using ONLY the provided "
        "facts. Do NOT use any outside knowledge. Include relevant numbers, dates, "
        "and claims directly from the facts. Write in a factual, neutral tone."
    )

    # Build user prompt with facts and optional feedback
    user_prompt = f"""
QUESTION: {question}

FACTS:
{facts_summary}

Instructions:
- Draft 1-3 short paragraphs that answer the question using ONLY the facts above.
- Include relevant numbers, dates, and claims directly from the facts.
- Write in a factual, neutral tone. Do NOT use outside knowledge.
"""

    # If feedback was provided (from reviewer), include it and instruct to fix
    if feedback:
        user_prompt += (
            "\nPREVIOUS REVIEW ISSUES (must be fixed using only the provided facts):\n"
            f"{feedback}\n"
            "Please rewrite the draft correcting all identified issues, using only "
            "the facts provided above. Do not add any new information beyond what "
            "the facts support."
        )
    else:
        user_prompt += "\nDraft the section now."

    draft: SectionDraft = ask_json(
        system=system_prompt,
        user=user_prompt,
        schema=SectionDraft,
        retries=2,
    )

    logger.info(f"Drafted section '{question}' from {len(facts)} facts")
    return draft