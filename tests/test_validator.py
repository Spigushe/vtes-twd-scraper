"""Tests for vtes_scraper.validator."""

from datetime import date
from unittest.mock import patch

from vtes_scraper.models import (
    Crypt_Card_Dict,
    Deck_Dict,
    Library_Card_Dict,
    Library_Section_Dict,
    Tournament_Dict,
)
from vtes_scraper.validator import (
    _pick_best_crypt_version,
    enrich_crypt_cards,
    error_types,
    fix_card_sections,
    parse_date_field,
)


def _deck(**kwargs) -> Deck_Dict:
    base = Deck_Dict(
        crypt_count=2,
        crypt=[
            Crypt_Card_Dict(
                count=2,
                name="Nathan Turner",
                capacity=4,
                disciplines="PRO ani",
                clan="Gangrel",
                grouping=6,
            ),
        ],
        library_count=1,
        library_sections=[
            Library_Section_Dict(
                name="Master",
                count=1,
                cards=[Library_Card_Dict(count=1, name="Blood Doll")],
            )
        ],
    )
    for k, v in kwargs.items():
        if k in Deck_Dict.__annotations__:
            base[k] = v
    return base


def _tournament(**kwargs) -> Tournament_Dict:
    base = Tournament_Dict(
        name="Test Event",
        location="Paris, France",
        date_start=date(2023, 3, 25),
        rounds_format="3R+F",
        players_count=15,
        winner="Jane Doe",
        vekn_number=1234567,
        event_url="https://www.vekn.net/event-calendar/event/9999",
        deck=_deck(**kwargs),
    )
    for k, v in kwargs.items():
        if k in Tournament_Dict.__annotations__:
            base[k] = v
    return base


# ---------------------------------------------------------------------------
# Mandatory field checks
# ---------------------------------------------------------------------------


class TestMandatoryFields:
    def test_valid_returns_no_errors(self):
        assert error_types(_tournament()) == []

    def test_missing_name(self):
        print(_tournament(name=""))
        assert "missing_name" in error_types(_tournament(name=""))

    def test_missing_location(self):
        assert "missing_location" in error_types(_tournament(location=None))

    def test_missing_date_start(self):
        assert "missing_date_start" in error_types(_tournament(date_start=None))

    def test_missing_rounds_format(self):
        assert "missing_rounds_format" in error_types(_tournament(rounds_format=""))

    def test_missing_players_count(self):
        assert "missing_players_count" in error_types(_tournament(players_count=0))

    def test_missing_winner(self):
        assert "missing_winner" in error_types(_tournament(winner=""))

    def test_missing_event_url(self):
        assert "missing_event_url" in error_types(_tournament(event_url=None))

    def test_limited_format(self):
        assert "limited_format" in error_types(_tournament(name="Limited Edition Cup"))


# ---------------------------------------------------------------------------
# Unconfirmed winner (missing vekn_number)
# ---------------------------------------------------------------------------


class TestUnconfirmedWinner:
    def test_missing_vekn_number_key(self):
        t = _tournament()
        del t["vekn_number"]
        assert "unconfirmed_winner" in error_types(t)

    def test_none_vekn_number(self):
        assert "unconfirmed_winner" in error_types(_tournament(vekn_number=None))

    def test_present_vekn_number(self):
        assert "unconfirmed_winner" not in error_types(_tournament(vekn_number=1234567))

    def test_priority_after_missing_winner(self):
        """missing_winner should come before unconfirmed_winner in errors list."""
        errors = error_types(_tournament(winner="", vekn_number=None))
        assert "missing_winner" in errors
        assert "unconfirmed_winner" in errors
        assert errors.index("missing_winner") < errors.index("unconfirmed_winner")


# ---------------------------------------------------------------------------
# Deck structure checks
# ---------------------------------------------------------------------------


class TestDeckChecks:
    def test_empty_crypt(self):
        deck = _deck(crypt=[])
        assert "empty_crypt" in error_types(_tournament(deck=deck))

    def test_illegal_crypt_non_consecutive(self):
        deck = _deck(
            crypt_count=3,
            crypt=[
                {
                    "count": 1,
                    "name": "A",
                    "capacity": 4,
                    "disciplines": "PRO",
                    "clan": "Gangrel",
                    "grouping": 4,
                },
                {
                    "count": 1,
                    "name": "B",
                    "capacity": 4,
                    "disciplines": "PRO",
                    "clan": "Gangrel",
                    "grouping": 6,
                },
                {
                    "count": 1,
                    "name": "C",
                    "capacity": 4,
                    "disciplines": "PRO",
                    "clan": "Gangrel",
                    "grouping": 8,
                },
            ],
        )
        assert "illegal_crypt" in error_types(_tournament(deck=deck))

    def test_empty_library(self):
        deck = _deck(library_sections=[])
        assert "empty_library" in error_types(_tournament(deck=deck))


