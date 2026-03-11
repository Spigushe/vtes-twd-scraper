"""CLI subcommand: validate.

Loads every YAML file under <output-dir> (excluding errors/), runs it through
the validator, and moves failing files to <output-dir>/errors/<error_type>/.
"""

from __future__ import annotations

import argparse
import io
import logging
import re
import shutil
from datetime import date
from pathlib import Path

import httpx
from ruamel.yaml import YAML

from vtes_scraper.cli._common import console, setup_logging
from vtes_scraper.scraper import DEFAULT_DELAY_SECONDS, HEADERS, fetch_event_date, fetch_player
from vtes_scraper.validator import error_types


def _load_yaml(path: Path) -> dict:
    yaml = YAML()
    return yaml.load(path.read_text(encoding="utf-8"))


def _save_yaml(path: Path, data: dict) -> None:
    """Write *data* back to *path* preserving ruamel.yaml formatting."""
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    yaml.width = 120
    buf = io.StringIO()
    yaml.dump(data, buf)
    path.write_text(buf.getvalue(), encoding="utf-8")


def _move_to_error(path: Path, output_dir: Path, error_type: str) -> Path:
    """Move *path* to <output_dir>/errors/<error_type>/<filename> and return the new path."""
    dest_dir = output_dir / "errors" / error_type
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    shutil.move(str(path), dest)
    return dest


def _name_without_digits(name: str) -> str:
    """Return *name* with digit sequences stripped and extra whitespace collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"\d+", "", name)).strip()


def _check_player(
    client: httpx.Client,
    path: Path,
    data: dict,
    output_dir: Path,
    delay: float,
    logger: logging.Logger,
) -> tuple[bool, bool]:
    """
    Verify that the winner listed in *data* is a registered VEKN member.

    Returns ``(player_found, file_moved)`` booleans:
    - ``player_found``: True if the winner was identified in the VEKN database.
    - ``file_moved``: True if the file was moved to ``errors/unknown_winner/``.

    Side effects:
    - If found: writes ``vekn_number`` (and optionally corrected ``winner``)
      back into *data* and saves the file.
    - If not found: moves the file to ``errors/unknown_winner/``.
    """
    winner = str(data.get("winner") or "").strip()
    if not winner:
        return False, False

    # Step 1: search with the original winner name.
    try:
        result = fetch_player(client, winner, delay=delay)
    except Exception as exc:
        logger.warning("Could not check player for %s: %s", path.name, exc)
        return False, False

    if result is None:
        # Step 2: retry with digits stripped (handles "Frederic Pin 3200006" style names).
        clean_name = _name_without_digits(winner)
        if clean_name and clean_name != winner:
            try:
                result = fetch_player(client, clean_name, delay=delay)
            except Exception as exc:
                logger.warning(
                    "Could not check player (clean name) for %s: %s", path.name, exc
                )
                result = None

    if result is None:
        # Winner not found in VEKN database — move to errors/unknown_winner.
        dest = _move_to_error(path, output_dir, "unknown_winner")
        console.print(
            f"[red]✗[/red] {path.name}  [unknown_winner]  → {dest.relative_to(output_dir)}"
        )
        return False, True

    found_name, vekn_number = result

    # Update the YAML data in-place and save.
    if found_name != winner:
        data["winner"] = found_name
        console.print(
            f"[yellow]~[/yellow] {path.name}  winner coerced: "
            f"{winner!r} → {found_name!r}  (VEKN {vekn_number})"
        )
    else:
        logger.debug("Player verified: %s  (VEKN %s)", winner, vekn_number)

    data["vekn_number"] = vekn_number
    _save_yaml(path, data)
    return True, False


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "validate",
        help="Check scraped YAML files for mandatory tournament and deck data.",
    )
    p.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("twds"),
        dest="output_dir",
        help="Root directory that was used by the scrape command. (default: twds)",
    )
    p.add_argument(
        "--check-dates",
        action="store_true",
        dest="check_dates",
        help=(
            "Fetch each file's event_url from the VEKN calendar and flag files "
            "whose date_start disagrees with the official date (incoherent_date). "
            "Requires network access; implies one extra HTTP request per file."
        ),
    )
    p.add_argument(
        "--check-players",
        action="store_true",
        dest="check_players",
        help=(
            "Look up each winner in the VEKN member database. "
            "When the winner is found their VEKN number is written to the file; "
            "when not found the file is moved to errors/unknown_winner. "
            "Only files that are missing a vekn_number are checked. "
            "Requires network access; implies one or two extra HTTP requests per file."
        ),
    )
    p.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=(
            "Seconds between HTTP requests when --check-dates or --check-players is active "
            + f"(default: {DEFAULT_DELAY_SECONDS})."
        ),
    )
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    """Validate all YAML files under <output-dir> and move invalid ones to errors/."""
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    output_dir: Path = args.output_dir
    check_dates: bool = getattr(args, "check_dates", False)
    check_players: bool = getattr(args, "check_players", False)
    delay: float = getattr(args, "delay", DEFAULT_DELAY_SECONDS)

    if not output_dir.exists():
        console.print(f"[red]✗[/red] Output directory does not exist: {output_dir}")
        return 1

    # Collect all .yaml files, excluding the errors/ subtree
    errors_dir = output_dir / "errors"
    yaml_files = [
        p for p in output_dir.rglob("*.yaml") if not p.is_relative_to(errors_dir)
    ]

    if not yaml_files:
        console.print(f"[yellow]No YAML files found in {output_dir}[/yellow]")
        return 0

    valid = moved = load_errors = 0

    with httpx.Client(headers=HEADERS, timeout=30.0) as client:
        for path in sorted(yaml_files):
            try:
                data = _load_yaml(path)
            except Exception as exc:
                console.print(f"[red]✗[/red] {path.name}: could not load YAML — {exc}")
                logger.debug("Stack trace:", exc_info=True)
                load_errors += 1
                continue

            # Optionally fetch the official date from the VEKN event calendar.
            calendar_date: date | None = None
            if check_dates:
                event_url = data.get("event_url")
                if event_url:
                    try:
                        calendar_date = fetch_event_date(client, event_url, delay=delay)
                    except Exception as exc:
                        logger.warning(
                            "Could not fetch calendar date for %s: %s", path.name, exc
                        )

            errs = error_types(data, calendar_date=calendar_date)
            if errs:
                # Use the first (most critical) error as the directory name; move once.
                first_error = errs[0]
                dest = _move_to_error(path, output_dir, first_error)
                label = ", ".join(errs)
                console.print(
                    f"[red]✗[/red] {path.name}  [{label}]  → {dest.relative_to(output_dir)}"
                )
                moved += 1
                continue

            # Optionally verify the winner against the VEKN member database.
            # Only check files that don't already have a vekn_number.
            if check_players and data.get("vekn_number") is None:
                _found, file_moved = _check_player(
                    client, path, data, output_dir, delay, logger
                )
                if file_moved:
                    moved += 1
                    continue

            logger.debug("OK  %s", path.name)
            valid += 1

    console.rule()
    console.print(
        f"Done — [green]{valid} valid[/green], "
        f"[red]{moved} moved to errors[/red]"
        + (f", [yellow]{load_errors} unreadable[/yellow]" if load_errors else "")
    )
    return 1 if (moved or load_errors) else 0

