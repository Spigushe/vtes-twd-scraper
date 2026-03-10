"""Pure validation logic for VTES TWD YAML files.

Each function here operates on plain dicts (as loaded from YAML) and returns
structured results — no I/O, no CLI concerns.

Error types
-----------
Mandatory tournament fields
  missing_name           : top-level name is absent or blank
  missing_location       : top-level location is absent or blank
  missing_date_start     : top-level date_start is absent
  missing_rounds_format  : top-level rounds_format is absent or blank
  missing_players_count  : top-level players_count is absent or zero
  missing_winner         : top-level winner is absent or blank
  missing_event_url      : top-level event_url is absent or blank
  limited_format         : tournament name contains "Limited" (draft/limited event)

Mandatory deck fields
  empty_crypt    : deck.crypt list is empty (no vampire cards found)
  illegal_crypt  : crypt groupings are not a pair of consecutive integers
                   (cards with grouping==ANY are ignored in this check)
  empty_library  : deck.library_sections list is empty (no library cards found)

Player count
  too_few_players : players_count is present but below the minimum of 12

Date coherence (requires a calendar_date from the VEKN event calendar)
  incoherent_date : date_start in the file does not match the official date

When multiple errors are present the first one (in the order listed above)
determines the error directory used by the CLI validate command.
"""

from __future__ import annotations

from datetime import date


def parse_date_field(raw) -> date | None:
    """Coerce whatever ruamel.yaml hands back for date_start into a date."""
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    from vtes_scraper.models import Tournament

    try:
        return Tournament.parse_date(str(raw))
    except ValueError:
        return None


def error_types(data: dict, calendar_date: date | None = None) -> list[str]:
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
    if "limited" in (data.get("name") or "").lower():
        errors.append("limited_format")

    # --- Mandatory deck fields ---
    deck = data.get("deck") or {}
    if not deck.get("crypt"):
        errors.append("empty_crypt")
    else:
        groupings = {
            card["grouping"]
            for card in deck["crypt"]
            if isinstance(card, dict) and card.get("grouping") not in (None, "ANY")
        }
        if len(groupings) > 2 or (
            len(groupings) == 2 and max(groupings) - min(groupings) != 1
        ):
            errors.append("illegal_crypt")
    if not deck.get("library_sections"):
        errors.append("empty_library")

    # --- Player count floor ---
    players_count = data.get("players_count") or 0
    if 0 < players_count < 12:
        errors.append("too_few_players")

    # --- Date coherence (only when calendar_date was fetched) ---
    if calendar_date is not None:
        file_date = parse_date_field(data.get("date_start"))
        if file_date is not None and file_date != calendar_date:
            errors.append("incoherent_date")

    return errors
