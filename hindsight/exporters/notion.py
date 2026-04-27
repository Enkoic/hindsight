from __future__ import annotations

from datetime import date
from typing import Any

import httpx

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
MAX_BLOCK_CHARS = 1900  # Notion hard-limits rich_text per block around 2000 chars


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _chunk(text: str, size: int = MAX_BLOCK_CHARS) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def _paragraph_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": chunk}} for chunk in _chunk(text)]
        },
    }


def _heading_block(text: str, level: int) -> dict[str, Any]:
    level = max(1, min(3, level))
    key = f"heading_{level}"
    return {
        "object": "block",
        "type": key,
        key: {"rich_text": [{"type": "text", "text": {"content": text[:MAX_BLOCK_CHARS]}}]},
    }


def _bulleted_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{"type": "text", "text": {"content": chunk}} for chunk in _chunk(text)]
        },
    }


def _markdown_to_blocks(md: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("### "):
            blocks.append(_heading_block(line[4:].strip(), 3))
        elif line.startswith("## "):
            blocks.append(_heading_block(line[3:].strip(), 2))
        elif line.startswith("# "):
            blocks.append(_heading_block(line[2:].strip(), 1))
        elif line.lstrip().startswith(("- ", "* ")):
            content = line.lstrip()[2:].strip()
            blocks.append(_bulleted_block(content))
        else:
            blocks.append(_paragraph_block(line.strip()))
    return blocks


def push_to_notion(
    token: str,
    database_id: str,
    day: date,
    summary: str,
    title_prefix: str = "Daily Digest",
) -> str:
    """Create a page in the given Notion database. Returns the new page URL.

    The database is expected to have a title property (default name 'Name' or 'Title')
    and optionally a 'Date' date property.
    """
    with httpx.Client(headers=_headers(token), timeout=30.0) as client:
        db = client.get(f"{NOTION_API}/databases/{database_id}")
        db.raise_for_status()
        schema = db.json().get("properties", {})

        title_prop = next((k for k, v in schema.items() if v.get("type") == "title"), "Name")
        date_prop = next((k for k, v in schema.items() if v.get("type") == "date"), None)

        properties: dict[str, Any] = {
            title_prop: {
                "title": [{"text": {"content": f"{title_prefix} — {day.isoformat()}"}}]
            }
        }
        if date_prop:
            properties[date_prop] = {"date": {"start": day.isoformat()}}

        blocks = _markdown_to_blocks(summary)
        first, rest = blocks[:100], blocks[100:]

        payload = {
            "parent": {"database_id": database_id},
            "properties": properties,
            "children": first,
        }
        r = client.post(f"{NOTION_API}/pages", json=payload)
        r.raise_for_status()
        page = r.json()
        page_id = page["id"]

        for i in range(0, len(rest), 100):
            chunk = rest[i : i + 100]
            client.patch(
                f"{NOTION_API}/blocks/{page_id}/children",
                json={"children": chunk},
            ).raise_for_status()

        return page.get("url", page_id)
