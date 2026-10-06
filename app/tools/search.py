import os
import logging
from typing import List, Dict

from tavily import TavilyClient

logger = logging.getLogger(__name__)


def search_web(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Search the web using Tavily and return result summaries.

    Args:
        query: The search query.
        max_results: Maximum number of results to return.

    Returns:
        List of dicts with keys 'title', 'url', 'content'.

    Raises:
        ValueError: If the Tavily API call fails or returns no results.
    """
    try:
        client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
        response = client.search(query=query, max_results=max_results)
        results = []
        for r in response.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
            })
        logger.info(f"Tavily search completed: {len(results)} results for query: '{query}'")
        if not results:
            raise ValueError("Tavily returned no results.")
        return results
    except Exception as e:
        logger.error(f"Tavily search failed: {e}")
        raise ValueError(f"Tavily search failed: {e}")