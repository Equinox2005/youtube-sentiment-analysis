# 🔭 YouTube Audience Research

**Find what a niche keeps asking for that nobody has published.**

Point it at a handful of channels in the same space. It pulls their recent
catalogues, samples comments across all of them, and returns a research report:
the demand nobody is serving, whose audiences overlap, which products get talked
about, and what is changing month over month.

The unit of analysis is a **niche**, not a video. That is the whole point —
single-video dashboards compete with YouTube Studio; nobody sells cheap
niche-level audience research.

---

## Why this is not a sentiment tool

It used to be. Sentiment scoring was removed because it could not answer a useful
question:

- **Polarity has no discriminating power here.** YouTube comments skew heavily
  positive on almost every video, because people who dislike something leave
  rather than comment. Average scores cluster in a narrow band, so two videos
  that are nothing alike get near-identical numbers.
- **Sarcasm inverts it.** "Great, another 10 minute ad" scores positive on any
  lexicon model. It is a pacing complaint.
- **Most comments have no polarity to measure.** Timestamps, in-jokes, "who's
  watching in 2026". They land in a neutral bucket that is usually the largest
  one, and it is a discard pile, not a finding.

"82% positive" is not actionable. **"37 comments across 4 channels asked for a
grinder-first buying guide, and nobody has published one"** is.

---

## What it produces

| Output | What it answers |
|---|---|
| **Content gaps** | Demand ranked by how poorly the published catalogue covers it — audience asks cross-referenced against every title, tag and description in the corpus |
| **Rising** | Themes accelerating faster than the corpus: demand before it is obvious |
| **Themes** | Requests, complaints, questions, confusions, factual pushback and specific praise, clustered with counts and quotes |
| **Audience overlap** | Jaccard overlap between channels' commenter sets, and who owns an exclusive slice |
| **Products** | Share of voice by product, with stance — from the audience's words, not the script |
| **Trust signals** | Purchase intent, sponsorship skepticism, deference, expertise challenges, per channel. The influencer-vetting view |
| **Audience vocabulary** | The words commenters use, with the creators' own title vocabulary subtracted out |
| **Theme drift** | Monthly volume per theme |

Single-video mode uses the same engine, plus a **timestamp heatmap** — the
moments people actually rewound to, parsed from timestamps in the comments.

---

## Setup

```bash
git clone https://github.com/Equinox2005/youtube-sentiment-analysis.git
cd youtube-sentiment-analysis
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in two keys:

- **`YOUTUBE_API_KEY`** — [Google Cloud Console](https://console.cloud.google.com/)
  → enable *YouTube Data API v3* → create an API key. Free tier is 10,000 units/day.
- **`ANTHROPIC_API_KEY`** — [Anthropic Console](https://console.anthropic.com/).
  An `ant auth login` profile works instead.

No keys yet? Everything below works with `demo`, which ships a pre-computed study.

```bash
uvicorn app.main:app
```

Open **http://127.0.0.1:8000**.

---

## Command line

```bash
python cli.py study @channel1 @channel2 @channel3 --videos 8 --comments 300
python cli.py study demo
python cli.py video "https://youtube.com/watch?v=VIDEO_ID"
python cli.py estimate --channels 12 --videos 8 --comments 500
```

`estimate` predicts a study's quota cost before you spend any of it.

---

## What it costs to run

### YouTube quota — the binding constraint, and it is fine

`search.list` costs **100 units** per call and this tool never uses it. A
channel's whole catalogue is reachable for far less: `channels.list` returns the
`uploads` playlist ID, then `playlistItems` pages it at 1 unit per 50 videos.
`videos.list` takes 50 IDs per call.

A 12-channel, 96-video, ~48,000-comment study:

```
channels.list      12 IDs, batched        →    1 unit
playlistItems.list 12 channels × 1 page   →   12 units
videos.list        96 IDs, batched by 50  →    2 units
commentThreads     96 videos × 5 pages    →  480 units
                                          ─────────────
                                             495 units
