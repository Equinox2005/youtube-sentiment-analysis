/* YouTube Audience Research - frontend.
   No libraries: the charts are small hand-written SVG/CSS, coloured through CSS
   variables so they follow the light/dark theme without re-rendering. */

const $ = (id) => document.getElementById(id);
const state = { mode: "study", source: null };

const KINDS = ["request", "complaint", "question", "confusion", "correction", "praise"];
const KIND_GROUP = {
  request: "Requests", complaint: "Complaints", question: "Questions",
  confusion: "Confusion", correction: "Factual pushback", praise: "What worked",
};
const KIND_NAME = {
  request: "Request", complaint: "Complaint", question: "Question",
  confusion: "Confusion", correction: "Correction", praise: "Praise",
};
const STAGES = {
  channels: "Resolving channels", comments: "Fetching comments",
  extract: "Reading comments", themes: "Clustering themes",
};

const esc = (v) => String(v ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v) => (Number(v) || 0).toLocaleString();
const plural = (n, word) => `${num(n)} ${word}${n === 1 ? "" : "s"}`;
const compact = (v) => new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 })
  .format(Number(v) || 0);
const signed = (v) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}`;

function monthLabel(month) {
  const [year, m] = month.split("-").map(Number);
  if (!year || !m) return month;
  return new Date(Date.UTC(year, m - 1, 1))
    .toLocaleString(undefined, { month: "short", year: "numeric", timeZone: "UTC" });
}

/* ---------------- theme ---------------- */

try {
  const saved = localStorage.getItem("theme");
  if (saved) document.documentElement.dataset.theme = saved;
} catch { /* storage unavailable: follow the system theme */ }

$("themeToggle").addEventListener("click", () => {
  const isDark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  const next = isDark ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("theme", next); } catch { /* not persisted */ }
});

/* ---------------- setup ---------------- */

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => {
      t.classList.toggle("is-active", t === tab);
      t.setAttribute("aria-selected", String(t === tab));
    });
    state.mode = tab.dataset.mode;
    showFields();
  });
});

// A hidden field that fails validation would block the form without a message,
// so the fields of the other mode are disabled as well as hidden.
function showFields() {
  for (const [id, mode] of [["studyFields", "study"], ["videoFields", "video"]]) {
    $(id).hidden = state.mode !== mode;
    $(id).querySelectorAll("input, textarea, select").forEach((el) => { el.disabled = state.mode !== mode; });
  }
}
showFields();

fetch("/api/status").then((r) => r.json()).then((s) => {
  const missing = [];
  if (!s.youtube_key_configured) missing.push("YouTube");
  if (!s.anthropic_key_configured) missing.push("Anthropic");
  const models = s.map_model === s.reduce_model ? s.map_model : `${s.map_model} / ${s.reduce_model}`;
  $("keyStatus").textContent = missing.length
    ? `No ${missing.join(" or ")} key set, demo only`
    : `${models}${s.batch_api ? ", batched" : ""}`;
}).catch(() => { $("keyStatus").textContent = ""; });

async function updateEstimate() {
  const refs = $("channels").value.split(/[,\n]/).map((s) => s.trim()).filter(Boolean);
  const box = $("quotaEstimate");
  if (!refs.length || (refs.length === 1 && refs[0].toLowerCase() === "demo")) {
    box.textContent = ""; return;
  }
  const params = new URLSearchParams({
    channels: refs.length, videos_per_channel: $("videosPer").value,
    comments_per_video: $("commentsPer").value,
  });
  try {
    const response = await fetch(`/api/estimate?${params}`);
    if (!response.ok) { box.textContent = ""; return; }
    const est = await response.json();
    const perDay = est.studies_per_day >= 1
      ? `about ${est.studies_per_day} studies like this a day on the free tier`
      : "more than the free tier allows in a day";
    box.textContent = `Uses up to ${num(est.estimated_units)} of ${num(est.daily_free_tier)} daily `
      + `YouTube quota units, ${perDay}.`;
  } catch { box.textContent = ""; }
}
["channels", "videosPer", "commentsPer"].forEach((id) =>
  $(id).addEventListener("input", updateEstimate));

$("demoBtn").addEventListener("click", () => {
  if (state.mode === "study") $("channels").value = "demo";
  else $("videoUrl").value = "demo";
  $("runForm").requestSubmit();
});

/* ---------------- run ---------------- */

$("runForm").addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.source) state.source.close();

  const params = new URLSearchParams();
  let url;
  if (state.mode === "study") {
    const channels = $("channels").value.trim();
    if (!channels) { $("channels").focus(); return; }
    params.set("channels", channels);
    // An emptied number box falls back to the API's default.
    if ($("videosPer").value) params.set("videos_per_channel", $("videosPer").value);
    if ($("commentsPer").value) params.set("comments_per_video", $("commentsPer").value);
    params.set("sort_by", $("sortBy").value);
    if ($("studyName").value.trim()) params.set("label", $("studyName").value.trim());
    url = `/api/study/stream?${params}`;
  } else {
    const videoUrl = $("videoUrl").value.trim();
    if (!videoUrl) { $("videoUrl").focus(); return; }
    params.set("url", videoUrl);
    if ($("videoComments").value) params.set("max_comments", $("videoComments").value);
    url = `/api/analyze/stream?${params}`;
  }

  $("error").hidden = true;
  $("report").hidden = true;
  $("progress").hidden = false;
  $("progressFill").style.width = "2%";
  $("progressLabel").textContent = "Starting…";
  setBusy(true);

  const source = new EventSource(url);
  state.source = source;

  source.onmessage = (message) => {
    const event = JSON.parse(message.data);
    if (event.type === "progress") {
      const pct = event.total ? Math.round((event.done / event.total) * 100) : 0;
      $("progressFill").style.width = `${Math.max(2, pct)}%`;
      $("progressLabel").textContent =
        `${STAGES[event.stage] || event.stage}: ${event.done} of ${event.total}`;
    } else if (event.type === "done") {
      source.close(); state.source = null;
      $("progress").hidden = true;
      setBusy(false);
      render(event.report);
    } else if (event.type === "error") {
      source.close(); state.source = null;
      fail(event.detail);
    }
  };
  source.onerror = () => {
    source.close(); state.source = null;
    fail("Lost the connection to the server.");
  };
});

// The demo button submits the same form, so it would cut off a run in progress.
function setBusy(busy) {
  $("runBtn").disabled = busy;
  $("demoBtn").disabled = busy;
}

function fail(detail) {
  $("progress").hidden = true;
  setBusy(false);
  $("error").hidden = false;
  $("error").textContent = detail;
}

/* ---------------- tooltip ---------------- */

const tip = $("tooltip");
document.addEventListener("mouseover", (event) => {
  const target = event.target.closest("[data-tip]");
  if (!target) return;
  tip.innerHTML = target.dataset.tip;   // built from escaped values below
  tip.hidden = false;
});
document.addEventListener("mousemove", (event) => {
  if (tip.hidden) return;
  const pad = 14;
  const x = Math.min(event.clientX + pad, innerWidth - tip.offsetWidth - 8);
  const y = Math.min(event.clientY + pad, innerHeight - tip.offsetHeight - 8);
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${Math.max(8, y)}px`;
});
document.addEventListener("mouseout", (event) => {
  if (event.target.closest("[data-tip]")) tip.hidden = true;
});

