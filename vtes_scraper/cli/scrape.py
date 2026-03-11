"""CLI subcommand: scrape."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from vtes_scraper.cli._common import console, setup_logging
from vtes_scraper.output import write_tournament_yaml
from vtes_scraper.output.yaml import tournament_to_yaml_str
from vtes_scraper.scraper import ICON_MERGED, scrape_forum


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
        "--start-page",
        type=int,
        default=0,
        dest="start_page",
        help="Forum index page to start scraping from, 0-indexed (default: 0).",
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
    """Scrape the VEKN forum and export each TWD as a YAML file.

    Icon routing:
      default / solved → <output-dir>/YYYY/MM/<event_id>.yaml  (normal)
      merged           → <output-dir>/changes_required/<event_id>.yaml
      idea             → skipped (informational only)
    """
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    changes_required_dir = args.output_dir / "changes_required"

    written = skipped = failed = 0

    for tournament, icon in scrape_forum(
        max_pages=args.max_pages, start_page=args.start_page, delay=args.delay
    ):
        if not tournament.event_id:
            console.print(
                f"[yellow]─[/yellow] {tournament.name!r}  [dim](no event_id — skipped)[/dim]"
            )
            skipped += 1
            continue

        if icon == ICON_MERGED:
            # Changes have been requested — keep in a dedicated folder and
            # overwrite on every run so the latest forum content is always
            # stored (the reporter may update their post).
            changes_required_dir.mkdir(parents=True, exist_ok=True)
            path = changes_required_dir / tournament.yaml_filename
            try:
                path.write_text(tournament_to_yaml_str(tournament), encoding="utf-8")
                console.print(
                    f"[yellow]⚠[/yellow] {path.name}  {tournament.name}"
                    "  [dim](changes required)[/dim]"
                )
                written += 1
            except Exception as exc:
                console.print(f"[red]✗[/red] {tournament.event_id}: {exc}")
                logger.debug("Stack trace:", exc_info=True)
                failed += 1
        else:
            try:
                path = write_tournament_yaml(
                    tournament,
                    args.output_dir,
                    overwrite=args.overwrite,
                )
                console.print(f"[green]✓[/green] {path.name}  {tournament.name}")
                written += 1

                # If this topic previously had a merged icon, remove the stale copy
                stale = changes_required_dir / tournament.yaml_filename
                if stale.exists():
                    stale.unlink()
                    console.print(
                        f"[dim]  removed stale changes_required/{stale.name}[/dim]"
                    )
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
