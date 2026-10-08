import json
import logging
import re
import time
from typing import Any

from .config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    LLM_PROVIDER,
    OLLAMA_MODEL,
)
from app.cache import cache_get, cache_set
from app.metrics import metrics

logger = logging.getLogger(__name__)


# Retry configuration for provider errors
ASK_MAX_ATTEMPTS = 3
ASK_BASE_BACKOFF = 20  # seconds backoff for rate limits/timeouts
GEMINI_RETRY_DELAYS = (3, 8, 15, 30, 60)

_TEMPORARY_WORDS = ("unavailable", "resource_exhausted", "timeout", "timed out")
_TEMPORARY_CODE = re.compile(r"\b(503|429)\b")


def _is_temporary_gemini_error(message: str) -> bool:
    """True for errors worth retrying: overload, rate limit, timeout."""
    lowered = message.lower()
    if "perday" in lowered or "per day" in lowered:
        return False  # daily quota will not recover within a retry window
    if _TEMPORARY_CODE.search(lowered):
        return True
    return any(word in lowered for word in _TEMPORARY_WORDS)


def _llm_cache_key(provider: str, model: str, system: str, user: str) -> str:
    """Create a cache key from provider, model, system, and user text."""
    return f"{provider}:{model}:{system}:{user}"


def ask(system: str, user: str) -> str:
    """Send one request to the LLM provider chosen by LLM_PROVIDER.

    Gemini retries temporary errors inside _ask_gemini. Other providers retry
    here with exponential backoff. A final failure raises RuntimeError with a
    clear message instead of returning empty text.
    """
    provider = LLM_PROVIDER

    for attempt in range(ASK_MAX_ATTEMPTS):
        try:
            if provider == "gemini":
                metrics.record_llm_call()
                return _ask_gemini(system, user)
            elif provider == "ollama":
                metrics.record_llm_call()
                return _ask_ollama(system, user)
            elif provider == "anthropic":
                metrics.record_llm_call()
                return _ask_anthropic(system, user)
            else:
                raise ValueError(f"Unknown LLM provider: {provider}")
        except Exception as e:
            err_str = str(e)
            lowered_error = err_str.lower()

            # Gemini already retried internally; do not retry again here.
            if provider == "gemini":
                raise RuntimeError(
                    f"LLM provider {provider} call failed: {err_str}"
                ) from e

            is_daily_quota = "perday" in lowered_error
            is_client_error = any(
                code in lowered_error for code in ("400", "401", "403", "404")
            )
            is_rate_limit = (
                "429" in lowered_error
                and not is_daily_quota
                and any(
                    marker in lowered_error
                    for marker in (
                        "rate",
                        "too many",
                        "perminute",
                        "per-minute",
                        "per minute",
                    )
                )
            )
            is_timeout = "timeout" in lowered_error or "timed out" in lowered_error

            if is_daily_quota or is_client_error or not (is_rate_limit or is_timeout):
                raise RuntimeError(
                    f"LLM provider {provider} call failed: {err_str}"
                ) from e

            if attempt < ASK_MAX_ATTEMPTS - 1:
                backoff = ASK_BASE_BACKOFF * (2 ** attempt)
                logger.warning(
                    "Provider error on attempt %d/%d: %s. Retrying in %ds...",
                    attempt + 1,
                    ASK_MAX_ATTEMPTS,
                    err_str,
                    backoff,
                )
                time.sleep(backoff)
                continue

            raise RuntimeError(
                f"LLM provider {provider} call failed after "
                f"{ASK_MAX_ATTEMPTS} attempts. Last error: {err_str}"
            ) from e


