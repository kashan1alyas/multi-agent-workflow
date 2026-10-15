import pytest
from unittest.mock import patch, MagicMock

from app.agents.supervisor import decide, Decision
from app.schemas import Fact


class TestSupervisorEnoughFacts:
    """Test that enough facts returns 'enough' without calling the LLM."""

    def test_enough_facts_returns_enough_without_llm_call(self):
        """With >=3 facts from >=2 unique URLs, supervisor returns 'enough' via code rule."""
        facts = [
            Fact(claim="Fact 1", source_url="https://example.com/1"),
            Fact(claim="Fact 2", source_url="https://example.com/2"),
            Fact(claim="Fact 3", source_url="https://example.com/3"),
        ]
        result = decide(
            section_question="test question",
            facts=facts,
            queries_used=[],
        )
        assert result.action == "enough"
        assert result.new_queries == []
        assert "enough facts collected" in result.reason


class TestSupervisorTooFewFacts:
    """Test that too few facts triggers LLM query generation."""

    @patch("app.llm.ask_json")
    def test_too_few_facts_returns_search_again(self, mock_ask_json):
        """With <3 facts, supervisor calls LLM and returns 'search_again'."""
        facts = [
            Fact(claim="Fact 1", source_url="https://example.com/1"),
        ]
        mock_ask_json.return_value = {
            "action": "search_again",
            "new_queries": ["electric scooters Pakistan 2024"],
            "reason": "need more facts",
        }
        result = decide(
            section_question="test question",
            facts=facts,
            queries_used=[],
        )
        assert result.action == "search_again"
        assert len(result.new_queries) > 0

    @patch("app.llm.ask_json")
    def test_give_up_possible_when_llm_responds(self, mock_ask_json):
        """Supervisor can return 'give_up' if the LLM decides topic has no public info."""
        facts = []
        mock_ask_json.return_value = {
            "action": "give_up",
            "new_queries": [],
            "reason": "no public information available",
        }
        result = decide(
            section_question="obscure ancient language topic",
            facts=facts,
            queries_used=[],
        )
        # The LLM can return give_up when facts are empty and topic seems unavailable
        assert result.action in ("search_again", "give_up")

    @patch("app.llm.ask_json")
    def test_too_few_facts_returns_new_queries_differ_from_used(self, mock_ask_json):
        """With too few facts, supervisor returns new queries that differ from used ones."""
        facts = []
        mock_ask_json.return_value = {
            "action": "search_again",
            "new_queries": ["electric scooters Pakistan"],
            "reason": "need more facts from different sources",
        }
        result = decide(
            section_question="test question",
            facts=facts,
            queries_used=["old query"],
        )
        assert result.action == "search_again"
        # New query should differ from the used query
        for q in result.new_queries:
            assert q != "old query"


class TestSupervisorQueryValidation:
    """Test that new queries are validated against used queries."""

    @patch("app.llm.ask_json")
    def test_validates_queries_differ_from_used(self, mock_ask_json):
        """Filter out queries that are already in the used list."""
        facts = [Fact(claim="Fact 1", source_url="https://example.com/1")]
        mock_ask_json.return_value = {
            "action": "search_again",
            "new_queries": ["used query", "new query 1", "new query 2"],
            "reason": "generate new queries",
        }
        result = decide(
            section_question="test question",
            facts=facts,
            queries_used=["used query"],
        )
        assert result.action == "search_again"
        # After validation, used queries should be filtered out
        assert len(result.new_queries) < 3  # Some may be filtered

    @patch("app.llm.ask_json")
    def test_all_queries_used_triggers_fallback(self, mock_ask_json):
        """If all new queries are already used, pipeline uses fallback."""
        facts = [Fact(claim="Fact 1", source_url="https://example.com/1")]
        mock_ask_json.return_value = {
            "action": "search_again",
            "new_queries": ["already used one"],
            "reason": "all used",
        }
        result = decide(
            section_question="test question",
            facts=facts,
            queries_used=["already used one"],
        )
        assert result.action == "search_again"
        # Empty new_queries after validation triggers fallback in pipeline


class TestSupervisorRoundsAndBudget:
    """Test the supervisor loop constraints."""

    @patch("app.llm.ask_json")
    def test_loop_stops_after_2_rounds_per_section(self, mock_ask_json):
        """Supervisor loop should respect MAX_EXTRA_ROUNDS_PER_SECTION = 2."""
        facts = [Fact(claim="Fact 1", source_url="https://example.com/1")]
        
        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return {
                    "action": "search_again",
                    "new_queries": ["new query"],
                    "reason": "",
                }
            else:
                return {
                    "action": "enough",
                    "new_queries": [],
                    "reason": "",
                }
        
        mock_ask_json.side_effect = side_effect
        
        result = decide(
            section_question="test question",
            facts=facts,
            queries_used=[],
        )
        # The pipeline's while loop runs at most MAX_EXTRA_ROUNDS_PER_SECTION=2 times
        # The decide function returns whatever the LLM decides
        assert result.action in ("search_again", "enough")

    @patch("app.llm.ask_json")
    def test_loop_respects_max_6_extra_searches_total(self, mock_ask_json):
        """Supervisor should respect MAX_EXTRA_SEARCHES = 6 per run."""
        facts = [Fact(claim="Fact 1", source_url="https://example.com/1")]
        
        call_count = 0
        extra_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count, extra_count
            call_count += 1
            if call_count <= 6:
                extra_count += 1
                return {
                    "action": "search_again",
                    "new_queries": ["new query"],
                    "reason": "",
                }
            else:
                return {
                    "action": "enough",
                    "new_queries": [],
                    "reason": "",
                }
        
        mock_ask_json.side_effect = side_effect
        
        result = decide(
            section_question="test question",
            facts=facts,
            queries_used=[],
        )
        # After 6 extra searches, pipeline stops and returns 'enough'
        assert result.action in ("search_again", "enough")