# ---------------------------------------------------------------------------
# Count consistency checks
# ---------------------------------------------------------------------------


class TestCryptCountMismatch:
    def test_matching_count_no_error(self):
        # crypt_count=2, sum of counts=2
        assert "crypt_count_mismatch" not in error_types(_tournament())

    def test_crypt_count_too_high(self):
        deck = _deck(crypt_count=5)  # actual sum is 2
        assert "crypt_count_mismatch" in error_types(_tournament(deck=deck))

    def test_crypt_count_too_low(self):
        deck = _deck(crypt_count=1)  # actual sum is 2
        assert "crypt_count_mismatch" in error_types(_tournament(deck=deck))

    def test_no_crypt_count_field_skipped(self):
        deck = _deck()
        del deck["crypt_count"]
        assert "crypt_count_mismatch" not in error_types(_tournament(deck=deck))


class TestLibrarySectionCountMismatch:
    def test_matching_count_no_error(self):
        assert "library_section_count_mismatch" not in error_types(_tournament())

    def test_section_count_too_high(self):
        deck = _deck(
            library_sections=[
                {
                    "name": "Master",
                    "count": 5,  # actual card sum is 1
                    "cards": [{"count": 1, "name": "Blood Doll"}],
                }
            ]
        )
        assert "library_section_count_mismatch" in error_types(_tournament(deck=deck))

    def test_section_count_matches_sum(self):
        deck = _deck(
            library_count=3,
            library_sections=[
                {
                    "name": "Master",
                    "count": 3,
                    "cards": [
                        {"count": 2, "name": "Blood Doll"},
                        {"count": 1, "name": "Vessel"},
                    ],
                }
            ],
        )
        assert "library_section_count_mismatch" not in error_types(_tournament(deck=deck))


class TestLibraryCountMismatch:
    def test_matching_count_no_error(self):
        assert "library_count_mismatch" not in error_types(_tournament())

    def test_library_count_too_high(self):
        deck = _deck(library_count=10)  # sum of sections is 1
        assert "library_count_mismatch" in error_types(_tournament(deck=deck))

    def test_library_count_matches_section_sum(self):
        deck = _deck(
            library_count=3,
            library_sections=[
                {
                    "name": "Master",
                    "count": 2,
                    "cards": [
                        {"count": 2, "name": "Blood Doll"},
                    ],
                },
                {
                    "name": "Action",
                    "count": 1,
                    "cards": [{"count": 1, "name": "Govern the Unaligned"}],
                },
            ],
        )
        assert "library_count_mismatch" not in error_types(_tournament(deck=deck))

    def test_no_library_count_field_skipped(self):
        deck = _deck()
        del deck["library_count"]
        assert "library_count_mismatch" not in error_types(_tournament(deck=deck))


# ---------------------------------------------------------------------------
# Player count floor
# ---------------------------------------------------------------------------


class TestTooFewPlayers:
    def test_exactly_12_ok(self):
        assert "too_few_players" not in error_types(_tournament(players_count=12))

    def test_11_flagged(self):
        assert "too_few_players" in error_types(_tournament(players_count=11))

    def test_zero_not_flagged_as_too_few(self):
        # Zero triggers missing_players_count but NOT too_few_players
        assert "too_few_players" not in error_types(_tournament(players_count=0))


# ---------------------------------------------------------------------------
# Date coherence
# ---------------------------------------------------------------------------


class TestDateCoherence:
    def test_matching_date_no_error(self):
        data = _tournament(date_start="2023-03-25")
        assert "incoherent_date" not in error_types(data, calendar_date=date(2023, 3, 25))

    def test_mismatched_date_flagged(self):
        data = _tournament(date_start="2023-03-25")
        assert "incoherent_date" in error_types(data, calendar_date=date(2023, 4, 1))

    def test_no_calendar_date_skipped(self):
        data = _tournament(date_start="2023-03-25")
        assert "incoherent_date" not in error_types(data, calendar_date=None)


