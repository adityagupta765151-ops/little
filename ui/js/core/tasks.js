/* LITTLE — the tasks, as the page knows them.

   Python keeps the record (jarvis/app/tasks.py). Each poll tells it which
   version the page already has, and gets back only the tasks that changed
   since; they're merged here by id. A reload starts from 0 and catches up.

   Listeners hear about every change, and about tasks that have just ended —
   ended while the page watched, not ones that were already over when it
   loaded — which is what the orb's success and error signs follow. */
(function () {
  const L = (window.Little = window.Little || {});

  const KEEP = 50;
  const OPEN = ["active", "waiting"];
  const ENDED = ["done", "failed", "stopped"];

  let version = 0;
  let loaded = false;
  const byId = new Map();
  const listeners = [];

  function valid(task) {
    return task && typeof task === "object" && Number.isInteger(task.id)
      && typeof task.status === "string" && typeof task.text === "string"
      && Array.isArray(task.steps);
  }

  function apply(delta) {
    if (!delta || !Number.isInteger(delta.v)) return;
    const first = !loaded;
    loaded = true;
    const ended = [];
    const changed = Array.isArray(delta.changed) ? delta.changed.filter(valid) : [];

    changed.forEach((task) => {
      const before = byId.get(task.id);
      byId.set(task.id, task);
      // Seen open and now over — or first seen already over, but only if it
      // started after the page did.
      const wasOpen = before ? OPEN.includes(before.status) : !first;
      if (wasOpen && ENDED.includes(task.status)) ended.push(task);
    });

    while (byId.size > KEEP) byId.delete(Math.min(...byId.keys()));
    version = Math.max(version, delta.v);

    if (first || changed.length) {
      // One listener failing mustn't stop the others — but it mustn't go
      // unnoticed either: a swallowed error here once hid a Chat bug.
      listeners.forEach((fn) => { try { fn({ ended, first }); } catch (e) { console.error(e); } });
    }
  }

  const sorted = () => [...byId.values()].sort((a, b) => a.id - b.id);

  L.tasks = {
    version: () => version,
    apply,
    /* The one being worked on: the oldest still open. */
    current: () => sorted().find((t) => OPEN.includes(t.status)) || null,
    recent: (n) => sorted().reverse().slice(0, n),
    get: (id) => byId.get(id) || null,
    failed: () => sorted().reverse().filter((t) => t.status === "failed"),
    onChange: (fn) => listeners.push(fn),
  };
})();
