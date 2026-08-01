/* YouTube Audience Research — frontend.
   No external libraries: every chart is hand-rolled SVG/CSS so the page works
   offline and renders identically in light and dark. */

const $ = (id) => document.getElementById(id);
const state = { mode: "study", report: null, source: null };

const KINDS = ["request", "complaint", "question", "confusion", "correction", "praise"];
const KIND_LABEL = {
  request: "Requests", complaint: "Complaints", question: "Questions",
  confusion: "Confusion", correction: "Factual pushback", praise: "What worked",
};

const esc = (v) => String(v ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v) => (Number(v) || 0).toLocaleString();
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/* ---------------- theme ---------------- */

const savedTheme = localStorage.getItem("theme");
if (savedTheme) document.documentElement.dataset.theme = savedTheme;

$("themeToggle").addEventListener("click", () => {
  const isDark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  const next = isDark ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("theme", next);
  if (state.report) render(state.report);   // re-draw SVGs against the new surface
});

/* ---------------- setup ---------------- */

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => {
      t.classList.toggle("is-active", t === tab);
      t.setAttribute("aria-selected", String(t === tab));
    });
    state.mode = tab.dataset.mode;
    $("studyFields").hidden = state.mode !== "study";
    $("videoFields").hidden = state.mode !== "video";
    $("report").hidden = true;
  });
});