# ---------------------------------------------------------------------------
# parse_date_field helper
# ---------------------------------------------------------------------------


class TestParseDateField:
    def test_none_returns_none(self):
        assert parse_date_field(None) is None

    def test_date_passthrough(self):
        d = date(2023, 3, 25)
        assert parse_date_field(d) == d

    def test_iso_string(self):
        assert parse_date_field("2023-03-25") == date(2023, 3, 25)

    def test_invalid_string_returns_none(self):
        assert parse_date_field("not-a-date") is None


# ---------------------------------------------------------------------------
# fix_card_sections
# ---------------------------------------------------------------------------


def _make_deck_with_sections(sections) -> Deck_Dict:
    """Build a minimal deck dict with given library_sections."""
    total = sum(s["count"] for s in sections)
    return Deck_Dict(
        library_count=total,
        library_sections=sections,
    )


def _section(name, cards) -> Library_Section_Dict:
    count = sum(c["count"] for c in cards)
    return Library_Section_Dict(name=name, count=count, cards=cards)


def _card(name, count=1) -> Library_Card_Dict:
    return Library_Card_Dict(name=name, count=count)


# Mapping used in tests: card name → krcg section name
_FAKE_KRCG = {
    "Villein": "Master",
    "Govern the Unaligned": "Action",
    "Deflection": "Reaction",
    "Mirror Walk": "Action Modifier",
    "Plasmic Form": "Action Modifier/Combat",
}


def _fake_krcg_section(card_name: str):
    return _FAKE_KRCG.get(card_name)


class TestFixCardSections:
    def _patch_krcg(self, available=True):
        """Return a context-manager stack that fakes krcg availability."""
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            krcg_fn = _fake_krcg_section if available else (lambda _: None)
            with patch(
                "vtes_scraper.validator.get_library_card_type",
                side_effect=krcg_fn,
            ):
                yield

        return _ctx()

    def test_no_changes_when_sections_correct(self):
        deck = _make_deck_with_sections(
            [
                _section("Master", [_card("Villein", 3)]),
                _section("Action", [_card("Govern the Unaligned", 2)]),
            ]
        )
        with self._patch_krcg():
            fixes = fix_card_sections(deck)
        assert fixes == []
        assert "library_sections" in deck
        assert "name" in deck["library_sections"][0]
        assert deck["library_sections"][0]["name"] == "Master"
        assert "name" in deck["library_sections"][1]
        assert deck["library_sections"][1]["name"] == "Action"

    def test_moves_card_to_correct_section(self):
        # Govern the Unaligned is in Master — should move to Action
        deck = _make_deck_with_sections(
            [
                _section(
                    "Master",
                    [_card("Villein", 2), _card("Govern the Unaligned", 1)],
                ),
            ]
        )
        with self._patch_krcg():
            fixes = fix_card_sections(deck)

        assert len(fixes) == 1
        assert "'Govern the Unaligned'" in fixes[0]
        assert "'Master'" in fixes[0]
        assert "'Action'" in fixes[0]

        assert "library_sections" in deck
        section_names = [s["name"] for s in deck["library_sections"] if "name" in s]
        assert "Master" in section_names
        assert "Action" in section_names
        master = next(s for s in deck["library_sections"] if "name" in s and s["name"] == "Master")
        assert "count" in master and master["count"] == 2
        action = next(s for s in deck["library_sections"] if "name" in s and s["name"] == "Action")
        assert "count" in action and action["count"] == 1

    def test_library_count_updated(self):
        deck = _make_deck_with_sections(
            [
                _section(
                    "Master",
                    [_card("Villein", 2), _card("Govern the Unaligned", 1)],
                ),
            ]
        )
        with self._patch_krcg():
            fix_card_sections(deck)
        assert "library_count" in deck and deck["library_count"] == 3  # unchanged total

    def test_unknown_card_stays_in_current_section(self):
        deck = _make_deck_with_sections([_section("Master", [_card("Some Unknown Card", 1)])])
        with self._patch_krcg():
            fixes = fix_card_sections(deck)
        assert fixes == []
        assert (
            "library_sections" in deck
            and deck["library_sections"]
            and "name" in deck["library_sections"][0]
            and deck["library_sections"][0]["name"] == "Master"
        )

    def test_krcg_unavailable_returns_empty(self):
        deck = _make_deck_with_sections([_section("Master", [_card("Govern the Unaligned", 1)])])
        with self._patch_krcg(available=False):
            fixes = fix_card_sections(deck)
        assert fixes == []

    def test_empty_library_sections_returns_empty(self):
        deck = _deck(library_sections=[])
        with self._patch_krcg():
            fixes = fix_card_sections(deck)
        assert fixes == []

    def test_sections_rebuilt_in_type_order(self):
        """After fixing, sections must follow krcg TYPE_ORDER."""
        # Put Reaction before Master deliberately
        deck = _make_deck_with_sections(
            [
                _section("Reaction", [_card("Deflection", 2)]),
                _section("Master", [_card("Villein", 3)]),
            ]
        )
        # Both are already correct, so we force a move to trigger rebuild.
        # Put Mirror Walk (Action Modifier) in the Master section.
        assert "library_sections" in deck and "library_count" in deck
        assert "cards" in deck["library_sections"][1] and "count" in deck["library_sections"][1]
        deck["library_sections"][1]["cards"].append(_card("Mirror Walk", 1))
        deck["library_sections"][1]["count"] += 1
        deck["library_count"] += 1

        with self._patch_krcg():
            fixes = fix_card_sections(deck)

        assert fixes  # something was moved
        names = [s["name"] for s in deck["library_sections"] if "name" in s]
        # Master should come before Action Modifier, which should come before Reaction
        assert names.index("Master") < names.index("Action Modifier")
        assert names.index("Action Modifier") < names.index("Reaction")