/* ---------------- chart primitives ---------------- */

/** One horizontal bar: square at the baseline, rounded at the data end. */
function bar(value, max, tipHtml) {
  const pct = max > 0 ? Math.max(1, (value / max) * 100) : 0;
  return `<div class="bar" data-tip="${esc(tipHtml)}"><span class="bar-fill" style="width:${pct}%"></span></div>`;
}

/** Stacked bar. Segments are [{value, cls}]; total length is relative to `max`. */
function stackedBar(segments, max, tipHtml) {
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  const width = max > 0 ? Math.max(1, (total / max) * 100) : 0;
  const parts = segments.filter((s) => s.value > 0)
    .map((s) => `<span class="${s.cls}" style="flex:${s.value} 1 0"></span>`).join("");
  return `<div class="bar" data-tip="${esc(tipHtml)}" style="width:${width}%">${parts}</div>`;
}

const barRow = (label, chart, value) => `<div class="bar-row">
  <div class="bar-label">${label}</div><div class="bar-track">${chart}</div>
  <div class="bar-value">${value}</div></div>`;

const barHead = (left, right) => `<div class="bar-row bar-head">
  <div class="bar-label label">${esc(left)}</div><div></div>
  <div class="bar-value label">${esc(right)}</div></div>`;

const legend = (items) => `<div class="legend">${items.map(([cls, text]) =>
  `<span><i class="swatch" style="background:var(${cls})"></i>${esc(text)}</span>`).join("")}</div>`;

