import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from fakes import fake_anthropic, make_message, map_reply

from app import extraction
from app.extraction import BatchFailed, ExtractionError, UsageMeter, run_map, run_reduce
from app.youtube import Comment


def _usage(fresh=0, written=0, cached=0, out=0):
    return SimpleNamespace(
        input_tokens=fresh,
        cache_creation_input_tokens=written,
        cache_read_input_tokens=cached,
        output_tokens=out,
    )


def _jobs(count, context="Video: test"):
    comments = [Comment(text=f"request|ask number {i}|q{i}", video_id="v1") for i in range(count)]
    return [(comments, context)]


def test_usage_meter_prices_each_kind_of_token():
    meter = UsageMeter()
    meter.add("claude-opus-5-5", _usage(fresh=1_000_000))  # $4
    meter.add("claude-opus-5-5", _usage(written=1_000_000))  # $5 (1.25x input)
    meter.add("claude-opus-5-5", _usage(cached=1_000_000))  # $0.20
    meter.add("claude-opus-5-5", _usage(out=1_000_000))  # $20
    assert meter.as_dict()["estimated_cost_usd"] == pytest.approx(29.20)
    assert meter.as_dict()["input_tokens"] == 3_000_000
    assert meter.requests == 4


def test_usage_meter_halves_only_batched_requests():
    meter = UsageMeter()
    meter.add("claude-opus-5-5", _usage(out=1_000_000), batched=True)  # $10
    meter.add("claude-opus-5-5", _usage(out=1_000_000))  # $20
    assert meter.as_dict()["estimated_cost_usd"] == pytest.approx(30.0)
    assert meter.batched is True


def test_text_is_joined_across_a_fallback_marker():
    message = make_message(blocks=[
        SimpleNamespace(type="text", text='{"themes": '),
        SimpleNamespace(type="fallback"),
        SimpleNamespace(type="text", text="[]}"),
    ])
    assert extraction._text_of(message) == '{"themes": []}'


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_unusable_replies_raise_batch_failed(stop_reason):
    with pytest.raises(BatchFailed):
        extraction._text_of(make_message("{}", stop_reason=stop_reason))


def test_fallbacks_are_requested_only_for_models_that_support_them(monkeypatch, use_client):
    client = use_client(fake_anthropic())
    run_map(_jobs(3), UsageMeter())
    assert client.calls[0]["fallbacks"] == "default"
    assert client.calls[0]["betas"] == ["server-side-fallback-2026-07-01"]

    monkeypatch.setenv("NICHE_MAP_MODEL", "claude-haiku-5-5")
    client = use_client(fake_anthropic())
    run_map(_jobs(3), UsageMeter())
    assert "fallbacks" not in client.calls[0]
    assert "betas" not in client.calls[0]


def test_map_requests_use_structured_output_and_low_effort(use_client):
    client = use_client(fake_anthropic())
    run_map(_jobs(3), UsageMeter())
    params = client.calls[0]
    assert params["output_config"]["effort"] == "low"
    assert params["output_config"]["format"]["type"] == "json_schema"
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_map_splits_jobs_into_batches(monkeypatch, use_client):
    monkeypatch.setenv("NICHE_BATCH_SIZE", "5")
    client = use_client(fake_anthropic())
    progress = []
    results = run_map(_jobs(12), UsageMeter(), progress=lambda done, total: progress.append((done, total)))
    assert [len(comments) for comments, _ in results] == [5, 5, 2]
    assert sum(len(result.items) for _, result in results) == 12
    assert progress[-1] == (3, 3)
    assert len(client.calls) == 3


def test_map_skips_a_refused_batch_and_keeps_the_rest(monkeypatch, use_client):
    monkeypatch.setenv("NICHE_BATCH_SIZE", "5")

    def refuse_second_batch(params):
        if "ask number 5" in params["messages"][0]["content"]:
            return make_message("", stop_reason="refusal")
        return map_reply(params)

    use_client(fake_anthropic(map_fn=refuse_second_batch))
    usage = UsageMeter()
    results = run_map(_jobs(15), usage)
    assert len(results) == 2
    assert usage.failed_requests == 1