# ---------------------------------------------------------------------------
# enrich_crypt_cards
# ---------------------------------------------------------------------------

# Fake krcg data used in tests: card name → single dict or list of dicts (multi-version)
_FAKE_CRYPT_KRCG: dict[str, dict | list] = {
    "Nathan Turner": {
        "capacity": 4,
        "disciplines": "PRO ani",
        "title": None,
        "clan": "Gangrel",
        "grouping": 6,
    },
    "Antón de Concepción": {
        "capacity": 8,
        "disciplines": "AUS DOM OBF for",
        "title": "Prince",
        "clan": "Lasombra",
        "grouping": 6,
    },
    "Anarch Convert": {
        "capacity": 1,
        "disciplines": "",
        "title": None,
        "clan": "Caitiff",
        "grouping": "ANY",
    },
    # Xaviar: base and ADV are separate entries (different names in the lookup)
    "Xaviar": {
        "capacity": 11,
        "disciplines": "ANI CEL FOR PRO",
        "title": "Justicar",
        "clan": "Gangrel",
        "grouping": 3,
    },
    "Xaviar (ADV)": {
        "capacity": 10,
        "disciplines": "aus cel pot ABO ANI FOR PRO",
        "title": "Justicar",
        "clan": "Gangrel",
        "grouping": 3,
    },
}


def _fake_krcg_all_crypt_data(card_name: str) -> list[dict]:
    data = _FAKE_CRYPT_KRCG.get(card_name)
    if data is None:
        return []
    # Support multi-version entries stored as a list
    if isinstance(data, list):
        return data
    return [data]


def _crypt_card(name: str, count: int = 2, **overrides) -> Crypt_Card_Dict:
    base = Crypt_Card_Dict(
        count=count,
        name=name,
        capacity=0,
        disciplines="",
        title=None,
        clan="Unknown",
        grouping=0,
    )
    for k, v in overrides.items():
        if k in Crypt_Card_Dict.__annotations__:
            base[k] = v
    return base


