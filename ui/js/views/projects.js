/* LITTLE — Projects.

   Each project your resume lists, as a card, with only what the resume says:
   the name, the line describing it, the skills from your own resume that the
   line names, and any web address written in it. A resume keeps a project as
   one line, so status, the backend / frontend / database split and AI parts
   aren't there — each card says so, rather than guessing them.

   A link opens in your normal browser through Python, named by its place in
   the list; the window itself never navigates. Loads when you open the
   section and after a task ends (a new scan may have changed the list). */
(function () {
  const L = (window.Little = window.Little || {});
  const { h, bridge } = L;
  const $ = (id) => document.getElementById(id);

  let data = null;
  let loading = false;
  let reloadTimer = null;

  function say(message) { $("projStatus").textContent = message || ""; }

  function card(project, n) {
    const missing = [...data.not_in_a_line];
    if (!project.links.length) missing.push("links");
    return h("li", { class: "proj-card", data: { project: n } },
      h("h3", null, project.name),
      project.description ? h("p", "proj-desc", project.description)
        : h("p", "proj-desc cv-missing", "No description on your resume"),
      project.named.length ? h("div", "proj-named",
        h("span", "proj-label", "Named in this line"),
        h("ul", { class: "skills", aria: { label: "Skills named" } },
          project.named.map((s) => h("li", "skill", s)))) : null,
      project.links.length ? h("div", "proj-links",
        project.links.map((url, m) => h("button", {
          class: "btn btn--sm btn--ghost", type: "button", data: { link: m },
          aria: { label: `Open ${url} in your browser` },
          on: { click: () => bridge.openProjectLink(n, m).then((why) => say(why || "Opened in your browser.")) },
        }, url.replace(/^https?:\/\//, "")))) : null,
      h("p", "proj-missing", `Not in your resume yet: ${missing.join(", ")}.`));
  }

  function render() {
    const list = $("projList");
    const empty = $("projEmpty");
    if (!data) {
      list.replaceChildren();
      empty.hidden = false;
      empty.replaceChildren(loading ? "Loading your projects…" : "");
      $("projSource").textContent = "";
      return;
    }
    if (data.error) {
      list.replaceChildren();
      empty.hidden = false;
      empty.replaceChildren(h("p", null, data.error),
        h("button", { class: "btn btn--sm", type: "button", on: { click: load } }, "Try again"));
      return;
    }
    const n = data.projects.length;
    $("projSource").textContent = data.ready
      ? `${n} project${n === 1 ? "" : "s"}, from ${data.file || "your resume"}`
      : "No resume read yet.";
    list.replaceChildren(...data.projects.map(card));
    empty.hidden = n > 0;
    if (!data.ready) {
      empty.replaceChildren(
        h("p", null, "Your projects come from your resume, and none has been read yet."),
        h("button", { class: "btn btn--primary btn--sm", type: "button", on: { click: () => L.router.go("resume") } },
          "Scan it in Resume"));
    } else if (!n) {
      empty.replaceChildren(
        h("p", null, "Your resume doesn't list any projects. Add them to it, then scan it again in Resume."));
    }
  }

  function load() {
    loading = true;
    if (!data) render();
    return bridge.projects().then((snapshot) => {
      loading = false;
      data = snapshot && (Array.isArray(snapshot.projects) || snapshot.error) ? snapshot
        : { error: "I couldn't read your resume profile." };
      render();
    });
  }

  $("projRefresh").addEventListener("click", load);
  $("projEdit").addEventListener("click", () => L.router.go("resume"));

  L.tasks.onChange(({ ended }) => {
    if (!ended.length) return;
    clearTimeout(reloadTimer);
    reloadTimer = setTimeout(() => { if (L.router.current() === "projects") load(); }, 150);
  });
  L.router.onChange((id) => { if (id === "projects") load(); });
  window.addEventListener("pywebviewready", () => { if (L.router.current() === "projects") load(); });

  L.projects = { load };
})();
