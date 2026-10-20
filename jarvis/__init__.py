"""LITTLE — a small, voice-controlled AI companion for the desktop.

The package is still called `jarvis`, the assistant's original name. Only
what the user sees and hears was renamed; the package, the JARVIS_*
settings, the database and jarvis.log kept their names so existing
installs, imports and .env files carry on working. LITTLE_IDENTITY.md has
the details.

    app/      settings, identity, the assistant loop, live readings
    voice/    speech in, speech out, the wake word, what gets said aloud
    routing/  the fast lane that answers without the model
    ai/       the model provider, the tool-calling brain, the planner, the prompts
    tools/    what it can actually do, one module per domain
    store/    what it remembers between sessions
    jobs/     resume, job search, matching, applications, dashboard

A command travels: voice -> wake word -> routing -> ai -> tools -> voice.
"""
