import pytest
from unittest.mock import patch, MagicMock
import time

from app.llm import ask


class TestLLMRetryBackoff:
    """Test retry with backoff for provider errors."""

    @patch("app.llm._ask_gemini")
    def test_rate_limit_retries_with_backoff(self, mock__ask_gemini):
        """Rate limit errors should retry with 20s backoff, max 3 attempts."""
        # Simulate 429 rate limit on first 2 attempts, then success on 3rd
        mock__ask_gemini.side_effect = [
            Exception("429 Too Many Requests"),
            Exception("429 Too Many Requests"),
            "Success response",
        ]

        with patch("app.llm.logger"):
            result = ask(system="test system", user="test user")

        # Should have been called 3 times
        assert mock__ask_gemini.call_count == 3
        # Should return the successful response
        assert result == "Success response"

    @patch("app.llm._ask_gemini")
    def test_timeout_retries_with_backoff(self, mock__ask_gemini):
        """Timeout errors should retry with backoff."""
        # Simulate timeout on first attempt, then success
        mock__ask_gemini.side_effect = [
            Exception("Request timeout"),
            "Success response",
        ]

        with patch("app.llm.logger"):
            result = ask(system="test system", user="test user")

        assert mock__ask_gemini.call_count == 2
        assert result == "Success response"

    @patch("app.llm._ask_gemini")
    def test_final_failure_raises_clear_error(self, mock__ask_gemini):
        """All retries exhausted should raise a clear RuntimeError."""
        # Simulate persistent failures
        mock__ask_gemini.side_effect = Exception("Persistent provider failure")

        with patch("app.llm.logger"):
            with pytest.raises(RuntimeError) as exc_info:
                ask(system="test system", user="test user")

        # Should raise RuntimeError, not return empty text
        assert "Persistent provider failure" in str(exc_info.value)
        assert "LLM provider" in str(exc_info.value)