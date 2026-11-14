"""Cross-channel niche studies: corpus building and the analytics on top of it.

The unit of analysis here is a niche, not a video. A study pulls the recent
catalogue of several channels, samples comments across all of them, extracts
structured items, and then answers four questions:

  * what does this audience keep asking for that nobody has published?
  * whose audiences overlap, and who owns an exclusive slice?
  * which products does the audience actually talk about, and how?
  * what is changing month over month?
"""

from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .extraction import (
    MAX_REDUCE_CANDIDATES,
    BatchFailed,
    ExtractionError,
    UsageMeter,
    run_map,
    run_reduce,
)
from .textutil import month_of, normalize_summary, token_set, tokens
from .youtube import (
    Comment,
    QuotaExceeded,
    QuotaMeter,
    VideoInfo,
    YouTubeError,
    fetch_channel_video_ids,
    fetch_comments,
    fetch_videos_info,
    resolve_channels,
)

# Kinds that get clustered into themes. product_mention is aggregated by product
# name instead, and praise is clustered but reported separately from the gaps.
THEME_KINDS = ["request", "question", "complaint", "confusion", "correction", "praise"]

DEMAND_KINDS = ("request", "question", "confusion")
RECENT_WINDOW_DAYS = 90
MIN_COMMENTERS_FOR_OVERLAP = 20

CAVEATS = [
    "Commenters are not viewers. Only a small share of viewers ever comment, "
    "and those who do skew engaged and opinionated. Treat every count here as a "
    "signal of intensity among the vocal minority, not a measure of the audience.",
    "Comment sampling is capped per video, so videos with very large comment "
    "counts are under-sampled relative to smaller ones.",
    "Themes are clustered by a language model. Counts are exact; the grouping "
    "is a judgment call and worth spot-checking against the quoted examples.",
]


@dataclass
class Record:
    """One extracted item, rejoined to the comment and video it came from."""

    kind: str
    summary: str
    quote: str
    product: str
    stance: str
    comment: Comment
    video: VideoInfo | None

    @property
    def channel(self) -> str:
        return self.video.channel if self.video else ""


@dataclass
class Corpus:
    channels: list
    videos: list[VideoInfo]
    comments: list[Comment]
    quota: QuotaMeter

    @property
    def videos_by_id(self) -> dict[str, VideoInfo]:
        return {video.video_id: video for video in self.videos}


def build_corpus(
    api_key: str,
    channel_refs: list[str],
    videos_per_channel: int = 8,
    comments_per_video: int = 300,
    sort_by: str = "time",
    progress=None,
) -> Corpus:
    """Resolve channels, enumerate recent uploads, and pull comments."""
    quota = QuotaMeter()

    if progress:
        progress("channels", 0, len(channel_refs))
    channels = resolve_channels(api_key, channel_refs, meter=quota)

    video_ids: list[str] = []
    for index, channel in enumerate(channels, start=1):
        video_ids.extend(
            fetch_channel_video_ids(api_key, channel, limit=videos_per_channel, meter=quota)
        )
        if progress:
            progress("channels", index, len(channels))

    if not video_ids:
        raise YouTubeError("No videos found for the supplied channels.")

    videos = fetch_videos_info(api_key, video_ids, meter=quota)

    comments: list[Comment] = []
    for index, video in enumerate(videos, start=1):
        try:
            comments.extend(
                fetch_comments(
                    api_key,
                    video.video_id,
                    max_comments=comments_per_video,
                    sort_by=sort_by,
                    meter=quota,
                )
            )
        except QuotaExceeded:
            raise
        except YouTubeError:
            pass  # comments disabled, or a transient failure — skip the video
        if progress:
            progress("comments", index, len(videos))

    if not comments:
        raise YouTubeError(
            "No comments could be fetched for any video in this corpus. "
            "Comments may be disabled, or the quota may be exhausted."
        )
    return Corpus(channels=channels, videos=videos, comments=comments, quota=quota)


