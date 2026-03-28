"""
Unit tests for the TWD parser.
Test data is taken verbatim from the README examples.
"""

from datetime import datetime

import pytest

from vtes_scraper_v1.parser import parse_twd_text

# ---------------------------------------------------------------------------
# Fixtures — real examples from the README
# ---------------------------------------------------------------------------

EXAMPLE_SIMPLE = """\
Conservative Agitation
Vila Velha, Brazil
October 1st 2016
2R+F
12 players
Ravel Zorzal
https://www.vekn.net/event-calendar/event/8470

-- 5VP in final

Deck Name : Eyes of the Insane
Created by: Bobby Lemon
Description:
A great deck that wins all the time.

Crypt (2 cards, min=4, max=4, avg=4)
-------------------------------------
2x Nathan Turner      4 PRO ani                 Gangrel:6

Library (1 cards)
Master (1)
1x Blood Doll
"""

EXAMPLE_FULL = """\
Sede de Vitae Part 26
Online
December 13th 2021 -- December 15th 2021
2R+F
16 players
Joab Rogerio Barbosa da Silva
https://www.vekn.net/event-calendar/event/10008

Deck Name: Tributo a Paulão

Crypt (12 cards, min=11, max=22, avg=4)
---------------------------------------
2x Nathan Turner      4 PRO ani                 Gangrel:6
2x Indira             3 PRO                     Gangrel:6
1x Ruslan Fedorenko   2 pro                     Gangrel:6

Library (89 cards)
Master (14; 2 trifle)
1x Anarch Free Press, The -- does not provide a free press!
1x Blood Doll
"""

EXAMPLE_WITH_HASH_COMMENTS = """\
6th Great Symposium                                # Event Name
Mikkeli, Finland                                   # Event Location
March 25th 2023                                    # Event Date
3R+F                                               # Number of Rounds
13 players                                         # Number of Players
Otso Saariluoma                                    # Winner
https://www.vekn.net/event-calendar/event/10546    # Event Link

Crypt (2 cards, min=4, max=4, avg=4)
-------------------------------------
2x Nathan Turner      4 PRO ani                 Gangrel:6

Library (1 cards)
Master (1)
1x Blood Doll
"""


# ---------------------------------------------------------------------------
# Mandatory fields
# ---------------------------------------------------------------------------


class TestMandatoryFields:
    def test_event_name(self):
        t = parse_twd_text(EXAMPLE_SIMPLE)
        assert t.name == "Conservative Agitation"

    def test_location(self):
        t = parse_twd_text(EXAMPLE_SIMPLE)
        assert t.location == "Vila Velha, Brazil"

    def test_date_single_day(self):
        t = parse_twd_text(EXAMPLE_SIMPLE)
        assert t.date_start == datetime(2016, 10, 1).date()
        assert t.date_end is None

    def test_date_multi_day(self):
        t = parse_twd_text(EXAMPLE_FULL)
        assert t.date_start == datetime(2021, 12, 13).date()
        assert t.date_end == datetime(2021, 12, 15).date()

    def test_rounds_format(self):
        t = parse_twd_text(EXAMPLE_SIMPLE)
        assert t.rounds_format == "2R+F"

    def test_players_count(self):
        t = parse_twd_text(EXAMPLE_SIMPLE)
        assert t.players_count == 12

    def test_winner(self):
        t = parse_twd_text(EXAMPLE_SIMPLE)
        assert t.winner == "Ravel Zorzal"

    def test_event_url(self):
        t = parse_twd_text(EXAMPLE_SIMPLE)
        assert t.event_url == "https://www.vekn.net/event-calendar/event/8470"

    def test_event_id_derived_from_url(self):
        t = parse_twd_text(EXAMPLE_SIMPLE)
        assert t.event_id == 8470

    def test_output_filename(self):
        t = parse_twd_text(EXAMPLE_SIMPLE)
        assert t.yaml_filename == "8470.yaml"


# ---------------------------------------------------------------------------
# Optional fields
# ---------------------------------------------------------------------------


