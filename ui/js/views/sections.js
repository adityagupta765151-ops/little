/* LITTLE — sections not built yet (none, since UI-10), and the palette's
   commands.

   Each one says, plainly, what the page will show and what already works
   today, with buttons that do the real thing: a button either sends Little
   a command it already understands, or goes to the section where the thing
   already is. Nothing here is a placeholder figure or a sample record.

   Every command below is checked by tests/test_shell.py to be one the fast
   lane answers on this computer, without a model call. As each section is
   built (UI-3 onward), its entry here is replaced by a real view —
   all of them since UI-10. */
(function () {
  const L = (window.Little = window.Little || {});
  const { h } = L;

  // Every section has its own view now (the last, Tools, in UI-10), so
  // nothing is left to hold a place for. The mechanism stays, empty, in case
  // a section is ever added before its view is ready.
  const SECTIONS = {};

  /* A command goes to Python exactly as a typed one would, then Home shows
     the reply as it arrives. */
  function run(action) {
    if (action.say) {
      L.bridge.send(action.say);
      L.router.go("home");
    } else if (action.go) {
      L.router.go(action.go);
    }
  }

  function render(id, section) {
    const view = document.querySelector(`#main > [data-view="${id}"]`);
    if (!view) return;
    const buttons = section.actions.map((action, i) =>
      h("button", {
        class: "btn" + (i === 0 && action.say ? " btn--primary" : ""),
        data: action.say ? { say: action.say } : { go: action.go },
        on: { click: () => run(action) },
      }, action.label));

    view.replaceChildren(h("div", "soon-body",
      h("p", "soon-lead", section.lead),
      h("section", "panel soon-card",
        h("h2", null, "Coming here"),
        h("p", null, section.soon)),
      h("section", "panel soon-card",
        h("h2", null, "Works now"),
        h("p", null, section.now),
        h("div", "soon-acts", buttons)),
    ));
  }

  Object.entries(SECTIONS).forEach(([id, section]) => render(id, section));

  /* Commands with no section of their own, offered in the palette only. */
  const PALETTE_ONLY = [
    { say: "list reminders", label: "List my reminders" },
    { say: "find jobs for me", label: "Find jobs for me" },
    { say: "show my top matches", label: "Show my top matches" },
    { say: "show new jobs", label: "Show new jobs" },
    { say: "show my application status", label: "Application status" },
    { say: "open my dashboard", label: "Open the job dashboard" },
    { say: "which skills am i missing", label: "Which skills am I missing?" },
    { say: "show my resume profile", label: "Show my resume profile" },
    { say: "check my resume", label: "Check my resume" },
    { say: "what do you remember", label: "What do you remember?" },
    { say: "run a system check", label: "Run a system check" },
    { say: "what voice are you using", label: "Voice report" },
    { say: "check the microphone", label: "Check the microphone" },
    { say: "list microphones", label: "List microphones" },
    { say: "check the tools", label: "Check that every tool loads" },
    { say: "start the demo", label: "Run the demo" },
  ];

  /* The commands, for the palette: each once, labelled as on its page. */
  function commands() {
    const seen = new Set();
    const out = [];
    [...Object.values(SECTIONS), { actions: PALETTE_ONLY }].forEach((section) => section.actions.forEach((action) => {
      if (action.say && !seen.has(action.say)) {
        seen.add(action.say);
        out.push({ say: action.say, label: action.label });
      }
    }));
    return out;
  }

  L.sections = { list: SECTIONS, commands };
})();
