"""Demo mode: a pre-computed niche study, so the app is explorable with no keys.

Unlike the rest of the pipeline this data is bundled rather than generated —
extraction needs an Anthropic key, and the point of demo mode is to need
nothing. The shapes match `niche.build_study_report` and `analysis.build_report`
exactly, so every view renders the same way it would on real data.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .niche import CAVEATS

_CHANNELS = [
    ("UC_demo_bench", "The Coffee Bench", 1_240_000, 412),
    ("UC_demo_purge", "Pull & Purge", 486_000, 233),
    ("UC_demo_kitchen", "Small Kitchen Coffee", 193_000, 178),
    ("UC_demo_roast", "Roast Theory", 88_400, 96),
]


def _example(quote, author, likes, channel, video_title):
    return {
        "quote": quote,
        "author": author,
        "likes": likes,
        "channel": channel,
        "video_title": video_title,
        "video_id": "demo0000000",
        "published_at": "2026-05-14T09:12:00Z",
    }


def _theme(kind, title, description, count, likes, spread, months, statements, examples):
    return {
        "kind": kind,
        "title": title,
        "description": description,
        "count": count,
        "likes": likes,
        "channel_spread": spread,
        "channels": [{"channel": name, "count": n} for name, n in months.pop("_channels", [])],
        "months": months,
        "statements": statements,
        "examples": examples,
    }


_GAPS = [
    {
        "title": "Grinder-first buying guidance",
        "description": (
            "The single largest unmet demand in this corpus. Viewers repeatedly "
            "conclude that grinder quality dominates machine quality, then find "
            "that every buying guide is organised around machines. They want a "
            "guide that starts from the grinder and works outward."
        ),
        "kind": "request",
        "count": 412,
        "likes": 18_940,
        "channel_spread": 4,
        "coverage": "none",
        "coverage_score": 0.125,
        "closest_video": None,
        "gap_score": 480.35,
        "keywords": ["budget", "burr", "espresso", "grinder", "machine", "upgrade"],
        "examples": [
            _example(
                "everyone shows the machine, nobody shows the grind. I wasted 900 "
                "on a machine and my shots got better the day I changed grinder",
                "@bench_pressed", 4102, "The Coffee Bench", "Best Espresso Machines Under $1000",
            ),
            _example(
                "third video this week telling me which machine to buy and not one "
                "of them says what to grind with",
                "@mmmcrema", 1877, "Pull & Purge", "2026 Espresso Machine Buyer's Guide",
            ),
        ],
    },
    {
        "title": "Water chemistry for people who are not chemists",
        "description": (
            "Water comes up constantly as the thing that broke someone's setup, "
            "but the audience says existing coverage is either a one-line "
            "'use filtered' or a full mineral-composition deep dive. The middle "
            "tier — what to actually buy and mix — is missing."
        ),
        "kind": "confusion",
        "count": 287,
        "likes": 9_310,
        "channel_spread": 4,
        "coverage": "partial",
        "coverage_score": 0.375,
        "closest_video": {
            "title": "Does Water Really Matter For Coffee?",
            "video_id": "demo0000000",
            "channel": "Roast Theory",
        },
        "gap_score": 240.18,
        "keywords": ["water", "filter", "scale", "minerals", "distilled", "recipe"],
        "examples": [
            _example(
                "I've watched four water videos and I still don't know what to put "
                "in the tank tomorrow morning. just tell me what to buy",
                "@kettle_logic", 2244, "Roast Theory", "Does Water Really Matter For Coffee?",
            ),
            _example(
                "killed a boiler with tap water because every video said 'filtered' "
                "and mine has a filter jug. that is apparently not the same thing",
                "@steamwand_sam", 1590, "Small Kitchen Coffee", "Descaling Your Machine",
            ),
        ],
    },
    {
        "title": "What actually breaks after year three",
        "description": (
            "Reviews cluster in the first weeks of ownership. The audience wants "
            "long-term failure data — gaskets, pumps, boilers, and which brands "
            "still sell the parts. Nobody in this corpus has published it."
        ),
        "kind": "request",
        "count": 198,
        "likes": 11_020,
        "channel_spread": 3,
        "coverage": "none",
        "coverage_score": 0.0,
        "closest_video": None,
        "gap_score": 302.97,
        "keywords": ["repair", "parts", "gasket", "reliability", "years", "warranty"],
        "examples": [
            _example(
                "every review is a honeymoon review. do a 3 year followup, that's the "
                "video nobody will make because it needs 3 years",
                "@longpull", 3560, "The Coffee Bench", "One Year With The E61",
            ),
        ],
    },
    {
        "title": "Dialling in for light roast specifically",
        "description": (
            "General dial-in tutorials assume medium roast. Light-roast drinkers "
            "say the standard 1:2 in 30 seconds advice actively fails them and "
            "they cannot find guidance written for their beans."
        ),
        "kind": "question",
        "count": 176,
        "likes": 6_430,
        "channel_spread": 4,
        "coverage": "partial",
        "coverage_score": 0.5,
        "closest_video": {
            "title": "How To Dial In Espresso",
            "video_id": "demo0000000",
            "channel": "Pull & Purge",
        },
        "gap_score": 128.10,
        "keywords": ["light", "roast", "dial", "ratio", "temperature", "sour"],
        "examples": [
            _example(
                "1:2 in 30s just gives me sour water with these beans. is the whole "
                "rule just wrong for light roast or am I doing something else wrong",
                "@nordic_pull", 2018, "Pull & Purge", "How To Dial In Espresso",
            ),
        ],
    },
    {
        "title": "Small-flat setups without a dedicated counter",
        "description": (
            "A persistent, geographically concentrated request: setups for people "
            "with under a metre of counter space, including where the grinder "
            "lives and how to manage waste water in a flat with no plumbing."
        ),
        "kind": "request",
        "count": 143,
        "likes": 5_120,
        "channel_spread": 2,
        "coverage": "none",
        "coverage_score": 0.111,
        "closest_video": None,
        "gap_score": 190.61,
        "keywords": ["space", "small", "counter", "apartment", "setup", "compact"],
        "examples": [
            _example(
                "these setups are all in kitchens the size of my flat. what does this "
                "look like on 80cm of worktop",
                "@onesquaremetre", 1744, "Small Kitchen Coffee", "My 2026 Coffee Setup",
            ),
        ],
    },
]

_THEMES = {
    "complaint": [
        _theme(
            "complaint", "Sponsored segments are not clearly marked",
            "Viewers say the ad read blends into the review often enough that they "
            "have stopped trusting recommendations in the first two minutes. The "
            "complaint concentrates on two of the four channels.",
            221, 8_940, 3,
            {"2026-01": 18, "2026-02": 24, "2026-03": 41, "2026-04": 62, "2026-05": 76,
             "_channels": [("Pull & Purge", 122), ("The Coffee Bench", 71), ("Roast Theory", 28)]},
            ["sponsored segment is not disclosed clearly",
             "review reads like an ad without saying so",
             "affiliate links not mentioned in the video"],
            [_example(
                "the 'honest review' has an affiliate link, a discount code and a "
                "brand rep in the comments. call it an ad and I'll still watch",
                "@flatwhitefred", 3310, "Pull & Purge", "2026 Espresso Machine Buyer's Guide")],
        ),
        _theme(
            "complaint", "Audio drops on the grinder segments",
            "A recurring production complaint: gain riding during grinder demos "
            "makes speech inaudible right where the technical detail is.",
            96, 2_140, 2,
            {"2026-02": 11, "2026-03": 22, "2026-04": 30, "2026-05": 33,
             "_channels": [("Small Kitchen Coffee", 61), ("Roast Theory", 35)]},
            ["audio is too quiet during the grinder demonstration",
             "cannot hear the voiceover over the grinder"],
            [_example(
                "had to put on headphones and still couldn't hear the part where you "
                "say the actual setting",
                "@quietgrind", 890, "Small Kitchen Coffee", "Grinder Comparison 2026")],
        ),
    ],
    "correction": [
        _theme(
            "correction", "The nine-bar rule is disputed",
            "A substantial and well-liked group argues the nine-bar standard is a "
            "historical artefact of spring lever design rather than an optimum, and "
            "pushes back whenever it is stated as fact.",
            134, 7_760, 4,
            {"2026-01": 20, "2026-02": 26, "2026-03": 28, "2026-04": 30, "2026-05": 30,
             "_channels": [("The Coffee Bench", 52), ("Roast Theory", 41),
                           ("Pull & Purge", 26), ("Small Kitchen Coffee", 15)]},
            ["nine bars is a historical artefact not an optimum",
             "lower pressure produces better extraction for light roast"],
            [_example(
                "9 bar is where the spring landed in 1961, it is not a law of physics. "
                "6 bar tastes better on most of what I buy",
                "@leverhead", 2890, "Roast Theory", "The Physics Of Espresso")],
        ),
    ],
    "praise": [
        _theme(
            "praise", "Unedited real-time pulls",
            "The most-praised specific format across the corpus: showing a full "
            "unedited shot including the failures, rather than a cut to the good one.",
            268, 12_400, 4,
            {"2026-01": 40, "2026-02": 48, "2026-03": 55, "2026-04": 60, "2026-05": 65,
             "_channels": [("The Coffee Bench", 110), ("Pull & Purge", 78),
                           ("Roast Theory", 45), ("Small Kitchen Coffee", 35)]},
            ["showing the unedited pull including the bad shots is valuable",
             "real time footage is more useful than edited highlights"],
            [_example(
                "the fact you left the choked shot in taught me more than the whole "
                "rest of the video",
                "@chokedshot", 4420, "The Coffee Bench", "One Year With The E61")],
        ),
    ],
}

_OVERLAP = {
    "nodes": [
        {"channel_id": "UC_demo_bench", "channel": "The Coffee Bench",
         "commenters": 1840, "exclusive": 1131, "exclusive_pct": 61.5},
        {"channel_id": "UC_demo_purge", "channel": "Pull & Purge",
         "commenters": 1120, "exclusive": 486, "exclusive_pct": 43.4},
        {"channel_id": "UC_demo_kitchen", "channel": "Small Kitchen Coffee",
         "commenters": 640, "exclusive": 402, "exclusive_pct": 62.8},
        {"channel_id": "UC_demo_roast", "channel": "Roast Theory",
         "commenters": 415, "exclusive": 121, "exclusive_pct": 29.2},
    ],
    "edges": [
        {"source": "The Coffee Bench", "target": "Pull & Purge", "shared": 512,
         "jaccard": 0.2075, "pct_of_source": 27.8, "pct_of_target": 45.7},
        {"source": "Pull & Purge", "target": "Roast Theory", "shared": 231,
         "jaccard": 0.1774, "pct_of_source": 20.6, "pct_of_target": 55.7},
        {"source": "The Coffee Bench", "target": "Roast Theory", "shared": 198,
         "jaccard": 0.0937, "pct_of_source": 10.8, "pct_of_target": 47.7},
        {"source": "The Coffee Bench", "target": "Small Kitchen Coffee", "shared": 154,
         "jaccard": 0.0658, "pct_of_source": 8.4, "pct_of_target": 24.1},
        {"source": "Pull & Purge", "target": "Small Kitchen Coffee", "shared": 88,
         "jaccard": 0.0526, "pct_of_source": 7.9, "pct_of_target": 13.8},
    ],
    "note": (
        "Overlap is measured over commenters sampled in this study, not all "
        "subscribers. It is a floor, not a total."
    ),
}

_PRODUCTS = [
    {"product": "Niche Zero", "mentions": 341, "likes": 9_120, "recommends": 268,
     "warns_against": 21, "compares": 44, "neutral": 8, "channel_spread": 4,
     "top_channels": ["The Coffee Bench", "Pull & Purge", "Roast Theory"],
     "net_stance": 0.855,
     "examples": [{"quote": "the zero is the only upgrade that changed my shots",
                   "likes": 1820, "channel": "The Coffee Bench"}]},
    {"product": "Gaggia Classic", "mentions": 289, "likes": 7_430, "recommends": 191,
     "warns_against": 63, "compares": 28, "neutral": 7, "channel_spread": 4,
     "top_channels": ["Small Kitchen Coffee", "Pull & Purge", "The Coffee Bench"],
     "net_stance": 0.504,
     "examples": [{"quote": "great machine if you accept you're buying a project",
                   "likes": 1460, "channel": "Small Kitchen Coffee"}]},
    {"product": "Breville Bambino", "mentions": 204, "likes": 4_880, "recommends": 142,
     "warns_against": 38, "compares": 19, "neutral": 5, "channel_spread": 3,
     "top_channels": ["Small Kitchen Coffee", "Pull & Purge"],
     "net_stance": 0.578,
     "examples": [{"quote": "best thing for a tiny kitchen, steam wand is the weak point",
                   "likes": 990, "channel": "Small Kitchen Coffee"}]},
    {"product": "DF64", "mentions": 156, "likes": 3_210, "recommends": 88,
     "warns_against": 47, "compares": 18, "neutral": 3, "channel_spread": 3,
     "top_channels": ["Roast Theory", "The Coffee Bench"],
     "net_stance": 0.304,
     "examples": [{"quote": "retention is still bad no matter what the mods claim",
                   "likes": 740, "channel": "Roast Theory"}]},
]

_TRUST = [
    {"channel": "The Coffee Bench", "purchase_intent": 412, "sponsorship_skepticism": 71,
     "deference": 388, "expertise_challenge": 44, "total": 915, "trust_ratio": 0.874},
    {"channel": "Roast Theory", "purchase_intent": 96, "sponsorship_skepticism": 28,
     "deference": 141, "expertise_challenge": 63, "total": 328, "trust_ratio": 0.723},
    {"channel": "Small Kitchen Coffee", "purchase_intent": 154, "sponsorship_skepticism": 19,
     "deference": 96, "expertise_challenge": 12, "total": 281, "trust_ratio": 0.890},
    {"channel": "Pull & Purge", "purchase_intent": 188, "sponsorship_skepticism": 122,
     "deference": 84, "expertise_challenge": 31, "total": 425, "trust_ratio": 0.640},
]

_VOCABULARY = [
    {"term": "channeling", "count": 412}, {"term": "puck prep", "count": 388},
    {"term": "wdt", "count": 341}, {"term": "sour shot", "count": 296},
    {"term": "retention", "count": 271}, {"term": "dialling in", "count": 254},
    {"term": "choked", "count": 233}, {"term": "gusher", "count": 198},
    {"term": "spritzing", "count": 176}, {"term": "naked portafilter", "count": 163},
    {"term": "single dosing", "count": 152}, {"term": "blonding", "count": 141},
    {"term": "temp surfing", "count": 128}, {"term": "espro", "count": 96},
]

_RISING = [
    {"kind": "question", "title": "Lever machines for beginners", "recent": 62, "total": 74,
     "lift": 3.41, "channel_spread": 3,
     "description": "Beginner-framed lever questions barely existed before March and "
                    "are now the fastest-accelerating question cluster in the corpus.",
     "examples": [_example("is a lever actually harder or does it just look harder",
                           "@springload", 640, "Roast Theory", "The Physics Of Espresso")]},
    {"kind": "complaint", "title": "Grinder prices after the tariff change", "recent": 88,
     "total": 103, "lift": 2.87, "channel_spread": 4,
     "description": "Price complaints tied to a specific import change, concentrated "
                    "almost entirely in the last two months.",
     "examples": [_example("this grinder went up 40% since your video, worth revisiting",
                           "@pricewatch", 1120, "The Coffee Bench", "Grinder Comparison 2026")]},
    {"kind": "request", "title": "Repairability scores in reviews", "recent": 54, "total": 71,
     "lift": 2.12, "channel_spread": 3,
     "description": "A new ask: viewers want a standing repairability rating in every "
                    "machine review, referencing right-to-repair coverage elsewhere.",
     "examples": [_example("add a repairability score to every review please",
                           "@fixitpull", 880, "Pull & Purge", "2026 Espresso Machine Buyer's Guide")]},
]

_DRIFT = [
    {"kind": "request", "title": "Grinder-first buying guidance",
     "months": {"2026-01": 52, "2026-02": 64, "2026-03": 81, "2026-04": 96, "2026-05": 119}},
    {"kind": "praise", "title": "Unedited real-time pulls",
     "months": {"2026-01": 40, "2026-02": 48, "2026-03": 55, "2026-04": 60, "2026-05": 65}},
    {"kind": "complaint", "title": "Sponsored segments are not clearly marked",
     "months": {"2026-01": 18, "2026-02": 24, "2026-03": 41, "2026-04": 62, "2026-05": 76}},
    {"kind": "confusion", "title": "Water chemistry for people who are not chemists",
     "months": {"2026-01": 44, "2026-02": 51, "2026-03": 58, "2026-04": 62, "2026-05": 72}},
]


def demo_study() -> dict:
    """A pre-computed niche study, shaped exactly like a real one."""
    return {
        "demo": True,
        "study": {
            "label": "Home espresso",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "channels": [
                {
                    "channel_id": cid,
                    "title": title,
                    "subscribers": subs,
                    "videos_total": total,
                    "thumbnail": "",
                }
                for cid, title, subs, total in _CHANNELS
            ],
            "videos_sampled": 32,
            "comments_sampled": 9_600,
            "spam_filtered": 341,
            "items_extracted": 4_182,
            "distinct_statements": 1_146,
        },
        # Real reports come out of content_gaps() already ranked; sort here so the
        # sample cannot drift out of order as entries are edited.
        "content_gaps": sorted(_GAPS, key=lambda gap: gap["gap_score"], reverse=True),
        "rising": _RISING,
        "themes": _THEMES,
        "audience_overlap": _OVERLAP,
        "vocabulary": _VOCABULARY,
        "products": _PRODUCTS,
        "trust": _TRUST,
        "drift": _DRIFT,
        # 4 handles, 4 upload-playlist pages, 1 videos.list call for all 32
        # videos, then 3 comment pages (300 comments) per video.
        "quota": {
            "units": 105,
            "calls": {
                "channels.list": 4,
                "playlistItems.list": 4,
                "videos.list": 1,
                "commentThreads.list": 96,
            },
            "daily_free_tier": 10_000,
        },
        # 192 map batches of 50 comments plus 6 clustering calls, priced the
        # way UsageMeter prices them on the default model.
        "usage": {
            "requests": 198,
            "failed_requests": 0,
            "input_tokens": 412_800,
            "output_tokens": 96_400,
            "cache_read_tokens": 301_200,
            "batched": False,
            "estimated_cost_usd": 2.43,
            "models": {"claude-opus-5-5": {"input": 412_800, "output": 96_400}},
        },
        "caveats": CAVEATS,
    }


_VIDEO_TITLE = "Best Espresso Machines Under $1000"


def _video_example(quote, author, likes):
    return _example(quote, author, likes, "The Coffee Bench", _VIDEO_TITLE)


# Themes for the single-video sample. Counts are on the scale of the 500
# comments that report analyses, not the corpus-wide study above.
_VIDEO_THEMES = {
    "question": [
        _theme(
            "question", "Does the grinder matter more than the machine at this budget?",
            "Asked repeatedly and never answered directly in the video.",
            21, 4_102, 1,
            {"2026-04": 15, "2026-05": 6, "_channels": [("The Coffee Bench", 21)]},
            ["does the grinder matter more than the machine at this budget"],
            [_video_example("everyone shows the machine, nobody shows the grind",
                            "@bench_pressed", 4102)],
        ),
        _theme(
            "question", "Which of these can actually be repaired at home?",
            "Viewers want parts availability before they commit.",
            12, 1_744, 1,
            {"2026-04": 7, "2026-05": 5, "_channels": [("The Coffee Bench", 12)]},
            ["which machines can be repaired at home"],
            [_video_example("can I get gaskets for this in three years or is it landfill",
                            "@fixitpull", 1744)],
        ),
        _theme(
            "question", "Is the pressure gauge worth paying extra for?",
            "Split opinions in the replies, no answer from the creator.",
            9, 980, 1,
            {"2026-04": 6, "2026-05": 3, "_channels": [("The Coffee Bench", 9)]},
            ["is a pressure gauge worth paying extra for"],
            [_video_example("does the gauge actually help or is it just jewellery",
                            "@ninebar", 980)],
        ),
    ],
    "request": [
        _theme(
            "request", "Grinder-first buying guidance", _GAPS[0]["description"],
            41, 5_980, 1,
            {"2026-04": 29, "2026-05": 12, "_channels": [("The Coffee Bench", 41)]},
            ["buying guide should start from the grinder",
             "grinder matters more than the machine at this budget"],
            [_video_example(
                "everyone shows the machine, nobody shows the grind. I wasted 900 "
                "on a machine and my shots got better the day I changed grinder",
                "@bench_pressed", 4102)],
        ),
    ],
    "complaint": [
        _theme(
            "complaint", "Sponsored segment is not clearly marked",
            "Viewers say the ad read blends into the review, and that it makes "
            "them doubt the ranking that follows it.",
            23, 3_310, 1,
            {"2026-04": 17, "2026-05": 6, "_channels": [("The Coffee Bench", 23)]},
            ["sponsored segment is not disclosed clearly",
             "review reads like an ad without saying so"],
            [_video_example(
                "the 'honest review' has an affiliate link, a discount code and a "
                "brand rep in the comments. call it an ad and I'll still watch",
                "@flatwhitefred", 3310)],
        ),
    ],
    "correction": [
        _theme(
            "correction", "The nine-bar rule is disputed",
            "A small, well-liked group argues nine bars is a historical artefact "
            "rather than an optimum, and objects to it being stated as fact.",
            9, 2_890, 1,
            {"2026-04": 6, "2026-05": 3, "_channels": [("The Coffee Bench", 9)]},
            ["nine bars is a historical artefact not an optimum"],
            [_video_example(
                "9 bar is where the spring landed in 1961, it is not a law of physics. "
                "6 bar tastes better on most of what I buy",
                "@leverhead", 2890)],
        ),
    ],
    "praise": [
        _theme(
            "praise", "Unedited real-time pulls",
            "Viewers single out the uncut shots, failures included, as the most "
            "useful part of the video.",
            17, 4_420, 1,
            {"2026-04": 12, "2026-05": 5, "_channels": [("The Coffee Bench", 17)]},
            ["showing the unedited pull including the bad shots is valuable"],
            [_video_example(
                "the fact you left the choked shot in taught me more than the whole "
                "rest of the video",
                "@chokedshot", 4420)],
        ),
    ],
}


def demo_video_report() -> dict:
    """A pre-computed single-video report, shaped like `analysis.build_report`."""
    return {
        "demo": True,
        "video": {
            "video_id": "demo0000000",
            "title": _VIDEO_TITLE,
            "channel": "The Coffee Bench",
            "channel_id": "UC_demo_bench",
            "published_at": "2026-04-02T10:00:00Z",
            "thumbnail": "",
            "view_count": 1_284_503,
            "like_count": 87_311,
            "comment_count": 6_204,
            "description": "Bundled sample data so you can explore without any API keys.",
            "tags": ["espresso", "coffee", "review"],
        },
        "summary": {
            "comments_analyzed": 500,
            "spam_filtered": 18,
            "items_extracted": 214,
            "distinct_statements": 96,
            "counts_by_kind": {
                "request": 61, "question": 48, "complaint": 39,
                "confusion": 27, "correction": 14, "praise": 25,
            },
        },
        "themes": _VIDEO_THEMES,
        "questions": [
            {"question": "Does the grinder matter more than the machine at this budget?",
             "detail": "Asked repeatedly and never answered directly in the video.",
             "asked_by": 21, "likes": 4_102, "author": "@bench_pressed",
             "example": "everyone shows the machine, nobody shows the grind"},
            {"question": "Which of these can actually be repaired at home?",
             "detail": "Viewers want parts availability before they commit.",
             "asked_by": 12, "likes": 1_744, "author": "@fixitpull",
             "example": "can I get gaskets for this in three years or is it landfill"},
            {"question": "Is the pressure gauge worth paying extra for?",
             "detail": "Split opinions in the replies, no answer from the creator.",
             "asked_by": 9, "likes": 980, "author": "@ninebar",
             "example": "does the gauge actually help or is it just jewellery"},
        ],
        "timestamps": [
            {"seconds": 624, "timestamp": "10:24", "count": 31, "likes": 6_240,
             "examples": [{"quote": "10:24 gave me actual goosebumps, that crema",
                           "author": "@chokedshot", "likes": 1_820}]},
            {"seconds": 252, "timestamp": "4:12", "count": 19, "likes": 2_910,
             "examples": [{"quote": "4:12 is the only honest moment in any review this year",
                           "author": "@longpull", "likes": 1_100}]},
            {"seconds": 1_086, "timestamp": "18:06", "count": 12, "likes": 1_450,
             "examples": [{"quote": "18:06 wait did the portafilter just drop",
                           "author": "@steamwand_sam", "likes": 620}]},
        ],
        "products": [
            {"product": "Niche Zero", "mentions": 38, "likes": 1_820, "recommends": 30,
             "warns_against": 2, "compares": 5, "neutral": 1, "channel_spread": 1,
             "top_channels": ["The Coffee Bench"], "net_stance": 0.875,
             "examples": [{"quote": "the zero is the only upgrade that changed my shots",
                           "likes": 1820, "channel": "The Coffee Bench"}]},
            {"product": "Gaggia Classic", "mentions": 27, "likes": 1_460, "recommends": 16,
             "warns_against": 6, "compares": 4, "neutral": 1, "channel_spread": 1,
             "top_channels": ["The Coffee Bench"], "net_stance": 0.455,
             "examples": [{"quote": "great machine if you accept you're buying a project",
                           "likes": 1460, "channel": "The Coffee Bench"}]},
            {"product": "Breville Bambino", "mentions": 22, "likes": 990, "recommends": 14,
             "warns_against": 4, "compares": 3, "neutral": 1, "channel_spread": 1,
             "top_channels": ["The Coffee Bench"], "net_stance": 0.556,
             "examples": [{"quote": "best thing for a tiny kitchen, steam wand is the weak point",
                           "likes": 990, "channel": "The Coffee Bench"}]},
        ],
        "vocabulary": [
            {"term": "channeling", "count": 41}, {"term": "puck prep", "count": 33},
            {"term": "wdt", "count": 29}, {"term": "sour shot", "count": 24},
            {"term": "retention", "count": 21}, {"term": "dialling in", "count": 19},
            {"term": "choked", "count": 17}, {"term": "gusher", "count": 12},
            {"term": "naked portafilter", "count": 11}, {"term": "single dosing", "count": 9},
        ],
        "trust": [
            {"channel": "The Coffee Bench", "purchase_intent": 46, "sponsorship_skepticism": 19,
             "deference": 38, "expertise_challenge": 7, "total": 110, "trust_ratio": 0.764},
        ],
        "quota": {"units": 6, "calls": {"videos.list": 1, "commentThreads.list": 5},
                  "daily_free_tier": 10_000},
        # 10 map batches plus 6 clustering calls.
        "usage": {"requests": 16, "failed_requests": 0, "input_tokens": 33_600,
                  "output_tokens": 7_800, "cache_read_tokens": 22_400, "batched": False,
                  "estimated_cost_usd": 0.21,
                  "models": {"claude-opus-5-5": {"input": 33_600, "output": 7_800}}},
        "caveats": CAVEATS,
    }
