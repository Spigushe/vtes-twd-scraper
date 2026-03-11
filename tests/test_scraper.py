"""Tests for vtes_scraper.scraper using httpx mocking."""

from datetime import date
from unittest.mock import MagicMock, patch

import httpx
import pytest
from bs4 import BeautifulSoup

from vtes_scraper.scraper import (
    _get,
    _kunena_div_to_text,
    extract_twd_from_thread,
    fetch_event_date,
    fetch_player,
    iter_thread_urls,
    scrape_forum,
)

# ---------------------------------------------------------------------------
# _kunena_div_to_text
# ---------------------------------------------------------------------------


class TestKuneaDivToText:
    def test_replaces_br_with_newline(self):
        html = "<div class='kmsg'>Line 1<br>Line 2</div>"
        soup = BeautifulSoup(html, "lxml")
        div = soup.find("div")
        text = _kunena_div_to_text(div)
        assert "Line 1\nLine 2" in text

    def test_replaces_hr_with_newline(self):
        html = "<div class='kmsg'>Before<hr>After</div>"
        soup = BeautifulSoup(html, "lxml")
        div = soup.find("div")
        text = _kunena_div_to_text(div)
        assert "Before\nAfter" in text

    def test_normalizes_bare_www_url(self):
        html = "<div class='kmsg'>See www.vekn.net/event-calendar/event/123</div>"
        soup = BeautifulSoup(html, "lxml")
        div = soup.find("div")
        text = _kunena_div_to_text(div)
        assert "https://www.vekn.net" in text

    def test_does_not_double_prefix_https_url(self):
        html = (
            "<div class='kmsg'>See https://www.vekn.net/event-calendar/event/123</div>"
        )
        soup = BeautifulSoup(html, "lxml")
        div = soup.find("div")
        text = _kunena_div_to_text(div)
        assert "https://https://" not in text


# ---------------------------------------------------------------------------
# _get
# ---------------------------------------------------------------------------


class TestGet:
    def test_returns_beautifulsoup(self):
        mock_response = MagicMock()
        mock_response.text = "<html><body>Hello</body></html>"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch("vtes_scraper.scraper.time.sleep"):
            soup = _get(mock_client, "https://example.com", delay=0)

        assert soup is not None
        assert soup.find("body") is not None

    def test_raises_on_http_error(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        )
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch("vtes_scraper.scraper.time.sleep"):
            with pytest.raises(httpx.HTTPStatusError):
                _get(mock_client, "https://example.com", delay=0)


# ---------------------------------------------------------------------------
# iter_thread_urls
# ---------------------------------------------------------------------------

FORUM_INDEX_HTML = """
<html><body>
  <a href="/forum/event-reports-and-twd/12345-test-tournament">Test Tournament</a>
  <a href="/forum/event-reports-and-twd/12346-another-event">Another Event</a>
  <a href="/forum/event-reports-and-twd/2119-how-to-report-a-twd">How to Report</a>
  <a href="/other-path/no-match">No match</a>
</body></html>
"""

EMPTY_PAGE_HTML = "<html><body><p>No threads here</p></body></html>"


class TestIterThreadUrls:
    def test_yields_thread_urls(self):
        page1 = BeautifulSoup(FORUM_INDEX_HTML, "lxml")
        page2 = BeautifulSoup(EMPTY_PAGE_HTML, "lxml")

        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", side_effect=[page1, page2]):
            results = list(iter_thread_urls(mock_client, delay=0))

        urls = [url for url, _ in results]
        assert (
            "https://www.vekn.net/forum/event-reports-and-twd/12345-test-tournament"
            in urls
        )
        assert (
            "https://www.vekn.net/forum/event-reports-and-twd/12346-another-event"
            in urls
        )

    def test_skips_meta_slugs(self):
        page1 = BeautifulSoup(FORUM_INDEX_HTML, "lxml")
        page2 = BeautifulSoup(EMPTY_PAGE_HTML, "lxml")

        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", side_effect=[page1, page2]):
            urls = list(iter_thread_urls(mock_client, delay=0))

        assert not any("2119-how-to-report-a-twd" in u for u in urls)

    def test_stops_at_max_pages(self):
        page = BeautifulSoup(FORUM_INDEX_HTML, "lxml")

        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=page):
            urls = list(iter_thread_urls(mock_client, max_pages=1, delay=0))

        # Only page 0 was fetched
        assert len(urls) == 2  # 2 valid threads on the page

    def test_stops_when_no_new_found(self):
        page = BeautifulSoup(EMPTY_PAGE_HTML, "lxml")
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=page):
            urls = list(iter_thread_urls(mock_client, delay=0))
        assert urls == []

    def test_deduplicates_urls(self):
        # Same URL on two pages
        double_html = FORUM_INDEX_HTML + FORUM_INDEX_HTML
        page1 = BeautifulSoup(double_html, "lxml")
        page2 = BeautifulSoup(EMPTY_PAGE_HTML, "lxml")

        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", side_effect=[page1, page2]):
            urls = list(iter_thread_urls(mock_client, delay=0))

        # Should not duplicate
        assert len(urls) == len(set(urls))


