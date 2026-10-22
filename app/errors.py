class LLMProviderError(RuntimeError):
    """An LLM provider request failed and should stop the pipeline."""


class DailyQuotaExceeded(LLMProviderError):
    """The configured LLM provider has exhausted its daily request quota."""
