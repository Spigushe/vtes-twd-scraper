"""CLI subcommand: publish."""

import argparse
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from ruamel.yaml import YAML

from vtes_scraper.cli._common import SubParsersAction, console, setup_logging
from vtes_scraper.models import Tournament
from vtes_scraper.publisher import BatchPRResult, publish_all_as_single_pr

logger = logging.getLogger(__name__)


def register(sub: SubParsersAction) -> None:
    p = sub.add_parser(
        "publish",
        help="Open a single PR in GiottoVerducci/TWD with all new decks from local YAML files.",
    )
    p.add_argument(
        "--twds-dir",
        type=Path,
        default=Path("twds"),
        dest="twds_dir",
        help="Directory containing scraped YAML files (default: twds/).",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds between GitHub API file commits (default: 1.0).",
    )
    p.add_argument(
        "--github-token",
        default=None,
        dest="github_token",
        help="GitHub PAT with 'public_repo' scope. Falls back to $GITHUB_TOKEN.",
    )
    p.add_argument(
        "--publish-dir",
        type=Path,
        default=Path("publish"),
        dest="publish_dir",
        help="Directory to write Markdown publish reports (default: publish/).",
    )
    p.add_argument(
        "--include-pre-2020",
        action="store_true",
        dest="include_pre_2020",
        help="Publish decks from before 2020 (skipped by default).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help=(
            "Simulate the full publish flow (fork, branch, file commits) "
            "without opening a PR. The branch is deleted after the run. "
            "Report is saved alongside normal reports under publish/YYYY/MM/, "
            "named dry-run-{date}-{HH-MM-SS}.md."
        ),
    )
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(func=run)