def _ask_gemini(system: str, user: str) -> str:
    from google import genai as google_genai

    client = google_genai.Client(api_key=GEMINI_API_KEY)
    max_retries = len(GEMINI_RETRY_DELAYS)

    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                config={"system_instruction": system},
                contents=user,
            )
            text = response.text
            if not text:
                raise RuntimeError("Gemini returned empty text.")
            usage = getattr(response, "usage_metadata", None)
            if usage is not None:
                metrics.record_tokens(
                    getattr(usage, "prompt_token_count", None)
                    or getattr(usage, "input_token_count", None),
                    getattr(usage, "candidates_token_count", None)
                    or getattr(usage, "output_token_count", None),
                )
            return text
        except Exception as e:
            message = str(e)

            if not _is_temporary_gemini_error(message):
                # Bad key, bad model name, empty reply, daily quota, etc.
                raise RuntimeError(f"Gemini request failed: {message}") from e

            if attempt == max_retries:
                raise RuntimeError(
                    f"Gemini request failed after {max_retries} retries: {message}"
                ) from e

            delay = GEMINI_RETRY_DELAYS[attempt]
            logger.warning(
                "Temporary Gemini error on attempt %d/%d: %s. Retrying in %d seconds...",
                attempt + 1,
                max_retries + 1,
                message,
                delay,
            )
            time.sleep(delay)


def _ask_ollama(system: str, user: str) -> str:
    import ollama

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return response["message"]["content"]


def _ask_anthropic(system: str, user: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


def ask_json(system: str, user: str, schema: type, retries: int = 2) -> Any:
    """Send a request and force a JSON response that validates against a Pydantic schema.

    - Appends a JSON schema hint to the system prompt.
    - Strips markdown code fences from the reply.
    - Validates with the schema.
    - On failure, retries and tells the model what was wrong.
    - Raises ValueError after the last retry.
    """
    provider = LLM_PROVIDER

    if provider == "gemini":
        model = GEMINI_MODEL
    elif provider == "ollama":
        model = OLLAMA_MODEL
    elif provider == "anthropic":
        model = ANTHROPIC_MODEL
    else:
        model = ""

    schema_hint = (
        "\n\nOUTPUT REQUIREMENTS: Respond with valid JSON only. No prose, "
        "no markdown code fences, no explanations. The JSON must conform to "
        f"this schema:\n{schema.model_json_schema()}"
    )
    system_with_hint = system + schema_hint

    # Check disk cache
    cache_key = _llm_cache_key(provider, model, system, user)
    cached = cache_get(cache_key)
    if cached is not None:
        metrics.record_llm_call(cache_hit=True)
        logger.info("LLM cache hit for key '%s/%s'", provider, model)
        return schema.model_validate(cached)

    for attempt in range(1 + retries):
        # Provider errors (already retried inside ask) propagate unchanged.
        raw = ask(system_with_hint, user)

        try:
            cleaned = _strip_markdown_fences(raw)
            data = json.loads(cleaned)
            instance = schema.model_validate(data)
            cache_set(cache_key, instance.model_dump())
            logger.info("LLM JSON validation successful on attempt %d", attempt + 1)
            return instance
        except json.JSONDecodeError as e:
            err_msg = str(e)
        except Exception as e:
            if type(e).__name__ != "ValidationError":
                raise RuntimeError(f"LLM JSON processing error: {e}") from e
            err_msg = str(e)

        logger.warning("LLM JSON attempt %d failed: %s", attempt + 1, err_msg)
        if attempt >= retries:
            raise ValueError(
                f"LLM failed to produce valid JSON after {1 + retries} attempts. "
                f"Last error: {err_msg}"
            )
        # Tell the model what was wrong on the next attempt
        system_with_hint = _add_retry_feedback(system, err_msg, attempt) + schema_hint


def _strip_markdown_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences (```json ... ```)."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def _add_retry_feedback(system: str, error: str, attempt: int) -> str:
    """Append error feedback to the system prompt for the next retry."""
    return (
        f"{system}\n\n--- ERROR ON ATTEMPT {attempt + 1} --- "
        f"The previous JSON output was invalid. Error: {error}. "
        "Please output valid JSON conforming to the schema."
    )