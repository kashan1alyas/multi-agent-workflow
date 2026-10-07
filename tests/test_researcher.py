import pytest
from unittest.mock import patch, MagicMock

from app.schemas import Fact, ResearchResult
from app.agents.researcher import research
from app.llm import ask_json


class TestResearcherDropsInvalidFacts:
    """Test that researcher drops facts whose source_url is not in search results."""

    @patch("app.agents.researcher.search_web")
    @patch("app.llm.ask_json")
    def test_drops_facts_with_foreign_source_url(self, mock_ask_json, mock_search_web):
        """Researcher should drop any fact whose source_url is not in search results."""
        # Mock search results with two URLs
        mock_search_web.return_value = [
            {"url": "https://example.com/real1", "title": "Real Result 1", "content": "Real content 1"},
            {"url": "https://example.com/real2", "title": "Real Result 2", "content": "Real content 2"},
        ]

        # Mock LLM to return 3 facts - two with valid URLs, one with invalid URL
        mock_ask_json.return_value = ResearchResult(
            question="test question",
            facts=[
                Fact(claim="Valid fact 1", source_url="https://example.com/real1"),
                Fact(claim="Valid fact 2", source_url="https://example.com/real2"),
                Fact(claim="Hallucinated fact", source_url="https://example.com/fake"),
            ],
        )

        result = research(question="test question")

        # Should only have 2 valid facts (the ones with URLs in search results)
        assert len(result.facts) == 2
        assert all(f.source_url in ["https://example.com/real1", "https://example.com/real2"] for f in result.facts)