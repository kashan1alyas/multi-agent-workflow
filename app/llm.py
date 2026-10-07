import json
import logging
import time
from typing import Any, Dict

from .config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    LLM_PROVIDER,
    OLLAMA_MODEL,
)
from app.cache import cache_get, cache_set

logger = logging.getLogger(__name__)


# Retry configuration for provider errors
ASK_MAX_ATTEMPTS = 3
ASK_BASE_BACKOFF = 20  # seconds backoff for rate limits/timeouts


def _llm_cache_key(provider: str, model: str, system: str, user: str) -> str:
    """Create a cache key from provider, model, system, and user text."""
    key_data = f"{provider}:{model}:{system}:{user}"
    return key_data


def ask(system: str, user: str) -> str:
    """Send one request to the LLM provider chosen by LLM_PROVIDER.

    Includes retry with exponential backoff for provider errors (rate limit, timeout).
    A final failure raises RuntimeError with a clear message instead of returning
    empty text.

    Args:
        system: The system prompt.
        user: The user prompt.

    Returns:
        The model's reply text.

    Raises:
        RuntimeError: If all retry attempts are exhausted.
    """
    provider = LLM_PROVIDER

    for attempt in range(ASK_MAX_ATTEMPTS):
        try:
            if provider == "gemini":
                return _ask_gemini(system, user)
            elif provider == "ollama":
                return _ask_ollama(system, user)
            elif provider == "anthropic":
                return _ask_anthropic(system, user)
            else:
                raise ValueError(f"Unknown LLM provider: {provider}")
        except Exception as e:
            err_str = str(e)
            lowered_error = err_str.lower()
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
                raise RuntimeError(err_str) from e

            if attempt < ASK_MAX_ATTEMPTS - 1:
                backoff = ASK_BASE_BACKOFF * (2 ** attempt)
                logger.warning(
                    f"Provider error on attempt {attempt + 1}/{ASK_MAX_ATTEMPTS}: {err_str}. "
                    f"Retrying in {backoff}s..."
                )
                time.sleep(backoff)
                continue
            else:
                raise RuntimeError(err_str) from e


def _ask_gemini(system: str, user: str) -> str:
    from google import genai as google_genai
    client = google_genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        config={"system_instruction": system},
        contents=user,
    )
    return response.text


def _ask_ollama(system: str, user: str) -> str:
    import ollama
    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
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
    - On failure, retries by telling the model what was wrong.
    - Raises ValueError after the last retry.

    Args:
        system: The system prompt.
        user: The user prompt.
        schema: A Pydantic BaseModel class to validate against.
        retries: Number of retry attempts after initial failure.

    Returns:
        The validated Pydantic model instance.

    Raises:
        ValueError: If validation fails after all retries.
    """
    provider = LLM_PROVIDER

    # Resolve the model name for the active provider
    if provider == "gemini":
        model = GEMINI_MODEL
    elif provider == "ollama":
        model = OLLAMA_MODEL
    elif provider == "anthropic":
        model = ANTHROPIC_MODEL
    else:
        model = ""

    # Build the system prompt with schema hint
    schema_hint = f"\n\nOUTPUT REQUIREMENTS: Respond with valid JSON only. No prose, no markdown code fences, no explanations. The JSON must conform to this schema:\n{schema.model_json_schema()}"

    system_with_hint = system + schema_hint

    # Check disk cache
    cache_key = _llm_cache_key(provider, model, system, user)
    cached = cache_get(cache_key)
    if cached is not None:
        logger.info(f"LLM cache hit for key '{provider}/{model}'")
        return schema.model_validate(cached)

    for attempt in range(1 + retries):
        try:
            raw = ask(system_with_hint if attempt == 0 else _make_retry_system(system, attempt) + schema_hint, user)
        except Exception as e:
            # Provider call error - don't retry, propagate immediately with clear message
            raise RuntimeError(f"LLM provider {provider} call failed: {e}") from e
        
        try:
            # Strip markdown code fences if present
            cleaned = _strip_markdown_fences(raw)
            # Parse JSON
            data = json.loads(cleaned)
            # Validate with Pydantic schema
            instance = schema.model_validate(data)
            # Cache the result keyed by provider + model + system + user
            cache_set(cache_key, instance.model_dump())
            logger.info(f"LLM JSON validation successful on attempt {attempt + 1}")
            return instance
        except json.JSONDecodeError as e:
            # JSON parsing error - retry with error feedback
            err_msg = str(e)
            logger.warning(f"LLM JSON attempt {attempt + 1} failed: {err_msg}")
            if attempt >= retries:
                raise ValueError(
                    f"LLM failed to produce valid JSON after {1 + retries} attempts. "
                    f"Last error: {err_msg}"
                )
            system_with_hint = _add_retry_feedback(system, err_msg, attempt)
        except Exception as e:
            # Pydantic validation error or other processing error
            # Check if it's a Pydantic ValidationError to determine retry behavior
            is_pydantic_error = type(e).__name__ == 'ValidationError'
            if is_pydantic_error:
                # Pydantic validation error - retry with error feedback (requirement 1)
                err_msg = str(e)
                logger.warning(f"LLM JSON attempt {attempt + 1} failed: {err_msg}")
                if attempt >= retries:
                    raise ValueError(
                        f"LLM failed to produce valid JSON after {1 + retries} attempts. "
                        f"Last error: {err_msg}"
                    )
                system_with_hint = _add_retry_feedback(system, err_msg, attempt)
            else:
                # Other error - propagate immediately (requirement 2)
                raise RuntimeError(f"LLM JSON processing error: {str(e)}") from e


def _strip_markdown_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences (```json ... ```)."""
    text = text.strip()
    if text.startswith("```"):
        # Find the end fence
        lines = text.split("\n")
        # Remove leading ```json or ```
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        # Remove trailing ```
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def _make_retry_system(system: str, attempt: int) -> str:
    """Build a retry system prompt indicating which attempt we're on."""
    return f"{system}\n\n--- RETRY {attempt + 1} --- Please fix the JSON output based on the error feedback below."


def _add_retry_feedback(system: str, error: str, attempt: int) -> str:
    """Append error feedback to the system prompt for the next retry."""
    return f"{system}\n\n--- ERROR ON ATTEMPT {attempt + 1} --- The previous JSON output was invalid. Error: {error}. Please output valid JSON conforming to the schema."