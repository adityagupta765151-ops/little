/* Reads /api/state and draws. Every number shown comes from the database;
   nothing is computed hopefully or filled in for effect. */

const $ = (id) => document.getElementById(id);
let data = null;

const fmtTime = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? String(iso).slice(0, 16).replace("T", " ")
                  : d.toLocaleString("en-GB", { day: "2-digit", month: "short",
                                                hour: "2-digit", minute: "2-digit" });
};

const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

const statusWord = (s) => (s || "").replace(/_/g, " ").toLowerCase();

/* Job links come from the job boards, not from us. Only a real web address
   becomes a link; anything else — javascript:, data:, a bare string — is
   dropped, so a posting can't hand this page a script to run on click. */
function safeUrl(url) {
  try {
    const parsed = new URL(String(url || ""));
    return (parsed.protocol === "https:" || parsed.protocol === "http:") ? parsed.href : null;
  } catch (e) {
    return null;
  }
}

function postingLink(url) {
  const href = safeUrl(url);
  if (!href) return null;
  const link = el("a", null, "Open posting");
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

/* ------------------------------------------------------------- tiles */

function tile(value, label, tone) {
  const node = el("div", "tile" + (tone ? " " + tone : ""));
  node.append(el("b", null, String(value)), el("span", null, label));
  return node;
}

function drawTiles() {
  const c = data.counts;
  const box = $("tiles");
  box.replaceChildren(
    tile(c.jobs_today, "found today"),
    tile(c.jobs_total, "jobs stored"),
    tile((data.jobs.filter((j) => j.match_score >= 70)).length, "match 70+"),
    tile(c.applied, "applied", c.applied ? "good" : null),
    tile(c.submitted || 0, "verified submitted", c.submitted ? "good" : null),
    tile(c.needs_action, "prepared, waiting", c.needs_action ? "warning" : null),
    tile(c.failed, "couldn't open", c.failed ? "serious" : null),
  );
}

/* ------------------------------------------------------------- job card */

function jobCard(job) {
  const card = el("article", "card");

  const head = el("header");
  const left = el("div");
  left.append(el("h3", null, job.title), el("div", "company", job.company));
  const score = el("div", "score");
  score.append(el("b", null, job.match_score), el("span", null, "MATCH"));
  head.append(left, score);

  const meta = el("div", "meta");
  [job.location || "location not stated", job.work_mode,
   job.employment_type, job.seniority,
   job.salary || "salary not stated"].filter(Boolean)
    .forEach((m) => meta.append(el("span", null, m)));

  // Age and board sit on their own line: how old a posting is decides
  // whether any of the rest is worth reading.
  const line = el("div", "meta age");
  line.append(el("span", job.stale ? "old" : null, job.posted_phrase
    ? "posted " + job.posted_phrase + (job.stale ? " — likely filled" : "")
    : "no date given"));
  line.append(el("span", "board", "via " + (job.platform || "unknown board")));

  const chips = el("div", "chips");
  (job.skills_matched || []).slice(0, 7)
    .forEach((s) => chips.append(el("span", "chip have", s)));
  (job.skills_partial || []).slice(0, 4)
    .forEach((s) => chips.append(el("span", "chip partial", "~" + s)));
  (job.skills_missing || []).slice(0, 5)
    .forEach((s) => chips.append(el("span", "chip gap", s)));

  // A concern isn't a reason to skip the job — it's a fact to know going
  // in, so it's never hidden but never phrased as a verdict either.
  const concerns = (job.score_breakdown && job.score_breakdown.concerns) || [];
  const warn = el("div", "concerns");
  concerns.slice(0, 3).forEach((c) => warn.append(el("p", "concern", "⚠ " + c)));

  const foot = el("footer");
  foot.append(el("span", "status " + (job.status || "").toLowerCase(), statusWord(job.status)));
  const link = postingLink(job.url);
  if (link) foot.append(link);

  card.append(head, meta, line);
  if (chips.children.length) card.append(chips);
  if (warn.children.length) card.append(warn);
  if (job.why) card.append(el("p", "why", job.why));
  card.append(foot);
  return card;
}

function drawJobs() {
  const needle = $("search").value.trim().toLowerCase();
  const min = Number($("minScore").value);
  const status = $("statusFilter").value;

  const shown = data.jobs.filter((job) => {
    if (job.match_score < min) return false;
    if (status && job.status !== status) return false;
    if (!needle) return true;
    const hay = [job.company, job.title, job.location,
                 ...(job.skills_required || [])].join(" ").toLowerCase();
    return hay.includes(needle);
  });

  $("jobsCount").textContent = `${shown.length} of ${data.jobs.length}`;
  const box = $("jobCards");
  box.replaceChildren();
  if (!shown.length) {
    box.append(el("p", "empty", data.jobs.length
      ? "Nothing matches those filters."
      : `No jobs stored yet. Tell ${who()}: find jobs for me`));
    return;
  }
  shown.forEach((job) => box.append(jobCard(job)));
}

/* ------------------------------------------------------------- applications */

function drawApplications() {
  const box = $("appFeed");
  box.replaceChildren();
  if (!data.applications.length) {
    box.append(el("p", "empty", "Nothing recorded yet."));
    return;
  }
  data.applications.forEach((app) => {
    const row = el("div", "event");
    row.append(el("time", null, fmtTime(app.applied_at) || "not submitted"));

    const body = el("div", "body");
    body.append(el("h3", null, `${app.title} — ${app.company}`));
    const line = el("div", "row");
    line.append(el("span", "status " + (app.status || "").toLowerCase(), statusWord(app.status)));
    line.append(el("span", "meta", `${app.platform || "unknown board"} · match ${app.match_score}`));
    const link = postingLink(app.url);
    if (link) line.append(link);
    body.append(line);
    if (app.notes) body.append(el("p", null, app.notes));
    row.append(body);
    box.append(row);
  });
}

/* ------------------------------------------------------------- charts */

/* One series per chart, so magnitude is the only thing colour encodes and
   a categorical palette never comes into it. Values are labelled, so the
   bar length is a convenience rather than the only way to read it. */
function drawBars(target, pairs, emptyText) {
  const box = $(target);
  box.replaceChildren();
  if (!pairs.length) {
    box.append(el("p", "empty", emptyText));
    return;
  }
  const max = Math.max(...pairs.map(([, n]) => n)) || 1;
  pairs.forEach(([name, n]) => {
    const row = el("div", "bar");
    row.append(el("span", "name", name));
    const track = el("span", "track");
    const fill = el("span", "fill");
    fill.style.width = Math.max(2, (n / max) * 100) + "%";
    track.append(fill);
    row.append(track, el("span", "value", n));
    box.append(row);
  });
}

function drawAnalytics() {
  const c = data.counts;
  $("rates").replaceChildren(
    tile(c.attempts, "attempts"),
    tile(c.applied, "applied", c.applied ? "good" : null),
    tile(c.submitted || 0, "verified submitted"),
    tile(c.success_rate + "%", "success rate"),
    tile(c.avg_score, "avg match"),
    tile(c.interviews, "interviews"),
    tile(c.offers, "offers"),
  );

  drawBars("missingChart", data.missing_skills,
           "No jobs scored yet, so there is nothing to compare against.");
  drawBars("platformChart", Object.entries(c.by_platform || {}), "No jobs stored yet.");
  drawBars("locationChart", Object.entries(c.by_location || {}), "No jobs stored yet.");
}

/* ------------------------------------------------------------- resume + log */

function drawResume() {
  const r = data.resume;
  const box = $("resumePanel");
  box.replaceChildren();

  if (!r.name && !r.skills.length) {
    box.append(el("p", "empty", `No resume scanned. Tell ${who()}: scan my resume followed by the file name`));
    return;
  }

  const dl = el("dl", "kv");
  const rows = [
    ["Name", r.name || "not stated"],
    ["Degree", [r.degree, r.graduation_year].filter(Boolean).join(", ") || "not stated"],
    ["Location", r.location || "not stated"],
    ["Target roles", r.roles.join(", ") || `not set — tell ${who()}: set roles to ...`],
    ["Skills", r.skills.join(", ") || "none found"],
    ["Projects", r.projects.join(" · ") || "none found"],
    ["Source file", r.file || "unknown"],
  ];
  rows.forEach(([k, v]) => { dl.append(el("dt", null, k), el("dd", null, v)); });
  box.append(dl);
}

function drawLog() {
  const body = $("logRows");
  body.replaceChildren();
  if (!data.audit.length) {
    const row = el("tr");
    const cell = el("td", "empty", "Nothing logged yet.");
    cell.colSpan = 5;
    row.append(cell);
    body.append(row);
    return;
  }
  data.audit.forEach((entry) => {
    const row = el("tr");
    [fmtTime(entry.timestamp), entry.action, entry.platform || "",
     entry.company || entry.job || "", entry.error || entry.result || ""]
      .forEach((v) => row.append(el("td", null, v)));
    body.append(row);
  });
}

/* ------------------------------------------------------------- shell */

function drawAll() {
  drawTiles();
  const box = $("dashCards");
  box.replaceChildren();
  const strong = data.jobs.slice(0, 6);
  if (!strong.length) {
    box.append(el("p", "empty", `No jobs yet. Tell ${who()}: find jobs for me`));
  } else {
    strong.forEach((job) => box.append(jobCard(job)));
  }

  const statuses = [...new Set(data.jobs.map((j) => j.status))].sort();
  const select = $("statusFilter");
  const keep = select.value;
  select.replaceChildren(el("option", null, "Any status"));
  select.firstChild.value = "";
  statuses.forEach((s) => {
    const option = el("option", null, statusWord(s));
    option.value = s;
    select.append(option);
  });
  select.value = keep;

  drawJobs();
  drawApplications();
  drawAnalytics();
  drawResume();
  drawLog();
}

/* The assistant's name, as Python reports it, for the hints that tell you
   what to say. "Little" before the first reading. */
function who() {
  const name = (data && data.assistant) || "Little";
  return name.charAt(0) + name.slice(1).toLowerCase();
}

function paintName() {
  const name = ((data && data.assistant) || "LITTLE").toUpperCase();
  $("brandName").textContent = name;
  document.title = name + " · Job Hunter";
}

async function refresh() {
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    data = await response.json();
    paintName();
    drawAll();
    $("updated").textContent = "updated " + new Date().toLocaleTimeString("en-GB");
  } catch (e) {
    $("updated").textContent = `${who()} isn't reachable`;
  }
}

$("tabs").addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b === button));
  document.querySelectorAll(".view").forEach((v) =>
    v.classList.toggle("on", v.dataset.view === button.dataset.view));
});

["search", "statusFilter"].forEach((id) => $(id).addEventListener("input", () => data && drawJobs()));
$("minScore").addEventListener("input", (e) => {
  $("minScoreOut").textContent = e.target.value;
  if (data) drawJobs();
});

setInterval(() => {
  $("clock").textContent = new Date().toLocaleTimeString("en-GB", { hour12: false });
}, 500);

refresh();
setInterval(refresh, 4000);
