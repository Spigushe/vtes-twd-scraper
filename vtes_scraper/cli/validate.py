"""CLI subcommand: validate.

Re-applies the full scraping validation pipeline to all published tournament
YAML files:

  1. Rescrape the forum post (forum_post_url) for fresh tournament data.
  2. Fetch the canonical winner name and VEKN number from the event calendar.
  3. Enrich crypt cards and fix library card sections via krcg.
  4. Fetch the official event date from the VEKN calendar for date-coherence.
  5. Run the full error_types() check (illegal_header, unconfirmed_winner,
     limited_format, illegal_crypt, illegal_library, too_few_players,
     incoherent_date).
  6. Move files that still have errors to twds/errors/<first_error>/.
     Files without errors that were modified in place are written back.

Scans all YAML files under twds/ except the ``changes_required/`` directory.
Files in ``errors/`` are also re-validated so that previously failing files can
be recovered when the underlying issue (e.g. missing calendar results) is fixed.
"""

import argparse
import shutil
from pathlib import Path
from typing import cast

import httpx

from vtes_scraper.cli._common import SubParsersAction, console
from vtes_scraper.models import Deck_Dict, Tournament, Tournament_Dict
from vtes_scraper.scraper._forum import extract_twd_from_thread
from vtes_scraper.scraper._http import DEFAULT_DELAY_SECONDS, HEADERS
from vtes_scraper.scraper._vekn import fetch_event_date, fetch_event_winner, fetch_player
from vtes_scraper.validator import enrich_crypt_cards, error_types, fix_card_sections

# Error dir is rechecked every time to see if errors have been fixed
# and can be removed; so we skip only tournaments flagged as "changes_required"
# to avoid moving them back and forth.
SKIP_DIRS = {"changes_required"}
_FAST_VALIDATION_YAML_FILES_NUMBER_THRESHOLD = 25

_TOURNAMENT_FIELD_ORDER = list(Tournament.model_fields.keys())


def _reorder_tournament_dict(data: Tournament_Dict) -> dict:
    """Return a new dict with keys ordered as per the Tournament model definition."""
    ordered: dict = {k: data[k] for k in _TOURNAMENT_FIELD_ORDER if k in data}
    for k in data:
        if k not in ordered:
            ordered[k] = data[k]
    return ordered


