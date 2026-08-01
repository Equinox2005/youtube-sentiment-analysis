"""The map-reduce extraction engine.

Map pass:    batches of raw comments  ->  structured items (requests, complaints,
             questions, confusions, corrections, product mentions)
Fold:        deterministic dedup + counting, done locally (no tokens spent)
Reduce pass: the head of each item kind -> named themes

Splitting it this way keeps the expensive model away from the raw firehose. The
map pass is mechanical and runs at low effort; the reduce pass sees only a few
hundred pre-aggregated strings and is where the actual judgment happens.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .config import (
    get_anthropic_key,
    get_batch_size,
    get_map_model,
    get_max_concurrency,
    get_reduce_model,
    use_batch_api,
)
from .schemas import MapResult, ReduceResult, strict_schema
from .youtube import Comment


class ExtractionError(Exception):
    """User-facing error while running the extraction passes."""


# Per-million-token prices, used only for the cost estimate shown in reports.
_PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

_MAX_COMMENT_CHARS = 600
_MAX_REDUCE_CANDIDATES = 400


@dataclass
class UsageMeter:
    """Accumulates token spend so a study can report what it cost to produce."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    requests: int = 0
    batched: bool = False
    per_model: dict[str, list[int]] = field(default_factory=dict)

    def add(self, model: str, usage) -> None:
        inp = getattr(usage, "input_tokens", 0) or 0
        out = getattr(usage, "output_tokens", 0) or 0
        cached = getattr(usage, "cache_read_input_tokens", 0) or 0
        created = getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.input_tokens += inp + cached + created
        self.output_tokens += out
        self.cache_read_tokens += cached
        self.requests += 1
        slot = self.per_model.setdefault(model, [0, 0])
        slot[0] += inp + cached + created
        slot[1] += out

    def estimated_cost_usd(self) -> float:
        total = 0.0
        for model, (inp, out) in self.per_model.items():
            price_in, price_out = _PRICES.get(model, (5.0, 25.0))
            total += inp / 1_000_000 * price_in + out / 1_000_000 * price_out
        return round(total * (0.5 if self.batched else 1.0), 4)

    def as_dict(self) -> dict:
        return {
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "batched": self.batched,
            "estimated_cost_usd": self.estimated_cost_usd(),
            "models": {m: {"input": i, "output": o} for m, (i, o) in self.per_model.items()},
        }


MAP_SYSTEM = """\
You extract research signal from YouTube comments for an audience-research tool.

You are NOT doing sentiment analysis. Nobody needs to know what percentage of \
comments were positive — on YouTube that number is always high and always \
useless. What matters is what the audience is actually telling the creator: \
what they want made, what they misunderstood, what they disputed, what annoyed \
them, and what products they talked about.

For each comment you are given, extract zero or more items. Most comments \
produce zero items, and that is the correct and expected outcome. Extract \
nothing from: timestamp-only comments, "who's watching in 2026", "first", \
in-jokes, emoji-only replies, generic praise with no specific object ("great \
video", "love this channel"), and anything addressed to another commenter \
rather than to the content.

Item kinds:
  request          wants coverage that does not exist yet ("do a video on X")
  question         asks something the video left unanswered
  complaint        something wrong with the content, product, or experience
  confusion        gets something wrong or finds it unclear — the teaching gap
  correction       disputes a specific factual claim made in the video
  praise           praise attached to a SPECIFIC thing that worked
  product_mention  names a product, brand, or tool

Reading the comments:
  * Sarcasm and irony are extremely common. "Great, another 10 minute ad" is a \
complaint about pacing and ad load, not praise. "This aged well" is almost \
always a correction or complaint. Read intent, not surface polarity.
  * A question phrased rhetorically to make a criticism is a complaint.
  * Slang carries real meaning: "mid" is lukewarm-negative, "goated"/"W" are \
strong positives, "L" is negative, "cope" signals disagreement.

Writing the `summary` field — this is the most important part:
  * It is a canonical restatement that will be deduplicated and clustered \
against thousands of others, so phrase it consistently.
  * Third person, present tense, no "I", "you", or "the commenter".
  * Lead with the subject, not the speaker. Write "grinder choice matters more \
than machine choice" — not "they think the grinder matters more".
  * Be specific enough to be actionable. "audio is quiet in the first few \
minutes" beats "audio problems".
  * Two comments making the same point must produce the same summary string \
wherever possible. Consistency here is worth more than elegance.
  * NEVER negate by omission. "recommends X over Y" and "recommends Y over X" \
are different summaries and must not collapse into each other.

`quote` is a short verbatim span from the comment (trim it, do not paraphrase).
`topic` is a one-to-three word tag. `product` is "" unless a product is named.
`stance` applies to product mentions; use "none" elsewhere.

Also return:
  spam_indices  indices of scam bots, engagement farming, crypto/"investment \
coach" spam, and sub-for-sub begging. Be strict — at corpus scale this pollutes \
every downstream theme.
  signals       only for comments showing a real trust signal; omit "none".
  vocabulary    distinctive terms this audience uses that an outsider would not \
know. Their words, not the video's. Skip generic English.

Indices refer to the numbered comments in the message. Use them exactly."""


