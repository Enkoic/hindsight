from __future__ import annotations

import json
from datetime import date
from pathlib import Path


def write_json(out_dir: Path, day: date, summary: str, raw_digest: str | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day.isoformat()}.json"
    payload = {"date": day.isoformat(), "summary": summary, "raw_digest": raw_digest}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
