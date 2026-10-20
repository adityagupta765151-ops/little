/* The pieces every section shares — the command box, the confirmation
   dialog, the orb's state, and the poll that keeps everything current —
   plus Home's readings. Home's tasks, quick actions and waiting list live
   in js/views/home.js.

   Talks to Python only through js/core/bridge.js, by polling, which behaves
   the same on every pywebview version and keeps all UI work on the UI
   thread. The shell around this — navigation, sections, the palette — lives
   in js/core/router.js and js/components/. */

const $ = (id) => document.getElementById(id);
const body = document.body;
const L = window.Little;
const { h, bridge } = L;                     // ui/js/core/h.js, bridge.js

/* The assistant's name comes from Python (JARVIS_ASSISTANT_NAME), so the
   panel never disagrees with what it says out loud. "Little" until the
   first reading arrives. */
let NAME = "LITTLE";
const call = () => NAME.charAt(0) + NAME.slice(1).toLowerCase();
L.identity = { name: () => NAME, call };

const STATES = {
  offline:     ["Offline",     () => "Click the core to wake me up.", "Activate"],
  calibrating: ["Calibrating", () => "Tuning the mic to your room. Stay quiet a moment.", "Wait"],
  listening:   ["Listening",   () => `Say "${call()}" and then a command.`, "Online"],
  waiting:     ["Listening",   () => "Go ahead.", "Online"],
  thinking:    ["Thinking",    () => "Working it out.", "Busy"],
  executing:   ["Working",     () => "On it.", "Busy"],
  speaking:    ["Speaking",    () => "Press Escape to cut me off.", "Online"],
};

let pendingAsk = null;
let rows = 0;

/* ------------------------------------------------------------- clock */

/* Only writes when the text changes: the page does no work it doesn't show. */
function setText(el, text) { if (el.textContent !== text) el.textContent = text; }

setInterval(() => {
  const d = new Date();
  setText($("clock"), d.toLocaleTimeString("en-GB", { hour12: false }));
  setText($("date"), d.toLocaleDateString("en-GB",
    { weekday: "short", day: "2-digit", month: "short" }));
}, 500);

/* ------------------------------------------------------------- state */

function setState(name) {
  const [word, hint, core] = STATES[name] || STATES.offline;
  if (body.dataset.state === name) return;
  body.dataset.state = name;
  $("stateWord").textContent = word;
  $("hint").textContent = hint();
  $("coreLabel").textContent = core;
  $("topState").textContent = word.toUpperCase();
}

/* Outcomes show over the current state for about a second: the orb closes
   its ring on success, or squints on an error. Called by js/views/home.js
   when a task ends done or failed in Python's task record — never guessed
   from the wording of a reply. */
let flashTimer = null;

function flash(kind) {
  if (kind !== "success" && kind !== "error") return;
  clearTimeout(flashTimer);
  body.dataset.flash = kind;
  const ms = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--flash")) * 1000 || 1100;
  flashTimer = setTimeout(() => { delete body.dataset.flash; }, ms);
}

window.Little.orb = { flash };

/* ------------------------------------------------------------- feed */

/* The one way anything reaches the screen. Every value — a reminder, a tool
   name, a reply, a path — goes in as text, never as markup. Reminder text
   comes from the model, and the model reads web pages; a value written as
   HTML here once let a planted <img> tag answer a confirmation by itself.
   tests/test_ui_safety.py fails the build if HTML-string rendering comes back. */
function node(tag, cls, text) {
  return h(tag, cls || null, text);
}

function addRow(kind, who, message) {
  const feed = $("feed");
  const row = node("div", "row " + kind);
  row.append(
    node("span", "t", new Date().toLocaleTimeString("en-GB", { hour12: false })),
    node("span", "w", who),
    node("span", "m", message),
  );

  const stuck = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 30;
  feed.appendChild(row);
  if (stuck) feed.scrollTop = feed.scrollHeight;
  while (feed.children.length > 400) feed.firstChild.remove();
  $("feedCount").textContent = ++rows;
}

