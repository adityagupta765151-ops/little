/* LITTLE — Chat.

   The conversation, one turn per command: what you asked, then Little's
   reply with the steps it took inside it — each tool as it ran, with its
   timing. While a turn is still running its steps show live; that is the
   progress there is (the reply arrives whole, so nothing here types itself
   out letter by letter).

   Under each finished reply:
     Copy       the reply, to the clipboard
     Speak      read out again, as briefly as the voice does
     Save       into "Saved from Little.md" in your workspace
     Try again  for one that didn't finish: sends the same command
     Ask again  for the model's latest plain answer: it answers afresh,
                forgetting the first answer. Never for one that ran tools,
                so asking again can't do anything twice.

   Speak, Save and Ask again name a task by its id; Python looks up the
   text itself, so the page can't hand it words to say or write.

   "New conversation" makes the model forget this one, after you confirm,
   and Chat starts again from there. Everything comes from the task record
   (jarvis/app/tasks.py); turns are re-drawn only when their task changes,
   so an open step list, the scroll position and keyboard focus survive the
   updates that arrive every poll. */
(function () {
  const L = (window.Little = window.Little || {});
  const { h, bridge } = L;
  const $ = (id) => document.getElementById(id);

  // Where the answer is coming from, while it runs and once it's in.
  const WORKING = { local: "on this computer", model: "asking the model", plan: "working through a plan" };
  const ANSWERED = { local: "on this computer", model: "by the model", plan: "as a plan" };
  const OPEN = ["active", "waiting"];

  const list = $("turns");
  const scroller = $("turnsWrap");     // the list, the divider and the empty note scroll together
  const rendered = new Map();        // task id -> { key, el }
  const expanded = new Map();        // task id -> true/false, once you've chosen
  let muted = false;
  let statusTimer = null;

  const call = () => (L.identity ? L.identity.call() : "Little");

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

  function say(message) {
    const out = $("chatStatus");
    out.textContent = message || "";
    clearTimeout(statusTimer);
    if (message) statusTimer = setTimeout(() => { out.textContent = ""; }, 5000);
  }

  /* The turns to show: everything after the latest new conversation. */
  function visible() {
    const all = L.tasks.recent(Infinity).reverse();
    let from = -1;
    all.forEach((task, i) => { if (task.reset) from = i; });
    return { fresh: from >= 0 ? all[from] : null, turns: all.slice(from + 1) };
  }

  function latestModelAnswer(turns) {
    for (let i = turns.length - 1; i >= 0; i--) {
      if (turns[i].route === "model") return turns[i];
    }
    return null;
  }

  function canAskAgain(task, turns) {
    if (task.status !== "done" || task.route !== "model" || task.steps.length) return false;
    if (!task.reply) return false;
    if (turns.some((t) => OPEN.includes(t.status))) return false;
    const latest = latestModelAnswer(turns);
    return !!latest && latest.id === task.id;
  }

  /* ------------------------------------------------------------ actions */

  async function copy(task, button) {
    let ok = false;
    try {
      await navigator.clipboard.writeText(task.reply);
      ok = true;
    } catch (e) {
      // Where the clipboard API isn't allowed, the old way still works.
      const area = h("textarea", { class: "sr-only", readonly: true, aria: { hidden: "true" } });
      area.value = task.reply;
      document.body.append(area);
      area.select();
      try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
      area.remove();
      button.focus();
    }
    say(ok ? "Copied." : "I couldn't reach the clipboard. Select the text and copy it instead.");
  }

  function speak(task) {
    bridge.speak(task.id).then((why) => say(why || "Reading it out."));
  }

  function save(task) {
    bridge.save(task.id).then((where) => say(where || "Saved."));
  }

  function tryAgain(task) {
    say("Trying again.");
    L.actions.send(task.text);
  }

  function askAgain(task) {
    bridge.regenerate(task.id).then((why) => say(why || "Asking again."));
  }

  /* -------------------------------------------------------------- turns */

  function stepRow(step) {
    const cls = { running: "now", done: "done", error: "bad" }[step.status] || null;
    return h("li", cls,
      h("span", "step-name", step.name),
      h("span", "step-detail", step.detail || ""),
      h("span", "step-ms", step.status === "running" ? "…" : duration(step.ms)));
  }

  function stepsBlock(task) {
    const n = task.steps.length;
    if (!n) return null;
    const running = OPEN.includes(task.status);
    const open = expanded.has(task.id) ? expanded.get(task.id) : running;
    const failed = task.steps.filter((s) => s.status === "error").length;
    const total = task.steps.reduce((sum, s) => sum + (s.ms || 0), 0);
    const summary = `${n} step${n > 1 ? "s" : ""}`
      + (failed ? ` · ${failed} failed` : "")
      + (!running && total ? ` · ${duration(total)}` : "");
    const listId = `trace-${task.id}`;

    const toggle = h("button", {
      class: "steps-toggle", type: "button",
      aria: { expanded: String(open), controls: listId },
      data: { key: `steps-${task.id}` },
      on: { click: () => {
        const now = toggle.getAttribute("aria-expanded") !== "true";
        expanded.set(task.id, now);
        toggle.setAttribute("aria-expanded", String(now));
        $(listId).hidden = !now;
      } },
    }, summary);

    return h("div", "msg-steps", toggle,
      h("ol", { class: "steps trace", id: listId, hidden: !open }, task.steps.map(stepRow)));
  }

  function body(task) {
    if (task.status === "active") {
      return h("p", "msg-working", "Working on it ",
        h("span", { class: "msg-elapsed", data: { since: task.started } }, ""));
    }
    if (task.status === "waiting") {
      return h("p", "msg-asking", "Waiting for your answer: ", task.asking);
    }
    if (task.status === "failed") {
      const why = task.error || task.reply;
      return [h("p", "msg-fail", "Didn't finish"), why ? h("div", "msg-reply", why) : null];
    }
    const parts = [h("div", "msg-reply", task.reply || (task.status === "stopped" ? "Stopped." : ""))];
    if (task.reply_cut) {
      parts.push(h("p", "msg-note", "This reply is long, so it's cut short here. Activity on Home has all of it."));
    }
    return parts;
  }

  function actions(task, turns) {
    if (OPEN.includes(task.status)) return null;
    const has = !!(task.reply && task.reply.trim());
    const button = (label, key, fn, extra) => {
      const el = h("button", { class: "btn btn--sm btn--ghost", type: "button",
                               data: { key: `${key}-${task.id}`, act: key }, ...extra }, label);
      el.addEventListener("click", () => fn(task, el));
      return el;
    };
    return h("div", { class: "msg-acts", role: "group", aria: { label: "Reply actions" } },
      has ? button("Copy", "copy", copy) : null,
      has ? button("Speak", "speak", speak,
        muted ? { disabled: true, title: "Voice is muted" } : {}) : null,
      has ? button("Save", "save", save) : null,
      task.status === "failed" || task.status === "stopped"
        ? button("Try again", "retry", tryAgain) : null,
      canAskAgain(task, turns) ? button("Ask again", "again", askAgain) : null);
  }

  function turn(task, turns) {
    const when = [clock(task.started)];
    if (task.source === "voice") when.push("said");
    if (task.again_of) when.push("asked again");
    const how = task.status === "waiting" ? "waiting for you"
      : OPEN.includes(task.status) ? (WORKING[task.route] || "starting")
      : [ANSWERED[task.route] || "", duration(task.ms)].filter(Boolean).join(" · ");

    return h("li", { class: `turn is-${task.status}`, data: { task: task.id } },
      h("div", "msg msg--you",
        h("p", "msg-who", "You", h("span", "msg-when", when.join(" · "))),
        h("p", "msg-text", task.text)),
      h("div", "msg msg--little",
        h("p", "msg-who", call(), h("span", "msg-when", how)),
        stepsBlock(task),
        body(task),
        actions(task, turns)));
  }

  /* What decides whether a turn has to be re-drawn: its task changed, or
     something its buttons depend on did. */
  function keyOf(task, turns) {
    return `${task.v}|${muted}|${canAskAgain(task, turns)}|${call()}`;
  }

  /* ------------------------------------------------------------- render */

  function atBottom() {
    return scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 40;
  }

  function sync() {
    const { fresh, turns } = visible();
    const stuck = atBottom();
    let arrived = false;

    const keep = new Set(turns.map((t) => t.id));
    for (const [id, rec] of rendered) {
      if (!keep.has(id)) { rec.el.remove(); rendered.delete(id); }
    }

    let before = list.firstChild;
    turns.forEach((task) => {
      const key = keyOf(task, turns);
      let rec = rendered.get(task.id);
      if (!rec || rec.key !== key) {
        const el = turn(task, turns);
        if (rec) {
          // Swap in place, and put keyboard focus back where it was.
          const focused = rec.el.contains(document.activeElement)
            ? document.activeElement.dataset.key : null;
          // The new element takes the old one's place, including as the
          // insertion point — the old one is about to leave the list.
          if (before === rec.el) before = el;
          rec.el.replaceWith(el);
          if (focused) {
            const again = el.querySelector(`[data-key="${CSS.escape(focused)}"]`);
            if (again && !again.disabled) again.focus();
          }
        } else {
          arrived = true;
        }
        rec = { key, el };
        rendered.set(task.id, rec);
      }
      if (rec.el !== before) list.insertBefore(rec.el, before);
      before = rec.el.nextSibling;
    });

    $("chatFresh").hidden = !fresh;
    if (fresh) $("chatFresh").textContent = `New conversation · ${clock(fresh.started)}`;
    $("chatEmpty").hidden = turns.length > 0;
    $("chatEmpty").textContent = fresh
      ? "Fresh start. Ask me anything below."
      : "Nothing here yet. Ask me anything below — my replies show up here, with the steps I took.";

    if (arrived || stuck) scroller.scrollTop = scroller.scrollHeight;
    tick();
  }

  /* How long a running turn has been at it: from when Python started it. */
  function tick() {
    list.querySelectorAll(".msg-elapsed").forEach((el) => {
      const since = Number(el.dataset.since);
      if (Number.isFinite(since)) {
        el.textContent = `· ${Math.max(0, Date.now() / 1000 - since).toFixed(1)}s`;
      }
    });
  }

  setInterval(tick, 250);

  /* --------------------------------------------------- new conversation */

  /* Forgetting the conversation can't be undone, so it takes two clicks,
     and the second one's default is to keep it. */
  function confirmReset(asking) {
    $("newChat").hidden = asking;
    $("resetAsk").hidden = !asking;
    if (asking) $("resetKeep").focus();
  }

  $("newChat").addEventListener("click", () => confirmReset(true));
  $("resetKeep").addEventListener("click", () => { confirmReset(false); $("newChat").focus(); });
  $("resetYes").addEventListener("click", () => {
    confirmReset(false);
    L.actions.send("new conversation");
    $("newChat").focus();
  });
  $("resetAsk").addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    e.stopPropagation();                       // Escape here means "keep it", not "stop"
    confirmReset(false);
    $("newChat").focus();
  });

  /* ------------------------------------------------------------- wiring */

  L.tasks.onChange(sync);

  if (L.router) {
    L.router.onChange((id) => {
      if (id === "chat") scroller.scrollTop = scroller.scrollHeight;
      else confirmReset(false);
    });
  }

  function setMuted(value) {
    if (muted === !!value) return;
    muted = !!value;
    sync();
  }

  sync();

  /* Show one turn, from elsewhere (the Task Center). */
  function reveal(id) {
    L.router.go("chat");
    const row = list.querySelector(`[data-task="${Number(id)}"]`);
    if (row) row.scrollIntoView({ block: "center" });
  }

  L.chat = { setMuted, reveal };
})();
