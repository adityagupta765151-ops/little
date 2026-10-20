/* LITTLE — the Task Center.

   Every command as a task: running, waiting for you, done, didn't finish,
   or stopped — and for the one you pick, its timeline as it happened.

   The timeline is honest. It shows only what took place: how the command
   came in, where the answer came from, the plan if there was one (each step
   with the tools it ran), each tool with its arguments and timing, any
   question it asked you and your answer, a stop you asked for, and how it
   ended. There's no "understanding" or "verifying" step that didn't run.
   Times are seconds after the task started, as Python measured them.

   "Stop this" asks a running task to stop at its next step. Only a task that
   has steps to stop between offers it — the model working through tools, or
   a plan. A command answered on this computer is a single call; the page
   says so rather than showing a button that couldn't keep its word.

   Which task is shown follows the one in hand until you pick one yourself. */
(function () {
  const L = (window.Little = window.Little || {});
  const { h, bridge } = L;
  const $ = (id) => document.getElementById(id);

  const OPEN = ["active", "waiting"];
  const FILTERS = {
    all: () => true,
    active: (t) => t.status === "active",
    waiting: (t) => t.status === "waiting",
    done: (t) => t.status === "done",
    failed: (t) => t.status === "failed",
    stopped: (t) => t.status === "stopped",
  };
  const OUTCOME = {
    active: "Running", waiting: "Waiting for you", done: "Done",
    failed: "Didn't finish", stopped: "Stopped",
  };
  const NONE = {
    all: "No tasks yet. Every command you give becomes one here, with each step it takes.",
    active: "Nothing is running right now.",
    waiting: "Nothing is waiting for you.",
    done: "Nothing has finished yet.",
    failed: "Nothing has failed. Anything that does shows up here with the reason.",
    stopped: "Nothing has been stopped.",
  };
  const ROUTE = {
    local: "Answered on this computer",
    model: "Asked the model",
  };
  const PLAN_STATE = {
    pending: "not started", running: "running", done: "done",
    failed: "failed", stopped: "stopped",
  };

  let filter = "all";
  let selected = null;        // task id on show
  let picked = false;         // you chose it, so it stays
  let listKey = "";
  let detailKey = "";
  let statusTimer = null;

  /* ------------------------------------------------------------ helpers */

  function duration(ms) {
    if (ms == null || !Number.isFinite(ms)) return "";
    if (ms < 1000) return `${Math.round(ms)} ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
    const s = Math.round(ms / 1000);
    return `${Math.floor(s / 60)}m ${s % 60}s`;
  }

  function clock(epochSeconds, seconds) {
    return new Date(epochSeconds * 1000).toLocaleTimeString("en-GB",
      seconds ? { hour12: false } : { hour: "2-digit", minute: "2-digit", hour12: false });
  }

  function offset(at) {
    return Number.isFinite(at) ? `+${at.toFixed(1)}s` : "";
  }

  function say(message) {
    $("tcStatus").textContent = message || "";
    clearTimeout(statusTimer);
    if (message) statusTimer = setTimeout(() => { $("tcStatus").textContent = ""; }, 6000);
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

  const all = () => L.tasks.recent(Infinity);            // newest first
  const byId = (id) => all().find((t) => t.id === id) || null;

  function stoppable(task) {
    if (!OPEN.includes(task.status) || task.stopping) return false;
    return task.route === "model" || task.route === "plan" || task.status === "waiting";
  }

  /* --------------------------------------------------------------- list */

  function renderFilters(tasks) {
    document.querySelectorAll("#tcFilters [data-filter]").forEach((b) => {
      const name = b.dataset.filter;
      b.setAttribute("aria-pressed", String(name === filter));
      b.querySelector(".count").textContent = String(tasks.filter(FILTERS[name]).length);
    });
  }

  function item(task) {
    const open = OPEN.includes(task.status);
    const meta = open
      ? (task.stopping ? "stopping" : OUTCOME[task.status].toLowerCase())
      : `${clock(task.started)} · ${duration(task.ms)}`;
    const button = h("button", {
      class: `tc-item is-${task.status}`, type: "button",
      data: { task: task.id, key: `task-${task.id}` },
      aria: { current: task.id === selected ? "true" : null },
    },
      h("span", "tc-text",
        h("span", "sr-only", `${OUTCOME[task.status] || task.status}: `), task.text),
      h("span", "tc-meta", meta));
    button.addEventListener("click", () => select(task.id, true));
    return h("li", null, button);
  }

  function renderList(tasks) {
    const shown = tasks.filter(FILTERS[filter]);
    const key = `${filter}|${selected}|` + shown.map((t) => `${t.id}:${t.v}`).join(",");
    if (key === listKey) return;
    listKey = key;
    keepFocus($("tcList"), () => $("tcList").replaceChildren(...shown.map(item)));
    $("tcEmpty").hidden = shown.length > 0;
    $("tcEmpty").textContent = NONE[filter];
  }

  /* ----------------------------------------------------------- timeline */

  function entry(kind, state, at, title, detail, extra) {
    return h("li", { class: `tl tl--${kind} is-${state}` },
      h("span", "tl-at", offset(at)),
      h("div", "tl-body",
        h("p", "tl-title", title),
        detail ? h("p", "tl-detail", detail) : null,
        extra || null));
  }

  function stepEntry(step) {
    if (step.name === "your answer") {
      const approved = step.detail === "approved";
      return entry("answer", approved ? "done" : "declined", step.at,
        approved ? "You approved" : "You declined", step.question || "");
    }
    const state = { running: "running", done: "done", error: "error" }[step.status] || "done";
    const time = step.status === "running" ? "running" : duration(step.ms);
    return entry("tool", state, step.at,
      h("span", null, h("span", "tl-tool", step.name), time ? h("span", "tl-ms", time) : null),
      step.detail || "");
  }

  function planEntry(part, n, total, steps) {
    const inner = steps.length ? h("ol", "timeline timeline--inner", steps.map(stepEntry)) : null;
    return entry("plan", part.status, null,
      h("span", null, `Step ${n} of ${total} · ${part.text}`,
        h("span", "tl-state", PLAN_STATE[part.status] || part.status)),
      null, inner);
  }

  function endEntry(task) {
    const at = task.ms != null ? task.ms / 1000 : null;
    const excerpt = (text) => (text && text.length > 240 ? text.slice(0, 239) + "…" : text || "");
    if (task.status === "done") return entry("end", "done", at, `Done in ${duration(task.ms)}`, excerpt(task.reply));
    if (task.status === "failed") return entry("end", "failed", at, "Didn't finish", task.error || excerpt(task.reply));
    if (task.status === "stopped") return entry("end", "stopped", at, "Stopped", excerpt(task.reply));
    if (task.status === "waiting") return entry("end", "waiting", null, "Waiting for your answer", task.asking);
    return entry("end", "running", null,
      h("span", null, "Running ", h("span", { class: "tl-elapsed", data: { since: task.started } }, "")));
  }

  function timeline(task) {
    const items = [entry("start", "done", 0, task.source === "voice" ? "You said it" : "You typed it",
      task.again_of ? "Asked again, for a fresh answer" : "")];

    if (task.route === "plan") {
      items.push(entry("route", "done", null,
        task.plan ? `Planned it: ${task.plan.length} steps` : "Asked the model whether it needs a plan"));
    } else if (ROUTE[task.route]) {
      items.push(entry("route", "done", null, ROUTE[task.route]));
    }

    task.steps.filter((s) => !s.part).forEach((s) => items.push(stepEntry(s)));
    (task.plan || []).forEach((part, i) => items.push(
      planEntry(part, i + 1, task.plan.length, task.steps.filter((s) => s.part === i + 1))));

    if (task.stopping) items.push(entry("stop", "done", task.stop_at, "You asked it to stop",
      OPEN.includes(task.status) ? "It will, at its next step." : ""));
    items.push(endEntry(task));
    return h("ol", { class: "timeline", aria: { label: "Timeline" } }, items);
  }

  /* ------------------------------------------------------------- detail */

  function controls(task) {
    if (stoppable(task)) {
      const stop = h("button", { class: "btn btn--sm", type: "button", data: { key: "stop" } }, "Stop this");
      stop.addEventListener("click", () => {
        bridge.cancel(task.id).then((why) => say(why || "Asked it to stop. It will at its next step."));
      });
      return stop;
    }
    if (OPEN.includes(task.status) && task.stopping) {
      return h("p", "tc-note", "Stopping at its next step.");
    }
    if (OPEN.includes(task.status)) {
      return h("p", "tc-note", "This one runs on this computer in one go, so it can't be stopped partway. It finishes on its own.");
    }
    return null;
  }

  function renderDetail() {
    const pane = $("tcDetail");
    const task = selected != null ? byId(selected) : null;
    const key = task ? `${task.id}:${task.v}` : "none";
    if (key === detailKey) return;
    detailKey = key;

    keepFocus(pane, () => {
      if (!task) {
        pane.replaceChildren(h("p", "tc-empty", "Pick a task to see what it did."));
        return;
      }
      const meta = [OUTCOME[task.status], `started ${clock(task.started, true)}`];
      if (task.ms != null) meta.push(`took ${duration(task.ms)}`);
      const chat = h("button", { class: "btn btn--sm btn--ghost", type: "button", data: { key: "chat" } }, "Show in Chat");
      chat.addEventListener("click", () => { if (L.chat) L.chat.reveal(task.id); });
      pane.replaceChildren(
        h("div", "tc-head",
          h("h2", { class: "tc-title", id: "tcTitle", tabindex: "-1" }, `“${task.text}”`),
          h("p", { class: `tc-meta is-${task.status}` }, meta.join(" · ")),
          h("div", "tc-controls", controls(task), chat)),
        timeline(task));
    });
    tick();
  }

  /* How long a running task has been at it, from when Python started it. */
  function tick() {
    document.querySelectorAll("#tcDetail .tl-elapsed").forEach((el) => {
      const since = Number(el.dataset.since);
      if (Number.isFinite(since)) el.textContent = `· ${Math.max(0, Date.now() / 1000 - since).toFixed(1)}s`;
    });
  }

  setInterval(tick, 250);

  /* -------------------------------------------------------------- state */

  function select(id, byYou) {
    selected = id;
    if (byYou) picked = true;
    sync();
    if (byYou && document.activeElement && document.activeElement.dataset.key !== `task-${id}`) {
      const again = $("tcList").querySelector(`[data-key="task-${id}"]`);
      if (again) again.focus();
    }
  }

  function sync() {
    const tasks = all();
    if (picked && !tasks.some((t) => t.id === selected)) picked = false;   // it aged out
    if (!picked) {
      const open = tasks.slice().reverse().find((t) => OPEN.includes(t.status));
      selected = open ? open.id : (tasks[0] ? tasks[0].id : null);
    }
    renderFilters(tasks);
    renderList(tasks);
    renderDetail();
  }

  document.querySelectorAll("#tcFilters [data-filter]").forEach((b) => {
    b.addEventListener("click", () => { filter = b.dataset.filter; sync(); });
  });

  L.tasks.onChange(sync);
  sync();

  /* Open a task here from elsewhere (Home's Recent). */
  function open(id) {
    if (!byId(id)) return;
    filter = "all";
    selected = id;
    picked = true;
    sync();
    L.router.go("tasks");
  }

  L.taskCenter = { open };
})();
