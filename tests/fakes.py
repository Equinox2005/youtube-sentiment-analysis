"""A fake Anthropic client that plays the map and reduce passes from the prompt."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

from app import extraction


def make_message(text="", stop_reason="end_turn", model="claude-opus-5-5", blocks=None,
                 input_tokens=100, output_tokens=20, cache_read=0):
    content = blocks if blocks is not None else [SimpleNamespace(type="text", text=text)]
    usage = SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=0,
    )
    return SimpleNamespace(content=content, stop_reason=stop_reason, model=model, usage=usage)


class _Stream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._message


class FakeMessages:
    """Stands in for `client.beta.messages`; `respond(params)` builds each reply."""

    def __init__(self, respond):
        self._respond = respond
        self.calls: list[dict] = []

    def create(self, **params):
        self.calls.append(params)
        return self._respond(params)

    def stream(self, **params):
        self.calls.append(params)
        return _Stream(self._respond(params))


class FakeClient:
    def __init__(self, respond):
        self.beta = SimpleNamespace(messages=FakeMessages(respond))

    @property
    def calls(self) -> list[dict]:
        return self.beta.messages.calls


_COMMENT_LINE = re.compile(r"^\[(\d+)\] \(likes \d+(?:, replies \d+)?\) (.*)$")
_CANDIDATE_LINE = re.compile(r"^\[(\d+)\] \(comments \d+, likes \d+\) (.*)$")


def map_reply(params) -> dict:
    """Pretend to be the map pass by reading the numbered comments back out.

    Test comments spell out what to extract:
      "kind|summary|quote"                    one item
      "product_mention|summary|quote|name|stance"
      "spam:<anything above>"                 flagged as spam (items still returned)
      "signal:<trust>"                        a trust signal
      "vocab:<term>"                          an audience term
    Anything else extracts nothing, like most real comments.
    """
    result = {"items": [], "spam_indices": [], "signals": [], "vocabulary": []}
    for line in params["messages"][0]["content"].splitlines():
        match = _COMMENT_LINE.match(line)
        if not match:
            continue
        index, text = int(match.group(1)), match.group(2)
        if text.startswith("spam:"):
            result["spam_indices"].append(index)
            text = text[len("spam:"):]
        if text.startswith("signal:"):
            result["signals"].append({"comment_index": index, "trust": text[len("signal:"):]})
        elif text.startswith("vocab:"):
            result["vocabulary"].append(text[len("vocab:"):])
        elif "|" in text:
            kind, summary, quote, *rest = text.split("|")
            product, stance = rest if rest else ("", "none")
            result["items"].append({
                "comment_index": index, "kind": kind, "summary": summary, "quote": quote,
                "product": product, "stance": stance,
            })
    return result


def reduce_reply(params) -> dict:
    """Pretend to be the reduce pass: one theme per kind, named after its top candidate."""
    candidates = []
    for line in params["messages"][0]["content"].splitlines():
        match = _CANDIDATE_LINE.match(line)
        if match:
            candidates.append((int(match.group(1)), match.group(2)))
    if not candidates:
        return {"themes": []}
    return {"themes": [{
        "title": candidates[0][1].capitalize(),
        "description": f"{len(candidates)} distinct statements.",
        "candidate_indices": [index for index, _ in candidates],
    }]}


def fake_anthropic(map_fn=map_reply, reduce_fn=reduce_reply) -> FakeClient:
    """A client whose map/reduce replies come from the two functions above.

    Either function may return a dict (sent back as JSON text) or a prepared
    message, e.g. a refusal; it may also raise to simulate an API error.
    """

    def respond(params):
        is_map = params["system"][0]["text"] == extraction.MAP_SYSTEM
        reply = (map_fn if is_map else reduce_fn)(params)
        return make_message(json.dumps(reply)) if isinstance(reply, dict) else reply

    return FakeClient(respond)