def register(sub: SubParsersAction) -> None:
    p = sub.add_parser(
        "validate",
        help="Re-validate all published tournament YAML files.",
        description=__doc__,
    )
    p.add_argument(
        "--full-validation",
        action="store_true",
        default=False,
        help="Perform a full validation of all tournaments (default: False).",
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


def _iter_published_yaml(twds_dir: Path, full_validation: bool):
    """Yield all YAML files that are NOT inside changes_required/."""
    for yaml_file in _filter_yaml_paths(twds_dir, full_validation):
        parts = yaml_file.relative_to(twds_dir).parts
        if parts and parts[0] in SKIP_DIRS:
            continue
        yield yaml_file


def _filter_yaml_paths(twds_dir: Path, full_validation: bool) -> list[Path]:
    yaml_files: list[Path] = sorted(list(twds_dir.rglob("*.yaml")), reverse=True)

    if not full_validation:
        skip_dirs_fast_validation = SKIP_DIRS.union({"errors"})
        yaml_files = [
            p
            for p in yaml_files
            if p.relative_to(twds_dir).parts[0] not in skip_dirs_fast_validation
        ]
        yaml_files = yaml_files[:_FAST_VALIDATION_YAML_FILES_NUMBER_THRESHOLD]

    return yaml_files


def _check_and_update_winner(
    client: httpx.Client,
    data: Tournament_Dict,
    event_url: str,
    delay: float = DEFAULT_DELAY_SECONDS,
) -> bool:
    """Mirror scraping steps 3+4: update winner and vekn_number from the VEKN calendar.

    Fetches the official winner from the event calendar page, then looks up
    their canonical name and VEKN number in the player registry.
    Mutates *data* in-place. Returns True if any field was changed.
    """
    dirty = False

    calendar_winner = fetch_event_winner(client, event_url, delay)
    if calendar_winner and calendar_winner != data.get("winner"):
        data["winner"] = calendar_winner  # type: ignore[assignment]
        dirty = True

    winner: str = data.get("winner") or ""
    if not winner:
        return dirty

    result = fetch_player(client, winner, delay)
    if result is None:
        return dirty

    canonical_name, vekn_number = result
    if canonical_name != data.get("winner"):
        data["winner"] = canonical_name  # type: ignore[assignment]
        dirty = True
    if vekn_number != data.get("vekn_number"):
        data["vekn_number"] = vekn_number  # type: ignore[assignment]
        dirty = True

    return dirty


def run(args: argparse.Namespace) -> int:
    from ruamel.yaml import YAML

    yaml = YAML()
    full_validation: bool = args.full_validation
    twds_dir: Path = args.twds_dir
    dry_run: bool = args.dry_run

    moved: list[Path] = []
    updated: list[Path] = []

    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=60.0) as client:
        for path in _iter_published_yaml(twds_dir, full_validation):
            with open(path, encoding="utf-8") as fh:
                data = cast(Tournament_Dict, yaml.load(fh))

            if not isinstance(data, dict):
                continue

            dirty = False

            # Step 1: rescrape the forum post for fresh tournament data
            forum_post_url: str = data.get("forum_post_url") or ""
            if forum_post_url and not dry_run:
                try:
                    fresh = extract_twd_from_thread(
                        client, forum_post_url, delay=DEFAULT_DELAY_SECONDS
                    )
                    if fresh is not None:
                        from vtes_scraper.cli.scrape import _to_serializable

                        fresh_data = cast(Tournament_Dict, _to_serializable(fresh))
                        # Preserve vekn_number — forum posts never contain it
                        preserved_vekn = data.get("vekn_number")
                        if preserved_vekn is not None:
                            fresh_data["vekn_number"] = preserved_vekn  # type: ignore[assignment]
                        data = fresh_data
                        dirty = True
                except Exception as exc:
                    console.print(f"  forum rescrape error for {path.name}: {exc}")

            # Step 2: check event calendar for canonical winner name + VEKN number
            event_url: str = data.get("event_url") or ""
            if event_url and not dry_run:
                try:
                    if _check_and_update_winner(client, data, event_url):
                        dirty = True
                except Exception as exc:
                    console.print(f"  calendar check error for {path.name}: {exc}")

            # Step 3: enrich crypt cards and fix library sections via krcg
            deck = cast(Deck_Dict, data.get("deck") or {})
            if deck:
                crypt_fixes = enrich_crypt_cards(deck)
                section_fixes = fix_card_sections(deck)
                if crypt_fixes:
                    console.print(
                        f"[cyan]⚙[/cyan] {path.name}  crypt enriched:\n" + "\n".join(crypt_fixes)
                    )
                    dirty = True
                if section_fixes:
                    console.print(
                        f"[cyan]⚙[/cyan] {path.name}  sections fixed:\n" + "\n".join(section_fixes)
                    )
                    dirty = True
                if dirty:
                    data["deck"] = deck  # type: ignore[assignment]

            # Step 4: fetch official event date for date-coherence check
            calendar_date = None
            if event_url and not dry_run:
                try:
                    calendar_date = fetch_event_date(client, event_url)
                except Exception as exc:
                    console.print(f"  calendar date error for {path.name}: {exc}")

            # Step 4: full validation
            errors = error_types(cast(Tournament_Dict, data), calendar_date=calendar_date)

            if not errors:
                if dirty and not dry_run:
                    with open(path, "w", encoding="utf-8") as fh:
                        yaml.dump(_reorder_tournament_dict(data), fh)
                    console.print(f"[green]✓[/green] updated {path.name}")
                    updated.append(path)
                continue

            # Step 5: move to errors/<first_error>/
            dest_dir = twds_dir / "errors" / errors[0]
            if dry_run:
                console.print(
                    f"[yellow]─[/yellow] [dry-run] would move {path.name} → "
                    f"errors/{errors[0]}/  [dim]({', '.join(errors)})[/dim]"
                )
            else:
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / path.name
                shutil.move(str(path), str(dest))
                console.print(
                    f"[red]✗[/red] {path.name} → errors/{errors[0]}/"
                    f"  [dim]({', '.join(errors)})[/dim]"
                )
            moved.append(path)

    if not moved and not updated:
        console.print("[green]All published files passed validation.[/green]")
    else:
        label = "would be moved" if dry_run else "moved"
        if moved:
            console.print(f"\n{len(moved)} file(s) {label}.")
        if updated:
            console.print(f"{len(updated)} file(s) updated in place.")

    return 0