/** Column path with rounded top corners and a square base. */
function columnPath(x, y, w, h, r) {
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}`
    + `Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

/** Small column chart for a month -> count series. */
function monthChart(months) {
  const keys = Object.keys(months).sort();
  if (!keys.length) return "";
  // Walk every month from the first to the last so a quiet month shows as a gap.
  const entries = [];
  let [year, month] = keys[0].split("-").map(Number);
  const [lastYear, lastMonth] = keys[keys.length - 1].split("-").map(Number);
  while (year < lastYear || (year === lastYear && month <= lastMonth)) {
    const key = `${year}-${String(month).padStart(2, "0")}`;
    entries.push([key, months[key] || 0]);
    if (++month > 12) { month = 1; year++; }
  }
  const width = 240, height = 76, axis = 20, plot = height - axis;
  const max = Math.max(...entries.map(([, v]) => v));
  const step = width / entries.length;
  const colWidth = Math.min(24, Math.max(step - 6, step / 2));

  const cols = entries.map(([month, value], i) => {
    if (!value) return "";
    const h = Math.max(2, (value / max) * (plot - 4));
    const x = i * step + (step - colWidth) / 2;
    return `<path d="${columnPath(x, plot - h, colWidth, h, 4)}" style="fill:var(--accent)"
      data-tip="${esc(`<b>${esc(monthLabel(month))}</b><br>${num(value)} comments`)}"/>`;
  }).join("");

  const first = (step - colWidth) / 2;
  const last = (entries.length - 1) * step + (step + colWidth) / 2;
  const axisLabel = (x, anchor, month) => `<text x="${x}" y="${height - 4}" font-size="11"
    style="fill:var(--muted)" text-anchor="${anchor}">${esc(monthLabel(month))}</text>`;

  return `<svg viewBox="0 0 ${width} ${height}" width="100%" role="img" aria-label="Comments per month">
    <line x1="0" y1="${plot}" x2="${width}" y2="${plot}" style="stroke:var(--baseline)" stroke-width="1"/>
    ${cols}${axisLabel(first, "start", entries[0][0])}
    ${entries.length > 1 ? axisLabel(last, "end", entries[entries.length - 1][0]) : ""}</svg>`;
}

