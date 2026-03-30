"""CLI subcommand: scrape."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import httpx

from vtes_scraper_v1.cli._common import console, setup_logging
from vtes_scraper_v1.cli.validate import _load_coercions, _save_coercions
from vtes_scraper_v1.output import write_tournament_yaml
from vtes_scraper_v1.output.yaml import tournament_to_yaml_str
from vtes_scraper_v1.scraper import (
    DEFAULT_DELAY_SECONDS,
    HEADERS,
    ICON_MERGED,
    resolve_winner,
    scrape_forum,
)


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

    # Mutually exclusive, mandatory: exactly one of --fast-check / --slow-check
    check_group = p.add_mutually_exclusive_group(required=True)
    check_group.add_argument(
        "--fast-check",
        action="store_true",
        default=False,
        dest="fast_check",
        help=(
            "Parse only the first post of each thread (fast). "
            "TWD content is almost always in the opening post."
        ),
    )
    check_group.add_argument(
        "--slow-check",
        action="store_true",
        default=False,
        dest="slow_check",
        help=(
            "Paginate through every post in every thread and return the first "
            "one that parses as a TWD (slow). Use when the deck may not be in "
            "the opening post."
        ),
    )

    p.add_argument(
        "--start-page",
        type=int,
        default=0,
        dest="start_page",
        help="Forum index page to start scraping from, 0-indexed (default: 0).",
    )
    p.add_argument(
        "--last-page",
        type=int,
        default=None,
        dest="last_page",
        help=("Last forum index page to scrape, 0-indexed inclusive (default: scrape all pages)."),
    )
    p.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=f"Seconds between HTTP requests (default: {DEFAULT_DELAY_SECONDS}).",
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

    fast_check: bool = args.fast_check

    # Compute max_pages from last_page and start_page when last_page is given.
    max_pages: int | None = None
    if args.last_page is not None:
        max_pages = args.last_page - args.start_page + 1

    changes_required_dir = args.output_dir / "changes_required"

    written = skipped = failed = overwrite_skipped = 0

    coercions = _load_coercions(args.output_dir)

    with httpx.Client(headers=HEADERS, timeout=60.0) as player_client:
        for tournament, icon in scrape_forum(
            max_pages=max_pages,
            start_page=args.start_page,
            delay=args.delay,
            fast_check=fast_check,
        ):
            if not tournament.event_id:
                console.print(
                    f"[yellow]─[/yellow] {tournament.name!r}  [dim](no event_id — skipped)[/dim]"
                )
                skipped += 1
                continue

            # Enrich the tournament with the canonical winner name and vekn_number
            # from the VEKN member database (always applied during scraping).
            if tournament.vekn_number is None:
                prev_len = len(coercions) if coercions is not None else 0
                resolution = resolve_winner(
                    player_client,
                    tournament.winner,
                    coercions=coercions,
                    delay=args.delay,
                )
                if resolution:
                    canonical_name, vekn_num = resolution
                    if canonical_name != tournament.winner:
                        console.print(
                            f"[yellow]~[/yellow] {tournament.yaml_filename}"
                            f"  winner coerced: {tournament.winner!r}"
                            f" → {canonical_name!r}  (VEKN {vekn_num})"
                        )
                    tournament = tournament.model_copy(
                        update={"winner": canonical_name, "vekn_number": vekn_num}
                    )
                    if coercions is not None and len(coercions) != prev_len:
                        _save_coercions(args.output_dir, coercions)
                else:
                    console.print(
                        f"[yellow]?[/yellow] {tournament.yaml_filename}"
                        f"  winner not found in VEKN: {tournament.winner!r}"
                    )

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
                        console.print(f"[dim]  removed stale changes_required/{stale.name}[/dim]")
                except FileExistsError as exc:
                    logger.debug("%s", exc)
                    skipped += 1
                    overwrite_skipped += 1
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
    if overwrite_skipped:
        console.print(
            f"[yellow]![/yellow] {overwrite_skipped} deck(s) already existed "
            f"and were not overwritten (use --overwrite to replace them)."
        )
    return 1 if failed else 0
