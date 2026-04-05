"""CLI subcommand: scrape.

Scraping workflow:
  1. Scrape forum data (fetch thread HTML).
  2. Parse data (extract Tournament from post text).
  3. Check event calendar for the winner's name.
  4. Look up the winner in the VEKN player registry for their VEKN number.
  5. Validate card information with the krcg library.
  6. Validate content and route files to the appropriate destination.
"""

import argparse
import logging
from pathlib import Path
from typing import Any, cast

import httpx

from vtes_scraper.cli._common import SubParsersAction, console, setup_logging
from vtes_scraper.models import Deck_Dict, Tournament, Tournament_Dict
from vtes_scraper.output import write_tournament_yaml
from vtes_scraper.output.yaml import tournament_to_yaml_str
from vtes_scraper.scraper import (
    DEFAULT_DELAY_SECONDS,
    HEADERS,
    ICON_MERGED,
    fetch_event_date,
    fetch_event_winner,
    fetch_player,
    scrape_forum,
)
from vtes_scraper.validator import (
    enrich_crypt_cards,
    error_types,
    fix_card_sections,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Serialization helper
# ---------------------------------------------------------------------------


def _to_serializable(obj: Tournament) -> Tournament_Dict:
    """Convert a Pydantic model to a plain dict, filtering None values."""

    def _filter_none(value: Any) -> Any:
        if isinstance(value, dict):
            d = cast(dict[str, Any], value)
            return {k: _filter_none(v) for k, v in d.items() if v is not None}
        if isinstance(value, list):
            items = cast(list[Any], value)  # type: ignore[redundant-cast]
            return [_filter_none(item) for item in items]
        return value

    return cast(Tournament_Dict, _filter_none(obj.model_dump()))


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------


def _check_calendar_winner(
    client: httpx.Client,
    tournament: Tournament,
    delay: float,
) -> tuple[Tournament, bool]:
    """Step 3: override the winner with the official VEKN calendar standings.

    Returns ``(tournament, calendar_winner_missing)`` where
    ``calendar_winner_missing`` is ``True`` when the event URL is set but the
    calendar page has no results/standings data yet.
    """
    if not tournament.event_url:
        return tournament, False
    try:
        calendar_winner = fetch_event_winner(client, tournament.event_url, delay=delay)
        if calendar_winner is None:
            logger.debug("No results data on event page: %s", tournament.event_url)
            return tournament, True
        if calendar_winner != tournament.winner:
            logger.debug(
                "Calendar winner override: %r → %r  (%s)",
                tournament.winner,
                calendar_winner,
                tournament.event_url,
            )
            return tournament.model_copy(update={"winner": calendar_winner}), False
    except Exception as exc:
        logger.warning(
            "Could not fetch calendar winner for %s: %s",
            tournament.event_url,
            exc,
        )
    return tournament, False


def _lookup_player(
    client: httpx.Client,
    tournament: Tournament,
    delay: float,
) -> Tournament:
    """Step 4: look up winner in the VEKN player registry."""
    if tournament.vekn_number is not None:
        return tournament

    winner = tournament.winner

    try:
        result = fetch_player(client, winner, delay=delay)
    except Exception as exc:
        logger.warning("Player lookup failed for %r: %s", winner, exc)
        return tournament

    if result is None:
        console.print(
            f"[yellow]?[/yellow] {tournament.yaml_filename}  winner not found in VEKN: {winner!r}"
        )
        return tournament

    canonical_name, vekn_number = result
    if canonical_name != winner:
        console.print(
            f"[yellow]~[/yellow] {tournament.yaml_filename}"
            f"  winner coerced: {winner!r}"
            f" → {canonical_name!r}  (VEKN {vekn_number})"
        )
    return tournament.model_copy(update={"winner": canonical_name, "vekn_number": vekn_number})


def _enrich_with_krcg(tournament: Tournament) -> Tournament:
    """Step 5: validate and enrich crypt and library cards via krcg."""
    data = _to_serializable(tournament)
    deck_data = cast(Deck_Dict, data.get("deck"))
    if not deck_data:
        return tournament

    crypt_fixes = enrich_crypt_cards(deck_data)
    section_fixes = fix_card_sections(deck_data)

    if crypt_fixes:
        console.print(
            f"[cyan]⚙[/cyan] {tournament.yaml_filename}  crypt enriched:\n" + "\n".join(crypt_fixes)
        )
    if section_fixes:
        console.print(
            f"[cyan]⚙[/cyan] {tournament.yaml_filename}  sections fixed:\n"
            + "\n".join(section_fixes)
        )

    if crypt_fixes or section_fixes:
        data["deck"] = deck_data
        return Tournament.model_validate(data)

    return tournament


def _validate_content(
    client: httpx.Client,
    tournament: Tournament,
    delay: float,
) -> list[str]:
    """Step 6: validate tournament content and return a list of error-type strings."""
    data = _to_serializable(tournament)

    calendar_date = None
    if tournament.event_url:
        try:
            calendar_date = fetch_event_date(client, tournament.event_url, delay=delay)
        except Exception as exc:
            logger.warning(
                "Could not fetch calendar date for %s: %s",
                tournament.event_url,
                exc,
            )

    errors = error_types(data, calendar_date=calendar_date)
    if errors:
        logger.debug(
            "Validation errors for %s: %s",
            tournament.yaml_filename,
            errors,
        )
    return errors


# ---------------------------------------------------------------------------
# CLI registration
# ---------------------------------------------------------------------------


def register(sub: SubParsersAction) -> None:
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


# ---------------------------------------------------------------------------
# Command runner
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    """Scrape the VEKN forum and export each TWD as a YAML file.

    Scraping workflow per tournament:
      1. Scrape forum data (fetch thread HTML).
      2. Parse data (extract Tournament from post text).
      3. Check event calendar for the winner's name.
      4. Look up the winner in the VEKN player registry.
      5. Validate card information with the krcg library.
      6. Validate content and route file to the appropriate destination.
    """
    setup_logging(args.verbose)

    max_pages: int | None = None
    if args.last_page is not None:
        max_pages = args.last_page - args.start_page + 1

    changes_required_dir = args.output_dir / "changes_required"

    written = skipped = failed = overwrite_skipped = 0

    with httpx.Client(headers=HEADERS, timeout=60.0) as client:
        # Steps 1-2: scrape forum data and parse it into Tournament objects
        for tournament, icon in scrape_forum(
            client,
            max_pages=max_pages,
            start_page=args.start_page,
            delay=args.delay,
        ):
            if not tournament.event_id:
                console.print(
                    f"[yellow]─[/yellow] {tournament.name!r}  [dim](no event_id — skipped)[/dim]"
                )
                skipped += 1
                continue

            # Step 3: check event calendar for the winner's name
            tournament, calendar_winner_missing = _check_calendar_winner(
                client, tournament, args.delay
            )

            # Step 4: look up winner in VEKN player registry
            tournament = _lookup_player(client, tournament, args.delay)

            # Step 5: validate card information with krcg
            tournament = _enrich_with_krcg(tournament)

            # Step 6: validate content
            errors = _validate_content(client, tournament, args.delay)
            if calendar_winner_missing:
                errors.append("unconfirmed_winner")

            # Route file to the appropriate destination
            if errors:
                error_dir = args.output_dir / "errors" / errors[0]
                error_dir.mkdir(parents=True, exist_ok=True)
                path = error_dir / tournament.yaml_filename
                try:
                    path.write_text(tournament_to_yaml_str(tournament), encoding="utf-8")
                    console.print(
                        f"[red]⚠[/red] {path.name}  {tournament.name}"
                        f"  [dim](errors: {', '.join(errors)})[/dim]"
                    )
                    written += 1
                except Exception as exc:
                    console.print(f"[red]✗[/red] {tournament.event_id}: {exc}")
                    logger.debug("Stack trace:", exc_info=True)
                    failed += 1
            elif icon == ICON_MERGED:
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
