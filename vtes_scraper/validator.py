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

Deck count consistency
  crypt_count_mismatch          : deck.crypt_count != sum of each crypt card count
  library_section_count_mismatch: a library section count != sum of its card counts
  library_count_mismatch        : deck.library_count != sum of all section counts

Player count
  too_few_players : players_count is present but below the minimum of 12

Date coherence (requires a calendar_date from the VEKN event calendar)
  incoherent_date : date_start in the file does not match the official date

Player identity (requires network; --check-players flag)
  unknown_winner  : winner name not found in the VEKN member database

When multiple errors are present the first one (in the order listed above)
determines the error directory used by the CLI validate command.
"""

import logging
from datetime import date
from typing import cast

from vtes_scraper._krcg_helper import (
    TYPE_ORDER,
    get_all_vamp_variants,
    get_library_card_type,
)
from vtes_scraper.models import Crypt_Card_Dict, Deck_Dict

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# krcg card-section validation helpers
# ---------------------------------------------------------------------------


def _pick_best_crypt_version(
    versions: list[Crypt_Card_Dict], reference_groups: set[int]
) -> Crypt_Card_Dict:
    """
    Pick the grouping version that best fits the established group range.

    Grouping rule: all non-ANY groups must form a set of at most 2 consecutive integers.
    Priority:
      1. Version whose group is already present in *reference_groups* (exact match).
      2. Version whose group extends *reference_groups* to at most 2 consecutive ints.
      3. First integer-grouped version found (fallback).
    """
    int_versions = [v for v in versions if isinstance(v["grouping"], int)]
    if not int_versions:
        return versions[0]

    if reference_groups:
        # Priority 1: group already in the established range
        for v in int_versions:
            if v["grouping"] in reference_groups:
                return v

        # Priority 2: group extends the range by exactly one consecutive integer
        for v in int_versions:
            g = v["grouping"]
            candidate = reference_groups | {g}
            c_sorted = sorted(candidate)
            if len(c_sorted) <= 2 and c_sorted[-1] - c_sorted[0] <= 1:
                return v

    # Fallback: first integer-grouped version
    return int_versions[0]


def enrich_crypt_cards(deck: Deck_Dict) -> list[str]:
    """
    Enrich crypt card data using krcg card database.

    For each crypt card, look it up in krcg by name and update ``capacity``,
    ``disciplines``, ``title``, ``clan``, and ``grouping`` from the database.
    ``count`` and ``name`` are always preserved from the scraped data.
    Cards not found in krcg are left unchanged.

    When a vampire exists in multiple groupings, the version whose group fits
    the grouping rules of the rest of the crypt is used (two consecutive
    integers at most, e.g. G5-G6).  If no version fits, the first one found
    is used.

    ADV and non-ADV versions are never mixed: a scraped ``"Xaviar"`` will
    never be enriched with ``"Xaviar (ADV)"`` data, and vice versa.

    Mutates *deck* in-place.  Returns a list of human-readable descriptions
    of the changes made (empty when no changes were needed or krcg is
    unavailable).
    """
    crypt_raw = deck.get("crypt")
    if not isinstance(crypt_raw, list) or not crypt_raw:
        return []
    crypt = cast(list[Crypt_Card_Dict], crypt_raw)

    # Step 1: resolve all krcg versions for each card
    all_versions: list[list[Crypt_Card_Dict]] = []
    for card in crypt:
        card_name = str(card.get("name") or "")
        all_versions.append(get_all_vamp_variants(card_name))

    # Step 2: establish the group range from cards with exactly one version
    fixed_groups: set[int] = set()
    for versions in all_versions:
        if len(versions) == 1:
            g = versions[0]["grouping"]
            if isinstance(g, int):
                fixed_groups.add(g)

    # Step 3: enrich each card using the best matching version
    fixes: list[str] = []
    for card, versions in zip(crypt, all_versions):
        if not versions:
            continue

        best = (
            _pick_best_crypt_version(versions, fixed_groups)
            if len(versions) > 1
            else versions[0]
        )

        changed: list[str] = []
        for field, new_value in best.items():
            old_value = card.get(field)
            if old_value != new_value:
                card[field] = new_value
                changed.append(f"{field}: {old_value!r} → {new_value!r}")
        if changed:
            fixes.append(f"  {card.get('name', '')!r}: " + ", ".join(changed))

    return fixes


def fix_card_sections(deck: Deck_Dict) -> list[str]:
    """
    Validate and fix library card sections using krcg card type data.

    For each library card, look it up in krcg and check whether it is in the
    correct section (section name == ``"/".join(sorted(card.types))``).
    Misassigned cards are moved to the correct section; cards that krcg cannot
    identify are left in their current section.

    Mutates *deck* in-place — ``library_sections`` is replaced with a rebuilt
    list when corrections are needed, and ``library_count`` is kept consistent.

    Returns a list of human-readable fix descriptions (empty when no changes
    were made or when krcg is unavailable).
    """
    library_sections = deck.get("library_sections") or []
    if not library_sections:
        return []

    # --- Pass 1: detect misassigned cards ---
    all_cards: list[tuple[str, dict]] = []  # (expected_section, card_dict)
    fixes: list[str] = []
    any_moved = False

    for section in library_sections:
        section_name = str(section.get("name") or "")
        for card in list(section.get("cards") or []):
            card_name = str(card.get("name") or "")
            expected = get_library_card_type(card_name)
            if expected is None or expected == section_name:
                all_cards.append((section_name, card))
            else:
                fixes.append(
                    f"  {card_name!r}: {section_name!r} → {expected!r}"
                )
                all_cards.append((expected, card))
                any_moved = True

    if not any_moved:
        return []

    # --- Pass 2: rebuild sections in TYPE_ORDER ---
    type_order: list[str] = TYPE_ORDER

    def _order(name: str) -> int:
        try:
            return type_order.index(name)
        except ValueError:
            return len(type_order)

    sections_map: dict[str, list[dict]] = {}
    for section_name, card in all_cards:
        sections_map.setdefault(section_name, []).append(card)

    new_sections = []
    for section_name in sorted(sections_map, key=_order):
        cards = sections_map[section_name]
        count = sum(int(c.get("count", 0)) for c in cards)
        new_sections.append(
            {"name": section_name, "count": count, "cards": cards}
        )

    deck["library_sections"] = new_sections
    if "library_count" in deck:
        deck["library_count"] = sum(s["count"] for s in new_sections)

    return fixes


def parse_date_field(raw: date | None) -> date | None:
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
            if isinstance(card, dict)
            and card.get("grouping") not in (None, "ANY")
        }
        if len(groupings) > 2 or (
            len(groupings) == 2 and max(groupings) - min(groupings) != 1
        ):
            errors.append("illegal_crypt")
    if not deck.get("library_sections"):
        errors.append("empty_library")

    # --- Deck count consistency ---
    if deck:
        crypt = deck.get("crypt") or []
        if crypt and deck.get("crypt_count") is not None:
            expected_crypt = sum(
                card.get("count", 0) for card in crypt if isinstance(card, dict)
            )
            if deck["crypt_count"] != expected_crypt:
                errors.append("crypt_count_mismatch")

        library_sections = deck.get("library_sections") or []
        for section in library_sections:
            if not isinstance(section, dict):
                continue
            section_cards = section.get("cards") or []
            if section.get("count") is not None and section_cards:
                expected_section = sum(
                    card.get("count", 0)
                    for card in section_cards
                    if isinstance(card, dict)
                )
                if section["count"] != expected_section:
                    errors.append("library_section_count_mismatch")
                    break  # one occurrence is enough

        if library_sections and deck.get("library_count") is not None:
            expected_library = sum(
                section.get("count", 0)
                for section in library_sections
                if isinstance(section, dict)
            )
            if deck["library_count"] != expected_library:
                errors.append("library_count_mismatch")

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