/** Channels on a circle; circle size is commenters, line width is shared commenters. */
function overlapGraph(nodes, edges) {
  if (nodes.length < 2) return "";
  const size = 460, cx = size / 2, cy = size / 2, radius = size / 2 - 100;
  const maxCommenters = Math.max(...nodes.map((n) => n.commenters));
  const maxShared = Math.max(...edges.map((e) => e.shared), 1);

  const points = nodes.map((node, index) => {
    const angle = (index / nodes.length) * Math.PI * 2 - Math.PI / 2;
    const r = 6 + (node.commenters / maxCommenters) * 12;
    return { ...node, x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius, angle, r };
  });
  // Crop the square canvas to the nodes and their two label lines.
  const top = Math.min(...points.map((p) => p.y - p.r)) - 8;
  const bottom = Math.max(...points.map((p) => p.y + Math.max(p.r, 24))) + 8;
  const byName = Object.fromEntries(points.map((p) => [p.channel, p]));

  const links = edges.map((edge) => {
    const a = byName[edge.source], b = byName[edge.target];
    if (!a || !b) return "";
    const width = 1 + (edge.shared / maxShared) * 8;
    const tipHtml = `<b>${esc(edge.source)} and ${esc(edge.target)}</b><br>`
      + `${num(edge.shared)} shared commenters<br>Jaccard ${edge.jaccard}`;
    return `<path d="M${a.x} ${a.y} Q ${cx} ${cy} ${b.x} ${b.y}" fill="none"
      style="stroke:var(--accent)" stroke-opacity="0.4" stroke-width="${width.toFixed(1)}"
      stroke-linecap="round" data-tip="${esc(tipHtml)}"/>`;
  }).join("");

  const dots = points.map((point) => {
    const r = point.r;
    const right = Math.cos(point.angle) > -0.1;
    const lx = point.x + (right ? r + 8 : -r - 8);
    const anchor = right ? "start" : "end";
    const tipHtml = `<b>${esc(point.channel)}</b><br>${num(point.commenters)} commenters, `
      + `${point.exclusive_pct}% only here`;
    return `<g>
      <circle cx="${point.x}" cy="${point.y}" r="${r}" style="fill:var(--accent);stroke:var(--page)"
        stroke-width="2" data-tip="${esc(tipHtml)}"/>
      <text x="${lx}" y="${point.y + 4}" font-size="13" style="fill:var(--text)"
        text-anchor="${anchor}">${esc(point.channel)}</text>
      <text x="${lx}" y="${point.y + 20}" font-size="12" style="fill:var(--muted)"
        text-anchor="${anchor}">${point.exclusive_pct}% only here</text>
    </g>`;
  }).join("");

  return `<svg class="overlap-graph" viewBox="0 ${top} ${size} ${bottom - top}" width="100%" role="img"
    aria-label="Audience overlap between channels">${links}${dots}</svg>`;
}

/* ---------------- sections ---------------- */

const section = (title, body) => `<section class="section"><h2>${esc(title)}</h2>${body}</section>`;

const stats = (pairs) => `<dl class="stats">${pairs.map(([label, value]) =>
  `<div><dt>${esc(label)}</dt><dd>${value}</dd></div>`).join("")}</dl>`;

function quoteBlock(example) {
  if (!example || !example.quote) return "";
  const source = [example.author, example.channel, example.likes ? plural(example.likes, "like") : ""]
    .filter(Boolean).join(", ");
  return `<blockquote class="quote">“${esc(example.quote)}”<cite>${esc(source)}</cite></blockquote>`;
}

function coverageText(gap) {
  if (gap.coverage === "none" || !gap.closest_video) return "no existing video";
  const title = `“${esc(gap.closest_video.title)}”`;
  return gap.coverage === "covered" ? `covered by ${title}` : `partly covered by ${title}`;
}

function gapsSection(gaps) {
  if (!gaps?.length) return "";
  const items = gaps.map((gap, index) => `
    <li class="gap">
      <span class="gap-rank">${index + 1}</span>
      <div>
        <h3>${esc(gap.title)}</h3>
        <p class="gap-meta">${esc(KIND_NAME[gap.kind] || gap.kind)} · ${plural(gap.count, "comment")}
          · ${plural(gap.likes, "like")} · ${plural(gap.channel_spread, "channel")} · ${coverageText(gap)}</p>
        <p class="gap-desc">${esc(gap.description)}</p>
        ${quoteBlock(gap.examples?.[0])}
      </div>
    </li>`).join("");
  return section("Content gaps", `<ol class="gaps">${items}</ol>
    <p class="note">Coverage is checked against the videos sampled in this study, not each
      channel's whole catalogue.</p>`);
}

