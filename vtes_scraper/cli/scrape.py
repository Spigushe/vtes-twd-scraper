"""CLI subcommand: scrape."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from vtes_scraper.cli._common import console, setup_logging
from vtes_scraper.output import write_tournament_yaml
from vtes_scraper.scraper import scrape_forum


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("scrape", help="Scrape the VEKN forum and write YAML files.")
    p.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("twds"),
        dest="output_dir",
        help="Root directory; files are written to <dir>/YYYY/MM/<event_id>.yaml. (default: twds)",
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
        "--overwrite",
        action="store_true",
        help="Overwrite existing YAML files.",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    """Scrape the VEKN forum and export each TWD as a YAML file under <output-dir>/YYYY/MM/."""
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    written = skipped = failed = 0

    for tournament in scrape_forum(max_pages=args.max_pages, delay=args.delay):
        try:
            path = write_tournament_yaml(
                tournament,
                args.output_dir,
                overwrite=args.overwrite,
            )
            console.print(f"[green]✓[/green] {path.name}  {tournament.name}")
            written += 1
        except FileExistsError as exc:
            console.print(f"[yellow]─[/yellow] {exc}")
            skipped += 1
        except Exception as exc:
            console.print(f"[red]✗[/red] {tournament.event_id}: {exc}")
            logger.debug("Stack trace:", exc_info=True)
            failed += 1

    console.rule()
    console.print(
        f"Done — [green]{written} written[/green], "
        f"[yellow]{skipped} skipped[/yellow], "
        f"[red]{failed} failed[/red]"
    )
    return 1 if failed else 0
