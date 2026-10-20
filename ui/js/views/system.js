/* LITTLE — System.

   How LITTLE is set up and whether it's healthy, from what's in effect:

     Health check     the 18 probes, each ok / works-but / problem, and for
                      any trouble what's wrong, why, and the fix. Asking the
                      model too costs a request, so it's its own button.
     Security         what never runs without your yes, the fences (the one
                      workspace folder, keys never shown), your answers to
                      questions this session, and the job activity trail
     Settings         every setting by group, each with its .env key — read
                      only here (decision D3): edit .env and restart. Keys
                      arrive as "set" or "missing", never as a value.
     Voice / mic      test the voice as set, the voice report, the
                      microphones Windows reports, and recalibrate
     Notifications,   what exists, said plainly; nothing to switch that
     Appearance       doesn't exist

   Loads when you open the section; the health check runs the first time
   and whenever you ask. */
(function () {
  const L = (window.Little = window.Little || {});
  const { h, bridge } = L;
  const $ = (id) => document.getElementById(id);

  const STATE = {
    ok: ["✓", "ok", "badge--ok"],
    warn: ["!", "works, but", "badge--warn"],
    fail: ["×", "problem", "badge--bad"],
  };
  const ORDER = ["ai", "voice", "mic", "wake", "browser", "jobs", "files"];

  let data = null;
  let loading = false;
  let checks = null;
  let checking = false;
  const commands = new Map();   // command text -> { after, out }

  function say(message) { $("sysStatus").textContent = message || ""; }

  function button(label, onClick, extra) {
    return h("button", { class: "btn btn--sm", type: "button", ...extra, on: { click: onClick } }, label);
  }

  /* ------------------------------------------------------ health check */

  function renderChecks() {
    const list = $("sysChecks");
    $("sysHealthRun").disabled = checking;
    $("sysHealthLive").disabled = checking;
    if (!checks) {
      $("sysHealthSummary").textContent = checking ? "Checking…" : "";
      $("sysHealthCount").textContent = "";
      list.replaceChildren();
      return;
    }
    const failing = checks.filter((c) => c.state === "fail").length;
    const warning = checks.filter((c) => c.state === "warn").length;
    $("sysHealthCount").textContent = String(checks.length);
    $("sysHealthSummary").textContent = checking ? "Checking…"
      : !failing && !warning ? "Everything checks out."
      : [failing && `${failing} broken`, warning && `${warning} working, but not fully`].filter(Boolean).join(", ") + ".";
    list.replaceChildren(...checks.map((c) => {
      const [mark, word, badge] = STATE[c.state] || STATE.fail;
      const trouble = c.state !== "ok" ? h("dl", "sys-trouble",
        h("dt", null, "Problem"), h("dd", null, c.problem),
        h("dt", null, "Why"), h("dd", null, c.cause),
        h("dt", null, "Fix"), h("dd", null, c.fix)) : null;
      return h("li", { class: `sys-check is-${c.state}`, data: { check: c.group } },
        h("div", "sys-check-head",
          h("span", `badge ${badge}`, h("span", { aria: { hidden: "true" } }, mark + " "), word),
          h("b", null, c.group), h("span", "sys-check-detail", c.detail)),
        trouble);
    }));
  }

  function runHealth(live) {
    if (checking) return;
    checking = true;
    renderChecks();
    bridge.health(live === true).then((out) => {
      checking = false;
      if (out && Array.isArray(out.checks)) checks = out.checks;
      else say("The health check didn't answer. Try again.");
      renderChecks();
    });
  }

  /* --------------------------------------------------- commands, followed */

  /* Run a command Little already understands, and show its reply here. The
     task is the newest one with exactly this text, started after the click. */
  function runCommand(text, out) {
    const known = L.tasks.recent(1)[0];
    commands.set(text, { after: known ? known.id : 0, out });
    out.textContent = "Starting…";
    bridge.send(text);
  }

  function followCommands() {
    commands.forEach((watch, text) => {
      const task = L.tasks.recent(Infinity).find((t) => t.id > watch.after && t.text === text);
      if (!task) return;
      watch.out.textContent = ["active", "waiting"].includes(task.status) ? "Working…"
        : task.reply || task.error || "Done.";
    });
  }

  /* ------------------------------------------------------------ settings */

  function rows(list) {
    return h("dl", "sys-rows", list.map((r) => [
      h("dt", null, r.label),
      h("dd", null,
        h("span", { class: "sys-value" + (r.value === "missing" ? " is-missing" : "") }, r.value),
        r.key ? h("code", "sys-key", r.key) : null,
        r.note ? h("span", "sys-note", r.note) : null),
    ]));
  }

  function extras(id) {
    if (id === "voice") {
      const out = h("p", { class: "sys-out", role: "status" });
      return [h("div", "sys-acts",
        button("Test the voice", () => bridge.testVoice().then((why) => {
          out.textContent = why || "Listen — it's speaking now.";
        }), { data: { key: "test-voice" } }),
        button("Voice report", () => runCommand("what voice are you using", out),
          { class: "btn btn--sm btn--ghost", data: { key: "voice-report" } })), out];
    }
    if (id === "mic") {
      const out = h("p", { class: "sys-out", role: "status" });
      const mics = data.mics.length
        ? h("ol", { class: "sys-mics", start: "0", aria: { label: "Microphones" } },
          data.mics.map((name, i) => h("li", null, h("code", null, `#${i}`), " ", name)))
        : h("p", "sys-note", "Windows reports no microphones, or the microphone packages aren't installed.");
      return [h("h3", "sys-h3", "Microphones Windows reports"), mics,
        h("p", "sys-note", "To use one, put its number in .env as JARVIS_MIC, then restart."),
        h("div", "sys-acts",
          button("Recalibrate", () => runCommand("recalibrate mic", out), {
            data: { key: "recalibrate" }, disabled: !data.listening,
            title: data.listening ? "Stay quiet for two seconds while it listens to the room" : "Start listening first",
          })),
        data.listening ? null : h("p", "sys-note", "Recalibrating needs the microphone on — start listening first."),
        out];
    }
    if (id === "browser") {
      const out = h("p", { class: "sys-out", role: "status" });
      return [h("div", "sys-acts", button("Close the browser", () => {
        L.actions.closeBrowser();
        out.textContent = "Closing it. Its logins stay in its profile.";
      }, { class: "btn btn--sm btn--ghost", data: { key: "close-browser" } })), out];
    }
    if (id === "files") {
      return [h("div", "sys-acts", button("Open Memory", () => L.router.go("memory"),
        { class: "btn btn--sm btn--ghost" }))];
    }
    return [];
  }

  function renderSettings() {
    const byId = Object.fromEntries(data.groups.map((g) => [g.id, g]));
    const groups = ORDER.filter((id) => byId[id]).map((id) => byId[id])
      .concat(data.groups.filter((g) => !ORDER.includes(g.id)));
    const motion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const nav = { full: "labels and icons", rail: "icons only", bottom: "a bar along the bottom" }[document.body.dataset.nav]
      || "labels and icons";

    $("sysSettings").replaceChildren(
      ...groups.map((g) => h("section", { class: "panel", data: { group: g.id }, aria: { label: g.title } },
        h("h2", null, g.title), rows(g.rows), ...extras(g.id))),
      h("section", { class: "panel", data: { group: "notifications" }, aria: { label: "Notifications" } },
        h("h2", null, "Notifications"),
        h("p", "sys-lead", "There's nothing to switch here — this is everything that tells you something:"),
        h("ul", "sys-plain",
          h("li", null, "Reminders are spoken aloud and listed on Home."),
          h("li", null, "A question for you opens the confirmation dialog."),
          h("li", null, "A command that didn't finish, or a setup problem, waits on Home under Waiting for you."),
          h("li", null, "Nothing reaches your phone or the Windows notification area."))),
      h("section", { class: "panel", data: { group: "appearance" }, aria: { label: "Appearance" } },
        h("h2", null, "Appearance"),
        rows([
          { label: "Theme", value: "Dark — the only one", key: "", note: "" },
          { label: "Motion", value: motion ? "reduced, as Windows asks" : "on",
            key: "", note: "Follows Windows' Animation effects setting." },
          { label: "Sidebar", value: nav, key: "", note: "The arrow at its foot switches, on wider windows." },
        ])));
  }

  /* ---------------------------------------------------------- at a glance */

  /* Each section as Python read it — state, title, rows. Rows without a
     label (the log's lines) run on under the one before. An older snapshot
     without the dashboard shows no panel rather than an empty one. */
  function renderGlance() {
    const sections = data.dashboard;
    $("sysGlanceWrap").hidden = !Array.isArray(sections);
    if (!Array.isArray(sections)) return;
    $("sysGlance").replaceChildren(...sections.map((s) =>
      h("section", { class: "glance-card", data: { id: s.id, state: s.state } },
        h("h3", null, s.title, s.state === "warn" ? h("span", "badge badge--warn", "Needs a look")
          : s.state === "off" ? h("span", "badge badge--info", "Off") : null),
        h("dl", "glance-rows", s.rows.flatMap(([label, value]) =>
          [h("dt", null, label), h("dd", null, value)])))));
  }

  /* ------------------------------------------------------------ security */

  const LEVEL_WORDS = {
    SAFE: "Safe — reads only", LOW_RISK: "Low risk — its own records, or opens things",
    CONFIRM: "Confirm — asks when it matters", HIGH_RISK: "High risk — asks every time",
    BLOCKED: "Blocked — never runs",
  };

  function renderSecurity() {
    $("sysAsks").replaceChildren(...data.asks_first.map((t) =>
      h("li", { data: { level: t.level || "" } }, h("code", null, t.name), h("span", null, t.does),
        t.level ? h("span", `badge ${t.level === "HIGH_RISK" ? "badge--warn" : "badge--info"}`,
          t.level === "HIGH_RISK" ? "Every time" : "When it matters") : null)));
    renderGuard();
    const keys = data.groups.flatMap((g) => g.rows).filter((r) => ["set", "missing"].includes(r.value));
    $("sysFences").replaceChildren(
      h("dt", null, "Files"), h("dd", null, "Only the workspace folder — see Files and memory."),
      h("dt", null, "Keys"), h("dd", null, `Never shown, only set or missing (${keys.filter((k) => k.value === "set").length} of ${keys.length} set).`),
      h("dt", null, "Job dashboard"), h("dd", null, "Read-only, and only on this computer."),
      h("dt", null, "Tools"), h("dd", null, `${data.tools} in all; ${data.asks_first.length} ask first.`));
    renderAnswers();
    $("sysAudit").replaceChildren(...(data.audit.length ? data.audit.map((a) => h("li", null,
      h("span", "sys-when", String(a.timestamp || "").replace("T", " ").slice(0, 16)),
      h("span", null, [a.action, a.company, a.job].filter(Boolean).join(" · ")),
      a.result || a.error ? h("span", "sys-note", a.error || a.result) : null))
      : [h("li", "sys-note", "Nothing yet. Searches, prepared forms and status changes show here.")]));
  }

  /* Levels, services, failed and blocked — Chapter 37. An older snapshot
     without them shows none of it rather than something made up. */
  function renderGuard() {
    const sec = data.security;
    $("sysGuard").hidden = !sec;
    if (!sec) return;
    $("sysLevels").replaceChildren(...Object.entries(LEVEL_WORDS).flatMap(([lv, words]) => [
      h("dt", null, words), h("dd", { data: { level: lv } },
        lv === "BLOCKED" && sec.blocked.length ? sec.blocked.join(", ")
          : `${sec.levels[lv] || 0} tool${sec.levels[lv] === 1 ? "" : "s"}`)]));
    $("sysServices").replaceChildren(...sec.services.map((s) =>
      h("li", null, h("b", null, s.name), h("span", null, ` — ${s.for}: ${s.state}`))));
    $("sysEvents").replaceChildren(...(sec.events.length ? sec.events.map((e) => h("li", null,
      h("span", "sys-when", new Date(e.at * 1000).toTimeString().slice(0, 5)),
      h("span", null, `${e.tool} · ${{ blocked: "blocked", recovered: "recovered", slow: "slow" }[e.kind] || "failed"}`),
      e.detail ? h("span", "sys-note", e.detail) : null))
      : [h("li", "sys-note", "Nothing has failed or been blocked this session.")]));
  }

  function renderAnswers() {
    const answers = L.tasks.recent(Infinity).flatMap((task) => task.steps
      .filter((s) => s.name === "your answer")
      .map((s) => ({ approved: s.detail === "approved", question: s.question || task.text, id: task.id })));
    $("sysAnswers").replaceChildren(...(answers.length ? answers.map((a) => h("li", null,
      h("span", `badge ${a.approved ? "badge--ok" : "badge--info"}`, a.approved ? "You said yes" : "You said no"),
      h("span", null, String(a.question).split("\n")[0])))
      : [h("li", "sys-note", "No questions asked yet this session.")]));
  }

  /* ------------------------------------------------------------- render */

  function render() {
    const body = $("sysBody");
    const error = $("sysError");
    if (!data || data.error) {
      body.hidden = true;
      error.hidden = false;
      error.replaceChildren(...(!data ? [loading ? "Loading the settings…" : ""]
        : [data.error, button("Try again", load)]));
      $("sysEnv").textContent = "";
      return;
    }
    error.hidden = true;
    body.hidden = false;
    $("sysEnv").textContent = data.env.exists
      ? `Settings come from ${data.env.path}. To change one, edit it there and restart Little.`
      : `There's no .env file at ${data.env.path}, so every setting is its default. Copy .env.example to .env to change them.`;
    renderSettings();
    renderGlance();
    renderSecurity();
    renderChecks();
    followCommands();
  }

  function load() {
    loading = true;
    if (!data) render();
    return bridge.system().then((snapshot) => {
      loading = false;
      data = snapshot && (Array.isArray(snapshot.groups) || snapshot.error) ? snapshot
        : { error: "I couldn't read the settings." };
      render();
      if (!checks && !checking && data && !data.error) runHealth(false);
    });
  }

  $("sysRefresh").addEventListener("click", load);
  $("sysHealthRun").addEventListener("click", () => runHealth(false));
  $("sysHealthLive").addEventListener("click", () => runHealth(true));

  L.tasks.onChange(() => {
    if (!data || data.error) return;
    followCommands();
    renderAnswers();
  });
  L.router.onChange((id) => { if (id === "system") load(); });
  window.addEventListener("pywebviewready", () => { if (L.router.current() === "system") load(); });

  L.system = { load };
})();
