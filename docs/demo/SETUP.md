# Before the demo — 15 minutes, once

**Owner:** Ryan Gant (Interface Designer)

Both scripts assume this is done. Do it the day before, not in the room.

## 1. Start the platform on the demo machine

```
python run.py
```

First run on a clean machine: it builds the virtual environment, picks a
database, offers to install Ollama (press Return — the default is yes),
downloads `llama3.2` once at roughly 2 GB, then loads the model in the
background so the first question in the room is fast.

Wait for this line, and read it:

```
Assistant: Local model through Ollama (120s budget per question)
```

If it says anything else, stop and fix it now. `8s` means you are running an
old checkout. "not ready" means the daemon is down.

## 2. Confirm the model actually answers

```
python scripts/check_local_model.py
```

Four checks in order — daemon, model pulled, live answer, non-empty content.
If all four pass, the assistant will work in the room.

## 3. Start from a clean database

```
python run.py --reset-db
```

Profiles start empty by design (ADR 0012), and both scripts build one up
live. A leftover profile from rehearsal breaks the story.

## 4. Have these open and ready

- `http://localhost:5173` — signed out
- `http://localhost:8000/docs` — a second tab
- The terminal running `run.py`, visible if you can arrange it. The turn log
  is good evidence.

## If something breaks mid-demo

| Symptom | Say this | Do this |
| --- | --- | --- |
| Answer takes >15 s | "It's generating locally on this laptop — no cloud, no API key." | Wait. It will land. |
| "The local language model is not running" | "That's the honest-failure path we built — it tells you what to start." | Move to the counsellor queue; the escalation is real and the demo continues. |
| Page is blank | — | Reload. The API keeps running. |
| Everything is wrong | "Let me show you the test suite instead." | `python run.py --check` — 284 tests, and it is genuinely impressive. |

Nothing in either script requires the internet.
