/* LITTLE — the command palette (Ctrl+K).

   Type to jump to a section, press a control, run a command Little already
   knows, or — if nothing fits — ask Little in your own words. Everything is
   reachable from the keyboard: arrows move, Enter runs, Escape closes and
   puts focus back where it was.

   It is a combobox over a listbox: focus stays in the text box, and the
   highlighted row is announced through aria-activedescendant.

   A confirmation always wins. If one arrives while the palette is open,
   the palette closes and the confirmation takes focus (app.js), and the
   palette won't open over one. */
(function () {
  const L = (window.Little = window.Little || {});
  const { h } = L;

  const veil = document.getElementById("paletteVeil");
  const input = document.getElementById("paletteInput");
  const list = document.getElementById("paletteList");

  const GROUPS = ["Go to", "Controls", "Commands"];

  let items = [];          // the rows on screen, in order
  let active = 0;
  let returnTo = null;

  const isOpen = () => !veil.hidden;
  const actions = () => L.actions || {};
  const call = () => (L.identity ? L.identity.call() : "Little");

  /* Everything the palette can do, read fresh each time it opens, so a
     label like Mute / Unmute is always the true one. */
  function catalogue() {
    const out = [];
    const a = actions();

    L.router.routes.forEach((route, i) => out.push({
      group: "Go to", kind: "go", label: route.title, keywords: route.keywords,
      hint: `Alt ${i + 1}`, run: () => L.router.go(route.id),
    }));

    const listening = document.body.dataset.state !== "offline";
    out.push({ group: "Controls", kind: "control",
      label: listening ? "Stop listening" : "Start listening",
      keywords: "wake sleep microphone mic voice activate", hint: "Ctrl Space",
      run: () => a.toggle && a.toggle() });
    out.push({ group: "Controls", kind: "control",
      label: a.muteLabel ? a.muteLabel() : "Mute voice",
      keywords: "sound speech quiet silence unmute", run: () => a.mute && a.mute() });
    out.push({ group: "Controls", kind: "control", label: "Stop",
      keywords: "interrupt cancel cut off quiet", hint: "Esc", run: () => a.stop && a.stop() });
    out.push({ group: "Controls", kind: "control", label: "Close the browser",
      keywords: "automation chromium", run: () => a.closeBrowser && a.closeBrowser() });
    out.push({ group: "Controls", kind: "control", label: "Clear the activity log",
      keywords: "feed screen", run: () => a.clearLog && a.clearLog() });
    if (L.sidenav && L.sidenav.canToggle()) {
      out.push({ group: "Controls", kind: "control",
        label: L.sidenav.shape() === "full" ? "Collapse the sidebar" : "Expand the sidebar",
        keywords: "navigation menu labels", run: () => L.sidenav.toggle() });
    }

    (L.sections ? L.sections.commands() : []).forEach((command) => out.push({
      group: "Commands", kind: "say", label: command.label, keywords: command.say,
      run: () => a.send && a.send(command.say),
    }));
    return out;
  }

  /* Every word typed must appear somewhere; words at the start of the label
     or of a word count for more. 0 means no match. */
  function score(item, words) {
    if (!words.length) return 1;
    const label = item.label.toLowerCase();
    const hay = label + " " + (item.keywords || "").toLowerCase();
    let total = 0;
    for (const word of words) {
      const at = hay.indexOf(word);
      if (at < 0) return 0;
      total += at === 0 ? 4 : /\s/.test(hay[at - 1]) ? 2 : 1;
      if (label.includes(word)) total += 2;
    }
    return total;
  }

  function option(item) {
    const index = items.length;
    items.push(item);
    return h("div", {
      class: "palette-item", id: "palOpt" + index, role: "option",
      aria: { selected: "false" }, data: { index },
      on: {
        mousedown: (e) => e.preventDefault(),        // keep focus in the text box
        mousemove: () => { if (active !== index) setActive(index, false); },
        click: () => runAt(index),
      },
    }, h("span", "palette-label", item.label),
       item.hint ? h("span", "palette-hint", item.hint) : null);
  }

  function group(title, rows, n) {
    const id = "palGroup" + n;
    return h("div", { role: "group", aria: { labelledby: id } },
      h("div", { class: "palette-group", id, role: "presentation" }, title),
      rows.map(option));
  }

  function render() {
    const text = input.value.trim();
    const words = text.toLowerCase().split(/\s+/).filter(Boolean);
    const scored = catalogue()
      .map((item) => ({ item, score: score(item, words) }))
      .filter((x) => x.score > 0);

    items = [];
    const nodes = [];
    GROUPS.forEach((title, n) => {
      const rows = scored.filter((x) => x.item.group === title)
        .sort((a, b) => b.score - a.score)
        .map((x) => x.item);
      if (rows.length) nodes.push(group(title, rows, n));
    });

    // Whatever was typed can always be asked as it is. It goes to Python as
    // text, exactly like the command box, and anything consequential still
    // stops at a confirmation there.
    if (text) {
      nodes.push(group("Ask", [{
        kind: "say", label: `Ask ${call()}: “${text}”`,
        run: () => actions().send && actions().send(text),
      }], GROUPS.length));
    }

    list.replaceChildren(...nodes);
    setActive(0, true);
  }

  function setActive(index, scroll) {
    if (!items.length) {
      input.removeAttribute("aria-activedescendant");
      return;
    }
    active = (index + items.length) % items.length;
    list.querySelectorAll('[role="option"]').forEach((row) => {
      row.setAttribute("aria-selected", String(Number(row.dataset.index) === active));
    });
    const row = document.getElementById("palOpt" + active);
    input.setAttribute("aria-activedescendant", row.id);
    if (scroll) row.scrollIntoView({ block: "nearest" });
  }

  function runAt(index) {
    const item = items[index];
    if (!item) return;
    // A control leaves you where you were; a move or a command takes you on.
    close(item.kind === "control");
    item.run();
    if (item.kind === "say") document.getElementById("input").focus();
  }

  function open() {
    if (isOpen()) { input.select(); return; }
    if (L.router.modalOpen()) return;            // a confirmation is waiting
    returnTo = document.activeElement;
    input.value = "";
    render();
    veil.hidden = false;
    input.focus();
  }

  function close(restore) {
    if (!isOpen()) return;
    veil.hidden = true;
    input.removeAttribute("aria-activedescendant");
    const back = returnTo;
    returnTo = null;
    if (restore !== false && back && back !== document.body && document.contains(back)
        && typeof back.focus === "function") {
      back.focus();
    }
  }

  input.addEventListener("input", render);

  input.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1, true); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1, true); }
    else if (e.key === "Enter") { e.preventDefault(); runAt(active); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(true); }
    else if (e.key === "Tab") { e.preventDefault(); }     // focus stays in the palette
  });

  // A click on the dimmed page closes it.
  veil.addEventListener("mousedown", (e) => { if (e.target === veil) close(true); });

  document.addEventListener("keydown", (e) => {
    if (e.code !== "KeyK" || !(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) return;
    e.preventDefault();
    if (isOpen()) close(true);
    else open();
  });

  document.getElementById("paletteBtn").addEventListener("click", open);

  L.palette = { open, close, isOpen };
})();