function logLine(text) {
  if (text.startsWith("You: ")) return addRow("you", "you", text.slice(5));
  // Its own replies are prefixed with its name. "JARVIS: " is still read,
  // so a log written before the rename shows up the same way.
  for (const prefix of [NAME + ": ", "JARVIS: "]) {
    if (text.startsWith(prefix)) {
      return addRow("assistant", call().toLowerCase(), text.slice(prefix.length));
    }
  }
  if (text.startsWith("   > ")) return addRow("tool", "·", text.slice(5));
  const warn = /GEMINI_API_KEY|^I couldn't|isn't signed in|rate limit|no linked/i.test(text);
  addRow(warn ? "warn" : "note", "", text.trim());
}

/* ------------------------------------------------------------- panels */

function gauge(name, percent, label) {
  const row = node("div", "gauge");
  const bar = node("span", "bar");
  const fill = node("i");
  const value = Math.max(0, Math.min(100, Number(percent) || 0));
  fill.style.width = value + "%";
  bar.append(fill);
  row.append(node("span", "g-name", name), bar, node("span", "g-val", label));
  return row;
}

function kv(pairs) {
  const out = [];
  pairs.forEach(([k, v, cls]) => out.push(node("dt", null, k), node("dd", cls || null, v)));
  return out;
}

function list(items, empty, render) {
  return items.length ? items.map(render) : [node("li", "muted", empty)];
}

function pair(left, right) {
  const li = node("li");
  li.append(node("span", null, left), node("span", null, right));
  return li;
}

function paintIdentity(identity) {
  if (!identity || !identity.name || identity.name === NAME) return;
  NAME = identity.name;
  $("brandName").textContent = NAME;
  L.router.retitle();
  $("power").setAttribute("aria-label", "Activate " + call());
  const state = body.dataset.state;
  if (STATES[state]) $("hint").textContent = STATES[state][1]();
}

/* Readings arrive with every poll, five times a second, mostly unchanged.
   Measured before this: the page rebuilt about 360 elements a second doing
   nothing, on every section. Now what every section needs — the name, the
   mute state — is applied at once; Home's panels are drawn only when the
   readings changed, and only while Home is showing (the newest are drawn
   the moment you go back to it). */
let statsDrawn = "";
let statsLater = null;

function takeStats(s) {
  paintIdentity(s.identity);
  if (L.chat && s.voice) L.chat.setMuted(s.voice.speech === "muted");
  const key = JSON.stringify(s);
  if (key === statsDrawn) { statsLater = null; return; }
  if (L.router.current() !== "home") { statsLater = s; return; }
  statsDrawn = key;
  statsLater = null;
  paintStats(s);
}

L.router.onChange((id) => {
  if (id !== "home" || !statsLater) return;
  const s = statsLater;
  statsLater = null;
  statsDrawn = JSON.stringify(s);
  guarded(() => paintStats(s));
});

function paintStats(s) {
  paintIdentity(s.identity);
  if (L.home) L.home.setWarnings(s.warnings);
  const sys = s.system || {};
  if (sys.available) {
    $("gauges").replaceChildren(
      gauge("CPU", sys.cpu, sys.cpu + "%"),
      gauge("RAM", sys.ram, sys.ram + "%"),
      gauge("DSK", sys.disk, sys.disk + "%"),
    );
    $("sysKv").replaceChildren(...kv([
      ["memory", `${sys.ram_used} / ${sys.ram_total} GB`],
      ["free disk", sys.disk_free + " GB"],
      ["os", s.session.os],
    ]));
  } else {
    $("gauges").replaceChildren(node("p", "muted", "install psutil for live readings"));
    $("sysKv").replaceChildren(...kv([["os", s.session.os]]));
  }

  const v = s.voice;
  if (L.chat) L.chat.setMuted(v.speech === "muted");
  $("voiceKv").replaceChildren(...kv([
    ["mic", v.mic, v.mic === "on" ? "on" : "off"],
    ["speech", v.speech, v.speech === "on" ? "on" : "off"],
    ["voice", v.voice || "—"],
    ["language", v.lang],
    ["model", v.model],
  ]));

  $("sessionKv").replaceChildren(...kv([
    ["uptime", s.session.uptime],
    ["commands", s.session.commands],
    ["tool calls", s.session.tools],
    ["workspace", String(s.workspace).split(/[\\/]/).pop() || s.workspace],
  ]));

  $("toolList").replaceChildren(...list(s.tools, "nothing yet",
    (t) => pair(t.name, `${t.ms} ms`)));

  $("remList").replaceChildren(...list(s.reminders, "none set",
    (r) => pair(r.text, r.at)));

  const plan = s.plan;
  if (plan) {
    $("planCount").textContent = `${plan.at}/${plan.steps.length}`;
    $("planSteps").replaceChildren(...plan.steps.map((step, i) => {
      const record = plan.done[i];
      let cls = "";
      if (record) cls = record.ok ? "done" : "bad";
      else if (i + 1 === plan.at) cls = "now";
      const li = node("li", cls || null);
      li.append(node("span", null, step));
      return li;
    }));
  } else {
    $("planCount").textContent = "";
    $("planSteps").replaceChildren(node("li", "muted", "no plan running"));
  }

  $("resKv").replaceChildren(...kv([
    ["browser", s.browser, s.browser === "open" ? "on" : "off"],
    ["contacts", s.contacts],
  ]));
}