function risingSection(rising) {
  if (!rising?.length) return "";
  const max = Math.max(...rising.map((r) => r.lift));
  const days = (n) => `${num(n)} ${n === 1 ? "day" : "days"}`;
  const rows = rising.map((row) => barRow(
    `${esc(row.title)}<span class="desc">${esc(KIND_NAME[row.kind] || row.kind)} · ${num(row.recent)} of
      ${num(row.total)} comments in the last ${days(row.window_days)}</span>`,
    bar(row.lift, max, `<b>${row.lift}× the corpus rate</b>`),
    `${row.lift.toFixed(1)}×`,
  )).join("");
  return section("Rising", `<div class="bars">${barHead("Theme", "Lift")}${rows}</div>
    <p class="note">Lift compares a theme's share of comments from the last ${days(rising[0].window_days)}
      with the share for the corpus as a whole.</p>`);
}

function themesSection(themes) {
  const present = KINDS.filter((kind) => themes?.[kind]?.length);
  if (!present.length) return "";
  // One scale for every group, since they share the comments column.
  const max = Math.max(...present.flatMap((kind) => themes[kind].slice(0, 6).map((t) => t.count)));
  const groups = present.map((kind) => {
    const rows = themes[kind].slice(0, 6).map((theme) => barRow(
      `${esc(theme.title)}<span class="desc">${esc(theme.description)}</span>`,
      bar(theme.count, max, `<b>${esc(theme.title)}</b><br>${plural(theme.count, "comment")}, `
        + `${plural(theme.likes, "like")}, ${plural(theme.channel_spread, "channel")}`),
      num(theme.count),
    )).join("");
    return `<h3 class="subhead">${esc(KIND_GROUP[kind])}</h3><div class="bars">${rows}</div>`;
  }).join("");
  return section("Themes", `<div class="bars">${barHead("Theme", "Comments")}</div>${groups}`);
}

function overlapSection(overlap) {
  if (!(overlap?.nodes?.length >= 2)) return "";
  const table = !overlap.edges.length
    ? `<p>None of these channels share a sampled commenter.</p>`
    : `<div class="scroll-x"><table class="data">
    <thead><tr><th>Channel A</th><th>Channel B</th><th class="num">Shared</th>
      <th class="num">Jaccard</th><th class="num">% of A</th><th class="num">% of B</th></tr></thead>
    <tbody>${overlap.edges.map((e) => `<tr><td>${esc(e.source)}</td><td>${esc(e.target)}</td>
      <td class="num">${num(e.shared)}</td><td class="num">${e.jaccard.toFixed(3)}</td>
      <td class="num">${e.pct_of_source}%</td><td class="num">${e.pct_of_target}%</td></tr>`).join("")}
    </tbody></table></div>`;
  // Past seven channels the names beside the circle run into each other.
  const graph = overlap.nodes.length <= 7 ? overlapGraph(overlap.nodes, overlap.edges) : "";
  const figure = graph ? `<figure class="overlap-figure">${graph}
    <figcaption class="note">Circle size is commenters sampled; line width is commenters
      the two channels share.</figcaption></figure>` : "";
  return section("Audience overlap", `${figure}${table}<p class="note">${esc(overlap.note)}</p>`);
}

function productsSection(products) {
  if (!products?.length) return "";
  const max = Math.max(...products.map((p) => p.mentions));
  const rows = products.map((p) => {
    const other = Math.max(0, p.mentions - p.recommends - p.warns_against);
    const tipHtml = `<b>${esc(p.product)}</b><br>${num(p.recommends)} recommend, `
      + `${num(p.warns_against)} warn against, ${num(other)} neutral or comparing`;
    return barRow(
      `${esc(p.product)}<span class="desc">net ${signed(p.net_stance)} ·
        ${plural(p.channel_spread, "channel")}</span>`,
      stackedBar([
        { value: p.recommends, cls: "pos" },
        { value: other, cls: "mid" },
        { value: p.warns_against, cls: "neg" },
      ], max, tipHtml),
      num(p.mentions),
    );
  }).join("");
  return section("Products", legend([
    ["--pos", "Recommends"], ["--neutral-mark", "Neutral or comparing"], ["--neg", "Warns against"],
  ]) + `<div class="bars">${barHead("Product", "Mentions")}${rows}</div>`);
}