# ---------------------------------------------------------------------------
# extract_twd_from_thread
# ---------------------------------------------------------------------------

THREAD_HTML_VALID = """
<html><body>
<div class="kmsg">Conservative Agitation<br>Vila Velha, Brazil<br>October 1st 2016<br>2R+F<br>12 players<br>Ravel Zorzal<br>https://www.vekn.net/event-calendar/event/8470<br><br>Crypt (2 cards, min=4, max=4, avg=4)<br>-------------------------------------<br>2x Nathan Turner      4 PRO ani                 Gangrel:6<br><br>Library (1 cards)<br>Master (1)<br>1x Blood Doll</div>
</body></html>
"""

THREAD_HTML_NO_KMSG = "<html><body><p>Just some text</p></body></html>"
THREAD_HTML_EMPTY_KMSG = "<html><body><div class='kmsg'>   </div></body></html>"
THREAD_HTML_INVALID_TWD = "<html><body><div class='kmsg'>This is not a valid TWD post at all.</div></body></html>"


class TestExtractTwdFromThread:
    def test_valid_thread_returns_tournament(self):
        soup = BeautifulSoup(THREAD_HTML_VALID, "lxml")
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=soup):
            result = extract_twd_from_thread(
                mock_client, "https://example.com", delay=0
            )
        assert result is not None
        assert result.name == "Conservative Agitation"

    def test_no_kmsg_returns_none(self):
        soup = BeautifulSoup(THREAD_HTML_NO_KMSG, "lxml")
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=soup):
            result = extract_twd_from_thread(
                mock_client, "https://example.com", delay=0
            )
        assert result is None

    def test_empty_kmsg_returns_none(self):
        soup = BeautifulSoup(THREAD_HTML_EMPTY_KMSG, "lxml")
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=soup):
            result = extract_twd_from_thread(
                mock_client, "https://example.com", delay=0
            )
        assert result is None

    def test_invalid_twd_returns_none(self):
        soup = BeautifulSoup(THREAD_HTML_INVALID_TWD, "lxml")
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=soup):
            result = extract_twd_from_thread(
                mock_client, "https://example.com", delay=0
            )
        assert result is None


# ---------------------------------------------------------------------------
# fetch_event_date
# ---------------------------------------------------------------------------

JSON_LD_HTML = """
<html><head>
<script type="application/ld+json">{"@type": "Event", "startDate": "2023-03-25T10:00:00"}</script>
</head><body></body></html>
"""

JSON_LD_LIST_HTML = """
<html><head>
<script type="application/ld+json">[{"@type": "Event", "startDate": "2023-03-25"}]</script>
</head><body></body></html>
"""

TIME_TAG_HTML = """
<html><body>
<time datetime="2023-03-25">March 25, 2023</time>
</body></html>
"""

TEXT_SCAN_HTML = """
<html><body>
<p>Event date: 2023-03-25 in Paris</p>
</body></html>
"""

NO_DATE_HTML = "<html><body><p>No date information here.</p></body></html>"

JSON_LD_INVALID_HTML = """
<html><head>
<script type="application/ld+json">not valid json {</script>
</head><body></body></html>
"""

JSON_LD_NO_START_HTML = """
<html><head>
<script type="application/ld+json">{"@type": "Event", "name": "No date here"}</script>
</head><body></body></html>
"""


class TestFetchEventDate:
    def test_json_ld_with_time(self):
        soup = BeautifulSoup(JSON_LD_HTML, "lxml")
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=soup):
            result = fetch_event_date(mock_client, "https://example.com", delay=0)
        assert result == date(2023, 3, 25)

    def test_json_ld_list(self):
        soup = BeautifulSoup(JSON_LD_LIST_HTML, "lxml")
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=soup):
            result = fetch_event_date(mock_client, "https://example.com", delay=0)
        assert result == date(2023, 3, 25)

    def test_time_tag_fallback(self):
        soup = BeautifulSoup(TIME_TAG_HTML, "lxml")
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=soup):
            result = fetch_event_date(mock_client, "https://example.com", delay=0)
        assert result == date(2023, 3, 25)

    def test_text_scan_fallback(self):
        soup = BeautifulSoup(TEXT_SCAN_HTML, "lxml")
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=soup):
            result = fetch_event_date(mock_client, "https://example.com", delay=0)
        assert result == date(2023, 3, 25)

    def test_no_date_returns_none(self):
        soup = BeautifulSoup(NO_DATE_HTML, "lxml")
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=soup):
            result = fetch_event_date(mock_client, "https://example.com", delay=0)
        assert result is None

    def test_invalid_json_ld_skipped(self):
        # Invalid JSON in script tag — falls through to time tag / text scan
        soup = BeautifulSoup(JSON_LD_INVALID_HTML, "lxml")
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=soup):
            result = fetch_event_date(mock_client, "https://example.com", delay=0)
        assert result is None

    def test_json_ld_without_start_date(self):
        soup = BeautifulSoup(JSON_LD_NO_START_HTML, "lxml")
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=soup):
            result = fetch_event_date(mock_client, "https://example.com", delay=0)
        assert result is None