REDUCE_SYSTEM = """\
You cluster pre-aggregated audience-research findings into named themes.

You receive numbered candidate statements. Each already carries a count of how \
many separate comments produced it, so frequent statements are load-bearing.

Group candidates that make substantively the same point into one theme. Then:
  * `title` is a short noun phrase a person would scan in a report. No preamble.
  * `description` is one or two sentences describing what this group of the \
audience actually wants or believes, written for the creator who has to act on \
it. Concrete, not hedged.
  * `candidate_indices` lists every candidate in the theme.

Rules:
  * Assign each candidate to at most one theme. Leave genuinely unrelated \
one-offs unassigned rather than forcing them into a theme.
  * NEVER merge opposing positions. "prefers manual over automatic" and \
"prefers automatic over manual" are two themes; collapsing them destroys the \
finding. The same goes for any A-over-B pair.
  * Prefer several specific themes over one broad one. "Grinder guidance is \
missing" and "Water chemistry is never explained" should not become "people \
want more technical depth".
  * Do not invent themes with no candidates, and do not restate a candidate \
verbatim as a theme unless it truly stands alone."""


def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ExtractionError(
            "The 'anthropic' package is required for extraction. Run: pip install anthropic"
        ) from exc

    key = get_anthropic_key()
    try:
        # A bare constructor also picks up an `ant auth login` profile, so only
        # pass the key when we actually have one.
        return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
    except Exception as exc:
        raise ExtractionError(
            "Could not initialise the Anthropic client. Set ANTHROPIC_API_KEY "
            "(or run `ant auth login`)."
        ) from exc


def _truncate(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_MAX_COMMENT_CHARS]


def _render_batch(comments: list[Comment], context: str) -> str:
    lines = [context, "", "Comments:"]
    for index, comment in enumerate(comments):
        meta = f"[{index}] (likes {comment.likes}"
        if comment.reply_count:
            meta += f", replies {comment.reply_count}"
        meta += ")"
        lines.append(f"{meta} {_truncate(comment.text)}")
    return "\n".join(lines)


def _text_of(message) -> str:
    if getattr(message, "stop_reason", None) == "refusal":
        raise ExtractionError(
            "The model declined to process this batch of comments. "
            "This usually means the content tripped a safety classifier; "
            "try a different video or a smaller sample."
        )
    for block in message.content:
        if block.type == "text":
            return block.text
    raise ExtractionError("The model returned no text content.")


def _request_params(model: str, system: str, user: str, schema: dict,
                    max_tokens: int, effort: str) -> dict:
    return {
        "model": model,
        "max_tokens": max_tokens,
        # Constant across every call in a pass, so cache it — the map pass alone
        # replays this prompt once per batch.
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
        "output_config": {
            "format": {"type": "json_schema", "schema": schema},
            "effort": effort,
        },
    }


def _complete(client, params: dict, usage: UsageMeter, stream: bool = False):
    try:
        if stream:
            with client.messages.stream(**params) as streamed:
                message = streamed.get_final_message()
        else:
            message = client.messages.create(**params)
    except Exception as exc:
        raise ExtractionError(f"Anthropic API error: {exc}") from exc

    usage.add(params["model"], message.usage)
    if getattr(message, "stop_reason", None) == "max_tokens":
        raise ExtractionError(
            "The model hit its output limit before finishing. Reduce the batch "
            "size (NICHE_BATCH_SIZE) and try again."
        )
    return _text_of(message)


# --------------------------------------------------------------------------
# Map pass
# --------------------------------------------------------------------------


