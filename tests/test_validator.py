"""Tests for vtes_scraper.validator."""

from datetime import date
from unittest.mock import patch

import pytest

from vtes_scraper.validator import error_types, fix_card_sections, parse_date_field


def _deck(**kwargs) -> dict:
    base = {
        "crypt_count": 2,
        "crypt": [
            {
                "count": 2,
                "name": "Nathan Turner",
                "capacity": 4,
                "disciplines": "PRO ani",
                "clan": "Gangrel",
                "grouping": 6,
            },
        ],
        "library_count": 1,
        "library_sections": [
            {
                "name": "Master",
                "count": 1,
                "cards": [{"count": 1, "name": "Blood Doll"}],
            }
        ],
    }
    base.update(kwargs)
    return base


def _tournament(**kwargs) -> dict:
    base = dict(
        name="Test Event",
        location="Paris, France",
        date_start="2023-03-25",
        rounds_format="3R+F",
        players_count=15,
        winner="Jane Doe",
        event_url="https://www.vekn.net/event-calendar/event/9999",
        deck=_deck(),
    )
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Mandatory field checks
# ---------------------------------------------------------------------------


class TestMandatoryFields:
    def test_valid_returns_no_errors(self):
        assert error_types(_tournament()) == []

    def test_missing_name(self):
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
        assert "library_section_count_mismatch" not in error_types(
            _tournament(deck=deck)
        )


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
        assert "incoherent_date" not in error_types(
            data, calendar_date=date(2023, 3, 25)
        )

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


def _make_deck_with_sections(sections):
    """Build a minimal deck dict with given library_sections."""
    total = sum(s["count"] for s in sections)
    return {
        "library_count": total,
        "library_sections": sections,
    }


def _section(name, cards):
    count = sum(c["count"] for c in cards)
    return {"name": name, "count": count, "cards": cards}


def _card(name, count=1):
    return {"name": name, "count": count}


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
            with patch("vtes_scraper.validator._KRCG_LOADED", available), patch(
                "vtes_scraper.validator._try_load_krcg", return_value=available
            ), patch(
                "vtes_scraper.validator._krcg_section", side_effect=_fake_krcg_section
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
        assert deck["library_sections"][0]["name"] == "Master"
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

        section_names = [s["name"] for s in deck["library_sections"]]
        assert "Master" in section_names
        assert "Action" in section_names
        master = next(s for s in deck["library_sections"] if s["name"] == "Master")
        assert master["count"] == 2
        action = next(s for s in deck["library_sections"] if s["name"] == "Action")
        assert action["count"] == 1

    def test_library_count_updated(self):
        deck = _make_deck_with_sections(
            [
                _section(
                    "Master", [_card("Villein", 2), _card("Govern the Unaligned", 1)]
                ),
            ]
        )
        with self._patch_krcg():
            fix_card_sections(deck)
        assert deck["library_count"] == 3  # unchanged total

    def test_unknown_card_stays_in_current_section(self):
        deck = _make_deck_with_sections(
            [_section("Master", [_card("Some Unknown Card", 1)])]
        )
        with self._patch_krcg():
            fixes = fix_card_sections(deck)
        assert fixes == []
        assert deck["library_sections"][0]["name"] == "Master"

    def test_krcg_unavailable_returns_empty(self):
        deck = _make_deck_with_sections(
            [_section("Master", [_card("Govern the Unaligned", 1)])]
        )
        with self._patch_krcg(available=False):
            fixes = fix_card_sections(deck)
        assert fixes == []

    def test_empty_library_sections_returns_empty(self):
        deck = {"library_sections": []}
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
        deck["library_sections"][1]["cards"].append(_card("Mirror Walk", 1))
        deck["library_sections"][1]["count"] += 1
        deck["library_count"] += 1

        with self._patch_krcg():
            fixes = fix_card_sections(deck)

        assert fixes  # something was moved
        names = [s["name"] for s in deck["library_sections"]]
        # Master should come before Action Modifier, which should come before Reaction
        assert names.index("Master") < names.index("Action Modifier")
        assert names.index("Action Modifier") < names.index("Reaction")
