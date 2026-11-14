import json
from collections import Counter

import anthropic
import httpx2
import pytest
from fakes import fake_anthropic, make_message, reduce_reply

from app.extraction import ExtractionError, UsageMeter
from app.niche import (
    Corpus,
    Record,
    audience_overlap,
    build_study_report,
    build_themes,
    content_gaps,
    extract_records,
    fold_candidates,
    product_report,
    rising_themes,
    trust_report,
    vocabulary_report,
)
from app.youtube import Comment, QuotaMeter, VideoInfo


def _video(video_id, channel, title="", tags=()):
    return VideoInfo(video_id=video_id, title=title, channel=channel,
                     channel_id=f"UC_{channel}", tags=list(tags))


def _comment(text="", video_id="v1", author="", likes=0, published_at="2026-05-01T00:00:00Z"):
    return Comment(text=text, video_id=video_id, author=author, author_channel_id=author,
                   likes=likes, published_at=published_at)


def _record(summary, kind="request", likes=0, published_at="2026-05-01T00:00:00Z",
            product="", stance="none", video=None):
    return Record(kind=kind, summary=summary, quote=summary, product=product,
                  stance=stance, comment=_comment(likes=likes, published_at=published_at),
                  video=video)


def _theme(title, statements, count=5, likes=0):
    return {"title": title, "description": "", "statements": statements, "count": count,
            "likes": likes, "channel_spread": 1, "examples": []}


def test_fold_collapses_identical_statements_and_ranks_by_count():
    records = [
        _record("Grinder guide wanted.", likes=3),
        _record("grinder guide wanted", likes=1),
        _record("prefers manual over automatic"),
        _record("prefers automatic over manual"),
    ]
    folded = fold_candidates(records)["request"]
    assert folded[0]["count"] == 2
    assert folded[0]["likes"] == 4
    # Opposite positions stay apart.
    assert len(folded) == 3


def test_content_gaps_score_demand_against_existing_titles():
    themes = {
        "request": [_theme("Water chemistry guide", ["explain water chemistry minerals"], count=9)],
        "question": [_theme("Light roast dialling", ["dialling light roast"], count=20)],
    }
    videos = [_video("v1", "Purge", title="Dialling in light roast")]
    gaps = content_gaps(themes, videos)

    covered = next(gap for gap in gaps if gap["title"] == "Light roast dialling")
    assert covered["coverage"] == "covered"
    assert covered["gap_score"] == 0
    assert covered["closest_video"]["video_id"] == "v1"

    unserved = next(gap for gap in gaps if gap["title"] == "Water chemistry guide")
    assert unserved["coverage"] == "none"
    assert unserved["closest_video"] is None
    assert gaps[0] is unserved  # unmet demand outranks bigger but covered demand


def test_audience_overlap_measures_shared_commenters():
    videos = [_video("a", "A"), _video("b", "B"), _video("c", "C")]
    comments = (
        [_comment(video_id="a", author=f"a{i}") for i in range(30)]
        + [_comment(video_id="b", author=f"b{i}") for i in range(20)]
        + [_comment(video_id="b", author=f"a{i}") for i in range(10)]
        + [_comment(video_id="c", author=f"c{i}") for i in range(5)]  # too few to count
    )
    overlap = audience_overlap(Corpus(channels=[], videos=videos, comments=comments, quota=QuotaMeter()))

    assert [node["channel"] for node in overlap["nodes"]] == ["A", "B"]
    assert overlap["nodes"][0]["exclusive_pct"] == pytest.approx(66.7)
    (edge,) = overlap["edges"]
    assert edge["shared"] == 10
    assert edge["jaccard"] == pytest.approx(0.2)