def _parse_map(raw: str) -> MapResult:
    try:
        return MapResult.model_validate_json(raw)
    except Exception:
        try:  # tolerate a stray wrapper if the schema was ever relaxed
            return MapResult.model_validate(json.loads(raw))
        except Exception as exc:
            raise ExtractionError(f"Could not parse extraction output: {exc}") from exc


def _map_sync(client, batches: list[tuple[list[Comment], str]], usage: UsageMeter,
              progress=None) -> list[tuple[list[Comment], MapResult]]:
    schema = strict_schema(MapResult)
    model = get_map_model()

    def run(job):
        comments, context = job
        params = _request_params(
            model, MAP_SYSTEM, _render_batch(comments, context), schema,
            max_tokens=12000, effort="low",
        )
        return comments, _parse_map(_complete(client, params, usage))

    results: list[tuple[list[Comment], MapResult]] = []
    workers = min(get_max_concurrency(), max(1, len(batches)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, outcome in enumerate(pool.map(run, batches), start=1):
            results.append(outcome)
            if progress:
                progress(done, len(batches))
    return results


def _map_batched(client, batches: list[tuple[list[Comment], str]], usage: UsageMeter,
                 progress=None) -> list[tuple[list[Comment], MapResult]]:
    """Same work through the Batches API — half price, but not interactive."""
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    schema = strict_schema(MapResult)
    model = get_map_model()
    usage.batched = True

    requests = [
        Request(
            custom_id=f"batch-{index}",
            params=MessageCreateParamsNonStreaming(
                **_request_params(
                    model, MAP_SYSTEM, _render_batch(comments, context), schema,
                    max_tokens=12000, effort="low",
                )
            ),
        )
        for index, (comments, context) in enumerate(batches)
    ]

    try:
        batch = client.messages.batches.create(requests=requests)
        while True:
            batch = client.messages.batches.retrieve(batch.id)
            if batch.processing_status == "ended":
                break
            if progress:
                progress(batch.request_counts.succeeded, len(requests))
            time.sleep(15)

        by_id: dict[str, MapResult] = {}
        for result in client.messages.batches.results(batch.id):
            if result.result.type != "succeeded":
                continue
            message = result.result.message
            usage.add(model, message.usage)
            by_id[result.custom_id] = _parse_map(_text_of(message))
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"Batch extraction failed: {exc}") from exc

    # Results come back in arbitrary order — key by custom_id, never by position.
    return [
        (comments, by_id[f"batch-{index}"])
        for index, (comments, _) in enumerate(batches)
        if f"batch-{index}" in by_id
    ]


def run_map(
    jobs: list[tuple[list[Comment], str]],
    usage: UsageMeter,
    progress=None,
) -> list[tuple[list[Comment], MapResult]]:
    """Run the map pass over (comments, context) jobs, splitting into batches."""
    client = _client()
    size = get_batch_size()

    batches: list[tuple[list[Comment], str]] = []
    for comments, context in jobs:
        for start in range(0, len(comments), size):
            batches.append((comments[start : start + size], context))

    if not batches:
        return []
    runner = _map_batched if use_batch_api() else _map_sync
    return runner(client, batches, usage, progress)


# --------------------------------------------------------------------------
# Reduce pass
# --------------------------------------------------------------------------


def run_reduce(kind: str, candidates: list[dict], usage: UsageMeter) -> ReduceResult:
    """Cluster pre-aggregated candidate summaries of one kind into themes."""
    if not candidates:
        return ReduceResult(themes=[])

    client = _client()
    head = candidates[:_MAX_REDUCE_CANDIDATES]
    lines = [
        f"Item kind: {kind}",
        f"{len(head)} candidate statements, each with the number of distinct "
        f"comments that produced it and their combined likes.",
        "",
    ]
    for index, candidate in enumerate(head):
        lines.append(
            f"[{index}] (comments {candidate['count']}, likes {candidate['likes']}) "
            f"{candidate['summary']}"
        )

    params = _request_params(
        get_reduce_model(), REDUCE_SYSTEM, "\n".join(lines),
        strict_schema(ReduceResult), max_tokens=32000, effort="high",
    )
    raw = _complete(client, params, usage, stream=True)
    try:
        return ReduceResult.model_validate_json(raw)
    except Exception as exc:
        raise ExtractionError(f"Could not parse clustering output: {exc}") from exc
