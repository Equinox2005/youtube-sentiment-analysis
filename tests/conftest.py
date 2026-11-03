"""Shared fixtures: no real keys, and a way to swap in the fake Anthropic client."""

import pytest

from app import extraction

_ENV_VARS = (
    "YOUTUBE_API_KEY",
    "ANTHROPIC_API_KEY",
    "NICHE_MAP_MODEL",
    "NICHE_REDUCE_MODEL",
    "NICHE_USE_BATCH_API",
    "NICHE_BATCH_SIZE",
    "NICHE_CONCURRENCY",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Tests never see real keys or tuning, whatever is in the shell or .env."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def use_client(monkeypatch):
    """Install a fake Anthropic client: `use_client(fake_anthropic(...))`."""

    def install(client):
        monkeypatch.setattr(extraction, "_client", lambda: client)
        return client

    return install
