/* LITTLE — the bridge.

   The one place the page talks to Python. pywebview puts the API on
   window.pywebview.api once the window is ready; the Python side is
   jarvis/app/bridge.py. Before that, and while the window closes, a call
   quietly does nothing and resolves to undefined, so no caller has to
   guard against a half-open window. */
(function () {
  const L = (window.Little = window.Little || {});

  function call(name, ...args) {
    const api = window.pywebview && window.pywebview.api;
    if (!api || typeof api[name] !== "function") return Promise.resolve(undefined);
    try {
      return Promise.resolve(api[name](...args)).catch(() => undefined);
    } catch (e) {
      return Promise.resolve(undefined);
    }
  }

  L.bridge = {
    /* since: the task version the page already has, so only changes come back */
    poll: (since) => call("poll", since),
    send: (text) => call("send", text),
    toggle: () => call("toggle"),
    control: (action) => call("control", action),
    /* Chat's actions name a task by id; Python looks up the words itself.
       Each resolves to "" when it went ahead, or a sentence saying why not. */
    speak: (taskId) => call("speak", taskId),
    save: (taskId) => call("save", taskId),
    regenerate: (taskId) => call("regenerate", taskId),
    /* Jobs: the snapshot (read only), a card's button by job id, and a
       posting opened in your browser. */
    jobs: () => call("jobs"),
    job: (jobId, action) => call("job", jobId, action),
    openPosting: (jobId) => call("open_posting", jobId),
    /* Resume: the snapshot (read only); the system's file dialog, which
       answers a number, not a path, and scanning by that number; the
       preferences form; and the six questions. Each task-starting call
       resolves to {task: id} or {error}. */
    resume: () => call("resume"),
    chooseResume: () => call("choose_resume"),
    scanPicked: (token) => call("scan_picked", token),
    savePreferences: (values) => call("save_preferences", values),
    resumeAction: (action, jobId) => call("resume_action", action, jobId || null),
    /* Projects: read only; a link in a project is opened by its position,
       and Python reads the address itself. */
    projects: () => call("projects"),
    openProjectLink: (project, link) => call("open_project_link", project, link),
    /* Memory: the snapshot (numbers masked), and Forget — by exact key or
       name. Each resolves to {message} or {error}. */
    memory: () => call("memory_view"),
    forgetFact: (key, scope, project) => call("forget_fact", key, scope || null, project || null),
    removeContact: (name) => call("remove_contact", name),
    clearLog: () => call("clear_log"),
    /* System: the settings (keys only ever "set" or "missing"), the health
       check — `live` also asks the model, one request — and a test of the
       voice as set. */
    system: () => call("system"),
    health: (live) => call("health", live === true),
    testVoice: () => call("test_voice"),
    /* Tools: every tool, grouped, and whether it asks first. Read only. */
    tools: () => call("tools"),
    /* The Task Center's "Stop this": the task stops at its next step. */
    cancel: (taskId) => call("cancel", taskId),
    /* Python accepts only a real true as a yes; anything else is a no. */
    confirmReply: (id, ok) => call("confirm_reply", id, ok === true),
  };
})();
