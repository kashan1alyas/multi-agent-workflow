import logging
import re
from typing import List, Optional
from urllib.parse import urlparse
from pydantic import ValidationError

from ..schemas import Fact, ResearchResult
from ..config import LLM_PROVIDER
from ..tools.search import search_web

logger = logging.getLogger(__name__)

# Max characters per page to send to LLM (tunable constant)
MAX_CHARS_PER_PAGE = 3000


def research(question: str, search_query: Optional[str] = None) -> ResearchResult:
    """Research a question and return structured, verified facts with sources.

    Steps:
        1. Search the web for the question (using search_query if provided).
        2. Build a context string from the search results.
        3. Call ask_json to extract facts, instructing the model to use ONLY the provided results.
        4. Anti-hallucination guard: drop any fact whose source_url is not in the set
           of URLs returned by the search.
        5. If no valid facts remain, return an empty list.

    Args:
        question: The research question to answer.
        search_query: Optional short search query (5-10 words) optimized for web search engines.
            If not provided, the full question is used for searching.

    Returns:
        A ResearchResult containing the question and a list of verified facts.

    Raises:
        Any provider errors (invalid key, quota, network) propagate up; they are not caught.
    """
    # Step 1: Search the web
    search_input = search_query if search_query else question
    logger.info(f"Research started: '{question}'")
    search_results = search_web(search_input, max_results=5)
    logger.info(f"Found {len(search_results)} search results")

    # Collect the set of source URLs from search results
    source_urls = {r["url"] for r in search_results}
    logger.info(f"Source URLs: {source_urls}")

    # Build a context string from the results for the LLM prompt
    # Log characters per source URL
    for r in search_results:
        chars = len(r.get("content", ""))
        logger.info(f"  {r['url'][:60]}: {chars} characters of content")
    
    context_parts = []
    for i, r in enumerate(search_results, 1):
        context_parts.append(f"[{i}] Title: {r['title']}\n      URL: {r['url']}\n      Snippet: {r['content']}")
    context_string = "\n\n".join(context_parts)

    # Step 3: Call ask_json with a system prompt telling the model to use ONLY the provided results
    system_prompt = (
        "You are a market research fact-extractor. Your task is to extract up to 6 facts "
        "from the provided search results. A fact qualifies if it contains at least one of: "
        "a number (price, percentage, quantity, year), a named company/product/law/policy, "
        "or a specific date/place. Each fact must be one self-contained sentence that can be "
        "understood without the source. Skip generic marketing statements and anything that "
        "restates the question. Prefer facts that answer the question directly. Return fewer "
        "facts only if the sources truly contain nothing relevant. Return valid JSON with the "
        "schema: { \"facts\": [ { \"claim\": \"...\", \"source_url\": \"...\" } ] }."
    )

    user_prompt = f"QUESTION: {question}\n\nSEARCH RESULTS:\n{context_string}"

    from ..llm import ask_json
    from ..schemas import ResearchResult

    result: ResearchResult = ask_json(
        system=system_prompt,
        user=user_prompt,
        schema=ResearchResult,
        retries=2,
    )

    # Step 4: Anti-hallucination guard - drop any fact whose source_url is not in the search results
    valid_facts = []
    # Log facts per source URL
    facts_per_source = {}
    for fact in result.facts:
        url = fact.source_url
        if url not in facts_per_source:
            facts_per_source[url] = []
        facts_per_source[url].append(fact.claim)
    
    for url, claims in facts_per_source.items():
        logger.info(f"  {url[:60]}: {len(claims)} facts extracted")
    
    # Anti-hallucination guard - drop any fact whose source_url is not in the search results
    # Normalize URLs: strip trailing slashes/#fragments, lowercase scheme+host
    def normalize_url(u: str) -> str:
        """Normalize a URL for comparison: lowercase scheme+host, strip trailing slash and fragment."""
        if "://" not in u:
            u = "https://" + u
        parsed = urlparse(u)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/") or "/"
        return f"{scheme}://{netloc}{path}"

    normalized_allowed = {normalize_url(u) for u in source_urls}

    valid_facts = []
    # Log facts per source URL and apply tolerant URL guard
    facts_per_source = {}
    for fact in result.facts:
        url = fact.source_url
        # Normalize the fact's URL for comparison
        normalized_fact_url = normalize_url(url) if "://" in url else f"https://{url}"

        # Check for exact match first
        if url in source_urls:
            valid_facts.append(fact)
            facts_per_source.setdefault(url, []).append(fact.claim)
        elif normalized_fact_url in normalized_allowed:
            # Tolerant match: find the allowed URL that matches
            match_url = None
            for allowed in source_urls:
                norm_allowed = normalize_url(allowed)
                if normalized_fact_url == norm_allowed or normalized_fact_url.startswith(norm_allowed) or norm_allowed.startswith(normalized_fact_url):
                    match_url = allowed
                    break
            if match_url:
                # Replace the fact's source_url with the matching allowed URL
                fact = Fact(claim=fact.claim, source_url=match_url)
                valid_facts.append(fact)
                facts_per_source.setdefault(match_url, []).append(fact.claim)
            else:
                # No match found - drop the fact, log it
                facts_per_source.setdefault(url, []).append(fact.claim)
        else:
            # No match found - drop the fact, log it
            facts_per_source.setdefault(url, []).append(fact.claim)

    # Log facts per source: extracted vs kept after guard
    for url, claims in facts_per_source.items():
        kept = sum(
            1
            for f in result.facts
            if normalize_url(f.source_url) == normalize_url(url) or f.source_url == url
        )
        logger.info(f"  {url[:60]}: {len(claims)} facts extracted, {kept} kept")

    # Log any drops with full allowed URL list for debugging
    dropped_count = len(result.facts) - len(valid_facts)
    if dropped_count > 0:
        logger.warning(
            f"Dropped {dropped_count} fact(s) whose source_url did not match allowed URLs: {list(source_urls)}"
        )

    # Step 5: Return result with valid facts only
    # If the model returned zero valid facts (or all were dropped), return empty list
    logger.info(f"Returning {len(valid_facts)} valid facts (dropped {len(result.facts) - len(valid_facts)})")
    return ResearchResult(question=question, facts=valid_facts)