/* ------------------------------------------------------------- confirm */

/* A confirmation guards something that can't be undone — a message sent, a
   file deleted. So it opens on No: an Enter meant for the command box,
   pressed just as the dialog appears, cancels instead of approving. Yes
   also stays unclickable for a moment, so a click already on its way
   can't land on it. Approving always takes a deliberate second action. */
const ARM_MS = 700;
const PREVIEW_LINES = 6;       // of a question's details, before Review
const PREVIEW_CHARS = 420;

let askNeedsReview = false;
let askArmed = false;
let askReturn = null;          // what had focus before the question, to go back to

/* The first few lines of the details, and whether that's all of them. */
function preview(text) {
  const lines = String(text || "").split("\n");
  let shown = lines.slice(0, PREVIEW_LINES).join("\n");
  if (shown.length > PREVIEW_CHARS) shown = shown.slice(0, PREVIEW_CHARS).trimEnd();
  return { shown, cut: shown.length < String(text || "").length };
}

/* Confirm is live once the moment has passed and, if there was more than
   the preview showed, once Review has been opened. */
function updateAskYes() {
  $("askYes").disabled = !askArmed || askNeedsReview;
}

function showAsk(ask) {
  // The palette never sits over a question; it closes, and focus comes here.
  if (L.palette && L.palette.isOpen()) L.palette.close(false);
  pendingAsk = ask.id;
  const was = document.activeElement;
  askReturn = was && !$("veil").contains(was) ? was : null;
  // Everything behind the question is out of reach — for the mouse, for Tab
  // and for a screen reader — until it's answered.
  document.querySelector(".shell").inert = true;
  const structured = typeof ask.action === "string" && ask.action !== "";
  const details = structured ? ask.details || "" : ask.message;
  const { shown, cut } = preview(details);

  $("askKicker").textContent = structured ? `${call()} wants to` : `${call()} needs your OK`;
  $("askTitle").textContent = structured ? ask.action : "Confirmation required";
  $("askTarget").textContent = structured ? ask.target || "" : "";
  $("askTarget").hidden = !$("askTarget").textContent;
  $("askText").textContent = shown;
  $("askText").hidden = !shown;
  $("askMore").hidden = !cut;
  $("askConsequence").textContent = structured ? ask.consequence || "" : "";
  $("askConsequence").hidden = !$("askConsequence").textContent;
  $("askConsequence").dataset.tone = ask.tone || "caution";
  $("askFull").textContent = details;
  $("askTool").textContent = structured && ask.tool ? `Tool: ${ask.tool}` : "";
  $("askReview").hidden = true;
  $("askReviewBtn").hidden = !structured && !cut;
  $("askReviewBtn").setAttribute("aria-expanded", "false");

  const yes = $("askYes");
  yes.textContent = structured && ask.verb ? ask.verb : "Yes, go ahead";
  yes.className = "btn " + (ask.tone === "safe" ? "btn--primary" : "btn--caution");
  askNeedsReview = cut;
  askArmed = false;
  yes.disabled = true;
  setTimeout(() => { if (pendingAsk === ask.id) { askArmed = true; updateAskYes(); } }, ARM_MS);
  $("veil").hidden = false;
  $("askNo").focus();
}

function reviewAsk() {
  const open = $("askReview").hidden;
  $("askReview").hidden = !open;
  $("askReviewBtn").setAttribute("aria-expanded", String(open));
  if (open) { askNeedsReview = false; updateAskYes(); }
}

