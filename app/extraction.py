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

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import anthropic

from .config import (
    DEFAULT_MAP_MODEL,
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


class BatchFailed(ExtractionError):
    """One request came back unusable: refused, cut off, unparseable, or a server error.

    Unlike a bad key or an unknown model, this only affects the one batch, so
    the passes skip it and carry on instead of throwing away the whole study.
    """


# Per-million-token prices (input, output, cache read), used only for the cost
# estimate shown in reports. Cache writes bill at 1.25x input.
_PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50),
    "claude-fable-5-2": (8.0, 40.0, 0.20),
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.00),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-sonnet-4-6": (3.0, 15.0, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
}

# Models that take server-side fallbacks. If a safety classifier declines a
# batch (comment sections trip them on ordinary text now and then), the API
# re-runs it on another model instead of returning a refusal. Not available on
# the Batches API.
_FALLBACK_MODELS = {
    "claude-opus-5-5", "claude-opus-5", "claude-fable-5-2", "claude-fable-5-1", "claude-sonnet-5-5",
}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

_MAX_COMMENT_CHARS = 600
MAX_REDUCE_CANDIDATES = 400


@dataclass
class UsageMeter:
    """Accumulates token spend so a study can report what it cost to produce."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    requests: int = 0
    failed_requests: int = 0
    batched: bool = False
    cost_usd: float = 0.0
    per_model: dict[str, list[int]] = field(default_factory=dict)
    # The map and reduce passes both report from worker threads.
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add(self, model: str, usage, batched: bool = False) -> None:
        fresh = getattr(usage, "input_tokens", 0) or 0
        written = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cached = getattr(usage, "cache_read_input_tokens", 0) or 0
        out = getattr(usage, "output_tokens", 0) or 0

        price_in, price_out, price_cached = _PRICES.get(model, _PRICES[DEFAULT_MAP_MODEL])
        cost = (
            fresh * price_in + written * price_in * 1.25 + cached * price_cached + out * price_out
        ) / 1_000_000
        if batched:
            cost *= 0.5  # the Batches API bills at half price

        with self._lock:
            self.input_tokens += fresh + written + cached
            self.output_tokens += out
            self.cache_read_tokens += cached
            self.requests += 1
            self.batched = self.batched or batched
            self.cost_usd += cost
            slot = self.per_model.setdefault(model, [0, 0])
            slot[0] += fresh + written + cached
            slot[1] += out

    def record_failures(self, count: int) -> None:
        with self._lock:
            self.failed_requests += count

    def as_dict(self) -> dict:
        return {
            "requests": self.requests,
            "failed_requests": self.failed_requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "batched": self.batched,
            "estimated_cost_usd": round(self.cost_usd, 4),
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
`product` is "" unless a product is named.
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


def _client() -> anthropic.Anthropic:
    key = get_anthropic_key()
    try:
        # A bare constructor also picks up an `ant auth login` profile, so only
        # pass the key when we actually have one.
        return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
    except Exception as exc:
        raise ExtractionError(f"Could not set up the Anthropic client: {exc}") from exc


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
    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason == "refusal":
        raise BatchFailed("The model declined to process this batch of comments.")
    if stop_reason == "max_tokens":
        raise BatchFailed(
            "The model hit its output limit before finishing. Lower NICHE_BATCH_SIZE."
        )
    # After a fallback the content can hold a `fallback` marker between two text
    # blocks (a stream that switched models mid-answer keeps what it had), so
    # join every text block instead of taking the first.
    text = "".join(block.text for block in message.content if block.type == "text")
    if not text:
        raise BatchFailed("The model returned no text content.")
    return text


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


def _complete(client, params: dict, usage: UsageMeter, stream: bool = False) -> str:
    params = dict(params)
    if params["model"] in _FALLBACK_MODELS:
        params["betas"] = [_FALLBACK_BETA]
        params["fallbacks"] = "default"

    try:
        if stream:
            with client.beta.messages.stream(**params) as streamed:
                message = streamed.get_final_message()
        else:
            message = client.beta.messages.create(**params)
    except anthropic.AuthenticationError as exc:
        raise ExtractionError("The Anthropic API rejected the key. Check ANTHROPIC_API_KEY.") from exc
    except anthropic.RateLimitError as exc:
        raise ExtractionError(
            "Rate limited by the Anthropic API. Lower NICHE_CONCURRENCY or try again shortly."
        ) from exc
    except anthropic.APIStatusError as exc:
        # The SDK has already retried a 5xx, so what reaches here is one unlucky
        # request. The code is tested rather than the class, since 500, 503, 504
        # and 529 each have their own. An overload that arrives mid-stream comes
        # with the stream's 200, so the error type in the body counts too.
        detail = exc.body.get("error") if isinstance(exc.body, dict) else None
        kind = detail.get("type") if isinstance(detail, dict) else None
        server_side = exc.status_code >= 500 or kind in ("overloaded_error", "api_error")
        error = BatchFailed if server_side else ExtractionError
        raise error(f"Anthropic API error ({exc.status_code}): {exc.message}") from exc
    except anthropic.APITimeoutError as exc:  # a subclass of APIConnectionError
        raise BatchFailed(f"The Anthropic API timed out: {exc}") from exc
    except anthropic.APIConnectionError as exc:
        raise ExtractionError(f"Could not reach the Anthropic API: {exc}") from exc
    except TypeError as exc:
        # The SDK raises this when no key, token or profile is available.
        if "authentication" not in str(exc):
            raise
        raise ExtractionError(
            "No Anthropic credentials found. Set ANTHROPIC_API_KEY in .env, or run `ant auth login`."
        ) from exc

    # After a fallback, `model` names the model that actually answered.
    usage.add(getattr(message, "model", None) or params["model"], message.usage)
    return _text_of(message)


def _parse_map(raw: str) -> MapResult:
    try:
        return MapResult.model_validate_json(raw)
    except Exception as exc:
        raise BatchFailed(f"Could not parse extraction output: {exc}") from exc


def _map_sync(client, batches: list[tuple[list[Comment], str]], usage: UsageMeter,
              progress=None):
    schema = strict_schema(MapResult)
    model = get_map_model()

    def run(job):
        comments, context = job
        params = _request_params(
            model, MAP_SYSTEM, _render_batch(comments, context), schema,
            max_tokens=12000, effort="low",
        )
        try:
            return comments, _parse_map(_complete(client, params, usage))
        except BatchFailed as exc:
            return comments, exc

    results: list[tuple[list[Comment], MapResult]] = []
    failures: list[BatchFailed] = []
    workers = min(get_max_concurrency(), max(1, len(batches)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run, batch) for batch in batches]
        try:
            for done, future in enumerate(futures, start=1):
                comments, outcome = future.result()
                if isinstance(outcome, BatchFailed):
                    failures.append(outcome)
                else:
                    results.append((comments, outcome))
                if progress:
                    progress(done, len(batches))
        except BaseException:
            # A bad key or model fails every batch the same way; stop sending them.
            pool.shutdown(cancel_futures=True)
            raise
    return results, failures


def _map_batched(client, batches: list[tuple[list[Comment], str]], usage: UsageMeter,
                 progress=None):
    """Same work through the Batches API — half price, but not interactive."""
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    schema = strict_schema(MapResult)
    model = get_map_model()

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

    by_id: dict[str, MapResult] = {}
    failures: list[BatchFailed] = []
    try:
        batch = client.messages.batches.create(requests=requests)
        while True:
            batch = client.messages.batches.retrieve(batch.id)
            if batch.processing_status == "ended":
                break
            if progress:
                progress(batch.request_counts.succeeded, len(requests))
            time.sleep(15)

        for result in client.messages.batches.results(batch.id):
            if result.result.type != "succeeded":
                failures.append(BatchFailed(f"A batch request {result.result.type}."))
                continue
            message = result.result.message
            usage.add(message.model or model, message.usage, batched=True)
            try:
                by_id[result.custom_id] = _parse_map(_text_of(message))
            except BatchFailed as exc:
                failures.append(exc)
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"Batch extraction failed: {exc}") from exc

    # Results come back in arbitrary order — key by custom_id, never by position.
    results = [
        (comments, by_id[f"batch-{index}"])
        for index, (comments, _) in enumerate(batches)
        if f"batch-{index}" in by_id
    ]
    return results, failures


def run_map(
    jobs: list[tuple[list[Comment], str]],
    usage: UsageMeter,
    progress=None,
) -> list[tuple[list[Comment], MapResult]]:
    """Run the map pass over (comments, context) jobs, splitting into batches.

    Batches that come back refused, cut off, unparseable or with a server error
    (after the SDK's own retries) are skipped and counted in
    `usage.failed_requests`. The pass only fails outright when every
    batch does, or on an error that would hit all of them (bad key, bad model).
    """
    client = _client()
    size = get_batch_size()

    batches: list[tuple[list[Comment], str]] = []
    for comments, context in jobs:
        for start in range(0, len(comments), size):
            batches.append((comments[start : start + size], context))

    if not batches:
        return []
    runner = _map_batched if use_batch_api() else _map_sync
    results, failures = runner(client, batches, usage, progress)
    usage.record_failures(len(failures))
    if failures and not results:
        raise ExtractionError(f"Every extraction request failed. First error: {failures[0]}")
    return results


def run_reduce(kind: str, candidates: list[dict], usage: UsageMeter) -> ReduceResult:
    """Cluster pre-aggregated candidate summaries of one kind into themes."""
    if not candidates:
        return ReduceResult(themes=[])

    client = _client()
    head = candidates[:MAX_REDUCE_CANDIDATES]
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

    # Streamed because thinking counts toward max_tokens and a long non-streaming
    # request risks an HTTP timeout.
    params = _request_params(
        get_reduce_model(), REDUCE_SYSTEM, "\n".join(lines),
        strict_schema(ReduceResult), max_tokens=64000, effort="high",
    )
    raw = _complete(client, params, usage, stream=True)
    try:
        return ReduceResult.model_validate_json(raw)
    except Exception as exc:
        raise BatchFailed(f"Could not parse clustering output: {exc}") from exc
