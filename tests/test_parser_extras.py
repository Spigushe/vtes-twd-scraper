"""Additional parser tests for edge cases not covered by test_parser.py."""

import pytest

from vtes_scraper_v1.parser import (
    _extract_vekn_url,
    _normalize_rounds,
    _parse_crypt_line,
    _parse_library_line,
    _split_date,
    _strip_hash_comment,
    _strip_inline_comment,
    parse_twd_text,
)

# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestStripInlineComment:
    def test_with_comment(self):
        text, comment = _strip_inline_comment("Blood Doll -- very useful")
        assert text == "Blood Doll"
        assert comment == "very useful"

    def test_without_comment(self):
        text, comment = _strip_inline_comment("Blood Doll")
        assert text == "Blood Doll"
        assert comment is None


class TestStripHashComment:
    def test_strips_hash(self):
        result = _strip_hash_comment("Some text # comment here")
        assert result == "Some text"

    def test_no_hash(self):
        result = _strip_hash_comment("Some text")
        assert result == "Some text"

    def test_leading_hash(self):
        result = _strip_hash_comment("# full comment")
        assert result == ""


class TestNormalizeRounds:
    def test_canonical(self):
        assert _normalize_rounds("3R+F") == "3R+F"

    def test_with_final(self):
        assert _normalize_rounds("3R+Final") == "3R+F"

    def test_with_spaces(self):
        assert _normalize_rounds("2 R + F") == "2R+F"

    def test_no_match_returns_stripped(self):
        assert _normalize_rounds("  blah  ") == "blah"


class TestExtractVeknUrl:
    def test_full_url(self):
        url = _extract_vekn_url("https://www.vekn.net/event-calendar/event/8470")
        assert url == "https://www.vekn.net/event-calendar/event/8470"

    def test_bare_www(self):
        url = _extract_vekn_url("www.vekn.net/event-calendar/event/1234")
        assert url == "https://www.vekn.net/event-calendar/event/1234"

    def test_no_url(self):
        url = _extract_vekn_url("No URL here")
        assert url is None


class TestSplitDate:
    def test_single_date(self):
        start, end = _split_date("March 25th 2023")
        assert start == "March 25th 2023"
        assert end is None

    def test_date_range(self):
        start, end = _split_date("March 25th 2023 -- March 26th 2023")
        assert start == "March 25th 2023"
        assert end == "March 26th 2023"

    def test_strips_time(self):
        start, end = _split_date("March 25th 2023 14:00")
        assert "14:00" not in start


class TestParseCryptLine:
    def test_valid_line(self):
        card = _parse_crypt_line(
            "2x Nathan Turner      4 PRO ani                 Gangrel:6"
        )
        assert card is not None
        assert card.name == "Nathan Turner"
        assert card.count == 2
        assert card.capacity == 4
        assert card.clan == "Gangrel"
        assert card.grouping == 6

    def test_invalid_line_returns_none(self):
        card = _parse_crypt_line("This is not a card line")
        assert card is None

    def test_with_comment(self):
        card = _parse_crypt_line(
            "2x Nathan Turner      4 PRO ani                 Gangrel:6 -- some note"
        )
        assert card is not None
        assert card.comment == "some note"

    def test_with_title(self):
        card = _parse_crypt_line(
            "1x Tara              6 cel POT PRE prince       Brujah:5"
        )
        assert card is not None
        assert card.title == "prince"
        assert card.clan == "Brujah"


class TestParseLibraryLine:
    def test_valid_line(self):
        card = _parse_library_line("1x Blood Doll")
        assert card is not None
        assert card.name == "Blood Doll"
        assert card.count == 1

    def test_with_comment(self):
        card = _parse_library_line("1x Blood Doll -- discard this")
        assert card is not None
        assert card.comment == "discard this"

    def test_invalid_line_returns_none(self):
        card = _parse_library_line("Not a card line")
        assert card is None


# ---------------------------------------------------------------------------
# Lenient parse mode
# ---------------------------------------------------------------------------

LENIENT_EXAMPLE = """\
Winner: Bobby Lemon
6th Great Symposium
Mikkeli, Finland
March 25th 2023
13 players
3R+F
https://www.vekn.net/event-calendar/event/10546

Crypt (2 cards, min=4, max=4, avg=4)
-------------------------------------
2x Nathan Turner      4 PRO ani                 Gangrel:6

Library (1 cards)
Master (1)
1x Blood Doll
"""


class TestLenientParse:
    def test_labeled_winner(self):
        t = parse_twd_text(LENIENT_EXAMPLE)
        assert t.winner == "Bobby Lemon"

    def test_event_name_inferred(self):
        t = parse_twd_text(LENIENT_EXAMPLE)
        assert t.name == "6th Great Symposium"

    def test_location_inferred(self):
        t = parse_twd_text(LENIENT_EXAMPLE)
        assert t.location == "Mikkeli, Finland"