# ---------------------------------------------------------------------------
# scrape_forum (integration via mocking)
# ---------------------------------------------------------------------------


class TestScrapeForum:
    def test_yields_tournaments(self):
        index_soup = BeautifulSoup(FORUM_INDEX_HTML, "lxml")
        empty_soup = BeautifulSoup(EMPTY_PAGE_HTML, "lxml")
        thread_soup = BeautifulSoup(THREAD_HTML_VALID, "lxml")

        def get_side_effect(client, url, delay=1.5):
            if (
                "forum/event-reports-and-twd" in url
                and "limitstart" not in url
                and url.endswith("twd")
            ):
                return index_soup
            elif "12345-test" in url or "12346-another" in url:
                return thread_soup
            else:
                return empty_soup

        with patch("vtes_scraper.scraper._get", side_effect=get_side_effect):
            results = list(scrape_forum(max_pages=1, delay=0))

        assert len(results) > 0


# ---------------------------------------------------------------------------
# fetch_player
# ---------------------------------------------------------------------------

PLAYER_SEARCH_ONE_RESULT = """
<html><body>
<table>
  <tr><th>Name</th><th>VEKN Number</th><th>Country</th></tr>
  <tr><td>Aleksander Idziak</td><td>3940009</td><td>Poland</td></tr>
</table>
</body></html>
"""

PLAYER_SEARCH_NO_RESULT = """
<html><body>
<table>
  <tr><th>Name</th><th>VEKN Number</th></tr>
</table>
</body></html>
"""

PLAYER_SEARCH_MULTI_RESULT = """
<html><body>
<table>
  <tr><th>Name</th><th>VEKN Number</th></tr>
  <tr><td>John Smith</td><td>1000001</td></tr>
  <tr><td>John Smith</td><td>1000002</td></tr>
</table>
</body></html>
"""

PLAYER_SEARCH_EXACT_MATCH = """
<html><body>
<table>
  <tr><th>Name</th><th>VEKN Number</th></tr>
  <tr><td>Jane Doe</td><td>2000001</td></tr>
  <tr><td>Jane Doe Smith</td><td>2000002</td></tr>
</table>
</body></html>
"""

PLAYER_SEARCH_NO_TABLE = "<html><body><p>No results</p></body></html>"

PLAYER_SEARCH_UNRECOGNISED_HEADERS = """
<html><body>
<table>
  <tr><th>Foo</th><th>Bar</th></tr>
  <tr><td>Alice</td><td>99</td></tr>
</table>
</body></html>
"""


class TestFetchPlayer:
    def test_single_result_returns_name_and_number(self):
        soup = BeautifulSoup(PLAYER_SEARCH_ONE_RESULT, "lxml")
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=soup):
            result = fetch_player(mock_client, "Aleksander Idziak", delay=0)
        assert result == ("Aleksander Idziak", "3940009")

    def test_no_result_returns_none(self):
        soup = BeautifulSoup(PLAYER_SEARCH_NO_RESULT, "lxml")
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=soup):
            result = fetch_player(mock_client, "Unknown Player", delay=0)
        assert result is None

    def test_ambiguous_results_returns_none(self):
        soup = BeautifulSoup(PLAYER_SEARCH_MULTI_RESULT, "lxml")
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=soup):
            result = fetch_player(mock_client, "John Smith", delay=0)
        assert result is None

    def test_exact_name_match_among_multiple(self):
        soup = BeautifulSoup(PLAYER_SEARCH_EXACT_MATCH, "lxml")
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=soup):
            result = fetch_player(mock_client, "Jane Doe", delay=0)
        assert result == ("Jane Doe", "2000001")

    def test_no_table_returns_none(self):
        soup = BeautifulSoup(PLAYER_SEARCH_NO_TABLE, "lxml")
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=soup):
            result = fetch_player(mock_client, "Alice", delay=0)
        assert result is None

    def test_unrecognised_headers_returns_none(self):
        soup = BeautifulSoup(PLAYER_SEARCH_UNRECOGNISED_HEADERS, "lxml")
        mock_client = MagicMock()
        with patch("vtes_scraper.scraper._get", return_value=soup):
            result = fetch_player(mock_client, "Alice", delay=0)
        assert result is None