class TestOptionalFields:
    def test_vp_comment(self):
        t = parse_twd_text(EXAMPLE_SIMPLE)
        assert t.vp_comment == "5VP in final"

    def test_no_vp_comment(self):
        t = parse_twd_text(EXAMPLE_FULL)
        assert t.vp_comment is None

    def test_deck_name(self):
        t = parse_twd_text(EXAMPLE_SIMPLE)
        assert t.deck is not None
        assert t.deck.name == "Eyes of the Insane"

    def test_created_by(self):
        t = parse_twd_text(EXAMPLE_SIMPLE)
        assert t.deck.created_by == "Bobby Lemon"

    def test_description(self):
        t = parse_twd_text(EXAMPLE_SIMPLE)
        assert "great deck" in t.deck.description


# ---------------------------------------------------------------------------
# Hash comment stripping
# ---------------------------------------------------------------------------


class TestHashComments:
    def test_strips_inline_hash_comments(self):
        t = parse_twd_text(EXAMPLE_WITH_HASH_COMMENTS)
        assert t.name == "6th Great Symposium"
        assert t.location == "Mikkeli, Finland"
        assert t.event_id == 10546


# ---------------------------------------------------------------------------
# Crypt parsing
# ---------------------------------------------------------------------------


class TestCryptParsing:
    def test_crypt_count(self):
        t = parse_twd_text(EXAMPLE_FULL)
        assert t.deck.crypt_count == 12

    def test_crypt_cards_parsed(self):
        t = parse_twd_text(EXAMPLE_FULL)
        assert len(t.deck.crypt) == 3

    def test_crypt_card_fields(self):
        t = parse_twd_text(EXAMPLE_FULL)
        nathan = t.deck.crypt[0]
        assert nathan.count == 2
        assert nathan.name == "Nathan Turner"
        assert nathan.capacity == 4
        assert "PRO" in nathan.disciplines
        assert nathan.clan == "Gangrel"
        assert nathan.grouping == 6


# ---------------------------------------------------------------------------
# Crypt fallback parsing (compact single-space format)
# ---------------------------------------------------------------------------

EXAMPLE_COMPACT_CRYPT = """\
Conservative Agitation
Vila Velha, Brazil
October 1st 2016
2R+F
12 players
Ravel Zorzal
https://www.vekn.net/event-calendar/event/8470

Crypt (4 cards, min=3, max=4, avg=3.5)
---------------------------------------
2x Nathan Turner 4 PRO ani Gangrel:6
2x Indira 3 PRO Gangrel:6

Library (1 cards)
Master (1)
1x Blood Doll
"""


class TestCryptCompactFormat:
    def test_card_count(self):
        t = parse_twd_text(EXAMPLE_COMPACT_CRYPT)
        assert len(t.deck.crypt) == 2

    def test_card_fields(self):
        t = parse_twd_text(EXAMPLE_COMPACT_CRYPT)
        card = t.deck.crypt[0]
        assert card.count == 2
        assert card.name == "Nathan Turner"
        assert card.capacity == 4
        assert "PRO" in card.disciplines
        assert card.clan == "Gangrel"
        assert card.grouping == 6

    def test_multi_discipline(self):
        t = parse_twd_text(EXAMPLE_COMPACT_CRYPT)
        # "2x Nathan Turner 4 PRO ani Gangrel:6" has two disciplines
        card = t.deck.crypt[0]
        assert "PRO" in card.disciplines
        assert "ani" in card.disciplines

    def test_single_discipline(self):
        t = parse_twd_text(EXAMPLE_COMPACT_CRYPT)
        indira = t.deck.crypt[1]
        assert indira.name == "Indira"
        assert indira.capacity == 3
        assert "PRO" in indira.disciplines


# ---------------------------------------------------------------------------
# Multi-word clan names (e.g. "Brujah antitribu")
# ---------------------------------------------------------------------------

EXAMPLE_ANTITRIBU_CLAN = """\
Dogs of War
Modena (MO) Italy
March 2nd 2025
2R+F
45 players
Marcin Szybkowski
https://www.vekn.net/event-calendar/event/11937

Crypt (4 cards, min=10, max=22, avg=3.83)
==========================================
2x Miguel Santo Domingo 7 POT PRE cel for Brujah antitribu:3
1x Evangeline 4 cel pot pre Brujah antitribu:2
1x Jacob Bragg 3 cel pot Brujah antitribu:2

Library (1 cards)
Master (1)
1x Blood Doll
"""


