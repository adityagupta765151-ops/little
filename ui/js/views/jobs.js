/* LITTLE — Jobs.

   The stored jobs as cards, best match first, each showing what the score
   is made of: all nine parts with their weights, the skills you have, the
   ones you're close on and the ones you're missing, anything worth knowing
   before applying, how old the posting is and where it came from.

   Nothing here is estimated. Every number is read from the job store, and
   the score is never called a verdict — whether a job is worth applying to
   is yours to decide.

   Buttons run the existing job tools on that exact job (by id, not by name),
   as tasks you can follow on Home, in Chat and in the Task Center:
     Save / Saved       shortlist it, or put it back
     Prepare…           open the posting and fill in what your resume answers
                        — asks first, and never submits
     Update status      I applied (asks first; only you can say it), interview,
                        offer, rejected, withdrawn
     Open posting       in your normal browser; only a web address opens

   The list loads when you open the section and again after anything
   changes, not on every poll. */
(function () {
  const L = (window.Little = window.Little || {});
  const { h, bridge, safeUrl } = L;
  const $ = (id) => document.getElementById(id);

  // The nine parts of a score, in the order they weigh, with their weights.
  const DIMENSIONS = [
    ["skills", "Skills", 30], ["role", "Role", 16], ["seniority", "Seniority", 12],
    ["experience", "Experience", 12], ["location", "Location", 12],
    ["employment_type", "Job type", 6], ["work_mode", "Work mode", 6],
    ["education", "Education", 4], ["projects", "Projects", 2],
  ];

  // Chapter 27's statuses. "Applied" is your word; "Submitted" is verified.
  const STATUS = {
    FOUND: "New", ANALYZED: "Analyzed", SAVED: "Saved", PREPARED: "Prepared",
    USER_APPROVED: "Applied", SUBMITTED: "Submitted ✓", INTERVIEW: "Interview", OFFER: "Offer",
    REJECTED: "Rejected", WITHDRAWN: "Withdrawn",
  };
  const TONE = {
    PREPARED: "warn", USER_APPROVED: "info", SUBMITTED: "ok", INTERVIEW: "ok", OFFER: "ok",
    REJECTED: "bad",
  };
  const GROUPS = {
    all: () => true,
    new: (j) => j.status === "FOUND" || j.status === "ANALYZED",
    saved: (j) => j.status === "SAVED",
    ready: (j) => j.status === "PREPARED",
    applied: (j) => ["USER_APPROVED", "SUBMITTED", "INTERVIEW", "OFFER"].includes(j.status),
    closed: (j) => ["REJECTED", "WITHDRAWN"].includes(j.status),
  };
  // Past the point of saving or preparing.
  const MOVED_ON = ["USER_APPROVED", "SUBMITTED", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"];
  // The choices, in order; each card offers the ones Python says it can make.
  const TRACK = [
    ["applied", "I applied"], ["verify", "It's submitted — check the page"], ["interview", "Interview"],
    ["offer", "Offer"], ["rejected", "Rejected"], ["withdrawn", "Withdrawn"],
  ];
  const TRACK_STATUS = { applied: "USER_APPROVED", verify: "SUBMITTED", interview: "INTERVIEW",
    offer: "OFFER", rejected: "REJECTED", withdrawn: "WITHDRAWN" };
  const WEEK = 7 * 24 * 3600 * 1000;

  let data = null;            // the last snapshot from Python
  let loading = false;
  let reloadTimer = null;
  let statusTimer = null;
  const view = { group: "all", sort: "best", query: "", recent: false };

  /* ------------------------------------------------------------ helpers */

  function say(message) {
    $("jobsStatus").textContent = message || "";
    clearTimeout(statusTimer);
    if (message) statusTimer = setTimeout(() => { $("jobsStatus").textContent = ""; }, 6000);
  }

  function postedTime(job) {
    const t = Date.parse(job.posted_at || "");
    return Number.isFinite(t) ? t : null;
  }

  function keepFocus(container, draw) {
    const active = document.activeElement;
    const key = container.contains(active) && active.dataset ? active.dataset.key : null;
    draw();
    if (key) {
      const again = container.querySelector(`[data-key="${CSS.escape(key)}"]`);
      if (again && !again.disabled) again.focus();
    }
  }

  function words(job) {
    return [job.title, job.company, job.location, job.platform,
      ...(job.skills_matched || []), ...(job.skills_partial || []), ...(job.skills_missing || [])]
      .join(" ").toLowerCase();
  }

  /* -------------------------------------------------------------- cards */

  function dimensions(job) {
    const b = job.score_breakdown || {};
    const values = b.dimensions || {};
    const notes = b.notes || {};
    return h("ul", { class: "dims", aria: { label: "What the score is made of" } },
      DIMENSIONS.filter(([key]) => key in values).map(([key, label, weight]) => {
        const value = Math.max(0, Math.min(100, Number(values[key]) || 0));
        const fill = h("i");
        fill.style.width = value + "%";
        return h("li", { title: notes[key] || null },
          h("span", "dim-name", label, h("span", "dim-weight", ` ${weight}%`)),
          h("span", "bar", fill),
          h("span", "dim-val", String(value)));
      }));
  }

  function why(job) {
    const b = job.score_breakdown || {};
    const notes = b.notes || {};
    const rows = DIMENSIONS.filter(([key]) => notes[key]).map(([key, label]) =>
      h("li", null, h("b", null, label + ": "), notes[key]));
    if (b.weighted != null) rows.push(h("li", null, h("b", null, "Weighted total: "), `${b.weighted}/100`));
    if (b.capped_at != null) {
      rows.push(h("li", null, h("b", null, `Capped at ${b.capped_at}: `), b.cap_reason || ""));
    }
    const bridges = b.skill_bridges || {};
    (job.skills_partial || []).forEach((s) => {
      const have = bridges[s] || [];
      if (have.length) rows.push(h("li", null, h("b", null, `${s}: `), `you have ${have.join(", ")}`));
    });
    return h("details", "job-why",
      h("summary", { data: { key: `why-${job.job_id}` } }, "Why this score"),
      h("ul", null, rows),
      h("p", "job-verdict", "This is what lines up and what doesn't. Whether it's worth applying to is your call."));
  }

  function skills(job) {
    const chip = (cls, mark, word, s) => h("li", { class: `skill skill--${cls}` },
      h("span", { aria: { hidden: "true" } }, mark + " "), h("span", "sr-only", word + ": "), s);
    const items = [
      ...(job.skills_matched || []).map((s) => chip("have", "✓", "you have", s)),
      ...(job.skills_partial || []).map((s) => chip("near", "~", "close", s)),
      ...(job.skills_missing || []).map((s) => chip("gap", "✗", "missing", s)),
    ];
    return items.length ? h("ul", { class: "skills", aria: { label: "Skills" } }, items) : null;
  }

  function actions(job) {
    const act = (action, label, extra) => {
      const b = h("button", { class: "btn btn--sm", type: "button",
                              data: { key: `${action}-${job.job_id}`, act: action }, ...extra }, label);
      b.addEventListener("click", () => run(job, action));
      return b;
    };
    const out = [];
    if (safeUrl(job.url)) {
      const open = h("button", { class: "btn btn--sm btn--ghost", type: "button",
                                 data: { key: `open-${job.job_id}`, act: "open" } }, "Open posting");
      open.addEventListener("click", () => bridge.openPosting(job.job_id).then((why) => say(why || "Opened in your browser.")));
      out.push(open);
    }
    if (job.status === "FOUND" || job.status === "ANALYZED") out.push(act("save", "Save"));
    if (job.status === "SAVED") out.push(act("unsave", "Saved", { aria: { pressed: "true" }, title: "Saved. Press to put it back." }));
    if (!MOVED_ON.includes(job.status)) out.push(act("prepare", "Prepare application…"));

    const next = Array.isArray(job.next) ? job.next : [];
    const choices = TRACK.filter(([value]) => next.includes(value) && TRACK_STATUS[value] !== job.status);
    if (!choices.length) return h("div", "job-acts", out);
    const track = h("select", { class: "select select--sm", data: { key: `track-${job.job_id}` },
                                aria: { label: `Update the status of ${job.title} at ${job.company}` } },
      h("option", { value: "", selected: true, disabled: true }, "Update status…"),
      choices.map(([value, label]) => h("option", { value }, label)));
    track.addEventListener("change", () => {
      const action = track.value;
      track.value = "";
      if (action) run(job, action);
    });
    out.push(track);
    return h("div", "job-acts", out);
  }

  /* What happened to this job, oldest first, from the job store (Chapter 27). */
  const EVENT = {
    found: (e) => `found via ${e.source || "a search"}`,
    status: (e) => `${STATUS[e.from_status] || e.from_status || "?"} → ${STATUS[e.to_status] || e.to_status}`,
    migrated: (e) => `${STATUS[e.to_status] || e.to_status} (was ${e.from_status})`,
    analyzed: () => "analysis looked at",
    prepared: () => "prepared again",
    prepare_failed: () => "Prepare couldn't open it",
  };
  function history(job) {
    const events = Array.isArray(job.events) ? job.events : [];
    if (events.length < 2) return null;
    return h("details", { class: "job-history", data: { key: `history-${job.job_id}` } },
      h("summary", null, `History · ${events.length}`),
      h("ol", null, events.map((e) => h("li", null,
        h("time", null, String(e.at || "").replace("T", " ").slice(0, 16)), " ",
        (EVENT[e.kind] || (() => String(e.kind || "").replace(/_/g, " ")))(e),
        [e.note, e.evidence].filter(Boolean).length ? ` — ${[e.note, e.evidence].filter(Boolean).join("; ")}` : ""))));
  }

  function card(job) {
    const b = job.score_breakdown || {};
    const capped = b.capped_at != null;
    const age = job.posted_phrase ? `posted ${job.posted_phrase}` : "no posting date given";
    const facts = [job.location || "location not stated", job.work_mode, job.employment_type,
      job.salary].filter(Boolean);
    const concerns = b.concerns || [];

    return h("li", { class: "job-card", data: { job: job.job_id } },
      h("header", "job-head",
        h("div", "job-name",
          h("h3", null, job.title),
          h("p", "job-company", job.company)),
        h("div", { class: "job-score" + (capped ? " is-capped" : ""),
                   aria: { label: `Match ${job.match_score} out of 100` } },
          h("b", null, String(job.match_score)), h("span", null, "match"))),
      h("p", "job-facts", facts.join(" · ")),
      h("p", "job-age",
        h("span", job.stale ? "is-stale" : null, age + (job.stale ? ", so it may be filled" : "")),
        ` · via ${job.platform || "an unknown board"}`),
      capped ? h("p", "job-cap", `Capped at ${b.capped_at}: ${b.cap_reason || ""}`) : null,
      dimensions(job),
      skills(job),
      concerns.length ? h("ul", { class: "job-concerns", aria: { label: "Worth knowing" } },
        concerns.map((c) => h("li", null, c))) : null,
      why(job),
      history(job),
      h("footer", "job-foot",
        h("span", `badge badge--${TONE[job.status] || "info"}`, STATUS[job.status] || job.status),
        actions(job)));
  }

  /* ------------------------------------------------------------- render */

  function shown() {
    if (!data || !data.jobs) return [];
    const terms = view.query.toLowerCase().split(/\s+/).filter(Boolean);
    let list = data.jobs.filter(GROUPS[view.group])
      .filter((j) => terms.every((t) => words(j).includes(t)));
    if (view.recent) {
      // Like the job search itself: a posting with no date is kept, since
      // not knowing when it went up isn't evidence that it's old.
      const cutoff = Date.now() - WEEK;
      list = list.filter((j) => postedTime(j) === null || postedTime(j) >= cutoff);
    }
    if (view.sort === "newest") {
      list = list.slice().sort((a, b) => (postedTime(b) ?? -Infinity) - (postedTime(a) ?? -Infinity));
    } else if (view.sort === "found") {
      list = list.slice().sort((a, b) => String(b.discovered_at).localeCompare(String(a.discovered_at)));
    }
    return list;
  }

  function summary() {
    if (!data || !data.counts) return "";
    const c = data.counts;
    const parts = [`${c.jobs_total} stored`, `${c.jobs_today} found today`, `${c.applied} applied`];
    if (c.needs_action) parts.push(`${c.needs_action} need you`);
    if (data.jobs.length < c.jobs_total) parts.push(`showing the best ${data.jobs.length}`);
    return parts.join(" · ");
  }

  function render() {
    const list = $("jobsList");
    const empty = $("jobsEmpty");

    if (!data) { empty.hidden = false; empty.replaceChildren(loading ? "Loading jobs…" : ""); list.replaceChildren(); return; }
    if (data.error) {
      list.replaceChildren();
      empty.hidden = false;
      empty.replaceChildren(h("p", null, data.error), refreshButton());
      return;
    }

    document.querySelectorAll("#jobsFilters [data-group]").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.group === view.group));
      b.querySelector(".count").textContent = String(data.jobs.filter(GROUPS[b.dataset.group]).length);
    });
    $("jobsSummary").textContent = summary();
    const gaps = data.missing_skills || [];
    $("jobsGaps").hidden = !gaps.length;
    $("jobsGaps").textContent = gaps.length
      ? "Asked for often, not on your resume: " + gaps.slice(0, 8).map(([s, n]) => `${s} (${n})`).join(", ")
      : "";

    const jobs = shown();
    keepFocus(list, () => list.replaceChildren(...jobs.map(card)));

    empty.hidden = jobs.length > 0;
    if (!data.resume.ready) {
      empty.replaceChildren(
        h("p", null, "Scan your resume first — every job is scored against it."),
        goButton("resume", "Scan it in Resume"));
    } else if (!data.jobs.length) {
      empty.replaceChildren(
        h("p", null, "No jobs stored yet. Find jobs searches the boards and scores every result against your resume."),
        sendButton("find jobs for me", "Find jobs for me"));
    } else if (!jobs.length) {
      empty.replaceChildren("No jobs match. Clear the search or pick another filter.");
    }
  }

  function sendButton(command, label) {
    const b = h("button", { class: "btn btn--primary btn--sm", type: "button" }, label);
    b.addEventListener("click", () => L.actions.send(command));
    return b;
  }

  function goButton(section, label) {
    const b = h("button", { class: "btn btn--primary btn--sm", type: "button" }, label);
    b.addEventListener("click", () => L.router.go(section));
    return b;
  }

  function refreshButton() {
    const b = h("button", { class: "btn btn--sm", type: "button" }, "Try again");
    b.addEventListener("click", load);
    return b;
  }

  /* --------------------------------------------------------------- data */

  function load() {
    loading = true;
    if (!data) render();
    return bridge.jobs().then((snapshot) => {
      loading = false;
      data = snapshot && (snapshot.jobs || snapshot.error) ? snapshot
        : { error: "I couldn't read the job store." };
      render();
    });
  }

  /* After any task ends, the store may have changed — a job saved, a
     search finished — so read it again, once, if the section is open. */
  function reloadSoon() {
    clearTimeout(reloadTimer);
    reloadTimer = setTimeout(() => { if (L.router.current() === "jobs") load(); }, 150);
  }

  function run(job, action) {
    bridge.job(job.job_id, action).then((why) => {
      if (why) say(why);
      else say(action === "prepare" || action === "applied"
        ? "Check the question on screen." : "Done — the card updates in a moment.");
    });
  }

  /* ------------------------------------------------------------- wiring */

  document.querySelectorAll("#jobsFilters [data-group]").forEach((b) => {
    b.addEventListener("click", () => { view.group = b.dataset.group; render(); });
  });
  let searchTimer = null;
  $("jobsSearch").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { view.query = $("jobsSearch").value; render(); }, 150);
  });
  $("jobsSort").addEventListener("change", () => { view.sort = $("jobsSort").value; render(); });
  $("jobsRecent").addEventListener("change", () => { view.recent = $("jobsRecent").checked; render(); });
  $("jobsFind").addEventListener("click", () => L.actions.send("find jobs for me"));
  $("jobsRefresh").addEventListener("click", load);

  L.tasks.onChange(({ ended }) => { if (ended.length) reloadSoon(); });
  L.router.onChange((id) => { if (id === "jobs") load(); });
  // Opened straight onto Jobs: wait until Python can answer.
  window.addEventListener("pywebviewready", () => { if (L.router.current() === "jobs") load(); });

  L.jobs = { load };
})();