def test_map_fails_when_every_batch_fails(use_client):
    use_client(fake_anthropic(map_fn=lambda params: make_message("not json")))
    with pytest.raises(ExtractionError, match="Every extraction request failed"):
        run_map(_jobs(3), UsageMeter())


def test_a_rejected_key_stops_the_pass_early(monkeypatch, use_client):
    monkeypatch.setenv("NICHE_BATCH_SIZE", "5")
    monkeypatch.setenv("NICHE_CONCURRENCY", "1")
    response = httpx2.Response(401, request=httpx2.Request("POST", "https://api.anthropic.com"))

    def reject(params):
        raise anthropic.AuthenticationError("invalid key", response=response, body=None)

    client = use_client(fake_anthropic(map_fn=reject))
    with pytest.raises(ExtractionError, match="rejected the key"):
        run_map(_jobs(100), UsageMeter())  # 20 batches
    assert len(client.calls) < 20


def test_missing_credentials_get_a_clear_message(use_client):
    def no_credentials(params):
        raise TypeError("Could not resolve authentication method. Expected one of api_key, ...")

    use_client(fake_anthropic(map_fn=no_credentials))
    with pytest.raises(ExtractionError, match="ANTHROPIC_API_KEY"):
        run_map(_jobs(3), UsageMeter())


def test_reduce_streams_and_parses_themes(use_client):
    client = use_client(fake_anthropic())
    candidates = [
        {"summary": "grinder guide", "count": 3, "likes": 10},
        {"summary": "water guide", "count": 1, "likes": 0},
    ]
    result = run_reduce("request", candidates, UsageMeter())
    assert result.themes[0].title == "Grinder guide"
    assert result.themes[0].candidate_indices == [0, 1]
    assert client.calls[0]["output_config"]["effort"] == "high"


class _FakeBatches:
    """Just enough of `client.messages.batches` for the Batches API path."""

    def __init__(self, replies):
        self._replies = replies  # custom_id -> message, or a result type string
        self.created = None

    def create(self, requests):
        self.created = requests
        return SimpleNamespace(id="batch_1")

    def retrieve(self, batch_id):
        return SimpleNamespace(id=batch_id, processing_status="ended")

    def results(self, batch_id):
        # Deliberately out of order: callers must key by custom_id.
        for custom_id, reply in reversed(list(self._replies.items())):
            if isinstance(reply, str):
                yield SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(type=reply))
            else:
                yield SimpleNamespace(
                    custom_id=custom_id,
                    result=SimpleNamespace(type="succeeded", message=reply),
                )


def test_batches_api_path_keys_results_by_custom_id(monkeypatch, use_client):
    monkeypatch.setenv("NICHE_USE_BATCH_API", "true")
    monkeypatch.setenv("NICHE_BATCH_SIZE", "5")
    comments = [Comment(text=f"request|ask {i}|q{i}", video_id="v1") for i in range(20)]

    def reply_for(batch):
        params = {"messages": [{"content": extraction._render_batch(batch, "ctx")}]}
        return make_message(json.dumps(map_reply(params)))

    batches = _FakeBatches({
        "batch-0": reply_for(comments[0:5]),
        "batch-1": "errored",
        "batch-2": make_message("", stop_reason="refusal"),
        "batch-3": reply_for(comments[15:20]),
    })
    client = fake_anthropic()
    client.messages = SimpleNamespace(batches=batches)
    use_client(client)

    usage = UsageMeter()
    results = run_map([(comments, "ctx")], usage)
    assert [batch[0].text for batch, _ in results] == ["request|ask 0|q0", "request|ask 15|q15"]
    assert [item.summary for _, result in results for item in result.items] == [
        f"ask {i}" for i in (*range(0, 5), *range(15, 20))
    ]
    assert usage.failed_requests == 2
    assert usage.batched is True
    # The Batches API rejects the fallbacks parameter, so it must never be sent there.
    assert all("fallbacks" not in request["params"] for request in batches.created)