class TestMultiWordClan:
    def test_clan_with_space(self):
        t = parse_twd_text(EXAMPLE_ANTITRIBU_CLAN)
        assert t.deck.crypt[0].clan == "Brujah antitribu"

    def test_all_cards_parsed(self):
        t = parse_twd_text(EXAMPLE_ANTITRIBU_CLAN)
        assert len(t.deck.crypt) == 3

    def test_grouping(self):
        t = parse_twd_text(EXAMPLE_ANTITRIBU_CLAN)
        assert t.deck.crypt[0].grouping == 3
        assert t.deck.crypt[1].grouping == 2


# ---------------------------------------------------------------------------
# Title parsing (baron, prince, justicar, archbishop, ...)
# ---------------------------------------------------------------------------

EXAMPLE_WITH_TITLES = """\
Eat the Rich
Aix en Provence, France
June 19th 2022
3R+F
15 players
Jérémy Mercier
https://www.vekn.net/event-calendar/event/10124

Deck Name: Eat the Rich, but with philosophy!
Author: LonelyLasombra

Crypt (7 cards, min=24, max=32, avg=6.92)
==========================================
3x Aline Gädeke 7 cel POT PRE baron Brujah:6
2x Dmitra Ilyanova 9 obf CEL FOR POT PRE justicar Brujah:5
1x Tara 6 cel POT PRE prince Brujah:5
1x Thucimia 10 CEL DEM OBF QUI for pro 1 vote Banu Haqim:4

Library (1 cards)
Master (1)
1x Blood Doll
"""


class TestTitleParsing:
    def test_baron_title_extracted(self):
        t = parse_twd_text(EXAMPLE_WITH_TITLES)
        aline = t.deck.crypt[0]
        assert aline.title == "baron"
        assert aline.clan == "Brujah"

    def test_justicar_title_extracted(self):
        t = parse_twd_text(EXAMPLE_WITH_TITLES)
        dmitra = t.deck.crypt[1]
        assert dmitra.title == "justicar"
        assert dmitra.clan == "Brujah"

    def test_prince_title_extracted(self):
        t = parse_twd_text(EXAMPLE_WITH_TITLES)
        tara = t.deck.crypt[2]
        assert tara.title == "prince"
        assert tara.clan == "Brujah"

    def test_1vote_title_extracted(self):
        t = parse_twd_text(EXAMPLE_WITH_TITLES)
        thucimia = t.deck.crypt[3]
        assert thucimia.title == "1 vote"
        assert thucimia.clan == "Banu Haqim"

    def test_no_title_is_none(self):
        t = parse_twd_text(EXAMPLE_ANTITRIBU_CLAN)
        assert t.deck.crypt[0].title is None


# ---------------------------------------------------------------------------
# Library parsing
# ---------------------------------------------------------------------------


class TestLibraryParsing:
    def test_library_count(self):
        t = parse_twd_text(EXAMPLE_FULL)
        assert t.deck.library_count == 89

    def test_library_section_name(self):
        t = parse_twd_text(EXAMPLE_FULL)
        assert t.deck.library_sections[0].name == "Master"

    def test_library_section_count(self):
        t = parse_twd_text(EXAMPLE_FULL)
        assert t.deck.library_sections[0].count == 14

    def test_library_card_with_comment(self):
        t = parse_twd_text(EXAMPLE_FULL)
        anarch_press = t.deck.library_sections[0].cards[0]
        assert anarch_press.name == "Anarch Free Press, The"
        assert anarch_press.comment == "does not provide a free press!"


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


class TestValidation:
    def test_too_few_lines_raises(self):
        with pytest.raises(ValueError, match="fewer than 7"):
            parse_twd_text("Only one line")

    def test_invalid_rounds_format_raises(self):
        bad = EXAMPLE_SIMPLE.replace("2R+F", "INVALID")
        with pytest.raises(ValueError):
            parse_twd_text(bad)

    def test_missing_crypt_raises(self):
        # Remove the Crypt block entirely
        bad = "\n".join(
            line
            for line in EXAMPLE_SIMPLE.splitlines()
            if not line.startswith("Crypt")
            and not line.startswith("2x Nathan")
            and "-----" not in line
        )
        with pytest.raises(ValueError, match="Crypt"):
            parse_twd_text(bad)

    def test_missing_library_raises(self):
        # Remove the Library block entirely
        bad = "\n".join(
            line
            for line in EXAMPLE_SIMPLE.splitlines()
            if not line.startswith("Library")
            and not line.startswith("Master")
            and not line.startswith("1x Blood")
        )
        with pytest.raises(ValueError, match="Library"):
            parse_twd_text(bad)
