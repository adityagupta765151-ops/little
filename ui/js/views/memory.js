/* LITTLE — Memory.

   What LITTLE keeps about you, by kind, where it's kept, and a way to take
   each piece back:
     You asked me to remember   facts from "remember that …", preferences and
                                each project's facts, tagged — Forget each
     Your resume and jobs       a summary, with the sections that show them
     Contacts                   names with numbers masked by Python — the page
                                never gets them whole; Remove each
     Conversation log           the record LITTLE writes and never reads; Clear

   Forgetting asks first, in the row itself: Keep has focus, and the button
   that deletes arms after a moment, so an Enter meant for something else
   can't. Python deletes by the exact key or name, never a near match.
   Loads when you open the section and after a task ends (a "remember that"
   may have added something). */
(function () {
  const L = (window.Little = window.Little || {});
  const { h, bridge } = L;
  const $ = (id) => document.getElementById(id);

  const SHOWN = 60;             // contacts listed at once; search finds the rest
  const ARM_MS = 700;

  let data = null;
  let loading = false;
  let reloadTimer = null;
  let asking = null;            // the row whose question is open: { close }

  function say(message) { $("memStatus").textContent = message || ""; }

  /* ----------------------------------------------------- asking first */

  /* Swap a row's button for "question  Keep  <verb>". Only one open at a
     time; Escape keeps it. `run()` asks Python, which answers {message}
     or {error}; either way the row closes and says so. */
  function askFirst(acts, question, verb, run) {
    if (asking) asking.close(false);
    const before = [...acts.childNodes];
    const keep = h("button", { class: "btn btn--sm", type: "button" }, "Keep");
    const yes = h("button", { class: "btn btn--sm btn--caution", type: "button", disabled: true }, verb);
    const timer = setTimeout(() => { yes.disabled = false; }, ARM_MS);
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();                     // Escape here means "keep it", not "stop"
      close(true);
    };
    const close = (refocus) => {
      clearTimeout(timer);
      acts.removeEventListener("keydown", onKey);
      acts.replaceChildren(...before);
      acts.classList.remove("is-asking");
      asking = null;
      if (refocus && before[0]) before[0].focus();
    };
    keep.addEventListener("click", () => close(true));
    yes.addEventListener("click", () => {
      yes.disabled = true;
      keep.disabled = true;
      run().then((out) => {
        close(false);
        if (!out || out.error) { say((out && out.error) || "That didn't work. Try again."); return; }
        say(out.message);
        load();
      });
    });
    acts.addEventListener("keydown", onKey);
    acts.classList.add("is-asking");
    acts.replaceChildren(h("span", "mem-ask", question), keep, yes);
    asking = { close };
    keep.focus();
  }

  function button(label, onClick, extra) {
    return h("button", { class: "btn btn--sm btn--ghost", type: "button", ...extra, on: { click: onClick } }, label);
  }

  /* -------------------------------------------------------------- facts */

  /* Facts, then preferences, then each project's facts — one list, each
     row tagged with where it's kept, each forgotten by its exact key. */
  function rememberedRows() {
    const rows = data.facts.map((f) => ({ ...f, tag: "", scope: null, project: null, id: `fact-${f.key}` }));
    (data.preferences || []).forEach((f) => rows.push({ ...f, tag: "Preference", scope: "preference",
      project: null, id: `pref-${f.key}` }));
    (data.projects || []).forEach((p) => p.facts.forEach((f) => rows.push({ ...f, tag: `Project · ${p.name}`,
      scope: "project", project: p.name, id: `proj-${p.name}-${f.key}` })));
    return rows;
  }

  function renderFacts() {
    const facts = rememberedRows();
    $("memFactsCount").textContent = facts.length ? String(facts.length) : "";
    if (!facts.length) {
      $("memFacts").replaceChildren(h("li", "mem-empty",
        h("span", null, "Nothing yet. To teach me something, type: remember that my editor is VS Code"),
        button("Teach me something…", () => {
          const input = $("input");
          input.value = "remember that ";
          input.focus();
          input.setSelectionRange(input.value.length, input.value.length);
        })));
      return;
    }
    $("memFacts").replaceChildren(...facts.map((fact) => {
      const acts = h("span", "mem-acts");
      acts.append(button("Forget", () => askFirst(acts, `Forget “${fact.key}”?`, "Forget",
        () => (fact.scope ? bridge.forgetFact(fact.key, fact.scope, fact.project) : bridge.forgetFact(fact.key))),
        { data: { key: fact.id }, aria: { label: `Forget ${fact.key}${fact.tag ? ` (${fact.tag})` : ""}` } }));
      return h("li", { class: "mem-row", data: { fact: fact.key } },
        h("span", "mem-what", h("b", null, fact.key), h("span", null, fact.value),
          fact.tag ? h("span", "mem-tag", fact.tag) : null), acts);
    }));
  }

  /* ----------------------------------------------------- resume and jobs */

  function renderAbout() {
    const go = (section, label) => button(label, () => L.router.go(section));
    const r = data.resume;
    const j = data.jobs;
    $("memAbout").replaceChildren(
      h("p", "mem-row",
        h("span", "mem-what", h("b", null, "Resume"),
          h("span", null, r.ready ? `${r.name || "Your profile"} — ${r.skills} skills, ${r.projects} projects`
            : "No resume read yet")),
        h("span", "mem-acts", go("resume", "Open Resume"), r.ready ? go("projects", "Projects") : null)),
      h("p", "mem-row",
        h("span", "mem-what", h("b", null, "Jobs"),
          h("span", null, `${j.total} stored, ${j.applied} you applied to`)),
        h("span", "mem-acts", go("jobs", "Open Jobs"))),
      data.documents ? h("p", { class: "mem-row", data: { docs: String(data.documents.length) } },
        h("span", "mem-what", h("b", null, "Your documents"),
          h("span", null, data.documents.length
            ? data.documents.map((d) => `${d.name} (${d.parts} part${d.parts === 1 ? "" : "s"})`).join(", ")
            : "None yet. Say: add notes.pdf to my knowledge base"))) : null);
  }

  /* ----------------------------------------------------------- contacts */

  function renderContacts() {
    const all = data.contacts;
    const terms = $("memContactSearch").value.toLowerCase().split(/\s+/).filter(Boolean);
    const found = all.filter((c) => terms.every((t) => c.name.toLowerCase().includes(t)));
    $("memContactsCount").textContent = all.length ? String(all.length) : "";
    $("memContactSearch").hidden = all.length <= 8;
    $("memContacts").replaceChildren(...found.slice(0, SHOWN).map((contact) => {
      const acts = h("span", "mem-acts");
      acts.append(button("Remove", () => askFirst(acts, `Remove ${contact.name}?`, "Remove",
        () => bridge.removeContact(contact.name)), { data: { key: `contact-${contact.name}` },
        aria: { label: `Remove ${contact.name}` } }));
      return h("li", { class: "mem-row", data: { contact: contact.name } },
        h("span", "mem-what", h("b", null, contact.name),
          h("span", "mem-number", contact.number),
          contact.sample ? h("span", "mem-sample", "a sample entry LITTLE starts with, not a real contact") : null),
        acts);
    }));
    const notes = [];
    if (!all.length) {
      notes.push("No contacts saved. Export your phone's contacts as a vCard (.vcf) into Downloads, "
        + "then type: import contacts contacts.vcf");
    } else if (!found.length) {
      notes.push("No saved contact has that in their name.");
    } else if (found.length > SHOWN) {
      notes.push(`Showing ${SHOWN} of ${found.length}. Search to find the others.`);
    }
    notes.push("Numbers show only their last four digits here.");
    $("memContactsNote").textContent = notes.join(" ");
  }

  /* ----------------------------------------------------------------- log */

  function renderLog() {
    const log = data.log;
    $("memLogCount").textContent = log.count ? String(log.count) : "";
    $("memLogNote").textContent = `Each command and my reply, the last ${log.keep}, kept on this computer. `
      + "I write it but never read it back — it's a record for you.";
    $("memLog").replaceChildren(...log.recent.map((turn) => h("li", null,
      h("p", "mem-you", turn.user), h("p", "mem-reply", turn.assistant))));
    const acts = $("memLogActs");
    acts.replaceChildren();
    if (!log.count) {
      acts.append(h("p", "mem-note", "Nothing logged yet."));
      return;
    }
    if (log.count > log.recent.length) {
      acts.append(h("p", "mem-note", `The latest ${log.recent.length} of ${log.count}.`));
    }
    const row = h("div", "mem-acts");
    row.append(button("Clear the log", () => askFirst(row, `Clear all ${log.count}?`, "Clear",
      () => bridge.clearLog()), { data: { key: "clear-log" } }));
    acts.append(row);
  }

  /* ------------------------------------------------------------- render */

  function render() {
    const body = $("memBody");
    const error = $("memError");
    if (!data || data.error) {
      body.hidden = true;
      error.hidden = false;
      error.replaceChildren(...(!data ? [loading ? "Loading what I remember…" : ""]
        : [data.error, h("button", { class: "btn btn--sm", type: "button", on: { click: load } }, "Try again")]));
      return;
    }
    error.hidden = true;
    body.hidden = false;
    $("memPrivacy").textContent = `Everything here is kept on this computer, in ${data.folder}. None of it `
      + "goes to the model with every request: the model sees a piece only when a request needs it and I "
      + "look it up — something you asked me to remember, a contact to message, your resume.";
    renderFacts();
    renderAbout();
    renderContacts();
    renderLog();
  }

  function load() {
    loading = true;
    if (!data) render();
    return bridge.memory().then((snapshot) => {
      loading = false;
      data = snapshot && (Array.isArray(snapshot.facts) || snapshot.error) ? snapshot
        : { error: "I couldn't read the memory folder." };
      if (asking) asking.close(false);
      render();
    });
  }

  let searchTimer = null;
  $("memContactSearch").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { if (data && !data.error) renderContacts(); }, 120);
  });
  $("memRefresh").addEventListener("click", load);

  L.tasks.onChange(({ ended }) => {
    if (!ended.length) return;
    clearTimeout(reloadTimer);
    reloadTimer = setTimeout(() => { if (L.router.current() === "memory" && !asking) load(); }, 150);
  });
  L.router.onChange((id) => {
    if (id === "memory") load();
    else if (asking) asking.close(false);
  });
  window.addEventListener("pywebviewready", () => { if (L.router.current() === "memory") load(); });

  L.memory = { load };
})();
