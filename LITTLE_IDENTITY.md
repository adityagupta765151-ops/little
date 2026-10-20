# LITTLE — identity, voice and wake word

The assistant is called **LITTLE**: a small, intelligent AI companion rather
than an Iron Man computer. This page is the one place that says who it is,
how it sounds, what wakes it, and how to change any of that later.

## Name

| | |
| --- | --- |
| Official name | `LITTLE` — the wordmark, window titles, the activity log |
| In speech and prose | `Little` |
| Former name | JARVIS — it still answers to it |
| Set in | `JARVIS_ASSISTANT_NAME` in `.env` (default `LITTLE`) |

Changing `JARVIS_ASSISTANT_NAME` renames it everywhere at once: the panel,
the job dashboard, the window title, the persona the model is given, the
greeting, and the wake word — its own name always wakes it.

### What was deliberately not renamed

| Kept | Why |
| --- | --- |
| The Python package `jarvis` | Every import, test and launcher uses it |
| The `JARVIS_*` settings | Your existing `.env` keeps working untouched |
| `jarvis.log`, `memory/`, `jobs.db` and its tables | Stored history stays where it is |
| The `Jarvis` class in `app/assistant.py` | An internal name; both launchers build it |
| The job boards' User-Agent | An identifier sent to other services, not something you see |

Only what you see and hear changed.

## Persona

Little is **friendly, calm, smart and quick, a little playful now and then**
— warm without gushing. It sounds like a helpful friend who is good with
computers, not a movie AI and not a butler.

- Simple commands get under ten words: *"Opening Chrome."* *"Done. I'll
  remind you at 8."*
- Everything else, one or two short sentences.
- No "Sir", no "As an AI", no drama, no sci-fi flourishes.
- It doesn't claim feelings it doesn't have.
- When something fails it says so plainly, and what to try next.

The persona lives in one paragraph, `PERSONA` in `jarvis/ai/prompts.py`.
Edit it there and the assistant changes; the working rules below it (draft a
WhatsApp message before sending, read a file before editing it) are
separate and weren't touched.

## Voice

| | |
| --- | --- |
| TTS provider | Microsoft neural voices through `edge-tts` |
| Voice | `en-IN-NeerjaNeural` — Indian English, female |
| Character | pitch `+10Hz`, speed `+5%`, volume `+0%` |
| Fallback engine | `pyttsx3` with the local Windows voices, lighter ones preferred |

Why Neerja: it is natural and warm, and an Indian English voice says Indian
names — your contacts, your city — the way they're actually said. Lifting
the pitch a little and the pace a touch makes it read young and light
without tipping into a child's voice. (`en-US-AnaNeural` *is* a child's
voice, and sounded too young for Little; it's listed if you want it.)

### Speech is short, the screen is complete

Replies are cut for the voice, never for the screen. The activity log shows
the whole reply; the voice says one or two sentences and, when there is
more, *"The rest is on screen."* Long reports are summed up the way a person
would sum them up:

| On screen | Out loud |
| --- | --- |
| Ten job listings | "Here are your top 10 matches. They're on screen." |
| A health report | "System check done. 1 broken, 2 degraded but working." |
| A match analysis | "It scores 84 out of 100. The breakdown is on screen." |

That's `jarvis/voice/brief.py`.

## Voice settings

All in `.env`, all optional:

| Setting | Default | Meaning |
| --- | --- | --- |
| `JARVIS_ASSISTANT_NAME` | `LITTLE` | What it's called |
| `JARVIS_VOICE` | `en-IN-NeerjaNeural` | Which neural voice |
| `JARVIS_VOICE_SPEED` | `+5%` | Speaking rate, as a percentage |
| `JARVIS_VOICE_PITCH` | `+10Hz` | Pitch, in hertz |
| `JARVIS_VOICE_VOLUME` | `+0%` | Volume, as a percentage |
| `JARVIS_VOICE_ENABLED` | `true` | `false` starts it muted; the Mute button still toggles it |
| `JARVIS_NEURAL_VOICE` | `true` | `false` forces the offline local voice |
| `JARVIS_VOICE_RATE` | `180` | Speed of the local fallback voice, words a minute |

A value in the wrong form — `JARVIS_VOICE_SPEED=fast` — is ignored and the
default used, with a line in `jarvis.log` saying why. A malformed value would
otherwise make every sentence fail, which sounds exactly like a broken voice.