fetch("/api/status").then((r) => r.json()).then((s) => {
  const chip = $("keyStatus");
  const missing = [];
  if (!s.youtube_key_configured) missing.push("YouTube");
  if (!s.anthropic_key_configured) missing.push("Anthropic");
  if (missing.length) {
    chip.textContent = `${missing.join(" + ")} key missing — demo only`;
    chip.className = "chip chip-warn";
  } else {
    chip.textContent = `ready · ${s.map_model}${s.batch_api ? " · batch" : ""}`;
    chip.className = "chip chip-ok";
  }
}).catch(() => { $("keyStatus").textContent = "status unavailable"; });

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
    const est = await (await fetch(`/api/estimate?${params}`)).json();
    box.innerHTML = `Plan: <b>${est.videos}</b> videos · about <b>${num(est.estimated_units)}</b>
      of ${num(est.daily_free_tier)} daily quota units
      — roughly <b>${est.studies_per_day}</b> studies/day on the free tier.`;
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
    if (!channels) return;
    params.set("channels", channels);
    params.set("videos_per_channel", $("videosPer").value);
    params.set("comments_per_video", $("commentsPer").value);
    params.set("sort_by", $("sortBy").value);
    url = `/api/study/stream?${params}`;
  } else {
    const videoUrl = $("videoUrl").value.trim();
    if (!videoUrl) return;
    params.set("url", videoUrl);
    params.set("max_comments", $("videoComments").value);
    url = `/api/analyze/stream?${params}`;
  }

  $("error").hidden = true;
  $("report").hidden = true;
  $("progress").hidden = false;
  $("progressFill").style.width = "2%";
  $("progressLabel").textContent = "Starting…";
  $("runBtn").disabled = true;

  const source = new EventSource(url);
  state.source = source;

  source.onmessage = (message) => {
    const event = JSON.parse(message.data);
    if (event.type === "progress") {
      const pct = event.total ? Math.round((event.done / event.total) * 100) : 0;
      const stage = { channels: "Resolving channels", comments: "Fetching comments",
                      extract: "Extracting themes" }[event.stage] || event.stage;
      $("progressFill").style.width = `${Math.max(2, pct)}%`;
      $("progressLabel").textContent = `${stage} — ${event.done} of ${event.total}`;
    } else if (event.type === "done") {
      source.close(); state.source = null;
      $("progressFill").style.width = "100%";
      $("progress").hidden = true;
      $("runBtn").disabled = false;
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

function fail(detail) {
  $("progress").hidden = true;
  $("runBtn").disabled = false;
  $("error").hidden = false;
  $("error").textContent = detail;
}

/* ---------------- tooltip ---------------- */

const tip = $("tooltip");
document.addEventListener("mouseover", (event) => {
  const target = event.target.closest("[data-tip]");
  if (!target) return;
  tip.innerHTML = target.dataset.tip;
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

/** Horizontal magnitude bar. Rounded data-end, square against the baseline. */
function bar(value, max, color, tipText) {
  const pct = max > 0 ? Math.max(1.5, (value / max) * 100) : 0;
  return `<div class="barwrap" data-tip="${esc(tipText)}" style="background:var(--gridline);
    height:9px;border-radius:0 4px 4px 0;overflow:hidden">
    <div style="width:${pct}%;height:100%;background:${color};border-radius:0 4px 4px 0"></div></div>`;
}

/** Diverging bar around a neutral midpoint: negative left, positive right. */
function divergingBar(value, tipText) {
  const half = Math.min(50, Math.abs(value) * 50);
  const positive = value >= 0;
  return `<div data-tip="${esc(tipText)}" style="position:relative;height:9px;
      background:var(--div-mid);border-radius:4px">
    <div style="position:absolute;top:0;bottom:0;${positive ? "left:50%" : `right:50%`};
      width:${half}%;background:${positive ? "var(--div-pos)" : "var(--div-neg)"};
      border-radius:${positive ? "0 4px 4px 0" : "4px 0 0 4px"}"></div>
    <div style="position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;
      background:var(--baseline)"></div></div>`;
}

/** Two-segment stacked bar with the required 2px surface gap between fills. */
function stackedBar(left, right, leftColor, rightColor, tipText) {
  const total = left + right || 1;
  return `<div data-tip="${esc(tipText)}" style="display:flex;gap:2px;height:9px">
    <div style="flex:${left / total};background:${leftColor};border-radius:4px 0 0 4px"></div>
    <div style="flex:${right / total};background:${rightColor};border-radius:0 4px 4px 0"></div></div>`;
}

/** Small-multiple column chart for a month->count series. */
function monthChart(months) {
  const entries = Object.entries(months);
  if (!entries.length) return "";
  const width = 230, height = 68, pad = 16;
  const max = Math.max(...entries.map(([, v]) => v));
  const step = (width - pad) / entries.length;
  const barWidth = Math.max(4, step - 4);

  const bars = entries.map(([month, value], index) => {
    const h = max > 0 ? Math.max(2, (value / max) * (height - pad)) : 2;
    const x = index * step + 2;
    const y = height - pad - h;
    return `<rect x="${x}" y="${y}" width="${barWidth}" height="${h}" rx="4" ry="4"
      fill="var(--mark)" data-tip="<b>${esc(month)}</b><br>${num(value)} comments"></rect>`;
  }).join("");

  const labels = entries.map(([month], index) =>
    (index === 0 || index === entries.length - 1)
      ? `<text x="${index * step + barWidth / 2 + 2}" y="${height - 3}" font-size="9"
           fill="var(--text-muted)" text-anchor="middle">${esc(month.slice(2))}</text>`
      : "").join("");

  return `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" role="img"
    aria-label="Monthly volume">
    <line x1="0" y1="${height - pad}" x2="${width}" y2="${height - pad}"
      stroke="var(--baseline)" stroke-width="1"/>${bars}${labels}</svg>`;
}

/** Circular node-link graph. Identity comes from direct labels, not hue — that
    keeps it clear of the all-pairs categorical cap. */
function overlapGraph(nodes, edges) {
  if (nodes.length < 2) return "";
  const size = 460, cx = size / 2, cy = size / 2, radius = size / 2 - 96;
  const maxCommenters = Math.max(...nodes.map((n) => n.commenters));
  const maxShared = Math.max(...edges.map((e) => e.shared), 1);

  const points = nodes.map((node, index) => {
    const angle = (index / nodes.length) * Math.PI * 2 - Math.PI / 2;
    return { ...node, x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius, angle };
  });
  const byName = Object.fromEntries(points.map((p) => [p.channel, p]));

  const links = edges.map((edge) => {
    const a = byName[edge.source], b = byName[edge.target];
    if (!a || !b) return "";
    const width = 1 + (edge.shared / maxShared) * 9;
    return `<path d="M${a.x} ${a.y} Q ${cx} ${cy} ${b.x} ${b.y}" fill="none"
      stroke="var(--mark)" stroke-opacity="0.45" stroke-width="${width.toFixed(1)}"
      stroke-linecap="round"
      data-tip="<b>${esc(edge.source)} ↔ ${esc(edge.target)}</b><br>
        ${num(edge.shared)} shared commenters<br>Jaccard ${edge.jaccard}<br>
        ${edge.pct_of_source}% of ${esc(edge.source)}, ${edge.pct_of_target}% of ${esc(edge.target)}"/>`;
  }).join("");

  const dots = points.map((point) => {
    const r = 8 + (point.commenters / maxCommenters) * 14;
    const right = Math.cos(point.angle) > -0.1;
    return `<g>
      <circle cx="${point.x}" cy="${point.y}" r="${r}" fill="var(--mark)"
        stroke="var(--surface-1)" stroke-width="2"
        data-tip="<b>${esc(point.channel)}</b><br>${num(point.commenters)} commenters<br>
          ${point.exclusive_pct}% exclusive to this channel"/>
      <text x="${point.x + (right ? r + 6 : -r - 6)}" y="${point.y + 4}" font-size="11"
        fill="var(--text-primary)" text-anchor="${right ? "start" : "end"}">${esc(point.channel)}</text>
      <text x="${point.x + (right ? r + 6 : -r - 6)}" y="${point.y + 17}" font-size="9.5"
        fill="var(--text-muted)" text-anchor="${right ? "start" : "end"}">${point.exclusive_pct}% exclusive</text>
    </g>`;
  }).join("");

  return `<svg viewBox="0 0 ${size} ${size}" width="100%" style="max-width:${size}px;margin:0 auto"
    role="img" aria-label="Audience overlap between channels">${links}${dots}</svg>`;
}

/* ---------------- sections ---------------- */

const card = (title, note, body) => `<section class="card">
  <h2>${esc(title)}${note ? `<span class="note">${esc(note)}</span>` : ""}</h2>
  <div class="card-body">${body}</div></section>`;

function tiles(pairs) {
  return `<div class="tiles">${pairs.map(([k, v]) =>
    `<div class="tile"><span class="v">${v}</span><span class="k">${esc(k)}</span></div>`).join("")}</div>`;
}

function quoteBlock(example) {
  if (!example || !example.quote) return "";
  const meta = [example.author, example.channel, `${num(example.likes)} likes`]
    .filter(Boolean).join(" · ");
  return `<blockquote class="quote">“${esc(example.quote)}”<cite>${esc(meta)}</cite></blockquote>`;
}

function gapsSection(gaps) {
  if (!gaps?.length) return "";
  const max = Math.max(...gaps.map((g) => g.gap_score));
  const body = gaps.map((gap, index) => `
    <article class="gap">
      <div class="gap-head">
        <span class="gap-rank">${index + 1}</span>
        <span class="kind" data-k="${esc(gap.kind)}">${esc(gap.kind)}</span>
        <span class="gap-title">${esc(gap.title)}</span>
        <span class="coverage" data-c="${esc(gap.coverage)}">${
          gap.coverage === "none" ? "unserved" : gap.coverage}</span>
      </div>
      <p class="gap-desc">${esc(gap.description)}</p>
      ${bar(gap.gap_score, max, "var(--mark)",
        `<b>Gap score ${gap.gap_score}</b><br>demand weighted by how unmet it is`)}
      <div class="gap-meta" style="margin-top:8px">
        <span>${num(gap.count)} comments</span>
        <span>${num(gap.likes)} likes</span>
        <span>${gap.channel_spread} channel${gap.channel_spread === 1 ? "" : "s"}</span>
        ${gap.closest_video ? `<span>closest: “${esc(gap.closest_video.title)}”</span>` : ""}
      </div>
      ${quoteBlock(gap.examples?.[0])}
    </article>`).join("");
  return card("Content gaps", "demand ranked by how poorly the published catalogue covers it", body);
}

function risingSection(rising) {
  if (!rising?.length) return "";
  const body = `<div class="rows">${rising.map((row) => `
    <div class="rowitem">
      <span class="nm"><span class="kind" data-k="${esc(row.kind)}">${esc(row.kind)}</span>
        ${esc(row.title)}</span>
      ${bar(row.lift, Math.max(...rising.map((r) => r.lift)), "var(--mark)",
        `<b>${row.lift}× over baseline</b><br>${row.recent} of ${row.total} in the last 90 days`)}
      <span class="val">${row.lift}× · ${row.recent}/${row.total}</span>
    </div>`).join("")}</div>`;
  return card("Rising", "accelerating faster than the corpus as a whole", body);
}

function themesSection(themes) {
  const present = KINDS.filter((kind) => themes?.[kind]?.length);
  if (!present.length) return "";
  const legend = `<div class="legend">${present.map((kind) =>
    `<span><i class="swatch" style="background:var(--series-${KINDS.indexOf(kind) + 1})"></i>
      ${esc(KIND_LABEL[kind])}</span>`).join("")}</div>`;

  const body = present.map((kind) => {
    const list = themes[kind].slice(0, 6);
    const max = Math.max(...list.map((t) => t.count));
    return `<h3 style="font-size:.86rem;margin:16px 0 8px;font-weight:600">
        ${esc(KIND_LABEL[kind])}</h3>
      <div class="rows">${list.map((theme) => `
        <div class="rowitem">
          <span class="nm" title="${esc(theme.description)}">${esc(theme.title)}</span>
          ${bar(theme.count, max, `var(--series-${KINDS.indexOf(kind) + 1})`,
            `<b>${esc(theme.title)}</b><br>${esc(theme.description)}<br>
             ${num(theme.count)} comments · ${num(theme.likes)} likes`)}
          <span class="val">${num(theme.count)}</span>
        </div>`).join("")}</div>`;
  }).join("");
  return card("Themes", "clustered from deduplicated statements", legend + body);
}

function overlapSection(overlap) {
  if (!overlap?.nodes?.length) return "";
  const table = `<div class="scroll-x"><table class="data">
    <thead><tr><th>Channel A</th><th>Channel B</th><th class="num">Shared</th>
      <th class="num">Jaccard</th><th class="num">% of A</th><th class="num">% of B</th></tr></thead>
    <tbody>${overlap.edges.map((e) => `<tr><td>${esc(e.source)}</td><td>${esc(e.target)}</td>
      <td class="num">${num(e.shared)}</td><td class="num">${e.jaccard}</td>
      <td class="num">${e.pct_of_source}%</td><td class="num">${e.pct_of_target}%</td></tr>`).join("")}
    </tbody></table></div>`;
  return card("Audience overlap", overlap.note,
    overlapGraph(overlap.nodes, overlap.edges) +
    `<p style="font-size:.8rem;color:var(--text-muted);margin:10px 0 14px;text-align:center">
      Node size is commenters sampled; link thickness is shared commenters.</p>` + table);
}

function productsSection(products) {
  if (!products?.length) return "";
  const legend = `<div class="legend">
    <span><i class="swatch" style="background:var(--div-pos)"></i>Recommends</span>
    <span><i class="swatch" style="background:var(--div-neg)"></i>Warns against</span></div>`;
  const max = Math.max(...products.map((p) => p.mentions));
  const body = `<div class="rows">${products.map((product) => `
    <div class="rowitem">
      <span class="nm">${esc(product.product)}</span>
      <div style="display:grid;gap:5px">
        ${bar(product.mentions, max, "var(--mark)",
          `<b>${esc(product.product)}</b><br>${num(product.mentions)} mentions ·
           ${product.channel_spread} channels`)}
        ${divergingBar(product.net_stance,
          `<b>Net stance ${product.net_stance >= 0 ? "+" : ""}${product.net_stance}</b><br>
           ${product.recommends} recommend · ${product.warns_against} warn against`)}
      </div>
      <span class="val">${num(product.mentions)}<br>
        <small style="color:var(--text-muted)">${product.net_stance >= 0 ? "+" : ""}${product.net_stance}</small></span>
    </div>`).join("")}</div>`;
  return card("Products by share of voice", "counted from the audience's words, not the script",
    legend + body);
}

function trustSection(trust) {
  if (!trust?.length) return "";
  const legend = `<div class="legend">
    <span><i class="swatch" style="background:var(--div-pos)"></i>Purchase intent + deference</span>
    <span><i class="swatch" style="background:var(--div-neg)"></i>Sponsorship doubt + expertise challenge</span></div>`;
  const body = `<div class="rows">${trust.map((row) => {
    const credible = row.purchase_intent + row.deference;
    const doubtful = row.sponsorship_skepticism + row.expertise_challenge;
    return `<div class="rowitem">
      <span class="nm">${esc(row.channel)}</span>
      ${stackedBar(credible, doubtful, "var(--div-pos)", "var(--div-neg)",
        `<b>${esc(row.channel)}</b><br>${row.purchase_intent} purchase intent ·
         ${row.deference} deference<br>${row.sponsorship_skepticism} sponsorship doubt ·
         ${row.expertise_challenge} expertise challenge`)}
      <span class="val">${row.trust_ratio}</span>
    </div>`;
  }).join("")}</div>`;
  return card("Trust signals by channel", "the influencer-vetting view — not polarity", legend + body);
}

function driftSection(drift) {
  if (!drift?.length) return "";
  const body = `<div class="smalls">${drift.map((row) => `
    <div class="small">
      <h3>${esc(row.title)}</h3>
      <p class="cap">${esc(row.kind)}</p>
      ${monthChart(row.months)}
    </div>`).join("")}</div>`;
  return card("Theme drift", "monthly comment volume per theme", body);
}

function vocabSection(vocabulary) {
  if (!vocabulary?.length) return "";
  const body = `<div class="tags">${vocabulary.map((row) =>
    `<span class="tag">${esc(row.term)} <b>${num(row.count)}</b></span>`).join("")}</div>`;
  return card("Audience vocabulary", "creator and title vocabulary subtracted out", body);
}

function timestampsSection(moments) {
  if (!moments?.length) return "";
  const max = Math.max(...moments.map((m) => m.count));
  const body = `<div class="rows">${moments.map((moment) => `
    <div class="rowitem">
      <span class="nm" style="font-variant-numeric:tabular-nums">${esc(moment.timestamp)}</span>
      ${bar(moment.count, max, "var(--mark)",
        `<b>${esc(moment.timestamp)}</b><br>${num(moment.count)} mentions ·
         ${num(moment.likes)} likes<br>${esc(moment.examples?.[0]?.quote || "")}`)}
      <span class="val">${num(moment.count)} mentions</span>
    </div>`).join("")}</div>`;
  return card("Moments the audience reacted to", "parsed from timestamps in the comments", body);
}

function questionsSection(questions) {
  if (!questions?.length) return "";
  const body = `<div class="scroll-x"><table class="data">
    <thead><tr><th>Question</th><th class="num">Asked by</th><th class="num">Likes</th></tr></thead>
    <tbody>${questions.map((row) => `<tr>
      <td><strong>${esc(row.question)}</strong>
        ${row.example ? `<div style="color:var(--text-muted);font-size:.82rem">
          “${esc(row.example)}”</div>` : ""}</td>
      <td class="num">${num(row.asked_by)}</td><td class="num">${num(row.likes)}</td>
    </tr>`).join("")}</tbody></table></div>`;
  return card("Top unanswered questions", "the cheapest reply a creator can make", body);
}

function footerSection(report) {
  const id = report._id || "";
  const quota = report.quota || {}, usage = report.usage || {};
  const isStudy = !!report.study;
  const exports = isStudy
    ? [["Content gaps CSV", `gaps.csv`], ["Themes CSV", `themes.csv`], ["Overlap CSV", `overlap.csv`]]
    : [["Themes CSV", `themes.csv`]];

  const links = exports.map(([label, file]) =>
    `<a class="btn" href="/api/export/${encodeURIComponent(id)}/${file}" download>${label}</a>`).join("")
    + `<a class="btn" href="/api/export/${encodeURIComponent(id)}.json" download>Full JSON</a>`;

  const cost = usage.estimated_cost_usd
    ? `~$${Number(usage.estimated_cost_usd).toFixed(2)}` : "—";

  return card("Cost, exports and caveats", "", `
    ${tiles([
      ["YouTube quota units", num(quota.units)],
      ["Model requests", num(usage.requests)],
      ["Estimated model cost", cost],
      ["Batched", usage.batched ? "yes" : "no"],
    ])}
    <div class="exports" style="margin:18px 0">${links}</div>
    <ul class="caveats">${(report.caveats || []).map((c) => `<li>${esc(c)}</li>`).join("")}</ul>`);
}

/* ---------------- render ---------------- */

function render(report) {
  state.report = report;
  const box = $("report");

  if (report.study) {
    const study = report.study;
    box.innerHTML =
      card(study.label, report.demo ? "pre-computed sample data" : "", `
        ${tiles([
          ["Channels", num(study.channels.length)],
          ["Videos sampled", num(study.videos_sampled)],
          ["Comments sampled", num(study.comments_sampled)],
          ["Items extracted", num(study.items_extracted)],
          ["Distinct statements", num(study.distinct_statements)],
          ["Spam filtered", num(study.spam_filtered)],
        ])}
        <div class="tags" style="margin-top:16px">${study.channels.map((channel) =>
          `<span class="tag">${esc(channel.title)}
            <b>${channel.subscribers ? num(channel.subscribers) + " subs" : ""}</b></span>`).join("")}
        </div>`)
      + gapsSection(report.content_gaps)
      + risingSection(report.rising)
      + themesSection(report.themes)
      + overlapSection(report.audience_overlap)
      + productsSection(report.products)
      + trustSection(report.trust)
      + driftSection(report.drift)
      + vocabSection(report.vocabulary)
      + footerSection(report);
  } else {
    const video = report.video, summary = report.summary;
    box.innerHTML =
      card(video.title, video.channel, `
        ${tiles([
          ["Views", num(video.view_count)],
          ["Comments analysed", num(summary.comments_analyzed)],
          ["Items extracted", num(summary.items_extracted)],
          ["Distinct statements", num(summary.distinct_statements)],
          ["Spam filtered", num(summary.spam_filtered)],
        ])}`)
      + questionsSection(report.questions)
      + themesSection(report.themes)
      + timestampsSection(report.timestamps)
      + productsSection(report.products)
      + vocabSection(report.vocabulary)
      + footerSection(report);
  }

  box.hidden = false;
  box.scrollIntoView({ behavior: "smooth", block: "start" });
}