function trustSection(trust) {
  if (!trust?.length) return "";
  const rows = trust.map((row) => {
    const credible = row.purchase_intent + row.deference;
    const doubtful = row.sponsorship_skepticism + row.expertise_challenge;
    const tipHtml = `<b>${esc(row.channel)}</b><br>${num(row.purchase_intent)} purchase intent, `
      + `${num(row.deference)} deference<br>${num(row.sponsorship_skepticism)} sponsorship doubt, `
      + `${num(row.expertise_challenge)} expertise challenge`;
    return barRow(
      `${esc(row.channel)}<span class="desc">${plural(row.total, "signal")}</span>`,
      stackedBar([{ value: credible, cls: "pos" }, { value: doubtful, cls: "neg" }], credible + doubtful, tipHtml),
      `${Math.round(row.trust_ratio * 100)}%`,
    );
  }).join("");
  return section("Trust signals", legend([
    ["--pos", "Purchase intent, deference"], ["--neg", "Sponsorship doubt, expertise challenge"],
  ]) + `<div class="bars">${barHead("Channel", "Trusting")}${rows}</div>`);
}

function driftSection(drift) {
  if (!drift?.length) return "";
  const body = `<div class="smalls">${drift.map((row) => `
    <div class="small">
      <h3>${esc(row.title)}</h3>
      <p class="muted">${esc(KIND_NAME[row.kind] || row.kind)}</p>
      ${monthChart(row.months)}
    </div>`).join("")}</div>`;
  return section("Theme drift", body);
}

function vocabSection(vocabulary) {
  if (!vocabulary?.length) return "";
  return section("Audience vocabulary", `<ul class="vocab">${vocabulary.map((row) =>
    `<li><span>${esc(row.term)}</span><b>${num(row.count)}</b></li>`).join("")}</ul>`);
}

function timestampsSection(moments) {
  if (!moments?.length) return "";
  const max = Math.max(...moments.map((m) => m.count));
  const rows = moments.map((moment) => barRow(
    `<span style="font-variant-numeric:tabular-nums">${esc(moment.timestamp)}</span>
      ${moment.examples?.[0] ? `<span class="desc">“${esc(moment.examples[0].quote)}”</span>` : ""}`,
    bar(moment.count, max, `<b>${esc(moment.timestamp)}</b><br>${plural(moment.count, "mention")}, `
      + `${plural(moment.likes, "like")}`),
    num(moment.count),
  )).join("");
  return section("Moments people reacted to", `<div class="bars">${barHead("Timestamp", "Mentions")}${rows}</div>`);
}

function questionsSection(questions) {
  if (!questions?.length) return "";
  const body = `<div class="scroll-x"><table class="data">
    <thead><tr><th>Question</th><th class="num">Asked by</th><th class="num">Likes</th></tr></thead>
    <tbody>${questions.map((row) => `<tr>
      <td>${esc(row.question)}${row.example ? `<span class="sub">“${esc(row.example)}”</span>` : ""}</td>
      <td class="num">${num(row.asked_by)}</td><td class="num">${num(row.likes)}</td>
    </tr>`).join("")}</tbody></table></div>`;
  return section("Unanswered questions", body);
}