def test_rising_themes_flags_recent_acceleration():
    old, new = "2026-01-10T00:00:00Z", "2026-05-20T00:00:00Z"
    comments = [_comment(published_at=old) for _ in range(10)] + [
        _comment(published_at=new) for _ in range(10)
    ]
    corpus = Corpus(channels=[], videos=[], comments=comments, quota=QuotaMeter())
    themes = {"request": [
        {"title": "Lever machines", "description": "", "count": 4, "channel_spread": 1,
         "examples": [], "_records": [_record("lever", published_at=new) for _ in range(4)]},
        {"title": "Steady topic", "description": "", "count": 4, "channel_spread": 1,
         "examples": [], "_records": [_record("steady", published_at=d) for d in (old, old, new, new)]},
    ]}
    rising = rising_themes(themes, corpus)
    assert [row["title"] for row in rising] == ["Lever machines"]
    assert rising[0]["lift"] == 2.0


def test_rising_themes_on_a_sample_shorter_than_ninety_days():
    def day(n):
        return f"2026-05-{n:02d}T00:00:00Z"

    comments = [_comment(published_at=day(n)) for n in range(1, 31) for _ in range(4)]
    corpus = Corpus(channels=[], videos=[], comments=comments, quota=QuotaMeter())

    def theme(title, days):
        return {"title": title, "description": "", "count": len(days), "channel_spread": 1,
                "examples": [], "_records": [_record(title, published_at=day(n)) for n in days]}

    themes = {"request": [theme("New this week", [27, 28, 29, 30]), theme("All month", [3, 10, 17, 24, 30])]}
    (row,) = rising_themes(themes, corpus)
    assert row["title"] == "New this week"
    assert row["window_days"] == 10
    assert row["lift"] == 3.0


def test_product_and_trust_reports():
    records = [
        _record("zero is great", kind="product_mention", product="Niche Zero", stance="recommends"),
        _record("zero again", kind="product_mention", product="niche zero", stance="recommends"),
        _record("zero bad", kind="product_mention", product="Niche Zero", stance="warns_against"),
    ]
    (row,) = product_report(records)
    assert row["mentions"] == 3
    assert row["net_stance"] == pytest.approx(0.333)

    signals = [
        {"trust": "purchase_intent", "channel": "Bench"},
        {"trust": "deference", "channel": "Bench"},
        {"trust": "sponsorship_skepticism", "channel": "Bench"},
    ]
    (trust,) = trust_report(signals)
    assert trust["total"] == 3
    assert trust["trust_ratio"] == pytest.approx(0.667)


def test_vocabulary_drops_terms_the_creators_already_use():
    videos = [_video("v1", "Bench", title="Puck prep basics", tags=["espresso"])]
    rows = vocabulary_report(Counter({"puck prep": 9, "channeling": 5, "espresso": 4}), videos)
    assert [row["term"] for row in rows] == ["channeling"]


def test_build_themes_skips_a_kind_whose_clustering_fails(use_client):
    def truncate_complaints(params):
        if "Item kind: complaint" in params["messages"][0]["content"]:
            return make_message("{", stop_reason="max_tokens")
        return reduce_reply(params)

    use_client(fake_anthropic(reduce_fn=truncate_complaints))
    candidates = fold_candidates([_record("grinder guide"), _record("audio too quiet", kind="complaint")])
    usage = UsageMeter()
    themes = build_themes(candidates, usage)
    assert set(themes) == {"request"}
    assert usage.failed_requests == 1


def test_build_themes_skips_a_kind_the_api_could_not_serve(use_client):
    def overload_complaints(params):
        if "Item kind: complaint" in params["messages"][0]["content"]:
            response = httpx2.Response(529, request=httpx2.Request("POST", "https://api.anthropic.com"))
            raise anthropic.OverloadedError("overloaded", response=response, body=None)
        return reduce_reply(params)

    use_client(fake_anthropic(reduce_fn=overload_complaints))
    candidates = fold_candidates([_record("grinder guide"), _record("audio too quiet", kind="complaint")])
    usage = UsageMeter()
    themes = build_themes(candidates, usage)
    assert set(themes) == {"request"}
    assert usage.failed_requests == 1


