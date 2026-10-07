import os
import logging
import time
from typing import List, Dict

from tavily import TavilyClient

from app.cache import cache_get, cache_set

logger = logging.getLogger(__name__)


def _search_cache_key(query: str, max_results: int) -> str:
    """Create a cache key from query and max_results."""
    return f"{query}:{max_results}"


def search_web(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Search the web using Tavily and return result summaries with full page content.

    Args:
        query: The search query.
        max_results: Maximum number of results to return.

    Returns:
        List of dicts with keys 'title', 'url', 'content'. The 'content' field contains
        up to ~3000 characters of full page text, or falls back to the short Tavily snippet.
    """
    cache_key = _search_cache_key(query, max_results)
    cached = cache_get(cache_key)
    if cached is not None:
        logger.info(f"Tavily cache hit for query: '{query[:30]}...'")
        return cached

    try:
        start_time = time.time()
        client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
        # Request full page content so we can extract detailed snippets
        # Exclude social media platforms to focus on substantive sources
        response = client.search(
            query=query,
            max_results=max_results,
            include_raw_content=True,
            exclude_domains=["youtube.com", "facebook.com", "instagram.com", "tiktok.com", "x.com", "twitter.com", "pinterest.com"],
        )
        elapsed = time.time() - start_time
        logger.info(f"Tavily search completed in {elapsed:.2f}s")
        results = []
        for r in response.get("results", []):
            title = r.get("title", "")
            url = r.get("url", "")
            # Try raw content first; fall back to short content snippet
            raw = r.get("raw_content", "")
            if raw and raw.strip():
                # Truncate to ~3000 characters
                content = raw[:3000].strip()
            else:
                # Fall back to the short Tavily content snippet
                content = r.get("content", "")
            results.append({
                "title": title,
                "url": url,
                "content": content,
            })
        logger.info(f"Tavily search completed: {len(results)} results for query: '{query}'")
        if not results:
            raise ValueError("Tavily returned no results.")
        # Cache the successful result
        cache_set(cache_key, results)
        return results
    except Exception as e:
        logger.error(f"Tavily search failed: {e}")
        raise ValueError(f"Tavily search failed: {e}")