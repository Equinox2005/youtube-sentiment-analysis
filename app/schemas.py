"""Structured-output schemas for the extraction passes.

These are Pydantic models purely so the shapes stay readable and validated;
what actually goes over the wire is the JSON Schema produced by
`strict_schema()`, which the Claude API enforces during generation.

Schema rules the API cares about (see the structured-outputs docs):
  * every object needs `additionalProperties: false`
  * every property must be listed in `required`
  * no recursion, no numeric/string length constraints

So: no defaults on any field, and `strict_schema()` walks the generated schema
to tighten it before use.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

# What a single extracted item can be. These are the units that later cluster
# into themes, so they are deliberately narrow and non-overlapping.
ItemKind = Literal[
    "request",         # wants content/coverage that does not exist yet
    "question",        # asks something the video did not answer
    "complaint",       # something wrong with the content, product, or experience
    "confusion",       # misunderstands something — the teaching gap
    "correction",      # disputes a factual claim made in the video
    "praise",          # specific, attributable praise (not generic "great video")
    "product_mention",  # names a product/brand/tool
]

TrustSignal = Literal[
    "purchase_intent",          # acted or intends to act on a recommendation
    "sponsorship_skepticism",   # doubts the creator's independence
    "deference",                # treats the creator as the authority
    "expertise_challenge",      # claims more expertise than the creator
    "none",
]

Stance = Literal["recommends", "warns_against", "compares", "neutral", "none"]


class ExtractedItem(BaseModel):
    """One actionable unit pulled out of one comment."""

    comment_index: int
    kind: ItemKind
    # Canonical restatement, third person, no "I"/"you". This is the string that
    # gets deduplicated and clustered, so consistent phrasing matters more here
    # than fidelity to the original wording.
    summary: str
    quote: str
    topic: str
    product: str   # "" unless kind is product_mention or a product is named
    stance: Stance


class CommentSignal(BaseModel):
    comment_index: int
    trust: TrustSignal


class MapResult(BaseModel):
    """Output of one map-pass request over a batch of comments."""

    items: list[ExtractedItem]
    spam_indices: list[int]
    signals: list[CommentSignal]
    vocabulary: list[str]


class ThemeOut(BaseModel):
    title: str
    description: str
    candidate_indices: list[int]


class ReduceResult(BaseModel):
    """Output of one reduce-pass request: clustered themes for a single kind."""

    themes: list[ThemeOut]


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return a JSON Schema for `model` that satisfies the strict-output rules."""
    schema = model.model_json_schema()
    _tighten(schema)
    return schema


def _tighten(node: Any) -> None:
    """Recursively force additionalProperties:false and required-on-everything."""
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            node["additionalProperties"] = False
            properties = node.get("properties")
            if isinstance(properties, dict) and properties:
                node["required"] = list(properties.keys())
        # Constraints the API rejects; harmless to drop since we validate locally.
        for unsupported in ("minLength", "maxLength", "minimum", "maximum", "multipleOf",
                            "minItems", "maxItems", "pattern", "default"):
            node.pop(unsupported, None)
        for value in node.values():
            _tighten(value)
    elif isinstance(node, list):
        for value in node:
            _tighten(value)
