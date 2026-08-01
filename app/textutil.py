"""Small text helpers shared by the analysis modules."""

from __future__ import annotations

import re

_URL_RE = re.compile(r"https?://\S+")
_TIMESTAMP_RE = re.compile(r"\b(\d{1,2}):([0-5]\d)(?::([0-5]\d))?\b")
_WHITESPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z'\-]{2,}")

STOPWORDS = frozenset(
    """a about after again all also am an and any are as at be because been before being
    but by can could did do does doing done down during each few for from further had has
    have having he her here hers him his how i if in into is it its itself just like me
    more most my no nor not now of off on once only or other our out over own same she so
    some such than that the their them then there these they this those through to too
    under until up very was we were what when where which while who whom why will with you
    your yours video videos youtube watch watching one get got really even much still way
    thing things going go know dont im it's thats he's she's they're would make made see
    say said want us lol omg btw pls plz guys guy people would could should really
    actually basically literally definitely probably maybe thanks thank please
    make making makes need needs needed use used using""".split()
)


def clean_text(text: str) -> str:
    """Strip URLs and collapse whitespace."""
    text = _URL_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def tokens(text: str) -> list[str]:
    """Lowercased content words, stopwords removed."""
    return [
        word
        for word in (match.group(0).lower().strip("'-") for match in _WORD_RE.finditer(text))
        if len(word) >= 3 and word not in STOPWORDS
    ]


def token_set(text: str) -> set[str]:
    return set(tokens(text))


def normalize_summary(text: str) -> str:
    """Key used to collapse identical extracted statements.

    Deliberately conservative — exact normalised string only. Token-sorting
    would merge 'prefers A over B' with 'prefers B over A', which are opposite
    findings, so it is not worth the extra recall.
    """
    text = _WHITESPACE_RE.sub(" ", text.lower()).strip()
    return text.rstrip(" .!?,;:")


def timestamp_seconds(text: str) -> list[int]:
    """Every video timestamp referenced in a comment, as seconds."""
    found: list[int] = []
    for match in _TIMESTAMP_RE.finditer(text):
        first, second, third = match.groups()
        if third is not None:
            found.append(int(first) * 3600 + int(second) * 60 + int(third))
        else:
            found.append(int(first) * 60 + int(second))
    return found


def month_of(published_at: str) -> str:
    """'2026-04-12T…' -> '2026-04'. Empty string when unparseable."""
    return published_at[:7] if len(published_at) >= 7 else ""


def format_timestamp(seconds: int) -> str:
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