class TestEnrichCryptCards:
    def _patch_krcg(self, available: bool = True):
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            krcg_fn = _fake_krcg_all_crypt_data if available else (lambda _: [])
            with patch(
                "vtes_scraper.validator.get_all_vamp_variants",
                side_effect=krcg_fn,
            ):
                yield

        return _ctx()

    def test_enriches_fields_from_krcg(self):
        card = _crypt_card("Nathan Turner", capacity=0, clan="Unknown", grouping=0)
        deck = _deck(crypt=[card])
        with self._patch_krcg():
            fixes = enrich_crypt_cards(deck)
        assert fixes
        assert "capacity" in card and card["capacity"] == 4
        assert "disciplines" in card and card["disciplines"] == "PRO ani"
        assert "clan" in card and card["clan"] == "Gangrel"
        assert "grouping" in card and card["grouping"] == 6
        assert "title" in card and card["title"] is None

    def test_count_and_name_preserved(self):
        card = _crypt_card("Nathan Turner", count=3)
        deck = _deck(crypt=[card])
        with self._patch_krcg():
            enrich_crypt_cards(deck)
        assert "count" in card and card["count"] == 3
        assert "name" in card and card["name"] == "Nathan Turner"

    def test_title_enriched(self):
        card = _crypt_card("Antón de Concepción", title=None)
        deck = _deck(crypt=[card])
        with self._patch_krcg():
            enrich_crypt_cards(deck)
        assert "title" in card and card["title"] == "Prince"

    def test_any_grouping_stored_as_string(self):
        card = _crypt_card("Anarch Convert", grouping=0)
        deck = _deck(crypt=[card])
        with self._patch_krcg():
            enrich_crypt_cards(deck)
        assert "grouping" in card and card["grouping"] == "ANY"

    def test_no_changes_when_already_correct(self):
        card = _crypt_card(
            "Nathan Turner",
            capacity=4,
            disciplines="PRO ani",
            clan="Gangrel",
            grouping=6,
        )
        deck = Deck_Dict(crypt=[card])
        with self._patch_krcg():
            fixes = enrich_crypt_cards(deck)
        assert fixes == []

    def test_unknown_card_left_unchanged(self):
        card = _crypt_card("Unknown Vampire", capacity=5, clan="Nosferatu", grouping=3)
        deck = Deck_Dict(crypt=[card])
        with self._patch_krcg():
            fixes = enrich_crypt_cards(deck)
        assert fixes == []
        assert "capacity" in card and card["capacity"] == 5
        assert "clan" in card and card["clan"] == "Nosferatu"

    def test_krcg_unavailable_returns_empty(self):
        card = _crypt_card("Nathan Turner", capacity=0, clan="Unknown")
        deck = Deck_Dict(crypt=[card])
        with self._patch_krcg(available=False):
            fixes = enrich_crypt_cards(deck)
        assert fixes == []
        assert "capacity" in card and card["capacity"] == 0  # unchanged

    def test_empty_crypt_returns_empty(self):
        deck = Deck_Dict(crypt=[])
        with self._patch_krcg():
            fixes = enrich_crypt_cards(deck)
        assert fixes == []

    def test_base_vampire_not_replaced_by_adv(self):
        """Scraped 'Xaviar' must never be enriched with 'Xaviar (ADV)' data."""
        card = _crypt_card("Xaviar", capacity=0)
        deck = Deck_Dict(crypt=[card])
        with self._patch_krcg():
            enrich_crypt_cards(deck)
        # Must use base Xaviar data (capacity=11), not ADV data (capacity=10)
        assert "capacity" in card and card["capacity"] == 11
        assert "disciplines" in card and card["disciplines"] == "ANI CEL FOR PRO"
        # Name must not be changed to include "(ADV)"
        assert "name" in card and card["name"] == "Xaviar"

    def test_adv_vampire_uses_adv_data(self):
        """Scraped 'Xaviar (ADV)' must be enriched with ADV data, not base data."""
        card = _crypt_card("Xaviar (ADV)", capacity=0)
        deck = Deck_Dict(crypt=[card])
        with self._patch_krcg():
            enrich_crypt_cards(deck)
        assert "capacity" in card and card["capacity"] == 10
        assert "disciplines" in card and card["disciplines"] == "aus cel pot ABO ANI FOR PRO"
        assert "name" in card and card["name"] == "Xaviar (ADV)"

    def test_multi_version_picks_matching_group(self):
        """When a vampire has two grouping versions, pick the one that fits."""
        _FAKE_CRYPT_KRCG["Nathan Turner"] = [
            {
                "capacity": 4,
                "disciplines": "PRO ani",
                "title": None,
                "clan": "Gangrel",
                "grouping": 5,
            },
            {
                "capacity": 4,
                "disciplines": "PRO ani",
                "title": None,
                "clan": "Gangrel",
                "grouping": 6,
            },
        ]
        try:
            single_card = _crypt_card("Antón de Concepción", grouping=6)  # krcg group=6
            multi_card = _crypt_card("Nathan Turner", grouping=0)
            deck = Deck_Dict(crypt=[single_card, multi_card])
            with self._patch_krcg():
                enrich_crypt_cards(deck)
            assert "grouping" in multi_card and multi_card["grouping"] == 6
        finally:
            _FAKE_CRYPT_KRCG["Nathan Turner"] = {
                "capacity": 4,
                "disciplines": "PRO ani",
                "title": None,
                "clan": "Gangrel",
                "grouping": 6,
            }

    def test_multi_version_fallback_to_first_when_no_match(self):
        """When no version fits the range, use the first version found."""
        _FAKE_CRYPT_KRCG["Nathan Turner"] = [
            {
                "capacity": 4,
                "disciplines": "PRO ani",
                "title": None,
                "clan": "Gangrel",
                "grouping": 3,
            },
            {
                "capacity": 4,
                "disciplines": "PRO ani",
                "title": None,
                "clan": "Gangrel",
                "grouping": 6,
            },
        ]
        _FAKE_CRYPT_KRCG["_RefCard_G10"] = {
            "capacity": 5,
            "disciplines": "",
            "title": None,
            "clan": "Gangrel",
            "grouping": 10,
        }
        try:
            single_card = _crypt_card("_RefCard_G10")  # krcg group=10
            multi_card = _crypt_card("Nathan Turner", grouping=0)
            deck = Deck_Dict(crypt=[single_card, multi_card])
            with self._patch_krcg():
                enrich_crypt_cards(deck)
            # G3→{3,10} not consecutive; G6→{6,10} not consecutive → fallback to first (G3)
            assert "grouping" in multi_card and multi_card["grouping"] == 3
        finally:
            _FAKE_CRYPT_KRCG["Nathan Turner"] = {
                "capacity": 4,
                "disciplines": "PRO ani",
                "title": None,
                "clan": "Gangrel",
                "grouping": 6,
            }
            del _FAKE_CRYPT_KRCG["_RefCard_G10"]

    def test_multi_version_no_reference_uses_first(self):
        """When all crypt cards are multi-version, fall back to first version."""
        _FAKE_CRYPT_KRCG["Nathan Turner"] = [
            {
                "capacity": 4,
                "disciplines": "PRO ani",
                "title": None,
                "clan": "Gangrel",
                "grouping": 5,
            },
            {
                "capacity": 4,
                "disciplines": "PRO ani",
                "title": None,
                "clan": "Gangrel",
                "grouping": 6,
            },
        ]
        try:
            multi_card = _crypt_card("Nathan Turner", grouping=0)
            deck = Deck_Dict(crypt=[multi_card])
            with self._patch_krcg():
                enrich_crypt_cards(deck)
            # No fixed reference → fallback to first version (G5)
            assert "grouping" in multi_card and multi_card["grouping"] == 5
        finally:
            _FAKE_CRYPT_KRCG["Nathan Turner"] = {
                "capacity": 4,
                "disciplines": "PRO ani",
                "title": None,
                "clan": "Gangrel",
                "grouping": 6,
            }


