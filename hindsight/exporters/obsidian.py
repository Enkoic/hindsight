from __future__ import annotations

from datetime import date
from pathlib import Path


def write_obsidian(
    vault_dir: Path,
    day: date,
    summary: str,
    subfolder: str = "Hindsight",
    tag: str = "hindsight",
) -> Path:
    """Write a daily digest into an Obsidian vault.

    The note path is `<vault>/<subfolder>/YYYY-MM-DD.md` with frontmatter that
    works with Obsidian's Daily Notes plugin and inline tagging.
    """
    target_dir = vault_dir / subfolder
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{day.isoformat()}.md"
    frontmatter = (
        "---\n"
        f"date: {day.isoformat()}\n"
        f"tags: [{tag}]\n"
        f"source: hindsight\n"
        "---\n\n"
    )
    body = f"# Daily Digest — {day.isoformat()}\n\n{summary}\n"
    path.write_text(frontmatter + body, encoding="utf-8")
    return path
