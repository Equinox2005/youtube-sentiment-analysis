/* YouTube Sentiment Insights — frontend logic */

const $ = (id) => document.getElementById(id);

const state = { mode: "single", charts: {} };

const COLORS = { pos: "#2ed573", neg: "#ff6b6b", neu: "#a4b0be" };

/* ---------- setup ---------- */

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    state.mode = tab.dataset.mode;
    $("url-b").classList.toggle("hidden", state.mode !== "compare");
    $("url-b").required = state.mode === "compare";
    $("results").classList.add("hidden");
    $("compare-results").classList.add("hidden");
  });
});

fetch("/api/status")
  .then((r) => r.json())
  .then((s) => {
    if (!s.api_key_configured) $("key-banner").classList.remove("hidden");
  })
  .catch(() => {});

$("analyze-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  hideError();
  setLoading(true);
  try {
    if (state.mode === "single") await runSingle();
    else await runCompare();
  } catch (err) {
    showError(err.message || "Something went wrong.");
  } finally {
    setLoading(false);
  }
});

/* ---------- API ---------- */

async function apiGet(path, params) {
  const qs = new URLSearchParams(params).toString();
  const res = await fetch(`${path}?${qs}`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}

async function runSingle() {
  const report = await apiGet("/api/analyze", {
    url: $("url-a").value.trim(),
    max_comments: $("max-comments").value,
    sort_by: $("sort-by").value,
    include_transcript: $("include-transcript").checked,
  });
  renderReport(report);
}

async function runCompare() {
  const data = await apiGet("/api/compare", {
    url_a: $("url-a").value.trim(),
    url_b: $("url-b").value.trim(),
    max_comments: Math.min(+$("max-comments").value, 2000),
  });
  renderCompare(data.a, data.b);
}

/* ---------- rendering: single ---------- */

function renderReport(r) {
  $("compare-results").classList.add("hidden");
  $("results").classList.remove("hidden");

  const v = r.video;
  const s = r.summary;

  $("video-card").innerHTML = `
    ${v.thumbnail ? `<img src="${esc(v.thumbnail)}" alt="thumbnail" />` : ""}
    <div class="meta">
      ${r.demo ? '<span class="demo-pill">DEMO DATA</span>' : ""}
      <h2>${esc(v.title)}</h2>
      <p>📺 ${esc(v.channel)}</p>
      <p>👁 ${fmt(v.view_count)} views · 👍 ${fmt(v.like_count)} likes · 💬 ${fmt(v.comment_count)} comments</p>
      <p>Published ${v.published_at ? v.published_at.slice(0, 10) : "—"}</p>
    </div>`;

  $("verdict").textContent = s.verdict;
  $("health-fill").style.width = `${s.health_score}%`;
  $("health-label").textContent = `Community health score: ${s.health_score}/100`;

  $("key-numbers").innerHTML = `
    <li><span>Comments analyzed</span><span class="val">${fmt(s.total_comments)}</span></li>
    <li><span>Positive</span><span class="val pos">${s.positive} (${s.positive_pct}%)</span></li>
    <li><span>Negative</span><span class="val neg">${s.negative} (${s.negative_pct}%)</span></li>
    <li><span>Neutral</span><span class="val">${s.neutral} (${s.neutral_pct}%)</span></li>
    <li><span>Avg sentiment</span><span class="val ${cls(s.avg_compound)}">${s.avg_compound}</span></li>
    <li><span>Like-weighted sentiment</span><span class="val ${cls(s.weighted_compound)}">${s.weighted_compound}</span></li>`;

  drawPie(s);
  drawTimeline(r.timeline);
  renderKeywords(r.keywords);
  renderAgreement(r);
  renderComments("top-positive", r.top_positive);
  renderComments("top-negative", r.top_negative);
  renderComments("most-liked", r.most_liked);

  $("export-csv").href = `/api/export/${v.video_id}.csv`;
  $("export-json").href = `/api/export/${v.video_id}.json`;

  $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

function drawPie(s) {
  destroyChart("pie");
  state.charts.pie = new Chart($("pie-chart"), {
    type: "doughnut",
    data: {
      labels: ["Positive", "Negative", "Neutral"],
      datasets: [{
        data: [s.positive, s.negative, s.neutral],
        backgroundColor: [COLORS.pos, COLORS.neg, COLORS.neu],
        borderWidth: 0,
      }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { color: "#9aa1b2" } } },
    },
  });
}

function drawTimeline(timeline) {
  destroyChart("timeline");
  const hasData = timeline && timeline.length > 1;
  $("timeline-chart").parentElement.style.opacity = hasData ? 1 : 0.4;
  state.charts.timeline = new Chart($("timeline-chart"), {
    type: "line",
    data: {
      labels: hasData ? timeline.map((t) => t.period) : ["no date data"],
      datasets: [{
        label: "Avg sentiment (-1 to 1)",
        data: hasData ? timeline.map((t) => t.avg_compound) : [0],
        borderColor: "#ff4757",
        backgroundColor: "rgba(255,71,87,0.15)",
        fill: true,
        tension: 0.35,
        pointRadius: 3,
      }],
    },
    options: {
      maintainAspectRatio: false,
      scales: {
        y: { min: -1, max: 1, grid: { color: "#262b3a" }, ticks: { color: "#9aa1b2" } },
        x: { grid: { display: false }, ticks: { color: "#9aa1b2" } },
      },
      plugins: { legend: { labels: { color: "#9aa1b2" } } },
    },
  });
}

function renderKeywords(keywords) {
  const max = keywords.length ? keywords[0].count : 1;
  $("keywords").innerHTML = keywords.length
    ? keywords
        .map((k) => {
          const size = 0.8 + (k.count / max) * 0.7;
          return `<span class="kw" style="font-size:${size}rem" title="${k.count} comments">${esc(k.word)}</span>`;
        })
        .join("")
    : '<p class="muted">No keywords found.</p>';
}

function renderAgreement(r) {
  const card = $("agreement-card");
  if (!r.agreement) {
    card.querySelector("#agreement").innerHTML = `<p class="muted">
      ${r.video_sentiment.label === "unknown"
        ? "No transcript available for this video, so agreement can't be measured."
        : "The video's tone is neutral, so agreement isn't meaningful here."}</p>`;
    return;
  }
  const a = r.agreement;
  const total = a.agree + a.disagree + a.neutral || 1;
  const pct = (n) => Math.round((n / total) * 100);
  card.querySelector("#agreement").innerHTML = `
    <div class="agree-bar">
      ${a.agree ? `<div class="seg agree" style="flex:${a.agree}">${pct(a.agree)}%</div>` : ""}
      ${a.disagree ? `<div class="seg disagree" style="flex:${a.disagree}">${pct(a.disagree)}%</div>` : ""}
      ${a.neutral ? `<div class="seg neutral" style="flex:${a.neutral}">${pct(a.neutral)}%</div>` : ""}
    </div>
    <p class="agree-caption">
      Video tone: <b>${esc(r.video_sentiment.label)}</b> (score ${r.video_sentiment.compound}).
      ${a.agree} comments share that tone, ${a.disagree} oppose it, ${a.neutral} are neutral.
      Among opinionated comments, <b>${a.agree_pct}%</b> agree with the video.
    </p>`;
}

function renderComments(elId, comments) {
  $(elId).innerHTML = comments.length
    ? comments
        .map(
          (c) => `
      <div class="comment ${c.label}">
        <p class="text">${esc(truncate(c.text, 280))}</p>
        <p class="meta">
          <span>${esc(c.author || "anonymous")}</span>
          <span>👍 ${fmt(c.likes)}</span>
          <span>score ${c.compound}</span>
          ${c.published_at ? `<span>${c.published_at.slice(0, 10)}</span>` : ""}
        </p>
      </div>`
        )
        .join("")
    : '<p class="muted">None found.</p>';
}

/* ---------- rendering: compare ---------- */

function renderCompare(a, b) {
  $("results").classList.add("hidden");
  $("compare-results").classList.remove("hidden");

  $("compare-cards").innerHTML = [a, b]
    .map(
      (r, i) => `
    <div class="card compare-summary">
      <h2>${i === 0 ? "🅰" : "🅱"} ${esc(r.video.title)}</h2>
      <p class="muted">${esc(r.video.channel)} · ${fmt(r.summary.total_comments)} comments analyzed</p>
      <p class="big ${cls(r.summary.avg_compound)}">${r.summary.health_score}/100</p>
      <p>${esc(r.summary.verdict)}</p>
    </div>`
    )
    .join("");

  destroyChart("compare");
  state.charts.compare = new Chart($("compare-chart"), {
    type: "bar",
    data: {
      labels: ["Positive %", "Negative %", "Neutral %", "Health score"],
      datasets: [
        {
          label: truncate(a.video.title, 40),
          data: [a.summary.positive_pct, a.summary.negative_pct, a.summary.neutral_pct, a.summary.health_score],
          backgroundColor: "#ff4757",
        },
        {
          label: truncate(b.video.title, 40),
          data: [b.summary.positive_pct, b.summary.negative_pct, b.summary.neutral_pct, b.summary.health_score],
          backgroundColor: "#5352ed",
        },
      ],
    },
    options: {
      maintainAspectRatio: false,
      scales: {
        y: { beginAtZero: true, grid: { color: "#262b3a" }, ticks: { color: "#9aa1b2" } },
        x: { grid: { display: false }, ticks: { color: "#9aa1b2" } },
      },
      plugins: { legend: { labels: { color: "#9aa1b2" } } },
    },
  });

  $("compare-results").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- helpers ---------- */

function destroyChart(name) {
  if (state.charts[name]) {
    state.charts[name].destroy();
    delete state.charts[name];
  }
}

function setLoading(on) {
  $("loading").classList.toggle("hidden", !on);
  $("analyze-btn").disabled = on;
}

function showError(msg) {
  const box = $("error-box");
  box.textContent = msg;
  box.classList.remove("hidden");
}

function hideError() {
  $("error-box").classList.add("hidden");
}

function esc(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

function fmt(n) {
  return Number(n || 0).toLocaleString();
}

function truncate(text, n) {
  return text.length > n ? text.slice(0, n - 1) + "…" : text;
}

function cls(score) {
  return score > 0.05 ? "pos" : score < -0.05 ? "neg" : "";
}
