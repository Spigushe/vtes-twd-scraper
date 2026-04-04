"""Pure validation logic for VTES TWD YAML files.

Each function here operates on plain dicts (as loaded from YAML) and returns
structured results — no I/O, no CLI concerns.

Error types
-----------
Mandatory tournament fields
  illegal_header     : any of name, location, date_start, rounds_format,
                       players_count, or event_url is absent or blank
  unconfirmed_winner : winner is absent/blank, or vekn_number is absent/None
  limited_format     : tournament name contains "Limited" (draft/limited event)

Mandatory deck fields
  illegal_crypt  : deck.crypt is empty, crypt groupings are not a pair of
                   consecutive integers, or deck.crypt_count != sum of card counts
                   (cards with grouping==ANY are ignored in the grouping check)
  illegal_library: deck.library_sections is empty, a section count != sum of
                   its card counts, or deck.library_count != sum of section counts

Player count
  too_few_players : players_count is present but below the minimum of 12

Date coherence (requires a calendar_date from the VEKN event calendar)
  incoherent_date : date_start in the file does not match the official date

When multiple errors are present the first one (in the order listed above)
determines the error directory used by the CLI validate command.
"""

import logging
from datetime import date
from typing import Any, cast

from vtes_scraper._krcg_helper import (
    TYPE_ORDER,
    get_all_vamp_variants,
    get_library_card_type,
)
from vtes_scraper.models import (
    Crypt_Card_Dict,
    Deck_Dict,
    Library_Card_Dict,
    Library_Section_Dict,
    Tournament_Dict,
)

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
    int_versions = [v for v in versions if isinstance(v.get("grouping"), int)]
    if not int_versions:
        return versions[0]

    if reference_groups:
        # Priority 1: group already in the established range
        for v in int_versions:
            g = v.get("grouping")
            if isinstance(g, int) and g in reference_groups:
                return v

        # Priority 2: group extends the range by exactly one consecutive integer
        for v in int_versions:
            g = v.get("grouping")
            if not isinstance(g, int):
                continue
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
    crypt = deck.get("crypt")
    if not isinstance(crypt, list) or not crypt:
        return []

    # Step 1: resolve all krcg versions for each card
    all_versions: list[list[Crypt_Card_Dict]] = []
    for card in crypt:
        card_name = str(card.get("name") or "")
        all_versions.append(get_all_vamp_variants(card_name))

    # Step 2: establish the group range from cards with exactly one version
    fixed_groups: set[int] = set()
    for versions in all_versions:
        if len(versions) == 1:
            g = versions[0].get("grouping")
            if isinstance(g, int):
                fixed_groups.add(g)

    # Step 3: enrich each card using the best matching version
    fixes: list[str] = []
    for card, versions in zip(crypt, all_versions):
        if not versions:
            continue

        best = (
            _pick_best_crypt_version(versions, fixed_groups) if len(versions) > 1 else versions[0]
        )

        changed: list[str] = []
        best_plain = cast(dict[str, Any], best)
        card_plain = cast(dict[str, Any], card)
        for field, new_value in best_plain.items():
            old_value = card_plain.get(field)
            if old_value != new_value:
                card_plain[field] = new_value
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
    library_sections = deck.get("library_sections")
    if not isinstance(library_sections, list) or not library_sections:
        return []

    # --- Pass 1: detect misassigned cards ---
    all_cards: list[tuple[str, Library_Card_Dict]] = []
    fixes: list[str] = []
    any_moved = False

    for section in library_sections:
        section_name = str(section.get("name") or "")
        cards_in_section = section.get("cards") or []
        for card in cards_in_section:
            card_name = str(card.get("name") or "")
            expected = get_library_card_type(card_name)
            if expected is None or expected == section_name:
                all_cards.append((section_name, card))
            else:
                fixes.append(f"  {card_name!r}: {section_name!r} → {expected!r}")
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

    sections_map: dict[str, list[Library_Card_Dict]] = {}
    for section_name, card in all_cards:
        sections_map.setdefault(section_name, []).append(card)

    new_sections: list[Library_Section_Dict] = []
    for section_name in sorted(sections_map, key=_order):
        cards = sections_map[section_name]
        count = sum([c.get("count", 0) for c in cards])
        entry = cast(
            Library_Section_Dict,
            {
                "name": section_name,
                "count": count,
                "cards": cards,
            },
        )
        new_sections.append(entry)

    deck["library_sections"] = new_sections
    if "library_count" in deck:
        deck["library_count"] = sum([s.get("count", 0) for s in new_sections])

    return fixes


def parse_date_field(raw: date | str | None) -> date | None:
    """Coerce whatever ruamel.yaml hands back for date_start into a date."""
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    from vtes_scraper.models import Tournament

    try:
        return Tournament.parse_date(raw)
    except ValueError:
        return None


def error_types(data: Tournament_Dict, calendar_date: date | None = None) -> list[str]:
    """Return a list of validation error-type strings for one YAML file."""
    errors: list[str] = []

    # --- Mandatory tournament fields ---
    if (
        not data.get("name")
        or not data.get("location")
        or data.get("date_start") is None
        or not data.get("rounds_format")
        or not data.get("players_count")
        or not data.get("event_url")
        or not data.get("forum_post_url")
    ):
        errors.append("illegal_header")
    if not data.get("winner") or not data.get("vekn_number"):
        errors.append("unconfirmed_winner")
    name_val: str = data.get("name") or ""
    if "limited" in name_val.lower():
        errors.append("limited_format")

    # --- Mandatory deck fields ---
    deck_raw: Any = data.get("deck") or {}
    deck = cast(Deck_Dict, deck_raw)
    crypt_list_raw = deck.get("crypt")
    crypt_list = cast(list[Library_Card_Dict], crypt_list_raw)
    illegal_crypt = False
    if not crypt_list:
        illegal_crypt = True
    else:
        groupings: set[int] = set()
        for card in crypt_list:
            g = card.get("grouping")
            if isinstance(g, int):
                groupings.add(g)
        if len(groupings) > 2 or (len(groupings) == 2 and max(groupings) - min(groupings) != 1):
            illegal_crypt = True
        crypt_count = deck.get("crypt_count")
        if crypt_count is not None:
            expected_crypt = sum([card.get("count", 0) for card in crypt_list])
            if crypt_count != expected_crypt:
                illegal_crypt = True
    if illegal_crypt:
        errors.append("illegal_crypt")
    if not deck.get("library_sections"):
        errors.append("illegal_library")

    # --- Deck count consistency ---
    illegal_library = False
    if deck_raw:
        lib_sections = deck.get("library_sections") or []
        for section in lib_sections:
            section_cards = section.get("cards") or []
            section_count = section.get("count")
            if section_count is not None and section_cards:
                expected_section = sum([card.get("count", 0) for card in section_cards])
                if section_count != expected_section:
                    illegal_library = True
                    break  # one occurrence is enough

        library_count = deck.get("library_count")
        if lib_sections and library_count is not None:
            expected_library = sum([section.get("count", 0) for section in lib_sections])
            if library_count != expected_library:
                illegal_library = True
    if illegal_library:
        errors.append("illegal_library")

    # --- Player count floor ---
    players_count: int = data.get("players_count") or 0
    if 0 < players_count < 12:
        errors.append("too_few_players")

    # --- Date coherence (only when calendar_date was fetched) ---
    if calendar_date is not None:
        file_date = parse_date_field(data.get("date_start"))
        if file_date is not None and file_date != calendar_date:
            errors.append("incoherent_date")

    return errors
