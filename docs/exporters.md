# Writing a new exporter

An exporter takes a Markdown summary that's already cached in the store and pushes it somewhere. It is *strictly* a sink: it never re-runs the LLM and never re-reads events.

## The shape

There is no formal `Exporter` ABC because exporters differ too much (file path vs HTTP API vs vault layout). The convention instead:

```python
def write_<name>(<sink_target>, day_or_label, content: str, **opts) -> Path | str:
    ...
```

It returns whatever identifier the user can use to find the result (a filesystem path, a URL).

## Walkthrough: an Anki exporter

Suppose you want each daily digest as an Anki note in a deck:

```python
# hindsight/exporters/anki.py
import httpx

ANKI_CONNECT = "http://127.0.0.1:8765"

def push_to_anki(deck: str, day, content: str) -> str:
    payload = {
        "action": "addNote",
        "version": 6,
        "params": {"note": {
            "deckName": deck,
            "modelName": "Basic",
            "fields": {"Front": f"Hindsight {day}", "Back": content},
            "tags": ["hindsight"],
        }},
    }
    r = httpx.post(ANKI_CONNECT, json=payload, timeout=10.0)
    r.raise_for_status()
    return f"anki:{r.json().get('result')}"
```

## Registering

1. Add the function to `hindsight/exporters/__init__.py`'s `__all__` and import it.
2. Add a branch to `cli.py::export()`'s `target == "anki"` case. Validate any required config (deck name, host) up front, fail clearly if missing.
3. If the new exporter is range-aware (rollup-friendly), branch on `is_rollup` and pick a different label/title prefix, like `notion`/`obsidian` already do.
4. Document the env var in `.env.example`.

## Markdown conversion gotchas

- **Notion** has a 100-blocks-per-page limit on the create call; `notion.py` already chunks the body via a follow-up `PATCH`. If you add new block types, keep the per-block 1900-char rich-text cap (`MAX_BLOCK_CHARS`).
- **Obsidian** is just file IO, but Daily Notes plugin expects `YYYY-MM-DD.md` exactly — don't prefix the filename, use a subfolder.
- **Anything that re-renders Markdown** (Discord, Slack) — strip `## 概览 / Overview` style headings, those don't look right in a chat message. Keep the digest as-is for archive sinks (Notion/Obsidian/Markdown), summarize harder for chat sinks.

## What an exporter must NOT do

- **Re-run the LLM.** If the user wants a different framing, they re-run `summarize`. Exporters are deterministic.
- **Mutate the store.** Read-only.
- **Block on optional external services at import time.** Lazy-import (`import httpx` inside the function) if your dependency isn't already a hard requirement of the package.