def extract_records(
    corpus: Corpus,
    usage: UsageMeter,
    progress=None,
) -> tuple[list[Record], set[int], Counter, list[dict]]:
    """Run the map pass and rejoin its output to the source comments.

    `progress`, if given, is called as progress("extract", done, total).
    """
    videos = corpus.videos_by_id
    by_video: dict[str, list[Comment]] = defaultdict(list)
    for comment in corpus.comments:
        by_video[comment.video_id].append(comment)

    jobs = []
    for video_id, video_comments in by_video.items():
        video = videos.get(video_id)
        context = (
            f'Video: "{video.title}"\nChannel: {video.channel}'
            if video
            else "Video: (unknown)"
        )
        jobs.append((video_comments, context))

    mapped = run_map(
        jobs,
        usage,
        progress=(lambda done, total: progress("extract", done, total)) if progress else None,
    )

    records: list[Record] = []
    # Keyed by object identity rather than comment_id: the API omits IDs on some
    # comments, and keying on a missing ID silently disables the spam filter for
    # exactly those. The corpus holds every Comment alive for the whole run, so
    # these keys are stable.
    spam_keys: set[int] = set()
    vocabulary: Counter = Counter()
    signals: list[dict] = []

    for batch_comments, result in mapped:
        for index in result.spam_indices:
            if 0 <= index < len(batch_comments):
                spam_keys.add(id(batch_comments[index]))

        for signal in result.signals:
            if signal.trust == "none" or not (0 <= signal.comment_index < len(batch_comments)):
                continue
            comment = batch_comments[signal.comment_index]
            if id(comment) in spam_keys:
                continue
            video = videos.get(comment.video_id)
            signals.append(
                {
                    "trust": signal.trust,
                    "channel": video.channel if video else "",
                    "channel_id": video.channel_id if video else "",
                    "likes": comment.likes,
                }
            )

        vocabulary.update(term.lower().strip() for term in result.vocabulary if term.strip())

        for item in result.items:
            if not (0 <= item.comment_index < len(batch_comments)):
                continue
            comment = batch_comments[item.comment_index]
            if id(comment) in spam_keys:
                continue
            if not item.summary.strip():
                continue
            records.append(
                Record(
                    kind=item.kind,
                    summary=item.summary.strip(),
                    quote=item.quote.strip(),
                    product=item.product.strip(),
                    stance=item.stance,
                    comment=comment,
                    video=videos.get(comment.video_id),
                )
            )

    return records, spam_keys, vocabulary, signals


def fold_candidates(records: list[Record]) -> dict[str, list[dict]]:
    """Collapse identical statements into counted candidates, per kind.

    This is the step that makes the reduce pass affordable: tens of thousands of
    items become a few hundred distinct statements before any tokens are spent.
    """
    grouped: dict[str, dict[str, dict]] = defaultdict(dict)
    for record in records:
        key = normalize_summary(record.summary)
        if not key:
            continue
        bucket = grouped[record.kind].setdefault(
            key, {"summary": record.summary, "count": 0, "likes": 0, "records": []}
        )
        bucket["count"] += 1
        bucket["likes"] += record.comment.likes
        bucket["records"].append(record)

    return {
        kind: sorted(
            buckets.values(),
            key=lambda candidate: (candidate["count"], candidate["likes"]),
            reverse=True,
        )
        for kind, buckets in grouped.items()
    }


def _theme_from_members(title: str, description: str, members: list[dict], kind: str) -> dict:
    records = [record for member in members for record in member["records"]]
    count = sum(member["count"] for member in members)
    likes = sum(member["likes"] for member in members)

    channels = Counter(record.channel for record in records if record.channel)
    months = Counter(month_of(record.comment.published_at) for record in records)
    months.pop("", None)

    examples = sorted(records, key=lambda record: record.comment.likes, reverse=True)[:4]

    return {
        "kind": kind,
        "title": title,
        "description": description,
        "count": count,
        "likes": likes,
        "channel_spread": len(channels),
        "channels": [{"channel": name, "count": n} for name, n in channels.most_common()],
        "months": dict(sorted(months.items())),
        "statements": [member["summary"] for member in members[:8]],
        "examples": [
            {
                "quote": record.quote or record.comment.text[:220],
                "author": record.comment.author,
                "likes": record.comment.likes,
                "channel": record.channel,
                "video_title": record.video.title if record.video else "",
                "video_id": record.comment.video_id,
                "published_at": record.comment.published_at,
            }
            for record in examples
        ],
        "_records": records,
    }


