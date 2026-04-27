from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import config as config_mod
from .collectors import (
    ActivityWatchCollector,
    ClaudeCodeCollector,
    ClaudeHistoryCollector,
    CodexCollector,
    CodexHistoryCollector,
)
from .exporters import push_to_notion, write_json, write_markdown
from .store import Store
from .summarizer import build_summarizer, render_digest

app = typer.Typer(add_completion=False, help="Aggregate and summarize your daily activity.")
console = Console()


def _parse_day(s: str | None) -> date:
    if not s or s == "today":
        return datetime.now(timezone.utc).date()
    if s == "yesterday":
        return (datetime.now(timezone.utc) - timedelta(days=1)).date()
    return date.fromisoformat(s)


def _day_bounds(d: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(d, time.min, tzinfo=timezone.utc),
        datetime.combine(d, time.max, tzinfo=timezone.utc),
    )


def _collectors(cfg) -> list:
    claude_home = cfg.claude_projects_dir.parent
    codex_home = cfg.codex_sessions_dir.parent
    return [
        ActivityWatchCollector(cfg.aw_server_url),
        ClaudeCodeCollector(cfg.claude_projects_dir),
        ClaudeHistoryCollector(claude_home),
        CodexCollector(cfg.codex_sessions_dir),
        CodexHistoryCollector(codex_home),
    ]


@app.command()
def collect(
    since: Optional[str] = typer.Option(None, help="ISO date or 'yesterday'. Default: last 2 days."),
    until: Optional[str] = typer.Option(None, help="ISO date. Default: now."),
    sources: Optional[str] = typer.Option(None, help="Comma-separated subset: activitywatch,claude_code,codex"),
):
    """Pull events from all sources into the local store."""
    cfg = config_mod.load()
    store = Store(cfg.db_path)
    try:
        if since:
            since_dt, _ = _day_bounds(_parse_day(since))
        else:
            since_dt = datetime.now(timezone.utc) - timedelta(days=2)
        until_dt = _day_bounds(_parse_day(until))[1] if until else datetime.now(timezone.utc)

        want = set(s.strip() for s in sources.split(",")) if sources else None
        totals: dict[str, int] = {}
        for c in _collectors(cfg):
            if want and c.name not in want:
                continue
            console.print(f"[cyan]→ {c.name}[/cyan] {since_dt.date()} .. {until_dt.date()}")
            events = list(c.collect(since_dt, until_dt))
            n = store.upsert_events(events)
            totals[c.name] = n
            console.print(f"  stored {n} new events (saw {len(events)})")

        table = Table(title="collect summary")
        table.add_column("source")
        table.add_column("new events", justify="right")
        for k, v in totals.items():
            table.add_row(k, str(v))
        console.print(table)
    finally:
        store.close()


@app.command()
def report(
    day: Optional[str] = typer.Option(None, help="ISO date. Default: today."),
):
    """Terminal report of raw events for the day (no LLM)."""
    cfg = config_mod.load()
    d = _parse_day(day)
    store = Store(cfg.db_path)
    try:
        rows = store.events_for_day(d)
        console.print(f"[bold]{d.isoformat()}[/bold]  {len(rows)} events")
        by_source: dict[str, int] = {}
        for r in rows:
            by_source[r["source"]] = by_source.get(r["source"], 0) + 1
        for s, n in sorted(by_source.items()):
            console.print(f"  {s}: {n}")
        console.print()
        for r in rows[:60]:
            console.print(
                f"[dim]{r['ts_start'][11:19]}[/dim] [magenta]{r['source']}[/magenta] "
                f"[yellow]{r['kind']}[/yellow] {r['title'][:100]}"
            )
        if len(rows) > 60:
            console.print(f"… and {len(rows) - 60} more")
    finally:
        store.close()


@app.command()
def summarize(
    day: Optional[str] = typer.Option(None, help="ISO date. Default: today."),
    save_digest: bool = typer.Option(False, help="Print the raw digest (no LLM)."),
):
    """Run the LLM summarizer over a day's events and cache the result."""
    cfg = config_mod.load()
    d = _parse_day(day)
    store = Store(cfg.db_path)
    try:
        rows = store.events_for_day(d)
        digest = render_digest(rows, d)
        if save_digest:
            console.print(digest)
            return

        summarizer = build_summarizer(cfg)
        console.print(f"[cyan]Summarizing {d} via {summarizer.provider}/{summarizer.model}…[/cyan]")
        out = summarizer.summarize(digest, d)
        store.save_summary(d, summarizer.provider, summarizer.model, out)
        console.print(out)
    finally:
        store.close()


@app.command()
def export(
    target: str = typer.Argument(..., help="markdown | json | notion"),
    day: Optional[str] = typer.Option(None, help="ISO date. Default: today."),
    out: Path = typer.Option(Path("./out"), help="Output directory (markdown/json)."),
):
    """Export the cached summary to markdown / json / Notion."""
    cfg = config_mod.load()
    d = _parse_day(day)
    store = Store(cfg.db_path)
    try:
        summary = store.get_summary(d, cfg.llm_provider, cfg.llm_model)
        if not summary:
            console.print(f"[red]No summary for {d}. Run `hindsight summarize` first.[/red]")
            raise typer.Exit(1)

        if target == "markdown":
            path = write_markdown(out, d, summary)
            console.print(f"[green]wrote[/green] {path}")
        elif target == "json":
            digest = render_digest(store.events_for_day(d), d)
            path = write_json(out, d, summary, digest)
            console.print(f"[green]wrote[/green] {path}")
        elif target == "notion":
            if not cfg.notion_token or not cfg.notion_database_id:
                console.print("[red]NOTION_TOKEN and NOTION_DATABASE_ID required.[/red]")
                raise typer.Exit(1)
            url = push_to_notion(cfg.notion_token, cfg.notion_database_id, d, summary)
            console.print(f"[green]pushed[/green] {url}")
        else:
            console.print(f"[red]Unknown target: {target}[/red]")
            raise typer.Exit(2)
    finally:
        store.close()


@app.command()
def run(
    day: Optional[str] = typer.Option(None, help="ISO date. Default: today."),
    targets: str = typer.Option("markdown", help="Comma-separated exports: markdown,json,notion"),
):
    """End-to-end: collect → summarize → export."""
    collect(since=day, until=day, sources=None)
    summarize(day=day, save_digest=False)
    for t in [s.strip() for s in targets.split(",") if s.strip()]:
        export(target=t, day=day, out=Path("./out"))


if __name__ == "__main__":
    app()
