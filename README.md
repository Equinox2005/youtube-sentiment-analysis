# ▶ YouTube Sentiment Insights

**A web app that shows you how an audience *really* feels about any YouTube video.**

Paste a video URL and get an interactive dashboard: sentiment breakdown, community
health score, sentiment trends over time, top keywords, the most loved/hated comments,
whether commenters agree with the video itself, side-by-side video comparison, and
CSV/JSON export.

Runs entirely on your machine — no accounts, no tracking.

---

## 🌟 What it does

| Feature | Why it's useful |
|---|---|
| **Sentiment breakdown** (positive / negative / neutral) | Instant read on audience reception |
| **Community health score** (0–100) & plain-English verdict | One number to compare videos at a glance |
| **Like-weighted sentiment** | Weighs opinions by likes — what the community *endorses*, not just what it says |
| **Sentiment over time** | See if reception improved or soured after upload (great for spotting controversies) |
| **Top keywords** | What the conversation is actually about |
| **Most positive / negative / liked comments** | Jump straight to the strongest reactions |
| **Transcript agreement** | Does the audience agree with the video's own tone/message? |
| **Compare two videos** | A/B thumbnails, competitors, before/after apology videos… |
| **Export CSV / JSON** | Take the scored comments into Excel, pandas, wherever |
| **Demo mode** | Try everything without an API key — just type `demo` |

### Who benefits
- **Creators** — read the room across thousands of comments in seconds; track reception over time.
- **Marketers / brands** — vet influencers and measure campaign reception before partnering.
- **Researchers / students** — export scored comment datasets with one click.
- **Viewers** — check if a video is community-approved before spending 40 minutes on it.

---

## 🎯 Accuracy

Earlier versions used a Naïve Bayes bag-of-words model trained on 2009-era tweets
(Sentiment140), which required a manual 1.6M-row dataset download and misread modern
comment language. This version uses **VADER**, a rule-based model built specifically
for social-media text. It correctly handles:

- **Negation** — "not good at all" → negative
- **Intensity** — "AMAZING!!!" scores higher than "amazing"
- **Emoji** — 🔥 ❤️ 💀 are scored
- **Slang** — plus a custom YouTube lexicon (`goated`, `mid`, `clickbait`, `W`, `L`, …)
- **Neutrality** — "Who's watching in 2026?" is neutral, not forced into pos/neg
- Long transcripts are scored in chunks to avoid saturation
- URLs and video timestamps (e.g. `10:24`) are stripped before scoring

No dataset download, no training step — it just works.

---

## 🛠 Setup

### 1. Install

```bash
git clone https://github.com/Equinox2005/youtube-sentiment-analysis.git
cd youtube-sentiment-analysis
pip install -r requirements.txt
```

### 2. Get a YouTube API key (free)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → enable **YouTube Data API v3** → create an **API key**
3. Provide it via environment variable, or copy `.env.example` to `.env` and paste it in:

```bash
# Windows (PowerShell)
$env:YOUTUBE_API_KEY = "your-key-here"

# macOS / Linux
export YOUTUBE_API_KEY="your-key-here"
```

> **No key yet?** Type `demo` as the URL in the app (or run `python cli.py demo`)
> to explore the full experience with bundled sample data.

### 3. Run the web app

```bash
uvicorn app.main:app
```

Open **http://127.0.0.1:8000** — paste a URL, hit **Analyze**.

---

## 💻 Command line

The same engine is available as a CLI:

```bash
python cli.py "https://www.youtube.com/watch?v=VIDEO_ID" --comments 1000 --sort top
python cli.py demo                          # sample data, no key needed
python cli.py VIDEO_ID --json report.json --csv comments.csv
```

---

## 🔌 API

The web UI is powered by a JSON API you can call directly:

| Endpoint | Description |
|---|---|
| `GET /api/analyze?url=…&max_comments=500&sort_by=relevance` | Full report for one video |
| `GET /api/compare?url_a=…&url_b=…` | Two reports for side-by-side comparison |
| `GET /api/export/{video_id}.csv` | Scored comments as CSV (analyze first) |
| `GET /api/export/{video_id}.json` | Full report as JSON |
| `GET /api/status` | Whether an API key is configured |

Interactive docs at **http://127.0.0.1:8000/docs**.

---

## 📁 Project layout

```
app/
  main.py        FastAPI app + API routes
  analysis.py    Report builder (breakdown, timeline, keywords, agreement…)
  sentiment.py   VADER engine + YouTube slang lexicon + keyword extraction
  youtube.py     YouTube Data API: metadata, comments, transcripts
  demo.py        Bundled sample data (demo mode)
  config.py      API key loading (.env / environment)
static/          Web frontend (HTML/CSS/JS + Chart.js)
cli.py           Command-line interface
```

---

## 🔧 Troubleshooting

- **"YouTube API quota exceeded"** — the free tier allows ~10,000 units/day; fetching
  comments costs 1 unit per 100 comments. Wait for the daily reset or request more quota.
- **"Comments are disabled for this video"** — nothing to analyze on that video.
- **"No transcript available"** — agreement analysis is skipped; everything else still works.
- **Charts don't load** — Chart.js is loaded from a CDN; check your internet connection.