def build_themes(
    candidates: dict[str, list[dict]],
    usage: UsageMeter,
    progress=None,
) -> dict[str, list[dict]]:
    """Cluster candidates into themes, one reduce call per kind (in parallel).

    A kind whose clustering call comes back unusable is left out rather than
    sinking the report; `progress`, if given, is called as
    progress("themes", done, total).
    """
    kinds = [kind for kind in THEME_KINDS if candidates.get(kind)]
    if not kinds:
        return {}

    def cluster(kind: str):
        head = candidates[kind][:MAX_REDUCE_CANDIDATES]
        try:
            return kind, head, run_reduce(kind, head, usage)
        except BatchFailed as exc:
            return kind, head, exc

    themes: dict[str, list[dict]] = {}
    failures: list[BatchFailed] = []
    with ThreadPoolExecutor(max_workers=min(len(kinds), 6)) as pool:
        for done, (kind, head, result) in enumerate(pool.map(cluster, kinds), start=1):
            if progress:
                progress("themes", done, len(kinds))
            if isinstance(result, BatchFailed):
                failures.append(result)
                continue
            built = []
            # The prompt asks for each candidate in at most one theme; enforce it
            # here so the counts stay exact (the first theme listed wins).
            used: set[int] = set()
            for theme in result.themes:
                indices = [i for i in dict.fromkeys(theme.candidate_indices)
                           if 0 <= i < len(head) and i not in used]
                if not indices:
                    continue
                used.update(indices)
                members = [head[i] for i in indices]
                built.append(_theme_from_members(theme.title, theme.description, members, kind))
            built.sort(key=lambda item: (item["count"], item["likes"]), reverse=True)
            themes[kind] = built

    usage.record_failures(len(failures))
    if len(failures) == len(kinds):
        raise ExtractionError(f"Clustering failed for every item kind. First error: {failures[0]}")
    return themes


def _theme_keywords(theme: dict, limit: int = 8) -> set[str]:
    counter: Counter = Counter()
    counter.update(tokens(theme["title"]))
    for statement in theme["statements"]:
        counter.update(tokens(statement))
    return {word for word, _ in counter.most_common(limit)}


def content_gaps(themes: dict[str, list[dict]], videos: list[VideoInfo], limit: int = 25) -> list[dict]:
    """Rank audience demand by how poorly the existing catalogue covers it.

    Demand comes from the comments; supply comes from the titles, descriptions
    and tags of the videos in the same corpus.
    """
    supply = [
        (video, token_set(f"{video.title} {' '.join(video.tags)} {video.description[:200]}"))
        for video in videos
    ]

    gaps: list[dict] = []
    for kind in DEMAND_KINDS:
        for theme in themes.get(kind, []):
            keywords = _theme_keywords(theme)
            if not keywords:
                continue

            best_video, best_overlap = None, 0.0
            for video, video_terms in supply:
                overlap = len(keywords & video_terms) / len(keywords)
                if overlap > best_overlap:
                    best_video, best_overlap = video, overlap

            if best_overlap >= 0.6:
                coverage = "covered"
            elif best_overlap >= 0.3:
                coverage = "partial"
            else:
                coverage = "none"

            # Demand weighted by how unmet it is. Likes are dampened so one viral
            # comment cannot outrank a steady drumbeat of separate requests.
            demand = theme["count"] + (theme["likes"] ** 0.5)
            gaps.append(
                {
                    "title": theme["title"],
                    "description": theme["description"],
                    "kind": kind,
                    "count": theme["count"],
                    "likes": theme["likes"],
                    "channel_spread": theme["channel_spread"],
                    "coverage": coverage,
                    "coverage_score": round(best_overlap, 3),
                    "closest_video": (
                        {"title": best_video.title, "video_id": best_video.video_id,
                         "channel": best_video.channel}
                        if best_video and best_overlap >= 0.3
                        else None
                    ),
                    "gap_score": round(demand * (1 - best_overlap), 2),
                    "keywords": sorted(keywords),
                    "examples": theme["examples"][:2],
                }
            )

    gaps.sort(key=lambda gap: gap["gap_score"], reverse=True)
    return gaps[:limit]


def gap_rows(gaps: list[dict]) -> list[dict]:
    """Content gaps as flat rows for a CSV file."""
    return [
        {
            "title": gap["title"],
            "kind": gap["kind"],
            "comments": gap["count"],
            "likes": gap["likes"],
            "channel_spread": gap["channel_spread"],
            "coverage": gap["coverage"],
            "gap_score": gap["gap_score"],
            "closest_video": (gap["closest_video"] or {}).get("title", ""),
            "description": gap["description"],
        }
        for gap in gaps
    ]