# ---------------------------------------------------------------------------
# VP comment in lenient mode
# ---------------------------------------------------------------------------

LENIENT_WITH_VP = """\
Conservative Agitation
Vila Velha, Brazil
October 1st 2016
2R+F
12 players
Winner: Ravel Zorzal
https://www.vekn.net/event-calendar/event/8470
-- 5VP in final

Crypt (2 cards, min=4, max=4, avg=4)
-------------------------------------
2x Nathan Turner      4 PRO ani                 Gangrel:6

Library (1 cards)
Master (1)
1x Blood Doll
"""


class TestVpCommentLenient:
    def test_vp_comment_parsed(self):
        t = parse_twd_text(LENIENT_WITH_VP)
        assert t.vp_comment == "5VP in final"


# ---------------------------------------------------------------------------
# forum_post_url passthrough
# ---------------------------------------------------------------------------

SIMPLE = """\
Conservative Agitation
Vila Velha, Brazil
October 1st 2016
2R+F
12 players
Ravel Zorzal
https://www.vekn.net/event-calendar/event/8470

Crypt (2 cards, min=4, max=4, avg=4)
-------------------------------------
2x Nathan Turner      4 PRO ani                 Gangrel:6

Library (1 cards)
Master (1)
1x Blood Doll
"""


class TestForumPostUrl:
    def test_forum_post_url_set(self):
        url = "https://www.vekn.net/forum/event-reports-and-twd/12345-test"
        t = parse_twd_text(SIMPLE, forum_post_url=url)
        assert t.forum_post_url == url

    def test_forum_post_url_none_by_default(self):
        t = parse_twd_text(SIMPLE)
        assert t.forum_post_url is None


# ---------------------------------------------------------------------------
# Library card without section header
# ---------------------------------------------------------------------------

NO_SECTION_HEADER = """\
Conservative Agitation
Vila Velha, Brazil
October 1st 2016
2R+F
12 players
Ravel Zorzal
https://www.vekn.net/event-calendar/event/8470

Crypt (2 cards, min=4, max=4, avg=4)
-------------------------------------
2x Nathan Turner      4 PRO ani                 Gangrel:6

Library (2 cards)
1x Blood Doll
1x Vessel
"""


class TestLibraryWithoutSection:
    def test_cards_parsed_without_section(self):
        t = parse_twd_text(NO_SECTION_HEADER)
        # Should still parse cards even without a section header
        total_cards = sum(len(s.cards) for s in t.deck.library_sections)
        assert total_cards == 2


# ---------------------------------------------------------------------------
# Deck with multiline description
# ---------------------------------------------------------------------------

MULTILINE_DESC = """\
Conservative Agitation
Vila Velha, Brazil
October 1st 2016
2R+F
12 players
Ravel Zorzal
https://www.vekn.net/event-calendar/event/8470

Deck Name: My Deck
Description:
A great description here.

Crypt (2 cards, min=4, max=4, avg=4)
-------------------------------------
2x Nathan Turner      4 PRO ani                 Gangrel:6

Library (1 cards)
Master (1)
1x Blood Doll
"""


class TestMultilineDescription:
    def test_description_on_next_line(self):
        t = parse_twd_text(MULTILINE_DESC)
        assert "great description" in t.deck.description


# ---------------------------------------------------------------------------
# Inline description (value on same line as Description:)
# ---------------------------------------------------------------------------

INLINE_DESC = """\
Conservative Agitation
Vila Velha, Brazil
October 1st 2016
2R+F
12 players
Ravel Zorzal
https://www.vekn.net/event-calendar/event/8470

Deck Name: My Deck
Description: Inline description value.

Crypt (2 cards, min=4, max=4, avg=4)
-------------------------------------
2x Nathan Turner      4 PRO ani                 Gangrel:6

Library (1 cards)
Master (1)
1x Blood Doll
"""


class TestInlineDescription:
    def test_description_inline(self):
        t = parse_twd_text(INLINE_DESC)
        assert t.deck.description == "Inline description value."


# ---------------------------------------------------------------------------
# Lenient parse: missing fields raises
# ---------------------------------------------------------------------------

INCOMPLETE = """\
Just a name here
https://www.vekn.net/event-calendar/event/1234

Crypt (2 cards, min=4, max=4, avg=4)
-------------------------------------
2x Nathan Turner      4 PRO ani                 Gangrel:6

Library (1 cards)
Master (1)
1x Blood Doll
"""


class TestLenientMissingFields:
    def test_raises_when_too_many_fields_missing(self):
        with pytest.raises(ValueError):
            parse_twd_text(INCOMPLETE)