function closingSections(report) {
  const id = encodeURIComponent(report._id || "");
  const quota = report.quota || {}, usage = report.usage || {};
  // The server answers 404 for an export with no rows, so only offer the ones that have data.
  const files = [
    [report.content_gaps?.length, "Content gaps", "gaps.csv"],
    [Object.values(report.themes || {}).some((list) => list.length), "Themes", "themes.csv"],
    [report.audience_overlap?.edges?.length, "Audience overlap", "overlap.csv"],
  ].filter(([has]) => has).map(([, label, file]) => [label, file]);
  const links = files.map(([label, file]) =>
    `<a href="/api/export/${id}/${file}" download>${label} (CSV)</a>`).join("")
    + `<a href="/api/export/${id}.json" download>Full report (JSON)</a>`;

  const cost = [
    `${num(quota.units)} YouTube quota units`,
    plural(usage.requests || 0, "model request"),
    usage.estimated_cost_usd ? `about $${Number(usage.estimated_cost_usd).toFixed(2)} in model usage` : "",
    usage.batched ? "map pass batched" : "",
    usage.failed_requests ? `${plural(usage.failed_requests, "request")} skipped` : "",
  ].filter(Boolean).join(" · ");

  return section("Cost and downloads", `<p>${cost}</p><p class="downloads">${links}</p>`)
    + section("Caveats", `<ul class="caveats">${(report.caveats || [])
      .map((c) => `<li>${esc(c)}</li>`).join("")}</ul>`);
}

/* ---------------- render ---------------- */

function render(report) {
  const box = $("report");
  const sample = report.demo ? `<span class="tag">Sample data</span>` : "";

  if (report.study) {
    const study = report.study;
    // "The Coffee Bench (1.2M subscribers), Pull & Purge (486K), ..."
    let unit = " subscribers";
    const channels = study.channels.map((c) => {
      if (!c.subscribers) return esc(c.title);
      const count = `${compact(c.subscribers)}${unit}`;
      unit = "";
      return `${esc(c.title)} <span class="muted">(${count})</span>`;
    }).join(", ");
    box.innerHTML = `<header class="report-head">
        <h1>${esc(study.label)}</h1>
        <p class="report-meta">${sample}${channels}</p>
        ${stats([
          ["Channels", num(study.channels.length)],
          ["Videos", num(study.videos_sampled)],
          ["Comments", num(study.comments_sampled)],
          ["Items extracted", num(study.items_extracted)],
          ["Distinct statements", num(study.distinct_statements)],
          ["Spam removed", num(study.spam_filtered)],
        ])}
      </header>`
      + gapsSection(report.content_gaps)
      + risingSection(report.rising)
      + themesSection(report.themes)
      + overlapSection(report.audience_overlap)
      + productsSection(report.products)
      + trustSection(report.trust)
      + driftSection(report.drift)
      + vocabSection(report.vocabulary)
      + closingSections(report);
  } else {
    const video = report.video, summary = report.summary;
    box.innerHTML = `<header class="report-head">
        <h1>${esc(video.title)}</h1>
        <p class="report-meta">${sample}${esc(video.channel)} · ${plural(video.view_count, "view")}
          · ${plural(video.comment_count, "comment")}</p>
        ${stats([
          ["Comments analysed", num(summary.comments_analyzed)],
          ["Items extracted", num(summary.items_extracted)],
          ["Distinct statements", num(summary.distinct_statements)],
          ["Spam removed", num(summary.spam_filtered)],
        ])}
      </header>`
      + questionsSection(report.questions)
      + themesSection(report.themes)
      + timestampsSection(report.timestamps)
      + productsSection(report.products)
      + vocabSection(report.vocabulary)
      + closingSections(report);
  }

  box.hidden = false;
  box.scrollIntoView({ behavior: "smooth", block: "start" });
  // The server keeps recent reports, so the id in the address survives a reload.
  if (report._id) history.replaceState(null, "", `#${encodeURIComponent(report._id)}`);
}

// A reload reopens the report named in the address if the server still has it;
// `/?demo` opens straight into the sample report.
const openDemo = () => { if (new URLSearchParams(location.search).has("demo")) $("demoBtn").click(); };
const saved = location.hash.slice(1);
if (/^[\w-]+$/.test(saved)) {
  fetch(`/api/export/${saved}.json`)
    .then((r) => (r.ok ? r.json() : Promise.reject()))
    .then(render)
    .catch(() => { history.replaceState(null, "", location.pathname + location.search); openDemo(); });
} else openDemo();