def _write_publish_report(
    result: BatchPRResult,
    publish_dir: Path,
    today: str,
    tournaments: list[Tournament],
    timestamp: str | None = None,
) -> Path:
    """Write a Markdown summary of a publish run.

    Normal runs  → publish/YYYY/MM/{today}.md
    Dry-run runs → publish/YYYY/MM/dry-run-{today}-{HH-MM-SS}.md
    """
    year, month = today[:4], today[5:7]
    report_dir = publish_dir / year / month
    report_dir.mkdir(parents=True, exist_ok=True)

    if result.dry_run:
        # timestamp is YYYY-MM-DD-HH-MM-SS; extract the time portion
        time_suffix = f"-{timestamp[11:]}" if timestamp and len(timestamp) > 10 else ""
        report_path = report_dir / f"dry-run-{today}{time_suffix}.md"
    else:
        report_path = report_dir / f"{today}.md"

    title_suffix = " (DRY RUN)" if result.dry_run else ""
    lines = [f"# TWD Publish Report — {today}{title_suffix}", ""]

    if result.dry_run:
        lines += [
            "> **Dry-run mode** — branch was created and files committed to verify "
            "behaviour, but the branch was deleted and no PR was opened.",
            "",
        ]

    if result.pr_url:
        lines += [f"**PR**: [{result.pr_url}]({result.pr_url})", ""]
    elif result.skipped_all:
        lines += ["_All decks already present on master — no PR opened._", ""]
    else:
        lines += ["_No PR opened._", ""]

    lines += [f"## Published ({len(result.published)})", ""]
    if result.published:
        published_set = set(result.published)
        lines += [
            "| Event ID | Event Name | Location | Date | Winner |",
            "| -------- | ---------- | -------- | ---- | ------ |",
        ]
        for t in tournaments:
            if (t.event_id or "unknown") in published_set:
                name_link = f"[{t.name}]({t.event_url})" if t.event_url else t.name
                lines.append(
                    f"| {t.event_id} | {name_link} | {t.location} | {t.date_start} | {t.winner} |"
                )
    else:
        lines.append("_None._")
    lines.append("")

    lines += [f"## Skipped — already on master ({len(result.skipped)})", ""]
    lines.append(", ".join(str(e) for e in result.skipped) if result.skipped else "_None._")
    lines.append("")

    lines += [f"## Errors ({len(result.errors)})", ""]
    if result.errors:
        for event_id, err in result.errors:
            lines.append(f"- `{event_id}`: {err}")
    else:
        lines.append("_None._")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def run(args: argparse.Namespace) -> int:
    """Load local YAML files and open a single Pull Request in GiottoVerducci/TWD."""
    setup_logging(args.verbose)

    token = args.github_token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        console.print(
            "[red]Error:[/red] GitHub token required. "
            "Set --github-token or the GITHUB_TOKEN environment variable."
        )
        return 1

    # ── Load local YAML files ──────────────────────────────────────────────
    yaml = YAML()
    twds_dir: Path = args.twds_dir
    errors_dir = twds_dir / "errors"
    yaml_files = sorted(p for p in twds_dir.rglob("*.yaml") if not p.is_relative_to(errors_dir))
    logger.debug("Found %d YAML file(s) in %s.", len(yaml_files), twds_dir)

    if not yaml_files:
        console.print(f"[yellow]No YAML files found in {twds_dir}.[/yellow]")
        return 0

    tournaments: list[Tournament] = []
    for path in yaml_files:
        try:
            data = yaml.load(  # pyright: ignore[reportUnknownMemberType]
                path.read_text(encoding="utf-8")
            )
            t = Tournament.model_validate(data)
            tournaments.append(t)
            logger.debug("Loaded %s: %s (%s)", t.event_id, t.name, t.location)
        except Exception as exc:
            logger.warning("Skipping %s — could not load: %s", path, exc)

    console.print(f"Loaded [green]{len(tournaments)}[/green] tournament(s) from {twds_dir}.")

    if not tournaments:
        console.print("[yellow]Nothing to publish.[/yellow]")
        return 0

    # ── Filter out pre-2020 decks ──────────────────────────────────────────
    if not args.include_pre_2020:
        before_count = len(tournaments)
        tournaments = [t for t in tournaments if t.date_start.year >= 2020]
        excluded = before_count - len(tournaments)
        if excluded:
            console.print(
                f"[yellow]Excluded {excluded} tournament(s) with date prior to 2020.[/yellow]"
            )
        if not tournaments:
            console.print("[yellow]Nothing to publish after year filter.[/yellow]")
            return 0

    # ── Publish ────────────────────────────────────────────────────────────
    now = datetime.now(UTC)
    today = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%Y-%m-%d-%H-%M-%S")

    dry_run: bool = getattr(args, "dry_run", False)
    if dry_run:
        console.print(
            f"[yellow]Dry-run:[/yellow] simulating publish of "
            f"[cyan]{len(tournaments)}[/cyan] tournament(s) — no PR will be opened…"
        )
    else:
        console.print(f"Publishing [cyan]{len(tournaments)}[/cyan] tournament(s) as a single PR…")
    logger.debug(
        "Submitting %d tournament(s) to publisher (dry_run=%s).",
        len(tournaments),
        dry_run,
    )
    result = publish_all_as_single_pr(tournaments, token=token, delay=args.delay, dry_run=dry_run)

    # ── Save Markdown report ───────────────────────────────────────────────
    try:
        report_path = _write_publish_report(
            result, args.publish_dir, today, tournaments, timestamp=timestamp
        )
        console.print(f"Report saved → [dim]{report_path}[/dim]")
        logger.debug("Publish report written to %s.", report_path)
    except Exception as exc:
        logger.warning("Could not write publish report: %s", exc)

    if result.skipped_all:
        console.print(
            "[yellow]All decks already exist in the target repo — nothing to do.[/yellow]"
        )
        return 0

    for event_id in result.skipped:
        console.print(f"[yellow]─[/yellow] {event_id} already in target repo — skipped")
    for event_id, err in result.errors:
        console.print(f"[red]✗[/red] {event_id}: {err}")
    for event_id in result.published:
        console.print(f"[green]✓[/green] {event_id} committed to PR branch")

    console.rule()
    if dry_run:
        console.print(
            f"[yellow]Dry-run complete[/yellow] — "
            f"[green]{len(result.published)}[/green] deck(s) committed and branch deleted, "
            f"no PR opened."
        )
    elif result.pr_url:
        console.print(
            f"[green]PR opened[/green] with [green]{len(result.published)}[/green]"
            f" deck(s) → {result.pr_url}"
        )
    else:
        console.print(
            f"[green]{len(result.published)}[/green] deck(s) committed but PR could not be opened "
            f"(check logs for details)."
        )
    console.print(
        f"[yellow]{len(result.skipped)} skipped[/yellow], [red]{len(result.errors)} failed[/red]"
    )
    return 1 if result.errors else 0
