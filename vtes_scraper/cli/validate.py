"""CLI subcommand: validate.

Loads every YAML file under <output-dir> (excluding errors/), runs it through
the validator, and moves failing files to <output-dir>/errors/<error_type>/.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import shutil
import unicodedata
from datetime import date
from pathlib import Path

import httpx
from ruamel.yaml import YAML, CommentedMap

from vtes_scraper.cli._common import console, setup_logging
from vtes_scraper.scraper import (
    DEFAULT_DELAY_SECONDS,
    HEADERS,
    fetch_event_date,
    fetch_player,
)
from vtes_scraper.validator import error_types


def _load_yaml(path: Path) -> CommentedMap:
    yaml = YAML()
    return yaml.load(path.read_text(encoding="utf-8"))


def _save_yaml(path: Path, data: CommentedMap) -> None:
    """Write *data* back to *path* preserving ruamel.yaml formatting."""
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    yaml.width = 120
    buf = io.StringIO()
    yaml.dump(data, buf)
    path.write_text(buf.getvalue(), encoding="utf-8")


_COERCIONS_FILENAME = "coercions.json"
"""
JSON file that permanently records every raw-winner → canonical-winner mapping
discovered during --check-players runs.  Stored as::

    {
        "<raw name from YAML>": {"winner": "<canonical name>", "vekn_number": <id>},
        ...
    }

