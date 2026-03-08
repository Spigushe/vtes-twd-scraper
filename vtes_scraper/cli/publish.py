"""CLI subcommand: publish."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from vtes_scraper.cli._common import console, setup_logging
from vtes_scraper.output import write_tournament_txt
from vtes_scraper.publisher import publish_all_as_single_pr
from vtes_scraper.scraper import scrape_forum


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "publish",
        help="Scrape and open a single PR in GiottoVerducci/TWD with all new decks.",
    )
    p.add_argument(
        "--max-pages",
        type=int,
        default=None,
        dest="max_pages",
        help="Limit the number of forum index pages to scrape (default: all).",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Seconds between HTTP requests (default: 1.5).",
    )
    p.add_argument(
        "--github-token",
        default=None,
        dest="github_token",
        help="GitHub PAT with 'public_repo' scope. Falls back to $GITHUB_TOKEN.",
    )
    p.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=None,
        dest="output_dir",
        help="Also write TXT files locally to this directory (optional).",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    """Scrape the VEKN forum and open a single Pull Request in GiottoVerducci/TWD."""
    setup_logging(args.verbose)

    token = args.github_token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        console.print(
            "[red]Error:[/red] GitHub token required. "
            "Set --github-token or the GITHUB_TOKEN environment variable."
        )
        return 1

    tournaments = []
    for tournament in scrape_forum(max_pages=args.max_pages, delay=args.delay):
        tournaments.append(tournament)
        if args.output_dir is not None:
            try:
                path = write_tournament_txt(tournament, args.output_dir)
                console.print(f"[dim]  wrote {path}[/dim]")
            except FileExistsError:
                pass

    console.print(f"Scraped [green]{len(tournaments)}[/green] tournaments.")

    if not tournaments:
        console.print("[yellow]Nothing to publish.[/yellow]")
        return 0

    console.print(
        f"Publishing [cyan]{len(tournaments)}[/cyan] scraped decks as a single PR…"
    )
    result = publish_all_as_single_pr(tournaments, token=token, delay=args.delay)

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
    if result.pr_url:
        console.print(
            (
                "[green]PR opened[/green] with [green]",
                f"{len(result.published)}[/green] deck(s) → {result.pr_url}",
            )
        )
    else:
        console.print(
            f"[green]{len(result.published)}[/green] deck(s) committed but PR could not be opened "
            f"(check logs for details)."
        )
    console.print(
        f"[yellow]{len(result.skipped)} skipped[/yellow], "
        f"[red]{len(result.errors)} failed[/red]"
    )
    return 1 if result.errors else 0
