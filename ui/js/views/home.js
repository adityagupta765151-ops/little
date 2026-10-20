/* LITTLE — Home.

   Answers, at a glance: what is Little doing, what can I do, what happened,
   and does anything need me.

     the hero       the orb, its state, and the task in hand with its steps
                    as they happen — or the last one, when nothing's running
     quick actions  commands Little already answers, or a start you finish
     waiting        setup problems and tasks that didn't finish, with a way
                    to try again
     recent         the last few tasks and how each one ended

   Everything comes from the task record in Python (jarvis/app/tasks.py) and
   the readings. The orb's success and error signs show when a task ends
   done or failed — an outcome the code decided, never read from the
   wording of a reply. */
(function () {
  const L = (window.Little = window.Little || {});
  const { h } = L;
  const $ = (id) => document.getElementById(id);

  /* A quick action either sends a command Little answers on this computer
     (tests/test_shell.py checks each one against the real router), or puts
     the start of one in the command box for you to finish — the … says so.
     "Set a reminder" and "Several steps" are what the plan called Create
     Task and Run Automation, named for what they actually do. */
  const QUICK = [
    { say: "find jobs for me", label: "Find jobs" },
    { say: "show my resume profile", label: "My resume" },
    { say: "what do you remember", label: "What you remember" },
    { fill: "look up ", label: "Look something up…" },
    { fill: "remind me to ", label: "Set a reminder…" },
    { fill: "first ", label: "Several steps…" },
  ];

  const ROUTE = {
    local: "on this computer",
    model: "asking the model",
    plan: "working through a plan",
  };
  const OUTCOME = {
    active: "running", waiting: "waiting for you",
    done: "done", failed: "didn't finish", stopped: "stopped",
  };
  const STEPS_SHOWN = 3;
  const RECENT_SHOWN = 5;
  const FAILED_SHOWN = 3;

  let warnings = [];
  let warningsKey = "";
  const dismissed = new Set();

  /* ------------------------------------------------------------ helpers */

  function duration(ms) {
    if (ms == null || !Number.isFinite(ms)) return "";
    if (ms < 1000) return `${Math.round(ms)} ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
    const s = Math.round(ms / 1000);
    return `${Math.floor(s / 60)}m ${s % 60}s`;
  }

  function clock(epochSeconds) {
    return new Date(epochSeconds * 1000).toLocaleTimeString("en-GB",
      { hour: "2-digit", minute: "2-digit", hour12: false });
  }

  /* Re-rendering a list mustn't throw away keyboard focus inside it. */
  function keepFocus(container, render) {
    const active = document.activeElement;
    const key = container.contains(active) && active.dataset ? active.dataset.key : null;
    render();
    if (key) {
      const again = container.querySelector(`[data-key="${CSS.escape(key)}"]`);
      if (again) again.focus();
    }
  }

  /* ------------------------------------------------------ quick actions */

  function runQuick(action) {
    if (action.say) {
      L.actions.send(action.say);
      return;
    }
    const input = $("input");
    input.value = action.fill;
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }

  $("quick").replaceChildren(...QUICK.map((action) => h("button", {
    class: "btn btn--sm",
    data: action.say ? { say: action.say } : { fill: action.fill },
    on: { click: () => runQuick(action) },
  }, action.label)));

  /* -------------------------------------------------------------- hero */

  function stepRow(step) {
    const cls = { running: "now", done: "done", error: "bad" }[step.status] || null;
    return h("li", { class: cls, title: step.detail || null },
      h("span", "step-name", step.name),
      h("span", "step-ms", step.status === "running" ? "…" : duration(step.ms)));
  }

  function renderNow() {
    const task = L.tasks.current();
    const now = $("now");
    const last = $("lastTask");

    if (task) {
      $("hint").hidden = true;
      last.hidden = true;
      now.hidden = false;
      now.classList.toggle("is-waiting", task.status === "waiting");
      $("nowText").textContent = `“${task.text}”`;
      const how = task.stopping ? "stopping at its next step"
        : task.status === "waiting" ? "waiting for your answer"
        : (ROUTE[task.route] || "starting");
      $("nowMeta").textContent = task.source === "voice" ? `${how} · you said it` : how;

      const steps = task.steps.slice(-STEPS_SHOWN);
      const earlier = task.steps.length - steps.length;
      // replaceChildren would write a null out as the text "null".
      const rows = steps.map(stepRow);
      if (earlier > 0) rows.unshift(h("li", "muted", `${earlier} earlier step${earlier > 1 ? "s" : ""}`));
      $("nowSteps").replaceChildren(...rows);
      tick();
      return;
    }

    now.hidden = true;
    $("hint").hidden = false;
    const previous = L.tasks.recent(1)[0];
    if (!previous) { last.hidden = true; return; }
    last.hidden = false;
    last.replaceChildren(
      "Last: ",
      h("span", "last-text", `“${previous.text}”`),
      ` · ${OUTCOME[previous.status] || previous.status}`
        + (previous.ms != null ? ` · ${duration(previous.ms)}` : ""));
  }

  /* How long the task in hand has run: a real measurement, from the moment
     Python started it. */
  function tick() {
    const task = L.tasks.current();
    if (!task) return;
    const seconds = Math.max(0, Date.now() / 1000 - task.started);
    $("elapsed").textContent = seconds.toFixed(1) + "s";
  }

  setInterval(tick, 100);

  /* ------------------------------------------------------------- recent */

  function renderRecent() {
    const list = $("recentList");
    const items = L.tasks.recent(RECENT_SHOWN);
    if (!items.length) {
      list.replaceChildren(h("li", "muted", "Nothing yet. What you ask shows up here."));
      return;
    }
    keepFocus(list, () => list.replaceChildren(...items.map((task) => {
      const running = task.status === "active" || task.status === "waiting";
      const meta = running ? OUTCOME[task.status]
        : `${clock(task.started)} · ${duration(task.ms)}`;
      // Each one opens in the Task Center, with its timeline.
      const button = h("button", { class: "task-open", type: "button",
                                   data: { key: `recent-${task.id}` }, title: task.error || null },
        h("span", "task-text",
          h("span", "sr-only", (OUTCOME[task.status] || task.status) + ": "), task.text),
        h("span", "task-meta", meta));
      button.addEventListener("click", () => L.taskCenter && L.taskCenter.open(task.id));
      return h("li", { class: "is-" + task.status }, button);
    })));
  }

  /* ------------------------------------------------------------ waiting */

  function retry(task) {
    dismissed.add(task.id);
    L.actions.send(task.text);
    renderWaiting();
  }

  function dismiss(task) {
    dismissed.add(task.id);
    renderWaiting();
  }

  function renderWaiting() {
    const list = $("waitList");
    const failed = L.tasks.failed().filter((t) => !dismissed.has(t.id)).slice(0, FAILED_SHOWN);

    const items = [
      ...warnings.map((w) => h("li", "is-warn",
        h("p", "wait-title", w.text),
        h("p", "wait-detail", w.fix))),
      ...failed.map((task) => h("li", "is-failed",
        h("p", "wait-title", `Didn't finish: “${task.text}”`),
        task.error ? h("p", "wait-detail", task.error) : null,
        h("div", "wait-acts",
          h("button", { class: "btn btn--sm", data: { key: `retry-${task.id}` },
                        on: { click: () => retry(task) } }, "Try again"),
          h("button", { class: "btn btn--sm btn--ghost", data: { key: `dismiss-${task.id}` },
                        aria: { label: `Dismiss “${task.text}”` },
                        on: { click: () => dismiss(task) } }, "Dismiss")))),
    ];

    $("waitCount").textContent = items.length ? String(items.length) : "";
    keepFocus(list, () => list.replaceChildren(
      ...(items.length ? items : [h("li", "muted", "Nothing needs you right now.")])));
  }

  function setWarnings(list) {
    const clean = Array.isArray(list)
      ? list.filter((w) => w && typeof w.text === "string" && typeof w.fix === "string")
      : [];
    const key = JSON.stringify(clean.map((w) => [w.text, w.fix]));
    if (key === warningsKey) return;               // readings arrive twice a second
    warningsKey = key;
    warnings = clean;
    renderWaiting();
  }

  /* ------------------------------------------------------------ outcome */

  L.tasks.onChange(({ ended, first }) => {
    renderNow();
    renderRecent();
    renderWaiting();
    if (first || !ended.length) return;
    const outcome = ended[ended.length - 1].status;
    const orb = L.orb;
    if (!orb) return;
    if (outcome === "done") orb.flash("success");
    else if (outcome === "failed") orb.flash("error");
  });

  L.home = { setWarnings, quick: QUICK };
})();
