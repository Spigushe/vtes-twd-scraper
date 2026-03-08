"""CLI subcommand: validate.

Checks that scraped YAML files contain all mandatory tournament and deck data.
Files that fail validation are moved to <output-dir>/errors/<error_type>/ for
manual review.

Mandatory tournament fields
---------------------------
missing_name           : top-level name is absent or blank
missing_location       : top-level location is absent or blank
missing_date_start     : top-level date_start is absent
missing_rounds_format  : top-level rounds_format is absent or blank
missing_players_count  : top-level players_count is absent or zero
missing_winner         : top-level winner is absent or blank
missing_event_url      : top-level event_url is absent or blank

Mandatory deck fields
---------------------
empty_crypt    : deck.crypt list is empty (no vampire cards found)
empty_library  : deck.library_sections list is empty (no library cards found)

When multiple errors are present the file is moved to the directory of the
first error encountered (in the order listed above) and all error labels are
shown in the console output.
"""

from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

from ruamel.yaml import YAML

from vtes_scraper.cli._common import console, setup_logging


def _load_yaml(path: Path) -> dict:
    yaml = YAML()
    return yaml.load(path.read_text(encoding="utf-8"))


def _error_types(data: dict) -> list[str]:
    """Return a list of validation error-type strings for one YAML file."""
    errors: list[str] = []

    # --- Mandatory tournament fields ---
    if not data.get("name"):
        errors.append("missing_name")
    if not data.get("location"):
        errors.append("missing_location")
    if data.get("date_start") is None:
        errors.append("missing_date_start")
    if not data.get("rounds_format"):
        errors.append("missing_rounds_format")
    if not data.get("players_count"):
        errors.append("missing_players_count")
    if not data.get("winner"):
        errors.append("missing_winner")
    if not data.get("event_url"):
        errors.append("missing_event_url")

    # --- Mandatory deck fields ---
    deck = data.get("deck") or {}
    if not deck.get("crypt"):
        errors.append("empty_crypt")
    if not deck.get("library_sections"):
        errors.append("empty_library")

    return errors


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
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    """Validate all YAML files under <output-dir> and move invalid ones to errors/."""
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    output_dir: Path = args.output_dir

    if not output_dir.exists():
        console.print(f"[red]✗[/red] Output directory does not exist: {output_dir}")
        return 1

    # Collect all .yaml files, excluding the errors/ subtree
    errors_dir = output_dir / "errors"
    yaml_files = [
        p
        for p in output_dir.rglob("*.yaml")
        if not p.is_relative_to(errors_dir)
    ]

    if not yaml_files:
        console.print(f"[yellow]No YAML files found in {output_dir}[/yellow]")
        return 0

    valid = moved = load_errors = 0

    for path in sorted(yaml_files):
        try:
            data = _load_yaml(path)
        except Exception as exc:
            console.print(f"[red]✗[/red] {path.name}: could not load YAML — {exc}")
            logger.debug("Stack trace:", exc_info=True)
            load_errors += 1
            continue

        errs = _error_types(data)
        if not errs:
            logger.debug("OK  %s", path.name)
            valid += 1
            continue

        # Use the first (most critical) error as the directory name; move once.
        error_type = errs[0]
        dest = _move_to_error(path, output_dir, error_type)
        label = ", ".join(errs)
        console.print(f"[red]✗[/red] {path.name}  [{label}]  → {dest.relative_to(output_dir)}")
        moved += 1

    console.rule()
    console.print(
        f"Done — [green]{valid} valid[/green], "
        f"[red]{moved} moved to errors[/red]"
        + (f", [yellow]{load_errors} unreadable[/yellow]" if load_errors else "")
    )
    return 1 if (moved or load_errors) else 0
