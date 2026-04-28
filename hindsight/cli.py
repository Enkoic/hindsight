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
    ChatGPTExportCollector,
    ClaudeCodeCollector,
    ClaudeHistoryCollector,
    CodexCollector,
    CodexHistoryCollector,
    CursorCollector,
    VSCodeCopilotCollector,
)
from .exporters import (
    push_to_notion,
    push_to_webhook,
)
from . import schedule as schedule_mod
from .redact import redact, rules_from_env
from .store import Store
from .summarizer import (
    build_summarizer,
    render_digest,
    summarize_rollup,
)

app = typer.Typer(add_completion=False, help="Aggregate and summarize your daily activity.")
console = Console()


def _default_out_dir(cfg) -> Path:
    """Default `export` output dir lives next to the SQLite store, not in cwd."""
    return cfg.db_path.parent / "exports"


KNOWN_SOURCES = {
    "activitywatch", "claude_code", "claude_history",
    "codex", "codex_history", "cursor", "chatgpt", "vscode",
}


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
    cs: list = [
        ActivityWatchCollector(cfg.aw_server_url),
        ClaudeCodeCollector(cfg.claude_projects_dir),
        ClaudeHistoryCollector(claude_home),
        CodexCollector(cfg.codex_sessions_dir),
        CodexHistoryCollector(codex_home),
    ]
    if cfg.cursor_storage_dir:
        cs.append(CursorCollector(cfg.cursor_storage_dir))
    if cfg.vscode_storage_dir:
        cs.append(VSCodeCopilotCollector(cfg.vscode_storage_dir))
    if cfg.chatgpt_export_path:
        cs.append(ChatGPTExportCollector(cfg.chatgpt_export_path))
    return cs


@app.command()
def collect(
    since: Optional[str] = typer.Option(None, help="ISO date or 'yesterday'. Default: last 2 days."),
    until: Optional[str] = typer.Option(None, help="ISO date. Default: now."),
    days: Optional[int] = typer.Option(
        None,
        help="Shortcut: collect the last N days (overrides --since if both given).",
    ),
    sources: Optional[str] = typer.Option(
        None,
        help=f"Comma-separated subset of source names; default = all configured. "
        f"Known: {sorted(KNOWN_SOURCES)}",
    ),
):
    """Pull events from all sources into the local store."""
    cfg = config_mod.load()
    store = Store(cfg.db_path)
    try:
        now = datetime.now(timezone.utc)
        if days is not None:
            if days < 1:
                raise typer.BadParameter("--days must be >= 1")
            since_dt = now - timedelta(days=days)
        elif since:
            since_dt, _ = _day_bounds(_parse_day(since))
        else:
            since_dt = now - timedelta(days=2)
        until_dt = _day_bounds(_parse_day(until))[1] if until else now

        want = set(s.strip() for s in sources.split(",")) if sources else None
        if want:
            unknown = want - KNOWN_SOURCES
            if unknown:
                console.print(f"[yellow]warn:[/yellow] unknown source(s) {sorted(unknown)}")
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
def purge(
    older_than: Optional[int] = typer.Option(
        None, help="Delete events with ts_start older than N days ago."
    ),
    source: Optional[str] = typer.Option(
        None, help="Comma-separated source name(s) to delete (in addition to --older-than if given)."
    ),
    vacuum: bool = typer.Option(True, help="Run VACUUM after delete to reclaim disk."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
):
    """Delete old or unwanted events from the local store. Cached summaries are kept."""
    if older_than is None and not source:
        console.print("[red]must pass at least one of --older-than or --source[/red]")
        raise typer.Exit(2)
    cfg = config_mod.load()
    before_day = (
        (datetime.now(timezone.utc) - timedelta(days=older_than)).date()
        if older_than is not None
        else None
    )
    sources = [s.strip() for s in source.split(",")] if source else None
    if not yes:
        msg = "Will delete events"
        if before_day:
            msg += f" before {before_day}"
        if sources:
            msg += f" from sources={sources}"
        console.print(f"[yellow]{msg}.  Confirm with --yes.[/yellow]")
        raise typer.Exit(1)
    store = Store(cfg.db_path)
    try:
        out = store.purge(before=before_day, sources=sources)
        if vacuum:
            store.vacuum()
        console.print(
            f"[green]deleted[/green] {out['deleted']} events "
            f"({out['before']} → {out['after']})"
        )
    finally:
        store.close()


@app.command()
def stats():
    """Show what's in the local store: per-source counts, time span, cached summaries."""
    cfg = config_mod.load()
    store = Store(cfg.db_path)
    try:
        s = store.stats()
        size_mb = cfg.db_path.stat().st_size / 1024 / 1024 if cfg.db_path.exists() else 0
        console.print(f"[bold]Store[/bold]: {cfg.db_path}  ({size_mb:.1f} MB)")
        console.print(
            f"  range: {s['first_event'] or '—'}  …  {s['last_event'] or '—'}"
        )
        console.print(f"  events: [green]{s['events_total']}[/green] total")

        table = Table(show_header=False, box=None, padding=(0, 2))
        for src, n in sorted(s["events_per_source"].items(), key=lambda kv: -kv[1]):
            table.add_row(f"  {src}", str(n))
        console.print(table)

        console.print(
            f"  summaries cached: [cyan]{s['summaries_total']}[/cyan] "
            f"(latest day: {s['last_summary_day'] or '—'})"
        )
        console.print(f"  rollups cached:   [cyan]{s['rollups_total']}[/cyan]")
        console.print(f"  provider/model:   {cfg.llm_provider}/{cfg.llm_model}")
    finally:
        store.close()


@app.command()
def report(day: Optional[str] = typer.Option(None, help="ISO date. Default: today.")):
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
    redact_secrets: bool = typer.Option(
        True, "--redact/--no-redact",
        help="Strip API keys / emails / private IPs / JWTs from the digest before LLM call.",
    ),
):
    """Run the LLM summarizer over a day's events and cache the result."""
    cfg = config_mod.load()
    d = _parse_day(day)
    store = Store(cfg.db_path)
    try:
        rows = store.events_for_day(d)
        digest = render_digest(rows, d)
        if redact_secrets:
            digest, hits = redact(digest, rules_from_env())
            if hits:
                console.print(f"[yellow]redacted[/yellow] {dict(hits)}")
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