```

**About 20 full studies per day on the free tier.**

### Model cost

Two passes, deliberately split:

- **Map** — reads raw comments, extracts structured items. Mechanical, high
  volume, runs at low effort.
- **Reduce** — clusters a few hundred pre-aggregated statements into themes.
  Small input, and where the judgment lives.

Between them sits a deterministic fold that collapses identical statements
locally, so tens of thousands of items become a few hundred distinct strings
before the expensive pass sees anything.

Both default to **`claude-opus-5`**. For a ~48,000-comment study that is roughly
**$9**, or **$4.50** through the Batches API. Two optional levers:

```bash
NICHE_MAP_MODEL=claude-haiku-4-5   # ~5x cheaper map pass, some loss of nuance
NICHE_USE_BATCH_API=true           # 50% off, but can take up to 24 hours
```

With both, a full study lands around **$1**. The map pass is where nearly all
the tokens go, so that switch is the one that matters — it is off by default
because model choice is your call, not the tool's.

---

## HTTP API

| Endpoint | Description |
|---|---|
| `GET /api/status` | Which keys are configured, which models are selected |
| `GET /api/estimate?channels=12&videos_per_channel=8&comments_per_video=500` | Quota preflight |
| `GET /api/study?channels=…` | Full niche study (minutes, not seconds) |
| `GET /api/study/stream?channels=…` | Same, as server-sent events with progress |
| `GET /api/analyze?url=…` | Single-video comment intelligence |
| `GET /api/analyze/stream?url=…` | Same, streamed |
| `GET /api/export/{id}/gaps.csv` | Content gaps as CSV |
| `GET /api/export/{id}/themes.csv` | Themes as CSV |
| `GET /api/export/{id}/overlap.csv` | Audience overlap edges as CSV |
| `GET /api/export/{id}.json` | Full report |

Interactive docs at **/docs**.

---

## Project layout

```
app/
  main.py        FastAPI routes, SSE progress streaming, CSV/JSON export
  niche.py       Corpus building, content gaps, overlap graph, drift, products
  analysis.py    Single-video report + timestamp heatmap
  extraction.py  Map-reduce engine, sync and Batches API paths, usage metering
  schemas.py     Structured-output models + strict JSON Schema
  youtube.py     Channels, batched video fetch, comments, quota metering
  textutil.py    Tokenising, normalisation, timestamp parsing
  demo.py        Pre-computed sample reports (no keys needed)
  config.py      Keys and model selection
static/          Frontend — hand-rolled SVG charts, no CDN, light + dark
cli.py           Command-line interface
```

---

## Read this before quoting any number

These ship inside every report, and they are not boilerplate:

- **Commenters are not viewers.** Roughly one viewer in several hundred
  comments, and those who do skew engaged and opinionated. Every count is a
  measure of intensity among the vocal minority, not of the audience.
- **Sampling is capped per video**, so videos with huge comment counts are
  under-sampled relative to smaller ones.
- **Themes are clustered by a language model.** The counts are exact; the
  grouping is a judgment call. Spot-check against the quoted examples.
- **Comment order matters.** `time` sampling is the default for studies because
  `relevance` surfaces high-engagement comments and biases the draw. Single-video
  mode defaults to `relevance`, which is right for a highlight reel and wrong for
  research.

**Before building anything that stores a corpus long-term**, check the current
[YouTube API Services Terms](https://developers.google.com/youtube/terms/api-services-terms-of-service).
There are rules on retaining and refreshing API data that constrain how a
persistent panel can work. Nothing here persists anything to disk today — reports
live in memory until the process exits — but that is the first thing to verify if
you add storage.

---

## Troubleshooting

- **"YouTube API quota exceeded"** — 10,000 units/day. Run `python cli.py estimate`
  before large studies; quota resets at midnight Pacific.
- **"No channel found for handle @…"** — handles resolve via `forHandle`. Try the
  `UC…` channel ID from the channel's page source if a custom URL fails.
- **"The model hit its output limit"** — lower `NICHE_BATCH_SIZE` (default 50).
- **"Could not initialise the Anthropic client"** — set `ANTHROPIC_API_KEY` or run
  `ant auth login`.
- **A study seems slow** — it is fetching hundreds of pages and running hundreds
  of model requests. Use the streaming endpoint or the CLI to watch progress, and
  raise `NICHE_CONCURRENCY` if you have the rate limits for it.
