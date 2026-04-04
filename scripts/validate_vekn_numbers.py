#!/usr/bin/env python3
"""Validate that all published tournament YAML files have a vekn_number.

Scans all YAML files under twds/<year>/<month>/ (i.e. files NOT in the
``errors/`` or ``changes_required/`` directories) and checks that each one
contains a non-null ``vekn_number`` field.

For files missing a vekn_number, the script first attempts to rescrape the
VEKN event calendar page (via event_url) to retrieve the winner and their
VEKN number.  If the rescrape succeeds the file is updated in place.
Only if the rescrape fails is the file moved to ``twds/errors/unconfirmed_winner/``.

Usage:
    python scripts/validate_vekn_numbers.py [--twds-dir twds] [--dry-run]
"""

import argparse
import shutil
from pathlib import Path

import httpx
from ruamel.yaml import YAML

from vtes_scraper.scraper._http import DEFAULT_DELAY_SECONDS, HEADERS
from vtes_scraper.scraper._vekn import fetch_event_winner, fetch_player

SKIP_DIRS = {"errors", "changes_required"}


def _iter_published_yaml(twds_dir: Path):
    """Yield all YAML files that are NOT inside errors/ or changes_required/."""
    for yaml_file in sorted(twds_dir.rglob("*.yaml")):
        parts = yaml_file.relative_to(twds_dir).parts
        if parts and parts[0] in SKIP_DIRS:
            continue
        yield yaml_file


def _try_rescrape_vekn_number(
    client: httpx.Client,
    event_url: str,
    delay: float = DEFAULT_DELAY_SECONDS,
) -> int | None:
    """Try to fetch the winner's VEKN number from the event calendar page.

    Returns the VEKN number as an int, or None if it cannot be determined.
    """
    winner_name = fetch_event_winner(client, event_url, delay)
    if not winner_name:
        return None
    result = fetch_player(client, winner_name, delay)
    if result is None:
        return None
    _, vekn_number = result
    return vekn_number


def validate(twds_dir: Path, *, dry_run: bool = False) -> list[Path]:
    """Return list of files that were (or would be) moved."""
    yaml = YAML()
    dest_dir = twds_dir / "errors" / "unconfirmed_winner"

    moved: list[Path] = []
    with httpx.Client(headers=HEADERS, follow_redirects=True) as client:
        for path in _iter_published_yaml(twds_dir):
            with open(path, encoding="utf-8") as fh:
                data = yaml.load(fh)

            if not isinstance(data, dict):
                continue

            if data.get("vekn_number") is not None:
                continue

            # vekn_number is missing or None — try rescraping the calendar first
            event_id = data.get("event_id", path.stem)
            event_url = data.get("event_url", "")

            vekn_number: int | None = None
            if event_url and not dry_run:
                print(f"rescraping calendar for event {event_id} ({event_url}) ...")
                try:
                    vekn_number = _try_rescrape_vekn_number(client, event_url)
                except Exception as exc:
                    print(f"  rescrape error: {exc}")

            if vekn_number is not None:
                data["vekn_number"] = vekn_number
                with open(path, "w", encoding="utf-8") as fh:
                    yaml.dump(data, fh)
                print(f"updated {path} with vekn_number={vekn_number} (event {event_id})")
                continue

            # Rescrape failed (or dry-run) — move the file
            if dry_run:
                rescrape_note = " (rescrape would be attempted first)" if event_url else ""
                print(
                    f"[dry-run] would move {path} -> errors/unconfirmed_winner/{path.name}"
                    f"{rescrape_note}"
                )
            else:
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / path.name
                shutil.move(str(path), str(dest))
                print(f"moved {path} -> errors/unconfirmed_winner/{path.name} (event {event_id})")
            moved.append(path)

    if not moved:
        print("All published files have a vekn_number. Nothing to move.")
    else:
        print(f"\n{len(moved)} file(s) {'would be' if dry_run else ''} moved.")

    return moved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--twds-dir",
        type=Path,
        default=Path("twds"),
        help="Root twds directory (default: twds)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report; do not move files.",
    )
    args = parser.parse_args()
    validate(args.twds_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