def _resolve_range(
    since: str | None, until: str | None, week: str | None, month: str | None
) -> tuple[date, date]:
    if week:
        # ISO week: YYYY-Www, e.g. 2026-W17
        try:
            year_s, w_s = week.split("-W")
            year = int(year_s)
            wk = int(w_s)
        except ValueError as e:
            raise typer.BadParameter(f"week must be YYYY-Www, got {week!r}") from e
        start = date.fromisocalendar(year, wk, 1)
        end = date.fromisocalendar(year, wk, 7)
        return start, end
    if month:
        try:
            y, m = month.split("-")
            start = date(int(y), int(m), 1)
        except ValueError as e:
            raise typer.BadParameter(f"month must be YYYY-MM, got {month!r}") from e
        if start.month == 12:
            end = date(start.year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(start.year, start.month + 1, 1) - timedelta(days=1)
        return start, end
    if since and until:
        return _parse_day(since), _parse_day(until)
    raise typer.BadParameter("provide either --week, --month, or both --since and --until")


@app.command()
def rollup(
    week: Optional[str] = typer.Option(None, help="ISO week, e.g. 2026-W17"),
    month: Optional[str] = typer.Option(None, help="Month, e.g. 2026-04"),
    since: Optional[str] = typer.Option(None, help="ISO start date (with --until)"),
    until: Optional[str] = typer.Option(None, help="ISO end date (with --since)"),
    fill_missing: bool = typer.Option(
        False, help="Auto-summarize any day in range that doesn't have a cached summary yet."
    ),
    redact_secrets: bool = typer.Option(
        True, "--redact/--no-redact",
        help="Strip API keys / emails / private IPs / JWTs from inputs before LLM call.",
    ),
):
    """Synthesize a multi-day rollup from cached daily summaries."""
    cfg = config_mod.load()
    start, end = _resolve_range(since, until, week, month)
    store = Store(cfg.db_path)
    rules = rules_from_env()
    try:
        if fill_missing:
            summarizer = build_summarizer(cfg)
            day = start
            while day <= end:
                if not store.get_summary(day, summarizer.provider, summarizer.model):
                    rows = store.events_for_day(day)
                    if rows:
                        console.print(f"[cyan]filling[/cyan] {day} ({len(rows)} events)")
                        digest = render_digest(rows, day)
                        if redact_secrets:
                            digest, _ = redact(digest, rules)
                        out = summarizer.summarize(digest, day)
                        store.save_summary(day, summarizer.provider, summarizer.model, out)
                day += timedelta(days=1)

        dailies = store.summaries_in_range(start, end, cfg.llm_provider, cfg.llm_model)
        if not dailies:
            console.print(
                f"[red]No cached daily summaries in {start}..{end}. "
                "Run `hindsight summarize` per day or pass --fill-missing.[/red]"
            )
            raise typer.Exit(1)

        summarizer = build_summarizer(cfg)
        console.print(
            f"[cyan]Rollup {start} .. {end}[/cyan] — {len(dailies)} daily summaries → "
            f"{summarizer.provider}/{summarizer.model}"
        )
        if redact_secrets:
            redacted: list[tuple] = []
            total_hits: dict[str, int] = {}
            for d, content in dailies:
                rc, hits = redact(content, rules)
                redacted.append((d, rc))
                for k, n in hits.items():
                    total_hits[k] = total_hits.get(k, 0) + n
            if total_hits:
                console.print(f"[yellow]redacted[/yellow] {total_hits}")
            dailies = redacted
        out = summarize_rollup(summarizer, dailies, start, end)
        store.save_rollup(start, end, summarizer.provider, summarizer.model, out)
        console.print(out)
    finally:
        store.close()


@app.command()
def export(
    target: str = typer.Argument(..., help="markdown | json | notion | obsidian | webhook"),
    day: Optional[str] = typer.Option(None, help="ISO date. Default: today."),
    week: Optional[str] = typer.Option(None, help="Export a cached rollup for this ISO week."),
    month: Optional[str] = typer.Option(None, help="Export a cached rollup for this month."),
    since: Optional[str] = typer.Option(None, help="Custom rollup range start (with --until)."),
    until: Optional[str] = typer.Option(None, help="Custom rollup range end (with --since)."),
    out: Optional[Path] = typer.Option(
        None, help="Output dir (markdown/json). Default: <data-dir>/exports/."
    ),
):
    """Export a cached daily summary or multi-day rollup."""
    cfg = config_mod.load()
    out_dir = out or _default_out_dir(cfg)
    store = Store(cfg.db_path)
    try:
        is_rollup = bool(week or month or (since and until))
        if is_rollup:
            start, end = _resolve_range(since, until, week, month)
            content = store.get_rollup(start, end, cfg.llm_provider, cfg.llm_model)
            if not content:
                console.print(
                    f"[red]No cached rollup for {start}..{end}. "
                    "Run `hindsight rollup` first.[/red]"
                )
                raise typer.Exit(1)
            label = f"{start.isoformat()}_to_{end.isoformat()}"
            d_for_export = end  # used for date-typed sinks (Notion / Obsidian frontmatter)
        else:
            d = _parse_day(day)
            content = store.get_summary(d, cfg.llm_provider, cfg.llm_model)
            if not content:
                console.print(f"[red]No summary for {d}. Run `hindsight summarize` first.[/red]")
                raise typer.Exit(1)
            label = d.isoformat()
            d_for_export = d

        if target == "markdown":
            path = _write_markdown(out_dir, label, content)
            console.print(f"[green]wrote[/green] {path}")
        elif target == "json":
            extra = (
                None
                if is_rollup
                else render_digest(store.events_for_day(d_for_export), d_for_export)
            )
            path = _write_json(out_dir, label, content, extra)
            console.print(f"[green]wrote[/green] {path}")
        elif target == "notion":
            if not cfg.notion_token or not cfg.notion_database_id:
                console.print("[red]NOTION_TOKEN and NOTION_DATABASE_ID required.[/red]")
                raise typer.Exit(1)
            title_prefix = "Hindsight Rollup" if is_rollup else "Daily Digest"
            url = push_to_notion(
                cfg.notion_token,
                cfg.notion_database_id,
                d_for_export,
                content,
                title_prefix=title_prefix,
            )
            console.print(f"[green]pushed[/green] {url}")
        elif target == "obsidian":
            if not cfg.obsidian_vault_dir:
                console.print("[red]OBSIDIAN_VAULT_DIR required.[/red]")
                raise typer.Exit(1)
            subfolder = "Hindsight/Rollups" if is_rollup else "Hindsight"
            tag = "hindsight-rollup" if is_rollup else "hindsight"
            path = _write_obsidian_any(
                cfg.obsidian_vault_dir, label, content, subfolder=subfolder, tag=tag
            )
            console.print(f"[green]wrote[/green] {path}")
        elif target == "webhook":
            if not cfg.webhook_url:
                console.print("[red]HINDSIGHT_WEBHOOK_URL required (Slack/Discord).[/red]")
                raise typer.Exit(1)
            url = push_to_webhook(cfg.webhook_url, label, content)
            console.print(f"[green]posted[/green] {url}")
        else:
            console.print(f"[red]Unknown target: {target}[/red]")
            raise typer.Exit(2)
    finally:
        store.close()


def _write_markdown(out_dir: Path, label: str, content: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{label}.md"
    header = f"---\nlabel: {label}\n---\n\n# Hindsight — {label}\n\n"
    path.write_text(header + content + "\n", encoding="utf-8")
    return path


def _write_json(out_dir: Path, label: str, content: str, raw_digest: str | None) -> Path:
    import json as _json

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{label}.json"
    payload = {"label": label, "summary": content, "raw_digest": raw_digest}
    path.write_text(_json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_obsidian_any(
    vault_dir: Path, label: str, content: str, subfolder: str, tag: str
) -> Path:
    target_dir = vault_dir / subfolder
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{label}.md"
    fm = (
        "---\n"
        f"label: {label}\n"
        f"tags: [{tag}]\n"
        f"source: hindsight\n"
        "---\n\n"
    )
    path.write_text(fm + f"# Hindsight — {label}\n\n{content}\n", encoding="utf-8")
    return path


@app.command()
def run(
    day: Optional[str] = typer.Option(None, help="ISO date. Default: today."),
    targets: str = typer.Option(
        "markdown",
        help="Comma-separated exports: markdown,json,notion,obsidian",
    ),
):
    """End-to-end: collect → summarize → export."""
    collect(since=day, until=day, days=None, sources=None)
    summarize(day=day, save_digest=False)
    for t in [s.strip() for s in targets.split(",") if s.strip()]:
        export(target=t, day=day, week=None, month=None, since=None, until=None, out=None)


schedule_app = typer.Typer(
    help="Install/remove a daily scheduled run (macOS launchd or Linux systemd --user)."
)
app.add_typer(schedule_app, name="schedule")


@schedule_app.command("install")
def schedule_install(
    hour: int = typer.Option(23, help="Hour (0-23) when the daily run fires."),
    minute: int = typer.Option(0, help="Minute (0-59)."),
    targets: str = typer.Option("markdown", help="Export targets passed to `hindsight run`."),
):
    """Install the platform's scheduler. macOS → launchd plist, Linux → systemd --user timer."""
    info = schedule_mod.install(hour=hour, minute=minute, targets=targets)
    console.print(f"[green]installed[/green] {info.primary}")
    for extra in info.extras:
        console.print(f"  + {extra}")
    if info.platform == "darwin":
        console.print("Verify with `launchctl list | grep hindsight`.")
    else:
        console.print("Verify with `systemctl --user list-timers hindsight.timer`.")


@schedule_app.command("uninstall")
def schedule_uninstall():
    """Remove the scheduled run."""
    info = schedule_mod.uninstall()
    if not info:
        console.print("[yellow]no schedule installed[/yellow]")
        return
    console.print(f"[green]removed[/green] {info.primary}")


@schedule_app.command("show")
def schedule_show():
    """Print the path(s) the scheduler writes to on this platform."""
    for p in schedule_mod.show_paths():
        console.print(str(p))


if __name__ == "__main__":
    app()