On subsequent validate runs the cache is consulted first so no HTTP request is
needed for already-resolved names.
"""


def _load_coercions(output_dir: Path) -> dict[str, dict[str, int | str]]:
    """Load the coercions cache from *output_dir*/coercions.json (empty dict if absent)."""
    path = output_dir / _COERCIONS_FILENAME
    if not path.exists():
        return {}
    try:
        raw: dict[str, dict[str, int | str]] = json.loads(
            path.read_text(encoding="utf-8")
        )
        # Migrate any legacy string vekn_number values to int.
        for entry in raw.values():
            if isinstance(entry.get("vekn_number"), str):
                entry["vekn_number"] = int(entry["vekn_number"])
        return raw
    except Exception:
        return {}


def _save_coercions(
    output_dir: Path, coercions: dict[str, dict[str, int | str]]
) -> None:
    """Persist *coercions* to *output_dir*/coercions.json (sorted keys, pretty-printed)."""
    path = output_dir / _COERCIONS_FILENAME
    path.write_text(
        json.dumps(coercions, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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


def _name_without_accents(name: str) -> str:
    """Return *name* with diacritics stripped and non-word, non-space characters removed."""
    # NFD decomposition splits accented chars into base + combining marks;
    # encoding to ASCII then drops the combining marks.
    ascii_name = (
        unicodedata.normalize("NFD", name).encode("ascii", "ignore").decode("ascii")
    )
    # Drop any remaining non-word, non-space chars (hyphens, apostrophes, etc.)
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", ascii_name)).strip()


def _check_player(
    client: httpx.Client,
    path: Path,
    data: CommentedMap,
    output_dir: Path,
    delay: float,
    logger: logging.Logger,
    coercions: dict[str, dict[str, int | str]] | None = None,
) -> tuple[bool, bool]:
    """
    Verify that the winner listed in *data* is a registered VEKN member.

    Returns ``(player_found, file_moved)`` booleans:
    - ``player_found``: True if the winner was identified in the VEKN database.
    - ``file_moved``: True if the file was moved to ``errors/unknown_winner/``.

    Side effects:
    - If found: writes ``vekn_number`` (and optionally corrected ``winner``)
      back into *data* and saves the file.  If *coercions* is provided the
      raw→canonical mapping is stored there (and the caller is responsible for
      persisting it with :func:`_save_coercions`).
    - If not found: moves the file to ``errors/unknown_winner/``.
    """
    raw_winner = str(data.get("winner") or "").strip()
    if not raw_winner:
        return False, False

    winner = raw_winner

    # Pre-normalization: strip "Winner:" label prefix if present.
    # The parser sometimes captures "Winner: Name" instead of just "Name".
    clean_winner_prefix = re.sub(r"^Winner\s*:\s*", "", winner, flags=re.IGNORECASE)
    if clean_winner_prefix and clean_winner_prefix != winner:
        winner = clean_winner_prefix

    def _coercions_get(candidate: str) -> tuple[str, int] | None:
        """Return ``(found_name, vekn_number)`` from cache if *candidate* is present."""
        if coercions is not None and candidate in coercions:
            entry = coercions[candidate]
            logger.debug(
                "Player resolved from coercions cache: %r (via %r) → %r (VEKN %s)",
                raw_winner,
                candidate,
                entry["winner"],
                entry["vekn_number"],
            )
            return str(entry["winner"]), int(entry["vekn_number"])
        return None

    def _apply_resolution(
        found_name: str, vekn_number: int, *, from_cache: bool = False
    ) -> tuple[bool, bool]:
        """Write *found_name* / *vekn_number* into *data*, update coercions, save file."""
        if coercions is not None:
            entry: dict[str, int | str] = {
                "winner": found_name,
                "vekn_number": vekn_number,
            }
            # Store both the raw name and the canonical name so that either can be
            # looked up at step 0 on a future run without any HTTP requests.
            coercions[raw_winner] = entry
            coercions[found_name] = entry
        if found_name != raw_winner:
            data["winner"] = found_name
            suffix = " (cached)" if from_cache else ""
            console.print(
                f"[yellow]~[/yellow] {path.name}  winner coerced{suffix}: "
                f"{raw_winner!r} → {found_name!r}  (VEKN {vekn_number})"
            )
        else:
            logger.debug("Player verified: %s  (VEKN %s)", found_name, vekn_number)
        keys = list(data.keys())
        pos = keys.index("winner") + 1 if "winner" in keys else len(keys)
        data.insert(pos, "vekn_number", vekn_number)
        _save_yaml(path, data)
        return True, False

    # Step 0: check the coercions cache with the exact raw name before any HTTP call.
    hit = _coercions_get(raw_winner)
    if hit is not None:
        return _apply_resolution(*hit, from_cache=True)

    # Step 1: search with the original winner name.
    result: tuple[str, int] | None = None
    try:
        result = fetch_player(client, winner, delay=delay)
    except Exception as exc:
        logger.warning("Could not check player for %s: %s", path.name, exc)
        return False, False

    if result is None:
        # Step 1b: retry with trailing unclosed brackets stripped.
        # Forum posts sometimes leave artefacts like "John Smith (" when a VP comment
        # such as "(3vp in final)" was split across lines by an HTML <br> tag.
        # winner is updated unconditionally so that steps 2 and 3 continue from the
        # cleaner form even when this step's HTTP call also fails (e.g. the canonical
        # VEKN name uses ASCII-only characters so the accented+bracket variant would
        # never match but the de-accented form without the bracket would).
        clean_bracket = re.sub(r"\s*[\(\[]+\s*$", "", winner)
        if clean_bracket and clean_bracket != winner:
            winner = clean_bracket
            hit = _coercions_get(winner)
            if hit is not None:
                return _apply_resolution(*hit, from_cache=True)
            try:
                result = fetch_player(client, winner, delay=delay)
            except Exception as exc:
                logger.warning(
                    "Could not check player (bracket-stripped) for %s: %s",
                    path.name,
                    exc,
                )
                result = None

    if result is None:
        # Step 2: retry with digits stripped (handles "Frederic Pin 3200006" style names).
        clean_name = _name_without_digits(winner)
        if clean_name and clean_name != winner:
            hit = _coercions_get(clean_name)
            if hit is not None:
                return _apply_resolution(*hit, from_cache=True)
            try:
                result = fetch_player(client, clean_name, delay=delay)
            except Exception as exc:
                logger.warning(
                    "Could not check player (clean name) for %s: %s", path.name, exc
                )
                result = None

    if result is None:
        # Step 3: retry with accents and non-word characters stripped.
        ascii_name = _name_without_accents(winner)
        if ascii_name and ascii_name != winner:
            hit = _coercions_get(ascii_name)
            if hit is not None:
                return _apply_resolution(*hit, from_cache=True)
            try:
                result = fetch_player(client, ascii_name, delay=delay)
            except Exception as exc:
                logger.warning(
                    "Could not check player (ascii name) for %s: %s", path.name, exc
                )
                result = None

    if result is None:
        # Winner not found in VEKN database — move to errors/unknown_winner.
        dest = _move_to_error(path, output_dir, "unknown_winner")
        console.print(
            f"[red]✗[/red] {path.name}  [unknown_winner]  → {dest.relative_to(output_dir)}"
        )
        return False, True

    return _apply_resolution(*result)


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
        "--check-unknowns",
        action="store_true",
        dest="check_unknowns",
        help=(
            "Retry files previously quarantined in errors/unknown_winner/. "
            "When a file passes it is moved back to its canonical YYYY/MM/ location. "
            "Implies --check-players. "
            "Requires network access."
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
    check_unknowns: bool = getattr(args, "check_unknowns", False)
    check_players: bool = getattr(args, "check_players", False) or check_unknowns
    delay: float = getattr(args, "delay", DEFAULT_DELAY_SECONDS)

    if not output_dir.exists():
        console.print(f"[red]✗[/red] Output directory does not exist: {output_dir}")
        return 1

    # Collect all .yaml files, excluding the errors/ subtree
    errors_dir = output_dir / "errors"
    yaml_files = [
        p for p in output_dir.rglob("*.yaml") if not p.is_relative_to(errors_dir)
    ]
    unknown_winners_errors_dir = errors_dir / "unknown_winner"
    if check_unknowns:
        yaml_files.extend(
            unknown_winners_errors_dir.rglob("*.yaml")
            if unknown_winners_errors_dir.exists()
            else []
        )

    if not yaml_files:
        console.print(f"[yellow]No YAML files found in {output_dir}[/yellow]")
        return 0

    valid = moved = load_errors = 0

    # Load the persistent coercions cache once; it will be updated and saved
    # incrementally as new player lookups are resolved.
    coercions: dict[str, dict[str, int | str]] | None = None
    if check_players:
        coercions = _load_coercions(output_dir)

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
                prev_coercions_len = len(coercions) if coercions is not None else 0
                _found, file_moved = _check_player(
                    client, path, data, output_dir, delay, logger, coercions=coercions
                )
                # Persist the coercions file immediately after each new resolution.
                if coercions is not None and len(coercions) != prev_coercions_len:
                    _save_coercions(output_dir, coercions)
                if file_moved:
                    moved += 1
                    continue

            # If the file was previously quarantined in errors/unknown_winner/,
            # move it back to its canonical output_dir/YYYY/MM/ location now that
            # it has passed all checks.
            if path.is_relative_to(unknown_winners_errors_dir):
                date_start = data.get("date_start")
                if isinstance(date_start, date):
                    subdir = (
                        output_dir
                        / f"{date_start.year:04d}"
                        / f"{date_start.month:02d}"
                    )
                    subdir.mkdir(parents=True, exist_ok=True)
                    dest = subdir / path.name
                    shutil.move(str(path), dest)
                    console.print(
                        f"[green]↩[/green] {path.name}  recovered"
                        f" → {dest.relative_to(output_dir)}"
                    )
            logger.debug("OK  %s", path.name)
            valid += 1

    console.rule()
    console.print(
        f"Done — [green]{valid} valid[/green], "
        f"[red]{moved} moved to errors[/red]"
        + (f", [yellow]{load_errors} unreadable[/yellow]" if load_errors else "")
    )
    return 1 if (moved or load_errors) else 0
