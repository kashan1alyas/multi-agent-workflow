import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root (parent of /app/).
# override=True ensures that .env values take precedence over any leftover
# Windows environment variables (e.g., TAVILY_API_KEY=placeholder-tavily-key).
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=True)

PROJECT_ROOT = Path(__file__).parent.parent


def _positive_int_env(name: str, default: int) -> int:
    value = os.getenv(name, str(default))
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be a positive integer.")
    return parsed


MAX_TOPIC_LENGTH = _positive_int_env("MAX_TOPIC_LENGTH", 200)
MAX_SECTIONS = min(_positive_int_env("MAX_SECTIONS", 3), 3)
MAX_RUNS_PER_IP_PER_DAY = _positive_int_env("MAX_RUNS_PER_IP_PER_DAY", 3)
MAX_RUNS_PER_DAY = _positive_int_env("MAX_RUNS_PER_DAY", 30)
RUN_TIMEOUT_SECONDS = _positive_int_env("RUN_TIMEOUT_SECONDS", 300)
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173").strip()
CACHE_DIR = Path(
    os.getenv("CACHE_DIR", str(PROJECT_ROOT / ".cache"))
).expanduser().resolve()


def _is_placeholder(key: str, value: str) -> bool:
    """Check if a value looks like a placeholder.

    A key counts as invalid if it is empty, or contains 'placeholder',
    'your_', or 'changeme' (case-insensitive).
    """
    if not value:
        return True
    lower = value.lower()
    return any(
        substr in lower
        for substr in ("placeholder", "your_", "changeme")
    )


def _validate_key(key: str, value: str) -> None:
    """Raise ValueError if the key looks like a placeholder."""
    if _is_placeholder(key, value):
        raise ValueError(
            f"{key} looks like a placeholder. Put your real key in .env and "
            "save the file."
        )


# Determine LLM provider early
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()

# Model names are not secrets, always load them from .env with sensible defaults
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
_PROVIDER_MODELS = {
    "gemini": GEMINI_MODEL,
    "ollama": OLLAMA_MODEL,
    "anthropic": ANTHROPIC_MODEL,
}
VERIFIER_PROVIDER = os.getenv("VERIFIER_PROVIDER", LLM_PROVIDER).lower()
VERIFIER_MODEL = os.getenv("VERIFIER_MODEL") or _PROVIDER_MODELS.get(
    VERIFIER_PROVIDER, ""
)
INPUT_PRICE_PER_MTOK = float(os.getenv("INPUT_PRICE_PER_MTOK", "0"))
OUTPUT_PRICE_PER_MTOK = float(os.getenv("OUTPUT_PRICE_PER_MTOK", "0"))

# Load credentials once; validate only the selected provider's key below.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")


def _validate_provider(provider: str) -> None:
    if provider == "gemini":
        _validate_key("GEMINI_API_KEY", GEMINI_API_KEY)
    elif provider == "ollama":
        return
    elif provider == "anthropic":
        _validate_key("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY)
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider}. Choose from: gemini, ollama, anthropic"
        )


_validate_provider(LLM_PROVIDER)
if VERIFIER_PROVIDER != LLM_PROVIDER:
    _validate_provider(VERIFIER_PROVIDER)

_validate_key("TAVILY_API_KEY", TAVILY_API_KEY)