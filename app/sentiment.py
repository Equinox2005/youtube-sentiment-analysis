"""Sentiment engine built on VADER, tuned for YouTube comment language.

VADER is purpose-built for social-media text: it understands negation,
intensifiers, ALL-CAPS emphasis, punctuation (!!!), emoji, and slang.
This is far more accurate for YouTube comments than a bag-of-words
Naive Bayes trained on 2009-era tweets, and it needs no dataset download.
"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Extra lexicon entries for YouTube-specific slang the base lexicon misses.
YOUTUBE_LEXICON = {
    "goat": 3.0,
    "goated": 3.2,
    "fire": 2.4,
    "banger": 2.6,
    "slaps": 2.4,
    "mid": -1.5,
    "cringe": -2.2,
    "clickbait": -2.0,
    "underrated": 1.8,
    "overrated": -1.6,
    "w": 1.5,
    "l": -1.5,
    "goosebumps": 2.0,
    "masterpiece": 3.2,
    "trash": -2.5,
    "scam": -2.8,
    "legend": 2.5,
    "iconic": 2.3,
    "unwatchable": -2.8,
    "clickbaity": -2.0,
}

_URL_RE = re.compile(r"https?://\S+")
_TIMESTAMP_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_WHITESPACE_RE = re.compile(r"\s+")

# Thresholds follow the VADER paper's recommendation.
POS_THRESHOLD = 0.05
NEG_THRESHOLD = -0.05


@lru_cache(maxsize=1)
def get_analyzer() -> SentimentIntensityAnalyzer:
    analyzer = SentimentIntensityAnalyzer()
    analyzer.lexicon.update(YOUTUBE_LEXICON)
    return analyzer


def clean_text(text: str) -> str:
    """Strip URLs and video timestamps that carry no sentiment."""
    text = _URL_RE.sub("", text)
    text = _TIMESTAMP_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def score_text(text: str) -> dict:
    """Return VADER scores plus a discrete label for a piece of text."""
    cleaned = clean_text(text)
    scores = get_analyzer().polarity_scores(cleaned) if cleaned else {
        "neg": 0.0, "neu": 1.0, "pos": 0.0, "compound": 0.0
    }
    compound = scores["compound"]
    if compound >= POS_THRESHOLD:
        label = "positive"
    elif compound <= NEG_THRESHOLD:
        label = "negative"
    else:
        label = "neutral"
    return {"label": label, "compound": compound, **scores}


def score_long_text(text: str, chunk_size: int = 400) -> dict:
    """Score long text (e.g. a transcript) by averaging word-chunk scores.

    VADER saturates on very long inputs, so we average across chunks.
    """
    words = clean_text(text).split()
    if not words:
        return {"label": "unknown", "compound": 0.0, "neg": 0.0, "neu": 1.0, "pos": 0.0}

    chunks = [" ".join(words[i : i + chunk_size]) for i in range(0, len(words), chunk_size)]
    analyzer = get_analyzer()
    compounds = [analyzer.polarity_scores(chunk)["compound"] for chunk in chunks]
    avg = sum(compounds) / len(compounds)
    if avg >= POS_THRESHOLD:
        label = "positive"
    elif avg <= NEG_THRESHOLD:
        label = "negative"
    else:
        label = "neutral"
    return {"label": label, "compound": round(avg, 4), "chunks": len(chunks)}


STOPWORDS = frozenset(
    """a about after again all also am an and any are as at be because been before being
    but by can could did do does doing down during each few for from further had has have
    having he her here hers him his how i if in into is it its itself just like me more
    most my no nor not now of off on once only or other our out over own same she so some
    such than that the their them then there these they this those through to too under
    until up very was we were what when where which while who whom why will with you your
    yours video videos youtube watch watching one get got really even much still way
    thing things going go know dont don't im i'm it's thats that's he's she's they're
    would make made see say said want us lol omg btw pls plz""".split()
)

_WORD_RE = re.compile(r"[a-zA-Z']{3,}")


def extract_keywords(texts: list[str], top_n: int = 20) -> list[dict]:
    """Most frequent meaningful words across texts."""
    counter: Counter[str] = Counter()
    for text in texts:
        words = {w.lower().strip("'") for w in _WORD_RE.findall(clean_text(text))}
        counter.update(w for w in words if w not in STOPWORDS and len(w) >= 3)
    return [{"word": word, "count": count} for word, count in counter.most_common(top_n)]
