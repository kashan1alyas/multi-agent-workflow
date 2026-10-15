import logging
from typing import List
from pydantic import BaseModel, Field

from app.llm import ask_json
from app.metrics import metrics
from app.schemas import Fact

logger = logging.getLogger(__name__)


class Decision(BaseModel):
    """Result of the supervisor's decide() function."""

    action: str = Field(
        description="One of: 'enough', 'search_again', 'give_up'"
    )
    new_queries: List[str] = Field(
        default_factory=list,
        description="Up to 2 new search queries that differ from every query already used"
    )
    reason: str = Field(description="Human-readable reason for the decision")


def decide(section_question: str, facts: List[Fact], queries_used: List[str]) -> Decision:
    """Decide whether enough facts have been collected for a section.

    Code rule first (no LLM):
    "enough" if there are at least 3 facts from at least 2 different source URLs.

    Otherwise, call ask_json to get up to 2 NEW search queries that differ from
    every query already used and target what is missing.
    Return "give_up" if the topic seems to have no public information.

    Args:
        section_question: The research question for this section.
        facts: List of Fact objects found so far.
        queries_used: List of search queries already used.

    Returns:
        A Decision instance indicating the action to take.
    """
    # Code rule first (no LLM): "enough" if there are at least 3 facts from at least 2 different source URLs
    unique_urls = set(f.source_url for f in facts)

    if len(facts) >= 3 and len(unique_urls) >= 2:
        logger.info(
            "Supervisor: enough facts (>=3 facts, >=2 unique source URLs) — action=enough",
            extra={"facts": len(facts), "unique_urls": len(unique_urls)}
        )
        return Decision(
            action="enough",
            new_queries=[],
            reason="enough facts collected from multiple sources",
        )

    # Otherwise, ask the LLM for new queries that target what is missing
    logger.info(
        "Supervisor: too few facts or too few sources (facts=%d, unique_urls=%d), querying LLM",
        len(facts),
        len(unique_urls),
    )

    with metrics.stage("supervise"):
        try:
            decision: Decision = ask_json(
                system=(
                    "You are a market research supervisor. Given a research question, "
                    "facts found so far, and queries already used, decide what to do next. "
                    "Respond with valid JSON conforming to this schema:\n"
                    f"{Decision.model_json_schema()}\n\n"
                    "Rules:"
                    "\n- 'enough': at least 3 facts from at least 2 different source URLs (code rule already checked above, so this means we still need more)."
                    "\n- 'search_again': provide up to 2 new search queries that differ from every query already used and target what is missing (official sources, different keywords, local language name, a related term)."
                    "\n- 'give_up': the topic seems to have no public information available."
                ),
                user=f"QUESTION: {section_question}\n\nFacts found so far: {len(facts)} facts from {len(unique_urls)} source URLs: {', '.join(f.source_url for f in facts) if facts else 'none'}\n\nQueries already used: {queries_used if queries_used else 'none'}\n\nWhat new search queries should we try?",
                schema=Decision,
                retries=1,
            )
        except Exception as e:
            # If the LLM call fails (including daily quota "PerDay"), stop the run
            logger.error(
                "Supervisor LLM call failed: %s", e,
                extra={"error": str(e)}
            )
            raise RuntimeError(
                f"Supervisor LLM call failed: {e}"
            ) from e

        logger.info(
            "Supervisor decision: action=%s, new_queries=%s, reason=%s",
            decision.action,
            decision.new_queries,
            decision.reason,
        )

        return decision