def audience_overlap(corpus: Corpus) -> dict:
    """Jaccard overlap between the commenter sets of each pair of channels.

    Costs no extra quota: the comment fetch already returns author channel IDs.
    """
    videos = corpus.videos_by_id
    per_channel: dict[str, set[str]] = defaultdict(set)
    names: dict[str, str] = {}

    for comment in corpus.comments:
        video = videos.get(comment.video_id)
        if not video or not video.channel_id:
            continue
        identity = comment.identity
        if identity:
            per_channel[video.channel_id].add(identity)
            names[video.channel_id] = video.channel

    eligible = {
        channel_id: people
        for channel_id, people in per_channel.items()
        if len(people) >= MIN_COMMENTERS_FOR_OVERLAP
    }

    nodes, edges = [], []
    for channel_id, people in eligible.items():
        shared = set()
        for other_id, other_people in eligible.items():
            if other_id != channel_id:
                shared |= people & other_people
        nodes.append(
            {
                "channel_id": channel_id,
                "channel": names.get(channel_id, ""),
                "commenters": len(people),
                "exclusive": len(people - shared),
                "exclusive_pct": round(len(people - shared) / len(people) * 100, 1),
            }
        )

    ids = sorted(eligible)
    for i, left in enumerate(ids):
        for right in ids[i + 1 :]:
            a, b = eligible[left], eligible[right]
            shared = len(a & b)
            if not shared:
                continue
            union = len(a | b)
            edges.append(
                {
                    "source": names.get(left, left),
                    "target": names.get(right, right),
                    "shared": shared,
                    "jaccard": round(shared / union, 4) if union else 0.0,
                    "pct_of_source": round(shared / len(a) * 100, 1),
                    "pct_of_target": round(shared / len(b) * 100, 1),
                }
            )

    nodes.sort(key=lambda node: node["commenters"], reverse=True)
    edges.sort(key=lambda edge: edge["shared"], reverse=True)
    return {
        "nodes": nodes,
        "edges": edges,
        "note": (
            "Overlap is measured over commenters sampled in this study, not all "
            "subscribers. It is a floor, not a total."
        ),
    }


def vocabulary_report(vocabulary: Counter, videos: list[VideoInfo], limit: int = 40) -> list[dict]:
    """Audience terms with the creators' own vocabulary subtracted out.

    Whatever survives is language the audience brought.
    """
    creator_terms: set[str] = set()
    for video in videos:
        creator_terms |= token_set(f"{video.title} {' '.join(video.tags)}")

    rows = [
        {"term": term, "count": count}
        for term, count in vocabulary.most_common()
        if term and not creator_terms.issuperset(token_set(term) or {term})
    ]
    return rows[:limit]


def product_report(records: list[Record], limit: int = 30) -> list[dict]:
    """Share of voice by product, from the audience's mouth rather than the script."""
    grouped: dict[str, dict] = {}
    for record in records:
        name = record.product.strip()
        if not name:
            continue
        key = name.lower()
        entry = grouped.setdefault(
            key,
            {
                "product": name,
                "mentions": 0,
                "likes": 0,
                "recommends": 0,
                "warns_against": 0,
                "compares": 0,
                "neutral": 0,
                "channels": Counter(),
                "examples": [],
            },
        )
        entry["mentions"] += 1
        entry["likes"] += record.comment.likes
        if record.stance in ("recommends", "warns_against", "compares", "neutral"):
            entry[record.stance] += 1
        if record.channel:
            entry["channels"][record.channel] += 1
        if len(entry["examples"]) < 3 and record.quote:
            entry["examples"].append(
                {"quote": record.quote, "likes": record.comment.likes, "channel": record.channel}
            )

    rows = []
    for entry in grouped.values():
        channels = entry.pop("channels")
        entry["channel_spread"] = len(channels)
        entry["top_channels"] = [name for name, _ in channels.most_common(3)]
        positive = entry["recommends"]
        negative = entry["warns_against"]
        judged = positive + negative
        entry["net_stance"] = round((positive - negative) / judged, 3) if judged else 0.0
        rows.append(entry)

    rows.sort(key=lambda row: (row["mentions"], row["likes"]), reverse=True)
    return rows[:limit]


