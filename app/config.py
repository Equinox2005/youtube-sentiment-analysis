"""Configuration: API keys and model selection, from environment or .env file."""

import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def get_api_key() -> str | None:
    """Return the YouTube Data API v3 key, or None if not configured."""
    return _env("YOUTUBE_API_KEY")


def get_anthropic_key() -> str | None:
    """Return the Anthropic API key, or None if not configured.

    The SDK also resolves credentials from an `ant auth login` profile, so a
    missing key here does not necessarily mean extraction will fail.
    """
    return _env("ANTHROPIC_API_KEY")


# The map pass reads raw comments and is by far the larger token spend; the
# reduce pass sees only extracted structure and is where the judgment lives.
# Both default to Opus 5. Setting NICHE_MAP_MODEL=claude-haiku-4-5 cuts map-pass
# cost roughly 5x with some loss of nuance on sarcastic or oblique comments.
DEFAULT_MAP_MODEL = "claude-opus-5"
DEFAULT_REDUCE_MODEL = "claude-opus-5"


def get_map_model() -> str:
    return _env("NICHE_MAP_MODEL") or DEFAULT_MAP_MODEL


def get_reduce_model() -> str:
    return _env("NICHE_REDUCE_MODEL") or DEFAULT_REDUCE_MODEL


def use_batch_api() -> bool:
    """Whether to route the map pass through the Batches API (50% cheaper).

    Off by default because batches can take up to 24 hours; worth enabling for
    large niche studies where latency does not matter.
    """
    return (os.getenv("NICHE_USE_BATCH_API", "").strip().lower()) in {"1", "true", "yes"}


def get_batch_size() -> int:
    """Comments per map-pass request."""
    try:
        return max(5, min(200, int(os.getenv("NICHE_BATCH_SIZE", "50"))))
    except ValueError:
        return 50


def get_max_concurrency() -> int:
    """Parallel in-flight map requests when not using the Batches API."""
    try:
        return max(1, min(16, int(os.getenv("NICHE_CONCURRENCY", "4"))))
    except ValueError:
        return 4
