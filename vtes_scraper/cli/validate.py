"""CLI subcommand: validate.

Validates that all published tournament YAML files have a vekn_number.

Scans all YAML files under twds/<year>/<month>/ (i.e. files NOT in the
``errors/`` or ``changes_required/`` directories) and checks that each one
contains a non-null ``vekn_number`` field.

For files missing a vekn_number, the command first attempts to rescrape the
VEKN event calendar page (via event_url) to retrieve the winner and their
VEKN number.  If the rescrape succeeds the file is updated in place.
Only if the rescrape fails is the file moved to ``twds/errors/unconfirmed_winner/``.
"""

import argparse
import shutil
from pathlib import Path

import httpx

from vtes_scraper.cli._common import SubParsersAction, console
from vtes_scraper.scraper._http import DEFAULT_DELAY_SECONDS, HEADERS
from vtes_scraper.scraper._vekn import fetch_event_winner, fetch_player

SKIP_DIRS = {"errors", "changes_required"}


def register(sub: SubParsersAction) -> None:
    p = sub.add_parser(
        "validate",
        help="Validate VEKN numbers for all published tournament YAML files.",
        description=__doc__,
    )
    p.add_argument(
        "--twds-dir",
        type=Path,
        default=Path("twds"),
        help="Root twds directory (default: twds)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report; do not move or update files.",
    )
    p.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging.")
    p.set_defaults(func=run)


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


def run(args: argparse.Namespace) -> int:
    from ruamel.yaml import YAML

    yaml = YAML()
    twds_dir: Path = args.twds_dir
    dry_run: bool = args.dry_run
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

            event_id = data.get("event_id", path.stem)
            event_url = data.get("event_url", "")

            vekn_number: int | None = None
            if event_url and not dry_run:
                console.print(f"rescraping calendar for event {event_id} ({event_url}) ...")
                try:
                    vekn_number = _try_rescrape_vekn_number(client, event_url)
                except Exception as exc:
                    console.print(f"  rescrape error: {exc}")

            if vekn_number is not None:
                data["vekn_number"] = vekn_number
                with open(path, "w", encoding="utf-8") as fh:
                    yaml.dump(data, fh)
                console.print(f"[green]✓[/green] updated {path} with vekn_number={vekn_number}")
                continue

            if dry_run:
                rescrape_note = " (rescrape would be attempted first)" if event_url else ""
                console.print(
                    f"[yellow]─[/yellow] [dry-run] would move {path} -> "
                    f"errors/unconfirmed_winner/{path.name}{rescrape_note}"
                )
            else:
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / path.name
                shutil.move(str(path), str(dest))
                console.print(f"[red]✗[/red] moved {path} -> errors/unconfirmed_winner/{path.name}")
            moved.append(path)

    if not moved:
        console.print("[green]All published files have a vekn_number.[/green]")
    else:
        label = "would be moved" if dry_run else "moved"
        console.print(f"\n{len(moved)} file(s) {label}.")

    return 0