The panel's Voice section shows the voice actually speaking, and whether
speech is on.

## Wake word

| Says | Wakes it |
| --- | --- |
| "Little, open Chrome" | yes |
| "Hey Little" / "Ok Little" / "Okay Little" | yes |
| "Um, Little, find jobs for me" | yes |
| "Jarvis, open Chrome" | yes — the old name still works |
| "I need a little help" | no |
| "Wait a little" | no |
| "The title of the song" | no |

"Little" is an everyday word, unlike "Jarvis". An assistant that woke on
every sentence containing it would answer the room all day, so the name only
counts **at the start** of what you say — alone, or after a "hey", "ok",
"um" or "so". Someone talking *to* it says its name first.

Its own name also needs a close match. Speech recognition spells "little"
correctly every time, so a loose match would only add false wakes ("title"
is 73% similar). The old name keeps the forgiving match it always had,
because recognition mangles "Jarvis" into "javis".

Nothing changed about *when* it listens: it starts listening for its name
only after you click the core or press Ctrl+Space, exactly as before.

| Setting | Meaning |
| --- | --- |
| `JARVIS_WAKE` | Extra wake words, comma separated. Blank keeps "Jarvis" working |
| `JARVIS_WAKE_FUZZY` | Tolerance for the other wake words (default `0.72`); its own name is always at least `0.85` |

## The panel

Little is an orb with a small face, and its state shows without a word:

| State | Orb |
| --- | --- |
| Idle | asleep, eyes closed, still |
| Listening | awake and smiling, a slow breath of light, an unhurried blink |
| Thinking | an arc circles the ring; the eyes glance around |
| Working | a steady ring of activity; eyes down on the work |
| Speaking | the smile becomes a small moving waveform |
| Success | happy eyes, and the ring draws itself closed — about a second |
| Error | a squint and a wobbly "hmm" in soft coral — clear, never alarming |

The speaking waveform is state, not a level meter: the audio level isn't
measured, so nothing pretends it is. Success and error show when a command
ends done or failed in the task record (`jarvis/app/tasks.py`) — an outcome
the code decided, never guessed from a reply's wording. A command you stop
shows neither.

The orb is the only thing that glows. With "reduce motion" set in Windows,
nothing moves; the colours still change. The look is defined once, in
[DESIGN_SYSTEM.md](DESIGN_SYSTEM.md).

## Changing things later

**Another voice.** Say *"what voice are you using"* — it lists the voices
Microsoft offers right now, with their personalities. Put one in `.env` as
`JARVIS_VOICE` and restart. If it doesn't exist, Little falls back to the
next voice that works and logs which.

**Another TTS provider.** Everything provider-specific is in
`jarvis/voice/speaking.py`: `_synthesise()` turns text into an audio file
and `_play()` plays it. A new provider replaces `_synthesise()` and reads
the same settings from `config.py`; the fallback chain, the local voice,
brevity and interruption (Esc) keep working around it.

**Another name.** `JARVIS_ASSISTANT_NAME=NOVA` renames the panel, the
dashboard, the greeting and the persona, and makes "Nova" a wake word. The
rules above still apply: if the new name is an everyday word, it's only
listened for at the start of a phrase.

## Upgrading an existing install

An `.env` made from the old template still says:

    JARVIS_VOICE=en-IN-PrabhatNeural
    JARVIS_VOICE_SPEED=+8%
    JARVIS_VOICE_PITCH=+0Hz

Your settings win over the defaults, so this keeps the old JARVIS voice. For
Little's voice, change those three lines to:

    JARVIS_VOICE=en-IN-NeerjaNeural
    JARVIS_VOICE_SPEED=+5%
    JARVIS_VOICE_PITCH=+10Hz

The system check warns about this if you forget. The wake word needs no
change — "Little" works whatever `JARVIS_WAKE` says.

## Known limitations

- A phrase that happens to *begin* with the word — "so little time" — can
  still wake it. Saying "hey Little" is the unambiguous form.
- A typed command that starts with the word as an adjective — "little
  reminder: call mom" — has "little" taken as the address.
- The voice list can only be checked live on a machine that can reach
  Microsoft's service; offline, the report shows a fixed list and says so.
- The `+10Hz` lift was tuned for Neerja. A different voice may want a
  different `JARVIS_VOICE_PITCH` to sound right.
