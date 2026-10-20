/* LITTLE — the router.

   One section on screen at a time, named in the address: #/jobs. Hash
   routes work from file://, where the panel loads, and back and forward
   work with no setup. Every section already exists in index.html as
   <section data-view="…">; the router only decides which one shows.

   On a move it marks the link as current, retitles the window, and puts
   keyboard focus on the section's heading, so a screen reader says where
   you landed and Tab carries on from there. */
(function () {
  const L = (window.Little = window.Little || {});

  const ROUTES = [
    { id: "home",     title: "Home",     keywords: "orb status activity start" },
    { id: "chat",     title: "Chat",     keywords: "conversation messages talk replies" },
    { id: "tasks",    title: "Tasks",    keywords: "plan steps running reminders todo" },
    { id: "jobs",     title: "Jobs",     keywords: "work openings matches applications" },
    { id: "resume",   title: "Resume",   keywords: "cv profile skills education" },
    { id: "projects", title: "Projects", keywords: "portfolio work" },
    { id: "memory",   title: "Memory",   keywords: "remember facts contacts forget" },
    { id: "tools",    title: "Tools",    keywords: "abilities actions runs" },
    { id: "system",   title: "System",   keywords: "settings health voice microphone diagnostics" },
  ];
  const DEFAULT = "home";
  const byId = Object.fromEntries(ROUTES.map((r) => [r.id, r]));

  let current = null;
  let focusNext = true;
  const listeners = [];

  function parse(hash) {
    const match = /^#\/([a-z]+)\/?$/.exec(hash || "");
    return match && byId[match[1]] ? match[1] : null;
  }

  function name() {
    return (L.identity && L.identity.name()) || "LITTLE";
  }

  function retitle() {
    const route = byId[current];
    document.title = !route || route.id === DEFAULT ? name() : `${route.title} · ${name()}`;
  }

  function show(id, focus) {
    current = id;
    document.querySelectorAll("#main > [data-view]").forEach((view) => {
      view.hidden = view.dataset.view !== id;
    });
    document.querySelectorAll("[data-route]").forEach((link) => {
      if (link.dataset.route === id) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    const heading = document.getElementById("viewTitle");
    heading.textContent = byId[id].title;
    document.body.dataset.section = id;
    retitle();
    if (focus) heading.focus();
    listeners.forEach((fn) => { try { fn(id); } catch (e) { console.error(e); } });   // reported, not fatal
  }

  /* go("jobs") — focus moves to the heading unless { focus: false }, used
     when the move follows typing, so the cursor stays in the command box. */
  function go(id, opts) {
    if (!byId[id]) return;
    const focus = !opts || opts.focus !== false;
    if (location.hash === "#/" + id) { show(id, focus); return; }
    focusNext = focus;
    location.hash = "#/" + id;
  }

  window.addEventListener("hashchange", () => {
    const id = parse(location.hash);
    if (!id) {
      try { history.replaceState(null, "", "#/" + DEFAULT); } catch (e) { /* stays unnamed; still home */ }
    }
    show(id || DEFAULT, focusNext);
    focusNext = true;
  });

  /* Alt+1 … Alt+9 jump straight to a section, in sidebar order. Not while a
     dialog is open: a confirmation must be answered where it is. */
  function modalOpen() {
    return !!document.querySelector(".veil:not([hidden])");
  }

  document.addEventListener("keydown", (e) => {
    if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    const match = /^Digit([1-9])$/.exec(e.code);
    if (!match || modalOpen()) return;
    const route = ROUTES[Number(match[1]) - 1];
    if (!route) return;
    e.preventDefault();
    go(route.id);
  });

  const first = parse(location.hash);
  if (!first) {
    try { history.replaceState(null, "", "#/" + DEFAULT); } catch (e) { /* see above */ }
  }
  show(first || DEFAULT, false);

  L.router = {
    routes: ROUTES,
    go,
    current: () => current,
    retitle,
    modalOpen,
    onChange: (fn) => listeners.push(fn),
  };
})();
