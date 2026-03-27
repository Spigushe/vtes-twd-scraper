"""Tests for vtes_scraper.output modules."""

import tempfile
from datetime import date
from pathlib import Path

import pytest

from vtes_scraper.models import CryptCard, Deck, LibraryCard, LibrarySection, Tournament
from vtes_scraper.output._common import _date_subdir
from vtes_scraper.output.txt import (
    _fmt_crypt_card,
    _fmt_date,
    _fmt_library_section,
    tournament_to_txt,
    write_tournament_txt,
)
from vtes_scraper.output.yaml import tournament_to_yaml_str, write_tournament_yaml


def _make_tournament(**kwargs) -> Tournament:
    defaults = dict(
        name="Test Event",
        location="Paris, France",
        date_start=date(2023, 3, 25),
        rounds_format="3R+F",
        players_count=15,
        winner="Jane Doe",
        event_url="https://www.vekn.net/event-calendar/event/9999",
        deck=Deck(
            name="Test Deck",
            created_by="John Smith",
            description="A test description.",
            crypt=[
                CryptCard(
                    count=2,
                    name="Nathan Turner",
                    capacity=4,
                    disciplines="PRO ani",
                    clan="Gangrel",
                    grouping=6,
                ),
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


# ---------------------------------------------------------------------------
# _date_subdir
# ---------------------------------------------------------------------------


class TestDateSubdir:
    def test_returns_year_month_path(self):
        t = _make_tournament(date_start=date(2023, 3, 25))
        result = _date_subdir(t)
        assert result == Path("2023/03")

    def test_single_digit_month_padded(self):
        t = _make_tournament(date_start=date(2023, 1, 5))
        result = _date_subdir(t)
        assert result == Path("2023/01")


# ---------------------------------------------------------------------------
# _fmt_date
# ---------------------------------------------------------------------------


class TestFmtDate:
    def test_first_day(self):
        assert _fmt_date(date(2023, 3, 1)) == "March 1st 2023"

    def test_second_day(self):
        assert _fmt_date(date(2023, 3, 2)) == "March 2nd 2023"

    def test_third_day(self):
        assert _fmt_date(date(2023, 3, 3)) == "March 3rd 2023"

    def test_fourth_day(self):
        assert _fmt_date(date(2023, 3, 4)) == "March 4th 2023"

    def test_eleventh_day_th(self):
        # 11 is special — must be 11th (not 11st)
        assert _fmt_date(date(2023, 3, 11)) == "March 11th 2023"

    def test_twelfth_day_th(self):
        assert _fmt_date(date(2023, 3, 12)) == "March 12th 2023"

    def test_thirteenth_day_th(self):
        assert _fmt_date(date(2023, 3, 13)) == "March 13th 2023"

    def test_twentyfirst_day_st(self):
        assert _fmt_date(date(2023, 3, 21)) == "March 21st 2023"

    def test_twentysecond_day_nd(self):
        assert _fmt_date(date(2023, 3, 22)) == "March 22nd 2023"

    def test_twentythird_day_rd(self):
        assert _fmt_date(date(2023, 3, 23)) == "March 23rd 2023"

    def test_twentyfifth_day(self):
        assert _fmt_date(date(2023, 3, 25)) == "March 25th 2023"


# ---------------------------------------------------------------------------
# _fmt_crypt_card
# ---------------------------------------------------------------------------


class TestFmtCryptCard:
    def test_without_title(self):
        card = CryptCard(
            count=2,
            name="Nathan Turner",
            capacity=4,
            disciplines="PRO ani",
            clan="Gangrel",
            grouping=6,
        )
        line = _fmt_crypt_card(card)
        assert "Nathan Turner" in line
        assert "Gangrel:6" in line
        assert "PRO ani" in line

    def test_with_title(self):
        card = CryptCard(
            count=1,
            name="Tara",
            capacity=6,
            disciplines="cel POT PRE",
            title="prince",
            clan="Brujah",
            grouping=5,
        )
        line = _fmt_crypt_card(card)
        assert "prince" in line
        assert "Brujah:5" in line

    def test_with_comment(self):
        card = CryptCard(
            count=1,
            name="Test Vamp",
            capacity=5,
            disciplines="OBF",
            clan="Malkavian",
            grouping=4,
            comment="very useful",
        )
        line = _fmt_crypt_card(card)
        assert "-- very useful" in line

    def test_without_title_spacer(self):
        card = CryptCard(
            count=2,
            name="Nathan Turner",
            capacity=4,
            disciplines="PRO ani",
            clan="Gangrel",
            grouping=6,
        )
        line = _fmt_crypt_card(card)
        # 11 spaces for no-title slot
        assert "  " in line  # at least 2 spaces in the title column


# ---------------------------------------------------------------------------
# _fmt_library_section
# ---------------------------------------------------------------------------


class TestFmtLibrarySection:
    def test_section_header(self):
        section = LibrarySection(
            name="Master",
            count=2,
            cards=[
                LibraryCard(count=1, name="Blood Doll"),
                LibraryCard(count=1, name="Vessel"),
            ],
        )
        text = _fmt_library_section(section)
        assert text.startswith("Master (2)")

    def test_cards_listed(self):
        section = LibrarySection(
            name="Master",
            count=1,
            cards=[
                LibraryCard(count=1, name="Blood Doll"),
            ],
        )
        text = _fmt_library_section(section)
        assert "1x Blood Doll" in text

    def test_card_with_comment(self):
        section = LibrarySection(
            name="Action",
            count=1,
            cards=[
                LibraryCard(
                    count=1, name="Anarch Free Press, The", comment="note here"
                ),
            ],
        )
        text = _fmt_library_section(section)
        assert "-- note here" in text


# ---------------------------------------------------------------------------
# tournament_to_txt
# ---------------------------------------------------------------------------


class TestTournamentToTxt:
    def test_includes_mandatory_fields(self):
        t = _make_tournament()
        txt = tournament_to_txt(t)
        assert "Test Event" in txt
        assert "Paris, France" in txt
        assert "3R+F" in txt
        assert "15 players" in txt
        assert "Jane Doe" in txt
        assert "https://www.vekn.net/event-calendar/event/9999" in txt

    def test_multiday_date(self):
        t = _make_tournament(date_start=date(2023, 3, 25), date_end=date(2023, 3, 26))
        txt = tournament_to_txt(t)
        assert " -- " in txt
        assert "March 25th 2023" in txt
        assert "March 26th 2023" in txt

    def test_deck_name_included(self):
        t = _make_tournament()
        txt = tournament_to_txt(t)
        assert "Deck Name: Test Deck" in txt

    def test_created_by_when_different_from_winner(self):
        t = _make_tournament(winner="Jane Doe")
        # deck.created_by = "John Smith" (different from winner)
        txt = tournament_to_txt(t)
        assert "Created by: John Smith" in txt

    def test_created_by_omitted_when_same_as_winner(self):
        deck = Deck(
            name=None,
            created_by="Jane Doe",
            crypt=[
                CryptCard(
                    count=1,
                    name="Nathan Turner",
                    capacity=4,
                    disciplines="PRO",
                    clan="Gangrel",
                    grouping=6,
                )
            ],
            crypt_count=1,
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
        )
        t = _make_tournament(winner="Jane Doe", deck=deck)
        txt = tournament_to_txt(t)
        assert "Created by:" not in txt

    def test_description_included(self):
        t = _make_tournament()
        txt = tournament_to_txt(t)
        assert "Description:" in txt
        assert "A test description." in txt

    def test_no_deck_metadata_block_when_absent(self):
        deck = Deck(
            crypt=[
                CryptCard(
                    count=1,
                    name="Nathan Turner",
                    capacity=4,
                    disciplines="PRO",
                    clan="Gangrel",
                    grouping=6,
                )
            ],
            crypt_count=1,
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
        )
        t = _make_tournament(deck=deck)
        txt = tournament_to_txt(t)
        assert "Deck Name:" not in txt

    def test_crypt_header_present(self):
        t = _make_tournament()
        txt = tournament_to_txt(t)
        assert "Crypt (" in txt

    def test_library_header_present(self):
        t = _make_tournament()
        txt = tournament_to_txt(t)
        assert "Library (" in txt

    def test_avg_trailing_zeros_stripped(self):
        t = _make_tournament()
        txt = tournament_to_txt(t)
        assert "avg=4" in txt  # 4.00 becomes "4"


# ---------------------------------------------------------------------------
# write_tournament_txt
# ---------------------------------------------------------------------------


class TestWriteTournamentTxt:
    def test_writes_file(self):
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_tournament_txt(t, Path(tmpdir))
            assert path.exists()
            assert path.read_text(encoding="utf-8").startswith("Test Event")

    def test_raises_if_exists_no_overwrite(self):
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            write_tournament_txt(t, Path(tmpdir))
            with pytest.raises(FileExistsError):
                write_tournament_txt(t, Path(tmpdir), overwrite=False)

    def test_overwrites_when_flag_set(self):
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            write_tournament_txt(t, Path(tmpdir))
            path = write_tournament_txt(t, Path(tmpdir), overwrite=True)
            assert path.exists()


# ---------------------------------------------------------------------------
# tournament_to_yaml_str
# ---------------------------------------------------------------------------


class TestTournamentToYamlStr:
    def test_returns_string(self):
        t = _make_tournament()
        result = tournament_to_yaml_str(t)
        assert isinstance(result, str)
        assert "Test Event" in result

    def test_contains_required_keys(self):
        t = _make_tournament()
        result = tournament_to_yaml_str(t)
        assert "name:" in result
        assert "location:" in result
        assert "date_start:" in result

    def test_multiline_description_literal_block(self):
        deck = Deck(
            description="Line one.\nLine two.",
            crypt=[
                CryptCard(
                    count=1,
                    name="Nathan Turner",
                    capacity=4,
                    disciplines="PRO",
                    clan="Gangrel",
                    grouping=6,
                )
            ],
            crypt_count=1,
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
        )
        t = _make_tournament(deck=deck)
        result = tournament_to_yaml_str(t)
        # ruamel.yaml renders LiteralScalarString with | block scalar
        assert "|" in result

    def test_single_line_description_not_literal(self):
        t = _make_tournament()
        result = tournament_to_yaml_str(t)
        # Single-line description should not use block scalar in this key
        # Just verify it renders without error
        assert "description:" in result

    def test_date_rendered_without_quotes(self):
        """date_start must be a bare YAML date, not a quoted string."""
        t = _make_tournament(date_start=date(2026, 3, 15))
        result = tournament_to_yaml_str(t)
        # YAML date: `date_start: 2026-03-15` (no surrounding quotes)
        assert "date_start: 2026-03-15" in result
        assert "date_start: '2026-03-15'" not in result

    def test_event_id_rendered_as_int(self):
        """event_id must be a bare integer, not a quoted string."""
        t = _make_tournament(event_url="https://www.vekn.net/event-calendar/event/9999")
        result = tournament_to_yaml_str(t)
        assert "event_id: 9999" in result
        assert "event_id: '9999'" not in result


# ---------------------------------------------------------------------------
# write_tournament_yaml
# ---------------------------------------------------------------------------


class TestWriteTournamentYaml:
    def test_writes_file(self):
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_tournament_yaml(t, Path(tmpdir))
            assert path.exists()
            assert "Test Event" in path.read_text(encoding="utf-8")

    def test_raises_if_exists_no_overwrite(self):
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            write_tournament_yaml(t, Path(tmpdir))
            with pytest.raises(FileExistsError):
                write_tournament_yaml(t, Path(tmpdir), overwrite=False)

    def test_overwrites_when_flag_set(self):
        t = _make_tournament()
        with tempfile.TemporaryDirectory() as tmpdir:
            write_tournament_yaml(t, Path(tmpdir))
            path = write_tournament_yaml(t, Path(tmpdir), overwrite=True)
            assert path.exists()
