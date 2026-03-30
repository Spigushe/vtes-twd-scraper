"""Tests for vtes_scraper.models."""

from datetime import date

import pytest

from vtes_scraper.models import CryptCard, Deck, LibraryCard, LibrarySection, Tournament


def _make_tournament(**kwargs) -> Tournament:
    defaults = dict(
        name="Test Event",
        location="Paris, France",
        date_start="2023-03-25",
        rounds_format="3R+F",
        players_count=15,
        winner="Jane Doe",
        event_url="https://www.vekn.net/event-calendar/event/9999",
        deck=Deck(
            crypt=[
                CryptCard(
                    count=2,
                    name="Nathan Turner",
                    capacity=4,
                    disciplines="PRO ani",
                    clan="Gangrel",
                    grouping=6,
                )
            ],
            crypt_count=2,
            crypt_min=4,
            crypt_max=4,
            crypt_avg=4.0,
            library_sections=[
                LibrarySection(
                    name="Master",
                    count=1,
                    cards=[LibraryCard(count=1, name="Blood Doll")],
                )
            ],
            library_count=1,
        ),
    )
    defaults.update(kwargs)
    return Tournament(**defaults)


class TestYamlFilename:
    def test_returns_event_id_yaml(self):
        t = _make_tournament()
        assert t.yaml_filename == "9999.yaml"

    def test_raises_without_event_id(self):
        t = _make_tournament(event_url="https://www.vekn.net/event-calendar/event/9999")
        t.event_id = None
        with pytest.raises(ValueError, match="event_id is missing"):
            _ = t.yaml_filename


class TestTxtFilename:
    def test_returns_event_id_txt(self):
        t = _make_tournament()
        assert t.txt_filename == "9999.txt"

    def test_raises_without_event_id(self):
        t = _make_tournament()
        t.event_id = None
        with pytest.raises(ValueError, match="event_id is missing"):
            _ = t.txt_filename


class TestCoercePlayers:
    def test_players_as_int(self):
        t = _make_tournament(players_count=42)
        assert t.players_count == 42

    def test_players_as_string_with_word(self):
        t = _make_tournament(players_count="42 players")
        assert t.players_count == 42

    def test_players_as_plain_string_number(self):
        t = _make_tournament(players_count="13")
        assert t.players_count == 13


class TestDateParsing:
    def test_iso_format(self):
        t = _make_tournament(date_start="2026-01-15")
        assert t.date_start == date(2026, 1, 15)

    def test_slash_format(self):
        t = _make_tournament(date_start="15/01/2026")
        assert t.date_start == date(2026, 1, 15)

    def test_month_day_year(self):
        t = _make_tournament(date_start="January 15 2026")
        assert t.date_start == date(2026, 1, 15)

    def test_ordinal_suffix_stripped(self):
        t = _make_tournament(date_start="March 25th 2023")
        assert t.date_start == date(2023, 3, 25)

    def test_day_month_year(self):
        t = _make_tournament(date_start="25 March 2023")
        assert t.date_start == date(2023, 3, 25)

    def test_abbreviated_month(self):
        t = _make_tournament(date_start="Mar 25 2023")
        assert t.date_start == date(2023, 3, 25)

    def test_date_object_passthrough(self):
        d = date(2023, 3, 25)
        t = _make_tournament(date_start=d)
        assert t.date_start == d

    def test_none_date_end(self):
        t = _make_tournament(date_end=None)
        assert t.date_end is None

    def test_invalid_date_raises(self):
        with pytest.raises(ValueError, match="Cannot parse date"):
            _make_tournament(date_start="not-a-date")


class TestRoundsFormat:
    def test_valid_format(self):
        t = _make_tournament(rounds_format="2R+F")
        assert t.rounds_format == "2R+F"

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="rounds_format"):
            _make_tournament(rounds_format="INVALID")


class TestEventId:
    def test_derived_from_url(self):
        t = _make_tournament(event_url="https://www.vekn.net/event-calendar/event/12345")
        assert t.event_id == 12345
        assert isinstance(t.event_id, int)

    def test_no_match_stays_none(self):
        t = _make_tournament(event_url="https://www.vekn.net/other/page")
        assert t.event_id is None

    def test_non_canonical_url_normalised(self):
        """A non-canonical vekn URL containing '/event/<id>' is rewritten."""
        t = _make_tournament(event_url="https://www.vekn.net/player-registry/event/12345")
        assert t.event_id == 12345
        assert t.event_url == "https://www.vekn.net/event-calendar/event/12345"

    def test_canonical_url_unchanged(self):
        t = _make_tournament(event_url="https://www.vekn.net/event-calendar/event/12345")
        assert t.event_url == "https://www.vekn.net/event-calendar/event/12345"