def test_build_themes_counts_a_repeated_candidate_once(use_client):
    def repeats(params):
        return {"themes": [{"title": "A", "description": "", "candidate_indices": [0, 0, 1]},
                           {"title": "B", "description": "", "candidate_indices": [0]}]}

    use_client(fake_anthropic(reduce_fn=repeats))
    records = [_record("grinder guide"), _record("grinder guide"), _record("water guide")]
    themes = build_themes(fold_candidates(records), UsageMeter())["request"]
    assert [(theme["title"], theme["count"]) for theme in themes] == [("A", 3)]


def test_spam_comments_carry_no_trust_signal(use_client):
    use_client(fake_anthropic())
    corpus = Corpus(channels=[], videos=[_video("v1", "Bench")], quota=QuotaMeter(), comments=[
        _comment("signal:deference", "v1", "ann"),
        _comment("spam:signal:purchase_intent", "v1", "bot"),
    ])
    _, spam_keys, _, signals = extract_records(corpus, UsageMeter())
    assert len(spam_keys) == 1
    (row,) = trust_report(signals)
    assert (row["deference"], row["purchase_intent"]) == (1, 0)


def test_build_themes_fails_when_every_kind_fails(use_client):
    use_client(fake_anthropic(reduce_fn=lambda params: make_message("", stop_reason="refusal")))
    with pytest.raises(ExtractionError, match="every item kind"):
        build_themes(fold_candidates([_record("grinder guide")]), UsageMeter())


def test_study_report_end_to_end(use_client):
    client = use_client(fake_anthropic())
    videos = [
        _video("v1", "Bench", title="Best espresso machines under $1000"),
        _video("v2", "Purge", title="Dialling in light roast"),
    ]
    comments = [
        _comment("request|grinder-first buying guide|do a grinder guide", "v1", "ann", likes=10),
        _comment("request|Grinder-first buying guide.|grinder first please", "v2", "bob", likes=4),
        _comment("question|why is my light roast sour|sour shots?", "v2", "cat"),
        _comment("spam:request|crypto coaching|dm me", "v1", "bot"),
        _comment("product_mention|zero is worth it|the zero|Niche Zero|recommends", "v1", "dan"),
        _comment("signal:purchase_intent", "v1", "eve"),
        _comment("vocab:puck prep", "v2", "fay"),
        _comment("first!", "v1", "gus"),
    ]
    corpus = Corpus(channels=[], videos=videos, comments=comments, quota=QuotaMeter())
    stages = set()
    report = build_study_report(corpus, UsageMeter(), label="Espresso",
                                progress=lambda stage, done, total: stages.add(stage))

    study = report["study"]
    assert study["comments_sampled"] == 8
    assert study["spam_filtered"] == 1
    assert study["items_extracted"] == 4  # the spam comment's item is dropped
    assert report["themes"]["request"][0]["count"] == 2
    assert report["themes"]["request"][0]["channel_spread"] == 2
    assert report["content_gaps"][0]["title"] == "Grinder-first buying guide"
    assert report["products"][0]["product"] == "Niche Zero"
    assert report["trust"][0]["purchase_intent"] == 1
    assert report["vocabulary"] == [{"term": "puck prep", "count": 1}]
    # One map call per video, then one clustering call per kind (request, question).
    assert report["usage"]["requests"] == len(client.calls) == 2 + 2
    assert stages == {"extract", "themes"}
    json.dumps(report)  # no internal back-references left in the output


def test_videos_sampled_counts_only_videos_that_gave_comments(use_client):
    use_client(fake_anthropic())
    videos = [_video("v1", "Bench", title="A"), _video("v2", "Bench", title="B")]
    corpus = Corpus(channels=[], videos=videos, quota=QuotaMeter(),
                    comments=[_comment("request|grinder guide|do a grinder guide", "v1", "ann")])
    assert build_study_report(corpus, UsageMeter())["study"]["videos_sampled"] == 1
