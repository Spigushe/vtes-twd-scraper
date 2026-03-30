"""CLI subcommand: rescrape — re-fetch all decks under twds/errors/."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import httpx

from vtes_scraper_v1.cli._common import console, setup_logging
from vtes_scraper_v1.output import write_tournament_yaml
from vtes_scraper_v1.scraper import (
    DEFAULT_DELAY_SECONDS,
    HEADERS,
    extract_twd_from_thread,
)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "rescrape",
        help="Re-fetch all decks whose YAML lives under twds/errors/ and rewrite them.",
    )
    p.add_argument(
        "--errors-dir",
        "-e",
        type=Path,
        default=Path("twds/errors"),
        dest="errors_dir",
        help="Root of the error tree to rescrape (default: twds/errors).",
    )
    p.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("twds"),
        dest="output_dir",
        help="Root directory for successfully parsed files (default: twds).",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=f"Seconds between HTTP requests (default: {DEFAULT_DELAY_SECONDS}).",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    error_files = sorted(args.errors_dir.rglob("*.yaml"))
    if not error_files:
        console.print(f"[yellow]No YAML files found under {args.errors_dir}[/yellow]")
        return 0

    console.print(f"Found [bold]{len(error_files)}[/bold] file(s) to rescrape.")

    written = skipped = failed = 0

    with httpx.Client(headers=HEADERS, timeout=60.0) as client:
        for yaml_path in error_files:
            # Read forum_post_url from the existing YAML without a full parse.
            # Some files use a multi-line style where the URL is on the next line:
            #   forum_post_url:
            #     https://...
            forum_post_url: str | None = None
            lines = yaml_path.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines):
                if line.startswith("forum_post_url:"):
                    value = line.split(":", 1)[1].strip()
                    if not value and i + 1 < len(lines):
                        value = lines[i + 1].strip()
                    forum_post_url = value or None
                    break

            if not forum_post_url:
                console.print(f"[yellow]─[/yellow] {yaml_path.name}  no forum_post_url, skipping")
                skipped += 1
                continue

            tournament = extract_twd_from_thread(client, forum_post_url, delay=args.delay)
            if tournament is None:
                console.print(f"[red]✗[/red] {yaml_path.name}  parse failed for {forum_post_url}")
                logger.debug("No tournament returned for %s", forum_post_url)
                failed += 1
                continue

            try:
                path = write_tournament_yaml(tournament, args.output_dir, overwrite=True)
                console.print(f"[green]✓[/green] {path.name}  {tournament.name}")
                written += 1

                # Delete the file in the errors directory if scraping is successful
                yaml_path.unlink()
            except Exception as exc:
                console.print(f"[red]✗[/red] {yaml_path.name}: {exc}")
                logger.debug("Write error:", exc_info=True)
                failed += 1

    console.rule()
    console.print(
        f"Done — [green]{written} written[/green], "
        f"[yellow]{skipped} skipped[/yellow], "
        f"[red]{failed} failed[/red]"
    )
    return 1 if failed else 0