def trust_report(signals: list[dict]) -> list[dict]:
    """Per-channel trust signals.

    Not polarity: purchase intent, sponsorship skepticism, deference, and
    challenges to the creator's expertise, counted separately.
    """
    grouped: dict[str, dict] = {}
    for signal in signals:
        channel = signal["channel"] or "(unknown)"
        entry = grouped.setdefault(
            channel,
            {
                "channel": channel,
                "purchase_intent": 0,
                "sponsorship_skepticism": 0,
                "deference": 0,
                "expertise_challenge": 0,
                "total": 0,
            },
        )
        if signal["trust"] in entry:
            entry[signal["trust"]] += 1
            entry["total"] += 1

    rows = list(grouped.values())
    for row in rows:
        credible = row["purchase_intent"] + row["deference"]
        doubtful = row["sponsorship_skepticism"] + row["expertise_challenge"]
        judged = credible + doubtful
        row["trust_ratio"] = round(credible / judged, 3) if judged else 0.0
    rows.sort(key=lambda row: row["total"], reverse=True)
    return rows


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def rising_themes(themes: dict[str, list[dict]], corpus: Corpus, limit: int = 12) -> list[dict]:
    """Themes over-represented in the recent window relative to the whole corpus.

    The recent window is the newest third of the sample, capped at 90 days.
    """
    dates = [d for d in (_parse_date(c.published_at) for c in corpus.comments) if d]
    if not dates:
        return []
    reference = max(dates)
    window = min(timedelta(days=RECENT_WINDOW_DAYS), (reference - min(dates)) / 3)
    if not window:
        return []
    cutoff = reference - window
    window_days = max(1, round(window / timedelta(days=1)))

    recent_total = sum(1 for date in dates if date >= cutoff)
    baseline = recent_total / len(dates)
    if baseline <= 0:
        return []

    rows = []
    for kind, kind_themes in themes.items():
        for theme in kind_themes:
            theme_dates = [
                d
                for d in (_parse_date(r.comment.published_at) for r in theme["_records"])
                if d
            ]
            if len(theme_dates) < 3:
                continue
            recent = sum(1 for date in theme_dates if date >= cutoff)
            if recent < 3:
                continue
            share = recent / len(theme_dates)
            lift = share / baseline
            if lift < 1.5:
                continue
            rows.append(
                {
                    "kind": kind,
                    "title": theme["title"],
                    "description": theme["description"],
                    "recent": recent,
                    "total": theme["count"],
                    "lift": round(lift, 2),
                    "window_days": window_days,
                    "channel_spread": theme["channel_spread"],
                    "examples": theme["examples"][:2],
                }
            )

    rows.sort(key=lambda row: (row["lift"], row["recent"]), reverse=True)
    return rows[:limit]


def theme_drift(themes: dict[str, list[dict]], limit: int = 12) -> list[dict]:
    """Month-by-month volume for the largest themes."""
    flat = [theme for kind_themes in themes.values() for theme in kind_themes]
    flat.sort(key=lambda theme: theme["count"], reverse=True)
    return [
        {"kind": theme["kind"], "title": theme["title"], "months": theme["months"]}
        for theme in flat[:limit]
        if theme["months"]
    ]


def strip_internals(themes: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Drop the `_records` back-references so themes can be serialised."""
    return {
        kind: [{k: v for k, v in theme.items() if not k.startswith("_")} for theme in kind_themes]
        for kind, kind_themes in themes.items()
    }


def build_study_report(corpus: Corpus, usage: UsageMeter, label: str = "", progress=None) -> dict:
    """Run both model passes over a corpus and assemble the full report."""
    records, spam_keys, vocabulary, signals = extract_records(corpus, usage, progress=progress)
    candidates = fold_candidates(records)
    themes = build_themes(candidates, usage, progress=progress)

    report = {
        "study": {
            "label": label or ", ".join(channel.title for channel in corpus.channels),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "channels": [
                {
                    "channel_id": channel.channel_id,
                    "title": channel.title,
                    "subscribers": channel.subscriber_count,
                    "videos_total": channel.video_count,
                    "thumbnail": channel.thumbnail,
                }
                for channel in corpus.channels
            ],
            "videos_sampled": len({comment.video_id for comment in corpus.comments}),
            "comments_sampled": len(corpus.comments),
            "spam_filtered": len(spam_keys),
            "items_extracted": len(records),
            "distinct_statements": sum(len(v) for v in candidates.values()),
        },
        "content_gaps": content_gaps(themes, corpus.videos),
        "rising": rising_themes(themes, corpus),
        "themes": strip_internals(themes),
        "audience_overlap": audience_overlap(corpus),
        "vocabulary": vocabulary_report(vocabulary, corpus.videos),
        "products": product_report(records),
        "trust": trust_report(signals),
        "drift": theme_drift(themes),
        "quota": corpus.quota.as_dict(),
        "usage": usage.as_dict(),
        "caveats": CAVEATS,
    }
    return report


def run_study(
    api_key: str,
    channel_refs: list[str],
    videos_per_channel: int = 8,
    comments_per_video: int = 300,
    sort_by: str = "time",
    label: str = "",
    progress=None,
) -> dict:
    """Fetch a niche corpus and produce the full research report.

    `progress`, if given, is called as progress(stage, done, total) with stage
    one of "channels", "comments", "extract" or "themes".
    """
    corpus = build_corpus(
        api_key,
        channel_refs,
        videos_per_channel=videos_per_channel,
        comments_per_video=comments_per_video,
        sort_by=sort_by,
        progress=progress,
    )
    return build_study_report(corpus, UsageMeter(), label=label, progress=progress)
