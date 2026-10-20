/* LITTLE — the navigation's three shapes.

     full    icons and labels, on wide windows (1440px and up by default)
     rail    icons only, labels as tooltips; below 1200px there isn't room
             for more, so it stays a rail and the toggle hides
     bottom  a bar along the bottom on narrow windows (under 720px): four
             sections and More, which opens the command palette

   The shape is written to <body data-nav>, and the stylesheet does the
   rest. Collapsing or expanding by hand is remembered for next time, where
   the window allows storage at all. */
(function () {
  const L = (window.Little = window.Little || {});

  const NARROW = 720;       // below this, a bottom bar
  const ROOM = 1200;        // below this, no room for labels beside the page
  const WIDE = 1440;        // from here, labels show unless you hid them
  const KEY = "little.nav";

  const toggleBtn = document.getElementById("navToggle");
  const toggleLabel = document.getElementById("navToggleLabel");
  const moreBtn = document.getElementById("navMore");

  function readPref() {
    try {
      const value = window.localStorage.getItem(KEY);
      return value === "rail" || value === "full" ? value : null;
    } catch (e) {
      return null;
    }
  }

  function writePref(value) {
    try { window.localStorage.setItem(KEY, value); } catch (e) { /* not kept; still works */ }
  }

  let pref = readPref();

  function shape() {
    const width = window.innerWidth;
    if (width < NARROW) return "bottom";
    if (width < ROOM) return "rail";
    if (pref) return pref;
    return width >= WIDE ? "full" : "rail";
  }

  function canToggle() {
    const width = window.innerWidth;
    return width >= ROOM;
  }

  function apply() {
    const now = shape();
    document.body.dataset.nav = now;
    toggleBtn.hidden = !canToggle();
    const label = now === "full" ? "Collapse" : "Expand";
    toggleLabel.textContent = label;
    toggleBtn.setAttribute("aria-label", label + " the sidebar");
  }

  function toggle() {
    if (!canToggle()) return;
    pref = document.body.dataset.nav === "full" ? "rail" : "full";
    writePref(pref);
    apply();
  }

  /* On the bottom bar, More stands in for the five sections that don't fit,
     so it reads as current when one of them is. */
  function markMore(id) {
    const primary = ["home", "chat", "tasks", "jobs"];
    moreBtn.classList.toggle("is-current", !primary.includes(id));
  }

  let queued = false;
  window.addEventListener("resize", () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; apply(); });
  });

  toggleBtn.addEventListener("click", toggle);
  moreBtn.addEventListener("click", () => { if (L.palette) L.palette.open(); });
  if (L.router) {
    L.router.onChange(markMore);
    markMore(L.router.current());
  }

  document.getElementById("skipLink").addEventListener("click", () => {
    document.getElementById("main").focus();
  });

  apply();

  L.sidenav = {
    toggle,
    canToggle,
    shape: () => document.body.dataset.nav,
  };
})();
