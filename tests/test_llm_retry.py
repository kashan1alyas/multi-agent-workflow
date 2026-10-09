import pytest
from unittest.mock import call, patch

from app.llm import ask


class TestLLMRetryBackoff:
    """Test retry with backoff for provider errors."""

    @patch("app.llm._sleep")
    @patch("app.llm._ask_gemini")
    def test_rate_limit_retries_with_backoff(self, mock__ask_gemini, mock_sleep):
        mock__ask_gemini.side_effect = [
            Exception("429 Too Many Requests"),
            Exception("429 Too Many Requests"),
            "Success response",
        ]

        result = ask(system="test system", user="test user")

        assert mock__ask_gemini.call_count == 3
        assert result == "Success response"
        assert mock_sleep.call_args_list == [call(20), call(40)]

    @patch("app.llm._sleep")
    @patch("app.llm._ask_gemini")
    def test_timeout_retries_with_backoff(self, mock__ask_gemini, mock_sleep):
        mock__ask_gemini.side_effect = [
            Exception("Request timeout"),
            "Success response",
        ]

        result = ask(system="test system", user="test user")

        assert mock__ask_gemini.call_count == 2
        assert result == "Success response"
        mock_sleep.assert_called_once_with(20)

    @patch("app.llm._sleep")
    @patch("app.llm._ask_gemini")
    def test_final_failure_raises_clear_error(self, mock__ask_gemini, mock_sleep):
        mock__ask_gemini.side_effect = Exception("Persistent provider failure")

        with pytest.raises(RuntimeError) as exc_info:
            ask(system="test system", user="test user")

        assert "Persistent provider failure" in str(exc_info.value)
        assert "LLM provider" in str(exc_info.value)
        mock__ask_gemini.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("app.llm._sleep")
    @patch("app.llm._ask_gemini")
    def test_per_day_429_is_not_retried(self, mock__ask_gemini, mock_sleep):
        mock__ask_gemini.side_effect = Exception("429 PerDay quota exhausted")

        with pytest.raises(RuntimeError, match="Daily free quota exhausted"):
            ask(system="test system", user="test user")

        mock__ask_gemini.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("app.llm._sleep")
    @patch("app.llm._ask_gemini")
    def test_404_is_not_retried(self, mock__ask_gemini, mock_sleep):
        mock__ask_gemini.side_effect = Exception("404 model not found")

        with pytest.raises(RuntimeError, match="404 model not found"):
            ask(system="test system", user="test user")

        mock__ask_gemini.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("app.llm._sleep")
    @patch("app.llm._ask_gemini")
    def test_retry_exhaustion_raises_after_three_calls(
        self,
        mock__ask_gemini,
        mock_sleep,
    ):
        mock__ask_gemini.side_effect = Exception("429 Too Many Requests")

        with pytest.raises(RuntimeError) as exc_info:
            ask(system="test system", user="test user")

        assert "429 Too Many Requests" in str(exc_info.value)
        assert mock__ask_gemini.call_count == 3
        assert mock_sleep.call_args_list == [call(20), call(40)]