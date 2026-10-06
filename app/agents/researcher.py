import logging
from typing import List

from pydantic import ValidationError

from ..schemas import Fact, ResearchResult
from ..config import LLM_PROVIDER
from ..tools.search import search_web

logger = logging.getLogger(__name__)


def research(question: str) -> ResearchResult:
    """Research a question and return structured, verified facts with sources.

    Steps:
        1. Search the web for the question.
        2. Build a context string from the search results.
        3. Call ask_json to extract facts, instructing the model to use ONLY the provided results.
        4. Anti-hallucination guard: drop any fact whose source_url is not in the set
           of URLs returned by the search.
        5. If no valid facts remain, return an empty list.

    Args:
        question: The research question to answer.

    Returns:
        A ResearchResult containing the question and a list of verified facts.
    """
    # Step 1: Search the web
    logger.info(f"Research started: '{question}'")
    search_results = search_web(question, max_results=5)
    logger.info(f"Found {len(search_results)} search results")

    # Collect the set of source URLs from search results
    source_urls = {r["url"] for r in search_results}
    logger.info(f"Source URLs: {source_urls}")

    # Build a context string from the results for the LLM prompt
    context_parts = []
    for i, r in enumerate(search_results, 1):
        context_parts.append(f"[{i}] Title: {r['title']}\n      URL: {r['url']}\n      Snippet: {r['content']}")
    context_string = "\n\n".join(context_parts)

    # Step 3: Call ask_json with a system prompt telling the model to use ONLY the provided results
    system_prompt = (
        "You are a market research assistant. Your task is to extract concrete, verifiable facts "
        "from the provided search results ONLY. Do not use any external knowledge. "
        "If a fact is not clearly supported by the results, do not include it.\n\n"
        "Format your response as JSON with the following structure:\n"
        "{ \"facts\": [ { \"claim\": \"...\", \"source_url\": \"...\" } ] }\n\n"
        "Only include facts that are directly supported by the results. Each fact must have a "
        "source_url that exactly matches one of the provided URLs."
    )

    user_prompt = f"QUESTION: {question}\n\nSEARCH RESULTS:\n{context_string}"

    from ..llm import ask_json
    from ..schemas import ResearchResult

    try:
        result: ResearchResult = ask_json(
            system=system_prompt,
            user=user_prompt,
            schema=ResearchResult,
            retries=2,
        )
    except Exception as e:
        logger.error(f"LLM research call failed: {e}")
        return ResearchResult(question=question, facts=[])

    # Step 4: Anti-hallucination guard - drop any fact whose source_url is not in the search results
    valid_facts = []
    for fact in result.facts:
        if fact.source_url in source_urls:
            valid_facts.append(fact)
        else:
            logger.info(
                f"Dropped hallucinated fact (source URL not in search results): "
                f"'{fact.claim[:60]}...' from {fact.source_url}"
            )

    # Step 5: Return result with valid facts only
    logger.info(f"Returning {len(valid_facts)} valid facts (dropped {len(result.facts) - len(valid_facts)})")
    return ResearchResult(question=question, facts=valid_facts)