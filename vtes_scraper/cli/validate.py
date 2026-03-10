"""CLI subcommand: validate.

Loads every YAML file under <output-dir> (excluding errors/), runs it through
the validator, and moves failing files to <output-dir>/errors/<error_type>/.
"""

from __future__ import annotations

import argparse
import logging
import shutil
from datetime import date
from pathlib import Path

import httpx
from ruamel.yaml import YAML

from vtes_scraper.cli._common import console, setup_logging
from vtes_scraper.scraper import DEFAULT_DELAY_SECONDS, HEADERS, fetch_event_date
from vtes_scraper.validator import error_types


def _load_yaml(path: Path) -> dict:
    yaml = YAML()
    return yaml.load(path.read_text(encoding="utf-8"))


def _move_to_error(path: Path, output_dir: Path, error_type: str) -> Path:
    """Move *path* to <output_dir>/errors/<error_type>/<filename> and return the new path."""
    dest_dir = output_dir / "errors" / error_type
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    shutil.move(str(path), dest)
    return dest


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
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=(
            "Seconds between HTTP requests when --check-dates is active "
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
            if not errs:
                logger.debug("OK  %s", path.name)
                valid += 1
                continue

            # Use the first (most critical) error as the directory name; move once.
            first_error = errs[0]
            dest = _move_to_error(path, output_dir, first_error)
            label = ", ".join(errs)
            console.print(
                f"[red]✗[/red] {path.name}  [{label}]  → {dest.relative_to(output_dir)}"
            )
            moved += 1

    console.rule()
    console.print(
        f"Done — [green]{valid} valid[/green], "
        f"[red]{moved} moved to errors[/red]"
        + (f", [yellow]{load_errors} unreadable[/yellow]" if load_errors else "")
    )
    return 1 if (moved or load_errors) else 0
