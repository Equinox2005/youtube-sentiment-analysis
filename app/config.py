"""Configuration: loads the YouTube Data API key from environment or .env file."""

import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def get_api_key() -> str | None:
    """Return the YouTube Data API v3 key, or None if not configured."""
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    return key or None
