/* LITTLE — the one way the interface builds anything.

   h(tag, props, ...children) makes an element. Everything that isn't an
   element becomes text. There is deliberately no way to pass HTML: values
   on screen come from the model, job boards, web pages and chats, and in
   this window a value that runs as code can answer a confirmation by itself.
   That happened once; this file is why it can't again.

     h("li", { class: "row" }, "call mom", h("span", null, "20:00"))
     h("a", { href: job.url }, "Open posting")   // dropped unless http(s)
     h("div", { style: { width: "40%" } })       // styles as properties only

   Classic script, not an ES module: the panel loads from file://, where
   Chromium won't import modules. It attaches to window.Little. */
(function () {
  "use strict";

  const Little = (window.Little = window.Little || {});

  /* Only a real web address may become a link or a source. */
  function safeUrl(url) {
    try {
      const parsed = new URL(String(url == null ? "" : url));
      return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
    } catch (e) {
      return null;
    }
  }

  // Attributes that can carry a URL, and so go through safeUrl.
  const URL_ATTRS = new Set(["href", "src", "action", "formaction", "xlink:href"]);

  function setAttr(el, name, value) {
    const key = String(name).toLowerCase();
    if (value === null || value === undefined || value === false) return;
    // Event handlers as attributes are how injected markup runs code.
    if (key.startsWith("on") || key === "style" || key === "srcdoc") return;
    if (URL_ATTRS.has(key)) {
      const safe = safeUrl(value);
      if (safe) el.setAttribute(name, safe);
      return;
    }
    el.setAttribute(name, value === true ? "" : String(value));
  }

  function append(el, child) {
    if (child === null || child === undefined || child === false || child === true) return;
    if (Array.isArray(child)) { child.forEach((c) => append(el, c)); return; }
    if (child instanceof Node) { el.appendChild(child); return; }
    el.appendChild(document.createTextNode(String(child)));
  }

  /* props: null, a class-name string, or an object —
       class, id, text, title, role, hidden, disabled, type, href, …
       aria: { label: "…" }   → aria-label
       data: { view: "jobs" } → data-view
       style: { width: "40%" } (properties, never a style string)
       on: { click: fn }      (listeners, never attribute strings) */
  function h(tag, props, ...children) {
    const el = document.createElement(tag);
    if (typeof props === "string") {
      el.className = props;
    } else if (props) {
      for (const [key, value] of Object.entries(props)) {
        if (value === null || value === undefined) continue;
        if (key === "class") el.className = String(value);
        else if (key === "text") el.textContent = String(value);
        else if (key === "aria") Object.entries(value).forEach(([k, v]) => setAttr(el, "aria-" + k, v));
        else if (key === "data") Object.entries(value).forEach(([k, v]) => { el.dataset[k] = String(v); });
        else if (key === "style") Object.entries(value).forEach(([k, v]) => { el.style[k] = String(v); });
        else if (key === "on") Object.entries(value).forEach(([k, fn]) => el.addEventListener(k, fn));
        else if (key === "hidden" || key === "disabled") el[key] = Boolean(value);
        else setAttr(el, key, value);
      }
    }
    append(el, children);
    return el;
  }

  /* Swap an element's contents for new ones, the safe way. */
  function mount(el, ...children) {
    el.replaceChildren();
    append(el, children);
    return el;
  }

  Little.h = h;
  Little.mount = mount;
  Little.safeUrl = safeUrl;
})();
