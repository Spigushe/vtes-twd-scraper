"""CLI subcommand: fix-date.

Coerces the ``date_start`` field of one or more YAML files to match the
official date published on the VEKN event calendar page referenced by each
file's ``event_url`` field.

Useful when the date recorded in a forum TWD post differs from the date
shown on the event calendar — e.g. the poster used the thread posting date
rather than the actual tournament date.

Example
-------
    vtes-scraper fix-date output/2026/01/12957.yaml
    vtes-scraper fix-date output/2026/01/*.yaml --dry-run
"""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

import httpx
from ruamel.yaml import YAML

from vtes_scraper.cli._common import console, setup_logging
from vtes_scraper.scraper import DEFAULT_DELAY_SECONDS, HEADERS, fetch_event_date


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "fix-date",
        help="Coerce date_start in YAML files to match the VEKN event calendar.",
    )
    p.add_argument(
        "files",
        nargs="+",
        type=Path,
        metavar="FILE",
        help="One or more YAML tournament files to update.",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=f"Seconds between HTTP requests (default: {DEFAULT_DELAY_SECONDS}).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Show what would change without writing any files.",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(func=run)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 120


def _load_yaml(path: Path) -> dict:
    return _yaml.load(path)


def _dump_yaml(data: dict, path: Path) -> None:
    with path.open("w", encoding="utf-8") as fh:
        _yaml.dump(data, fh)


def _current_date_start(data: dict) -> date | None:
    """Parse the date_start field from a raw YAML dict.

    ruamel.yaml may return the value as a ``datetime.date`` (if it looks like
    an ISO date), or as a plain string (if written in long-form).  We normalise
    both to a ``date`` object using the same validator the Tournament model uses.
    """
    from datetime import date as _date

    from vtes_scraper.models import Tournament

    raw = data.get("date_start")
    if raw is None:
        return None
    if isinstance(raw, _date):
        return raw
    # Use the Pydantic validator to handle all supported string formats
    return Tournament.parse_date(str(raw))


# ---------------------------------------------------------------------------
# Command runner
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    updated = unchanged = failed = 0

    with httpx.Client(headers=HEADERS, timeout=30.0) as client:
        for path in args.files:
            if not path.exists():
                console.print(f"[red]✗[/red] {path}: file not found")
                failed += 1
                continue

            try:
                data = _load_yaml(path)
            except Exception as exc:
                console.print(f"[red]✗[/red] {path.name}: failed to load YAML — {exc}")
                failed += 1
                continue

            event_url = data.get("event_url")
            if not event_url:
                console.print(f"[yellow]─[/yellow] {path.name}: no event_url, skipping")
                unchanged += 1
                continue

            current = _current_date_start(data)

            try:
                calendar_date = fetch_event_date(client, event_url, delay=args.delay)
            except Exception as exc:
                console.print(
                    f"[red]✗[/red] {path.name}: HTTP error fetching {event_url} — {exc}"
                )
                logger.debug("Stack trace:", exc_info=True)
                failed += 1
                continue

            if calendar_date is None:
                console.print(
                    f"[yellow]─[/yellow] {path.name}: could not parse date from {event_url}"
                )
                unchanged += 1
                continue

            if current == calendar_date:
                console.print(
                    f"[dim]·[/dim] {path.name}: date already correct ({calendar_date})"
                )
                unchanged += 1
                continue

            # Date differs — update the field
            iso = calendar_date.isoformat()
            old_str = str(data.get("date_start"))
            console.print(
                f"[green]✓[/green] {path.name}: "
                f"[red]{old_str}[/red] → [green]{iso}[/green]"
                + (" [dim](dry-run)[/dim]" if args.dry_run else "")
            )

            if not args.dry_run:
                data["date_start"] = iso
                try:
                    _dump_yaml(data, path)
                except Exception as exc:
                    console.print(f"[red]✗[/red] {path.name}: write failed — {exc}")
                    failed += 1
                    continue

            updated += 1

    console.rule()
    label = "would update" if args.dry_run else "updated"
    console.print(
        f"Done — [green]{updated} {label}[/green], "
        f"[dim]{unchanged} unchanged[/dim], "
        f"[red]{failed} failed[/red]"
    )
    return 1 if failed else 0
