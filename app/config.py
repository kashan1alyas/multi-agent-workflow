import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root (parent of /app/).
# override=True ensures that .env values take precedence over any leftover
# Windows environment variables (e.g., TAVILY_API_KEY=placeholder-tavily-key).
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=True)

PROJECT_ROOT = Path(__file__).parent.parent


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
        first5 = value[:5] if value else "(empty)"
        raise ValueError(
            f"{key} looks like a placeholder. Put your real key in .env and "
            f"save the file. Loaded value started with: {first5}"
        )


# Determine LLM provider early
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()

# Model names are not secrets, always load them from .env with sensible defaults
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# Load credentials once; validate only the selected provider's key below.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# Conditionally require keys based on selected provider
if LLM_PROVIDER == "gemini":
    _validate_key("GEMINI_API_KEY", GEMINI_API_KEY)
elif LLM_PROVIDER == "ollama":
    pass
elif LLM_PROVIDER == "anthropic":
    _validate_key("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY)
else:
    raise ValueError(f"Unknown LLM provider: {LLM_PROVIDER}. Choose from: gemini, ollama, anthropic")

_validate_key("TAVILY_API_KEY", TAVILY_API_KEY)