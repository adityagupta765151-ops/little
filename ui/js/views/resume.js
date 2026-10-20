/* LITTLE — Resume.

   What LITTLE read from your resume, the job preferences the search uses,
   and six questions you can ask about it.

     Profile, and what's on it   read from resume_profile.json, as saved.
                                 Anything the resume didn't say reads "Not on
                                 your resume" — nothing is filled in here.
     Scan a resume…              the system's own file dialog. Python keeps
                                 the path and hands back only a number, which
                                 is all the page can scan by. With a profile
                                 already here, it asks first: a new scan
                                 replaces it (your own preferences stay).
     Job preferences             edited in place and saved together, checked
                                 by Python the way the job search reads them.
     The six questions           each runs as a task, so it also shows on
                                 Home, in Chat and in the Task Center:
       Analyze, Improve, Interview prep, Inconsistencies   ask the model,
         with your resume's own text (jarvis/jobs/advice.py)
       Skill gaps, Match   the existing job tools, on this computer

   The data loads when you open the section and again after a task ends,
   not on every poll. */
(function () {
  const L = (window.Little = window.Little || {});
  const { h, bridge } = L;
  const $ = (id) => document.getElementById(id);

  const OPEN = ["active", "waiting"];
  const TEXT_FIELDS = { roles: "cvRoles", locations: "cvLocations", countries: "cvCountries" };
  const CHECK_FIELDS = { work_modes: "cvModes", employment_types: "cvTypes" };
  const HINTS = { roles: "cvRolesHint", locations: "cvLocationsHint", countries: "cvCountriesHint",
                  work_modes: "cvModesHint", employment_types: "cvTypesHint" };
  const WORDS = {
    remote: "Remote", hybrid: "Hybrid", onsite: "On-site",
    "full-time": "Full-time", internship: "Internship", contract: "Contract",
    "part-time": "Part-time", temporary: "Temporary",
  };
  const LISTS = [
    ["skills", "Skills"], ["languages", "Programming languages"],
    ["frameworks", "Frameworks and libraries"], ["education", "Education"],
    ["projects", "Projects"], ["experience", "Experience"], ["internships", "Internships"],
    ["certifications", "Certifications"], ["achievements", "Achievements"], ["links", "Links"],
  ];
  // Marks as the resume writes them (Chapter 26). Read-only here: corrected by command.
  const SCORES = [["degree_score", "CGPA / %"], ["class_12", "Class 12"], ["class_10", "Class 10"]];
  // The words a reply uses for each field, for the rescan question.
  const FIELD_WORDS = {
    name: "name", email: "email", phone: "phone", location: "address", degree: "degree",
    graduation_year: "graduation year", degree_score: "CGPA or %", class_12: "Class 12 marks",
    class_10: "Class 10 marks", skills: "skills", languages: "languages", frameworks: "frameworks",
    projects: "projects", experience: "experience", internships: "internships",
    certifications: "certifications", education: "education", achievements: "achievements", links: "links",
  };
  const CHIPS = new Set(["skills", "languages", "frameworks"]);
  const TITLES = {
    analyze: "Analyze my resume", gaps: "Find my skill gaps", match: "Match my resume against the job",
    health: "Check my resume",
    improve: "Suggest improvements to my resume", interview: "Prepare me for an interview",
    inconsistencies: "Find inconsistencies in my resume",
  };
  const ARM_MS = 700;           // as the confirmation dialog: Yes can't be hit by accident

  let data = null;              // the last snapshot from Python
  let loading = false;
  let asked = null;             // the question being shown: { id, action }
  let scanning = null;          // the scan being followed: { id, name }
  let picked = null;            // a file chosen and waiting for "Scan it": { token, name }
  let shown = null;             // the preferences the form was last filled with
  let reloadTimer = null;
  let armTimer = null;

  /* ------------------------------------------------------------ helpers */

  function say(message) {
    $("cvStatus").textContent = message || "";
  }

  function duration(ms) {
    if (ms == null || !Number.isFinite(ms)) return "";
    if (ms < 1000) return `${Math.round(ms)} ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
    const s = Math.round(ms / 1000);
    return `${Math.floor(s / 60)}m ${s % 60}s`;
  }

  function when(iso) {
    const t = Date.parse(iso || "");
    if (!Number.isFinite(t)) return "";
    return new Date(t).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  }

  /* Still going? A task Python has started but the page hasn't heard of
     yet — the next poll brings it — counts as going. */
  function going(id) {
    if (id == null) return false;
    const task = L.tasks.get(id);
    return task ? OPEN.includes(task.status) : true;
  }

  /* A resume task is running — one this page started, or (after a reload)
     one Python says is. One at a time; Python refuses a second too. */
  function busy() {
    return going(asked && asked.id) || going(scanning && scanning.id) || going(data && data.running);
  }

  const split = (text) => text.split(/[,\n]/).map((v) => v.trim()).filter(Boolean);
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const sortedBy = (choices, list) => choices.filter((c) => list.includes(c));

  /* ------------------------------------------------------------ profile */

  function renderSource() {
    if (!data || data.error) { $("cvSource").textContent = ""; return; }
    if (!data.ready) { $("cvSource").textContent = "No resume read yet."; return; }
    const parts = [`Read from ${data.file || "a file"}`];
    if (data.scanned_at) parts.push(`scanned ${when(data.scanned_at)}`);
    if (!data.file_found) parts.push("the file isn't where it was, so the questions use the saved profile");
    $("cvSource").textContent = parts.join(" · ");
  }

  const missing = () => h("span", "cv-missing", "Not on your resume");
  const edited = (key) => (data.edited || []).includes(key);
  // A value you corrected by command says so, until a new scan replaces it.
  const yoursMark = (key) => (edited(key)
    ? [" ", h("span", { class: "badge badge--info", data: { edited: key } }, "corrected by you")] : []);

  function renderProfile() {
    const c = data.candidate;
    $("cvName").replaceChildren(c.name || missing(), ...yoursMark("name"));
    const degree = [c.degree, c.graduation_year && `graduating ${c.graduation_year}`].filter(Boolean);
    $("cvDegree").replaceChildren(degree.length ? degree.join(" · ") : missing(),
      ...yoursMark("degree"), ...(edited("degree") ? [] : yoursMark("graduation_year")));
    const rows = (list) => list.flatMap(([label, key]) => [h("dt", null, label),
      h("dd", { data: { field: key } }, c[key] || missing(), ...yoursMark(key))]);
    $("cvContact").replaceChildren(...rows([["Email", "email"], ["Phone", "phone"], ["Location", "location"]]));
    $("cvScores").replaceChildren(...rows(SCORES.map(([key, label]) => [label, key])));

    $("cvLists").replaceChildren(...LISTS.map(([key, label]) => {
      const items = Array.isArray(c[key]) ? c[key].filter((v) => String(v).trim()) : [];
      const body = !items.length ? h("p", null, missing())
        : CHIPS.has(key) ? h("ul", { class: "skills", aria: { label } }, items.map((v) => h("li", "skill", v)))
        : h("ul", "cv-list", items.map((v) => h("li", null, v)));
      return h("section", { class: "cv-group", data: { list: key } },
        h("h3", null, label, items.length ? h("span", "count", ` ${items.length}`) : null, ...yoursMark(key)), body);
    }));
  }

  /* -------------------------------------------------------- preferences */

  function hint(field) {
    const has = data.preferences[field].length > 0;
    const extra = {
      roles: `The job search uses the first ${data.limits.roles_searched}.`,
      locations: "The job search looks in the first one.",
    }[field];
    if (has) {
      const whose = data.yours.includes(field)
        ? "Yours — kept when you scan a new resume."
        : "From your resume — a new scan can change it.";
      return [whose, extra].filter(Boolean).join(" ");
    }
    return {
      roles: "Not set: the job search picks roles from your skills.",
      locations: "Not set: the job search isn't narrowed to a place.",
      countries: data.home_country
        ? `Not set: “${data.home_country}”, from your address, is used.`
        : "Not set: no job is ruled out by country.",
      work_modes: "Not set: every work mode scores the same.",
      employment_types: "Not set: internships and full-time jobs score highest.",
    }[field];
  }

  function formValues() {
    const out = {};
    Object.entries(TEXT_FIELDS).forEach(([field, id]) => { out[field] = split($(id).value); });
    Object.entries(CHECK_FIELDS).forEach(([field, id]) => {
      out[field] = [...$(id).querySelectorAll("input:checked")].map((box) => box.value);
    });
    return out;
  }

  /* Changed since the form was filled? Work modes and job types compare
     as sets, in the order the checkboxes stand. */
  function isDirty() {
    if (!shown) return false;
    const now = formValues();
    return Object.keys(TEXT_FIELDS).some((f) => !same(now[f], shown[f]))
      || Object.keys(CHECK_FIELDS).some((f) => !same(now[f],
        sortedBy(data.choices[f], shown[f].map((v) => v.toLowerCase()))));
  }

  function renderCheckboxes(field) {
    const box = $(CHECK_FIELDS[field]);
    if (box.childElementCount) return;          // built once; values are set below
    box.replaceChildren(...data.choices[field].map((value) =>
      h("label", "check", h("input", { type: "checkbox", value, on: { change: updateButtons } }),
        ` ${WORDS[value] || value}`)));
  }

  /* Fill the form from what's saved — unless you're partway through
     editing it, when only the hints move. */
  function renderPrefs(force) {
    Object.keys(CHECK_FIELDS).forEach(renderCheckboxes);
    if (force || !isDirty()) {
      shown = JSON.parse(JSON.stringify(data.preferences));
      Object.entries(TEXT_FIELDS).forEach(([field, id]) => { $(id).value = shown[field].join(", "); });
      Object.entries(CHECK_FIELDS).forEach(([field, id]) => {
        const on = shown[field].map((v) => v.toLowerCase());
        $(id).querySelectorAll("input").forEach((input) => { input.checked = on.includes(input.value); });
      });
    }
    Object.entries(HINTS).forEach(([field, id]) => { $(id).textContent = hint(field); });
    updateButtons();
  }

  function updateButtons() {
    const dirty = isDirty();
    $("cvSave").disabled = !dirty;
    $("cvUndo").disabled = !dirty;
  }

  function save(event) {
    if (event) event.preventDefault();
    if (!isDirty()) return;
    const values = formValues();
    Object.keys(CHECK_FIELDS).forEach((f) => { values[f] = sortedBy(data.choices[f], values[f]); });
    $("cvSave").disabled = true;
    $("cvPrefsStatus").textContent = "Saving…";
    bridge.savePreferences(values).then((out) => {
      if (!out || out.error) {
        $("cvPrefsStatus").textContent = (out && out.error) || "That didn't save. Try again.";
        updateButtons();
        return;
      }
      data.preferences = out.preferences;
      data.yours = out.yours;
      renderPrefs(true);
      $("cvPrefsStatus").textContent = out.message;
    });
  }

  /* ---------------------------------------------------------- questions */

  function renderJobs() {
    const select = $("cvJob");
    const keep = select.value;
    const jobs = data.jobs || [];
    select.replaceChildren(
      h("option", { value: "" }, jobs.length ? "None — use my target roles" : "No jobs found yet"),
      ...jobs.map((j) => h("option", { value: j.id },
        `${j.title} — ${j.company}${j.score != null ? ` (${j.score})` : ""}`)));
    select.value = jobs.some((j) => j.id === keep) ? keep : "";
    select.disabled = !jobs.length;
    $("cvJobHint").textContent = jobs.length
      ? "Match needs a job. Interview prep uses it too, or your target roles if none is picked."
      : "Find jobs first, then pick one here to match your resume against.";
  }

  function renderActions() {
    const running = busy();
    const job = $("cvJob").value;
    document.querySelectorAll("#cvActions [data-action]").forEach((b) => {
      b.disabled = running || !data || !data.ready || (b.dataset.action === "match" && !job);
    });
    $("cvChoose").disabled = running;
  }

  function stateOf(task) {
    if (task.status === "waiting") return "Waiting for you";
    if (task.status === "active") {
      if (!task.route) return "Waiting for the task before it";
      if (task.steps.some((s) => s.name === "read_resume" && s.status === "running")) return "Reading your resume…";
      return task.route === "model" ? "Asking Gemini…" : "Working…";
    }
    if (task.status === "done") return ["Done", duration(task.ms)].filter(Boolean).join(" · ");
    if (task.status === "stopped") return "Stopped";
    return "Didn't finish";
  }

  async function copy(text, status) {
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch (e) {
      const area = h("textarea", { class: "sr-only", readonly: true, aria: { hidden: "true" } });
      area.value = text;
      document.body.append(area);
      area.select();
      try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
      area.remove();
    }
    status.textContent = ok ? "Copied." : "Couldn't copy. Select the text instead.";
  }

  function renderResult() {
    const box = $("cvResult");
    const task = asked ? L.tasks.get(asked.id) : null;
    if (!asked) { box.hidden = true; return; }
    box.hidden = false;
    box.dataset.task = String(asked.id);
    $("cvResultTitle").textContent = task ? task.text : TITLES[asked.action];
    $("cvResultState").textContent = task ? stateOf(task) : "Starting…";
    $("cvResultState").dataset.status = task ? task.status : "active";
    const text = task ? (task.reply || (task.status === "failed" ? task.error : "")) : "";
    $("cvResultText").textContent = text || "";

    const acts = $("cvResultActs");
    if (!task || OPEN.includes(task.status) || !task.reply) { acts.replaceChildren(); return; }
    const note = h("span", { class: "cv-result-note", role: "status" });
    const button = (label, fn) => h("button", { class: "btn btn--sm btn--ghost", type: "button", on: { click: fn } }, label);
    acts.replaceChildren(
      button("Copy", () => copy(task.reply, note)),
      button("Save to notes", () => bridge.save(task.id).then((why) => { note.textContent = why || ""; })),
      button("Open in Chat", () => L.chat && L.chat.reveal(task.id)),
      note);
  }

  function ask(action) {
    if (busy() || !data || !data.ready) return;
    const job = $("cvJob").value || null;
    const button = document.querySelector(`#cvActions [data-action="${action}"]`);
    if (action === "match" && !job) return;
    button.disabled = true;
    bridge.resumeAction(action, job).then((out) => {
      if (out && Number.isInteger(out.task)) {
        asked = { id: out.task, action };
        say("");
        renderResult();
        renderActions();
        $("cvResult").focus();
      } else {
        say((out && out.error) || "That didn't start. Try again.");
        renderActions();
      }
    });
  }

  /* --------------------------------------------------------------- scan */

  function choose() {
    if (busy()) return;
    bridge.chooseResume().then((out) => {
      if (!out) { say("The file picker didn't open. Try again."); return; }
      if (out.cancelled) return;
      if (out.error || !Number.isInteger(out.token)) { say(out.error || "The file picker didn't open. Try again."); return; }
      picked = { token: out.token, name: out.name };
      if (data && data.ready) confirmScan();
      else scan();
    });
  }

  /* Replacing a profile asks first: Cancel has focus, and "Scan it" only
     arms after a moment, so an Enter meant for something else can't. */
  function confirmScan() {
    const mine = (data.edited || []).map((key) => FIELD_WORDS[key] || key);
    $("cvConfirmQ").textContent = `Scan “${picked.name}”? What it says replaces the profile below`
      + (mine.length ? `, including what you corrected (${mine.join(", ")}). ` : ". ")
      + "Preferences you set yourself are kept.";
    $("cvConfirm").hidden = false;
    const yes = $("cvConfirmYes");
    yes.disabled = true;
    clearTimeout(armTimer);
    armTimer = setTimeout(() => { yes.disabled = false; }, ARM_MS);
    $("cvConfirmNo").focus();
  }

  function closeConfirm() {
    clearTimeout(armTimer);
    $("cvConfirm").hidden = true;
    picked = null;
  }

  function scan() {
    if (!picked) return;
    const { token, name } = picked;
    closeConfirm();
    say(`Reading ${name}…`);
    bridge.scanPicked(token).then((out) => {
      if (out && Number.isInteger(out.task)) {
        scanning = { id: out.task, name };
        followScan();
        renderActions();
      } else {
        say((out && out.error) || "That didn't start. Try again.");
      }
    });
  }

  function followScan() {
    const task = scanning ? L.tasks.get(scanning.id) : null;
    if (!task) return;
    if (OPEN.includes(task.status)) say(`${scanning.name}: ${stateOf(task)}`);
    else say(task.reply || task.error || stateOf(task));
  }

  /* ------------------------------------------------------------- render */

  function render() {
    const empty = $("cvEmpty");
    const body = $("cvBody");
    renderSource();

    if (!data) {
      body.hidden = true;
      empty.hidden = false;
      empty.replaceChildren(loading ? "Loading your resume…" : "");
      return;
    }
    if (data.error) {
      body.hidden = true;
      empty.hidden = false;
      empty.replaceChildren(h("p", null, data.error),
        h("button", { class: "btn btn--sm", type: "button", on: { click: load } }, "Try again"));
      return;
    }
    if (!data.ready) {
      body.hidden = true;
      empty.hidden = false;
      const found = data.suggestions || [];
      empty.replaceChildren(
        h("h2", null, "No resume read yet"),
        h("p", null, "Your profile, job matching and the questions here all start from it. "
          + "Pick the file — a PDF, Word file, image or text file — and I'll read it."),
        h("button", { class: "btn btn--primary", type: "button", data: { key: "choose" }, on: { click: choose } },
          "Choose your resume…"),
        found.length ? h("p", "cv-note", `Or type: scan my resume ${found[0]}`) : null);
      renderActions();
      return;
    }

    empty.hidden = true;
    body.hidden = false;
    renderProfile();
    renderJobs();
    renderPrefs(false);
    renderActions();
    renderResult();
  }

  /* --------------------------------------------------------------- data */

  function load() {
    loading = true;
    if (!data) render();
    return bridge.resume().then((snapshot) => {
      loading = false;
      data = snapshot && (snapshot.candidate || snapshot.error) ? snapshot
        : { error: "I couldn't read your resume profile." };
      render();
    });
  }

  function reloadSoon() {
    clearTimeout(reloadTimer);
    reloadTimer = setTimeout(() => { if (L.router.current() === "resume") load(); }, 150);
  }

  /* ------------------------------------------------------------- wiring */

  document.querySelectorAll("#cvActions [data-action]").forEach((b) => {
    b.addEventListener("click", () => ask(b.dataset.action));
  });
  $("cvJob").addEventListener("change", renderActions);
  $("cvChoose").addEventListener("click", choose);
  $("cvRefresh").addEventListener("click", load);
  $("cvConfirmNo").addEventListener("click", () => { closeConfirm(); $("cvChoose").focus(); });
  $("cvConfirmYes").addEventListener("click", scan);
  $("cvConfirm").addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    e.stopPropagation();                       // Escape here means "don't scan", not "stop"
    closeConfirm();
    $("cvChoose").focus();
  });
  $("cvPrefs").addEventListener("submit", save);
  $("cvPrefs").addEventListener("input", updateButtons);
  $("cvUndo").addEventListener("click", () => { renderPrefs(true); $("cvPrefsStatus").textContent = "Back to what's saved."; });

  L.tasks.onChange(({ ended }) => {
    if (asked) renderResult();
    if (scanning) followScan();
    if (data && !data.error) renderActions();
    if (ended.length) reloadSoon();
  });
  L.router.onChange((id) => {
    if (id === "resume") load();
    else if (picked) closeConfirm();
  });
  // Opened straight onto Resume: wait until Python can answer.
  window.addEventListener("pywebviewready", () => { if (L.router.current() === "resume") load(); });

  L.resume = { load };
})();