function answerAsk(ok) {
  if (pendingAsk === null) return;
  bridge.confirmReply(pendingAsk, ok);
  pendingAsk = null;
  $("veil").hidden = true;
  document.querySelector(".shell").inert = false;
  // Back where you were, if it's still there to go back to; else the command box.
  const back = askReturn && askReturn.isConnected && askReturn.offsetParent !== null ? askReturn : $("input");
  askReturn = null;
  back.focus();
}

/* Tab and Shift+Tab go round the dialog's own buttons, never behind it. */
$("veil").addEventListener("keydown", (e) => {
  if (e.key !== "Tab" || pendingAsk === null) return;
  const stops = [...$("veil").querySelectorAll("button")].filter((b) => !b.hidden && !b.disabled);
  if (!stops.length) return;
  const at = stops.indexOf(document.activeElement);
  const next = e.shiftKey ? (at <= 0 ? stops.length - 1 : at - 1) : (at + 1) % stops.length;
  e.preventDefault();
  stops[next].focus();
});

/* ------------------------------------------------------------- announcing */

/* A reply is said to a screen reader when its task ends — once, briefly,
   from outside the page so it's heard even behind a dialog. */
function announce(text) {
  const out = $("announcer");
  out.textContent = "";
  setTimeout(() => { out.textContent = text; }, 50);
}

L.tasks.onChange(({ ended }) => {
  const task = ended[ended.length - 1];
  if (!task) return;
  const said = task.status === "failed" ? `Didn't finish: ${task.error || task.reply || ""}`
    : task.status === "stopped" ? "Stopped." : task.reply || "Done.";
  const line = said.replace(/\s+/g, " ").trim();
  announce(`${call()}: ${line.length > 240 ? line.slice(0, 240) + "…" : line}`);
});

/* ------------------------------------------------------------- loop */

/* Each part of a poll is drawn on its own, so one that fails can't stop
   the others — least of all a confirmation, which goes first. A failure is
   reported to the console rather than swallowed: a silent catch here once
   hid a rendering bug. (The bridge itself already turns a closing window or
   a Python that isn't up yet into an empty answer.) */
function guarded(draw) {
  try { draw(); } catch (e) { console.error(e); }
}

async function poll() {
  // Tell Python which tasks the page already has; only changes come back.
  const data = (await bridge.poll(L.tasks.version())) || {};
  if (data.ask && pendingAsk === null) guarded(() => showAsk(data.ask));
  if (data.status) guarded(() => setState(data.status));
  guarded(() => (data.lines || []).forEach(logLine));
  if (data.tasks) guarded(() => L.tasks.apply(data.tasks));
  if (data.stats) guarded(() => takeStats(data.stats));
}

/* Replies show on Home (Activity) and in Chat. A command typed on any other
   section takes you to Home; on those two you stay. The cursor stays in the
   command box. */
function sendText(text) {
  bridge.send(text);
  const here = L.router.current();
  if (here !== "home" && here !== "chat") L.router.go("home", { focus: false });
}

function send() {
  const input = $("input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  sendText(text);
}

function mute() {
  return bridge.control("mute").then((label) => { if (label) $("muteBtn").textContent = label; });
}

function clearLog() {
  $("feed").replaceChildren(); rows = 0; $("feedCount").textContent = "";
}

/* What the palette can press. The same functions the buttons use. */
L.actions = {
  send: sendText,
  toggle: () => bridge.toggle(),
  mute,
  muteLabel: () => $("muteBtn").textContent,
  stop: () => bridge.control("stop"),
  closeBrowser: () => bridge.control("browser"),
  clearLog,
};

$("power").onclick = () => bridge.toggle();
$("send").onclick = send;
$("input").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
$("askYes").onclick = () => answerAsk(true);
$("askNo").onclick = () => answerAsk(false);
$("askReviewBtn").onclick = reviewAsk;

document.querySelectorAll(".acts button").forEach((b) => {
  b.onclick = () => {
    if (b.dataset.act === "clear") return clearLog();
    if (b.dataset.act === "mute") return mute();
    bridge.control(b.dataset.act);
  };
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (pendingAsk !== null) return answerAsk(false);
    if (L.palette && L.palette.isOpen()) return L.palette.close(true);
    bridge.control("stop");
  }
  if (e.ctrlKey && e.code === "Space") bridge.toggle();
});

window.addEventListener("pywebviewready", () => {
  addRow("note", "", `Hi, I'm ${call()}. Type a command, or click me to use your voice.`);
  $("input").focus();
  setInterval(poll, 200);
  poll();
});
