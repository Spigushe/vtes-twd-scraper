import logging
from typing import Literal

from krcg.cards import Card
from krcg.config import TYPE_ORDER as TYPE_ORDER

_logger = logging.getLogger(__name__)

_krcg_loaded: bool | None = None
_seen_cards: set[str | int] = set()
_cards_loaded: dict[str | int, Card | None] = {}


def _is_krcg_loaded() -> bool:
    """Check if the KRCG module is available."""
    global _krcg_loaded
    if _krcg_loaded is not None:
        return _krcg_loaded

    try:
        from krcg import vtes as _kv  # noqa: PLC0415

        _kv.VTES.load()
        _krcg_loaded = True
    except ImportError as exc:
        _logger.debug("krcg unavailable — card-section check skipped: %s", exc)
        _krcg_loaded = False
    return _krcg_loaded


def _krcg_card_search(card_name_or_id: str | int) -> Card | None:
    """Search for a card by name in KRCG's VTES database. Returns the card ID if found."""
    if not _is_krcg_loaded():
        return None

    from krcg import vtes as _kv  # noqa: PLC0415

    if card_name_or_id in _seen_cards:
        return _cards_loaded.get(card_name_or_id)

    card = _kv.VTES.get(card_name_or_id, None)
    _seen_cards.add(card_name_or_id)
    _cards_loaded[card_name_or_id] = card
    if not card:
        _logger.debug("Error searching for card '%s' in KRCG", card_name_or_id)

    return card


def get_all_vamp_variants(
    vamp_name: str,
) -> list[dict[str, str | int | Literal["ANY"] | None]]:
    """
    Return krcg data for all relevant grouping versions of a crypt card by name.

    When a vampire exists in multiple groupings (e.g. G5 and G6), each non-ADV
    version is returned as a separate dict (for a non-ADV lookup), or each ADV
    version (for an ADV lookup).  ADV and non-ADV are never mixed:

    - ``"Xaviar"``       → only base (non-ADV) Xaviar versions
    - ``"Xaviar (ADV)"`` → only ADV Xaviar versions

    Returns an empty list if the card is not found in krcg.

    Each returned dict contains:
    - ``capacity``    - blood capacity (int)
    - ``disciplines`` - space-separated discipline string, e.g. ``"PRO ani cel"``
    - ``title``       - title string or ``None``
    - ``clan``        - primary clan name string
    - ``grouping``    - group number (int) or ``"ANY"`` for group-independent cards
    """
    card = _krcg_card_search(vamp_name)
    if not card or not card.crypt:
        return []

    # Determine whether the scraped name is an ADV card. This is a heuristic but
    # should be reliable since the presence of "(ADV)" in the name is a strong
    # signal of the card's identity and krcg's data is consistent in this regard.
    want_adv: bool = "(ADV)" in vamp_name

    # Gather all variant IDs: the card itself plus all related grouping variants
    all_ids: set[int] = {card.id}
    all_ids.update(card.variants.values())

    try:
        result: list[dict[str, str | int | Literal["ANY"] | None]] = []
        for card_id in all_ids:
            try:
                card_from_id = _krcg_card_search(card_id)
            except KeyError:
                continue
            if not card_from_id:
                continue
            if not card_from_id.crypt:
                continue
            # Skip variants that don't match the ADV/non-ADV kind of the lookup
            if bool(card_from_id.adv) != want_adv:
                continue
            disciplines = " ".join(card_from_id.disciplines) if card_from_id.disciplines else ""
            clan = card_from_id.clans[0] if card_from_id.clans else ""
            raw_group = card_from_id.group
            if not raw_group:
                continue
            if raw_group == "ANY":
                grouping: int | str = "ANY"
            else:
                try:
                    grouping = int(raw_group)
                except TypeError, ValueError:
                    continue
            result.append(
                {
                    "capacity": card_from_id.capacity,
                    "disciplines": disciplines,
                    "title": card_from_id.title or None,
                    "clan": clan,
                    "grouping": grouping,
                }
            )

        return result
    except Exception:
        return []


def get_library_card_type(card_name: str) -> str | None:
    """
    Return the canonical section name for a library card according to krcg, or
    ``None`` if the card is not in the database.

    The section name is the card's types joined by ``"/"`` in alphabetical order,
    matching krcg's ``TYPE_ORDER`` convention (e.g. ``"Action/Combat"``).
    """
    card = _krcg_card_search(card_name)
    if not card:
        return None
    return "/".join(sorted(card.types))
