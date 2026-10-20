/* LITTLE — Tools.

   Everything LITTLE can do, grouped by what it works on, each in its own
   words (the description the model is given), with the ones that never run
   without your yes marked. Beside it, what ran this session: every tool
   step from the task record, with how long it took and whether it failed —
   the same record the Task Center shows, not a separate count.

   The list is read from Python when you open the section; the runs follow
   the task record as it changes. */
(function () {
  const LEVEL = { SAFE: "Reads only", LOW_RISK: "Low risk", CONFIRM: "Asks when it matters",
                  HIGH_RISK: "Asks every time", BLOCKED: "Blocked" };

  const L = (window.Little = window.Little || {});
  const { h, bridge } = L;
  const $ = (id) => document.getElementById(id);

  const RUNS_SHOWN = 25;

  let data = null;
  let loading = false;
  let checkAfter = null;        // the newest task id when "Check" was pressed

  function duration(ms) {
    if (ms == null || !Number.isFinite(ms)) return "";
    if (ms < 1000) return `${Math.round(ms)} ms`;
    return `${(ms / 1000).toFixed(1)} s`;
  }

  /* --------------------------------------------------------------- list */

  function renderList() {
    const list = $("toolsList");
    const empty = $("toolsEmpty");
    if (!data || data.error) {
      list.replaceChildren();
      empty.hidden = false;
      empty.replaceChildren(...(!data ? [loading ? "Loading the tools…" : ""]
        : [data.error, h("button", { class: "btn btn--sm", type: "button", on: { click: load } }, "Try again")]));
      $("toolsSummary").textContent = "";
      return;
    }
    const terms = $("toolsSearch").value.toLowerCase().split(/\s+/).filter(Boolean);
    const onlyAsking = $("toolsAsking").checked;
    const shown = data.tools.filter((t) => (!onlyAsking || t.asks)
      && terms.every((w) => `${t.name} ${t.does} ${t.group}`.toLowerCase().includes(w)));
    const asking = data.tools.filter((t) => t.asks).length;
    $("toolsCount").textContent = String(data.tools.length);
    $("toolsSummary").textContent = `${data.tools.length} tools · ${asking} ask first`
      + (shown.length < data.tools.length ? ` · showing ${shown.length}` : "");

    const groups = [];
    shown.forEach((t) => {
      let g = groups.find((x) => x.name === t.group);
      if (!g) groups.push((g = { name: t.group, tools: [] }));
      g.tools.push(t);
    });
    list.replaceChildren(...groups.map((g) => h("section", { class: "tools-group", data: { group: g.name } },
      h("h3", null, g.name, h("span", "count", ` ${g.tools.length}`)),
      h("ul", null, g.tools.map((t) => h("li", { class: "tools-item", data: { tool: t.name, level: t.level || "" } },
        h("div", "tools-name", h("code", null, t.name),
          t.asks ? h("span", "badge badge--warn", "Asks first") : null),
        h("p", null, t.does),
        t.level ? h("p", "tools-meta", [LEVEL[t.level] || t.level,
          t.uses && t.uses.length ? `uses ${t.uses.join(", ")}` : "",
          t.timeout ? `${t.timeout} s` : "",
          t.log === "names" ? "its words aren't logged" : ""].filter(Boolean).join(" · ")) : null))))));
    empty.hidden = shown.length > 0;
    if (!shown.length) empty.replaceChildren("No tool matches. Clear the search or the filter.");
  }

  /* --------------------------------------------------------------- runs */

  function renderRuns() {
    const runs = L.tasks.recent(Infinity).flatMap((task) => task.steps
      .filter((s) => s.name !== "your answer")
      .map((s) => ({ ...s, task })))
      .slice(0, RUNS_SHOWN);
    $("toolsRunsCount").textContent = runs.length ? String(runs.length) : "";
    $("toolsRuns").replaceChildren(...(runs.length ? runs.map((run) => h("li",
      { class: `tools-run is-${run.status}` },
      h("div", "tools-name",
        h("code", null, run.name),
        h("span", "tools-ms", run.status === "running" ? "running" : duration(run.ms)),
        run.status === "error" ? h("span", "badge badge--bad", "failed") : null),
      h("button", { class: "tools-task", type: "button", on: { click: () => L.taskCenter.open(run.task.id) },
                    aria: { label: `Open the task: ${run.task.text}` } }, run.task.text)))
      : [h("li", "tools-note", "No tool has run yet this session. They show here as they run.")]));

    if (checkAfter !== null) {
      const task = L.tasks.recent(Infinity).find((t) => t.id > checkAfter && t.text === "check the tools");
      if (task) {
        $("toolsOut").textContent = ["active", "waiting"].includes(task.status) ? "Checking…"
          : task.reply || task.error || "Done.";
      }
    }
  }

  /* --------------------------------------------------------------- data */

  function load() {
    loading = true;
    if (!data) renderList();
    return bridge.tools().then((snapshot) => {
      loading = false;
      data = snapshot && Array.isArray(snapshot.tools) ? snapshot : { error: "I couldn't read the tool list." };
      renderList();
      renderRuns();
    });
  }

  let searchTimer = null;
  $("toolsSearch").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(renderList, 120);
  });
  $("toolsAsking").addEventListener("change", renderList);
  $("toolsCheck").addEventListener("click", () => {
    const newest = L.tasks.recent(1)[0];
    checkAfter = newest ? newest.id : 0;
    $("toolsOut").textContent = "Checking…";
    bridge.send("check the tools");
  });

  L.tasks.onChange(() => { if (L.router.current() === "tools" || checkAfter !== null) renderRuns(); });
  L.router.onChange((id) => { if (id === "tools") { if (!data || data.error) load(); else renderRuns(); } });
  window.addEventListener("pywebviewready", () => { if (L.router.current() === "tools") load(); });

  L.tools = { load };
})();