# ---------------------------------------------------------------------------
# _pick_best_crypt_version
# ---------------------------------------------------------------------------


class TestPickBestCryptVersion:
    def _v(self, grouping) -> Crypt_Card_Dict:
        return Crypt_Card_Dict(
            capacity=5,
            disciplines="",
            title=None,
            clan="Gangrel",
            grouping=grouping,
        )

    def test_exact_match_preferred(self):
        versions = [self._v(5), self._v(6)]
        best = _pick_best_crypt_version(versions, {6})
        assert "grouping" in best and best["grouping"] == 6

    def test_consecutive_extension_chosen(self):
        versions = [self._v(4), self._v(5)]
        best = _pick_best_crypt_version(versions, {6})
        # G5 extends {6} to {5,6} which is consecutive; G4 would give {4,6} which is not
        assert "grouping" in best and best["grouping"] == 5

    def test_no_reference_returns_first(self):
        versions = [self._v(3), self._v(7)]
        best = _pick_best_crypt_version(versions, set())
        assert "grouping" in best and best["grouping"] == 3

    def test_no_fit_returns_first(self):
        versions = [self._v(3), self._v(7)]
        best = _pick_best_crypt_version(versions, {1})
        assert "grouping" in best and best["grouping"] == 3

    def test_any_grouping_only_falls_back(self):
        versions = [
            Crypt_Card_Dict(
                capacity=1,
                disciplines="",
                title=None,
                clan="Caitiff",
                grouping="ANY",
            )
        ]
        best = _pick_best_crypt_version(versions, {5})
        assert "grouping" in best and best["grouping"] == "ANY"
