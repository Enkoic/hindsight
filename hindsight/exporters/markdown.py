from __future__ import annotations

from datetime import date
from pathlib import Path


def write_markdown(out_dir: Path, day: date, summary: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day.isoformat()}.md"
    header = f"---\ndate: {day.isoformat()}\n---\n\n# Daily Digest — {day.isoformat()}\n\n"
    path.write_text(header + summary + "\n", encoding="utf-8")
    return path
