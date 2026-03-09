"""
Scraper for https://www.vekn.net/forum/event-reports-and-twd

The forum runs Kunena (Joomla CMS), NOT phpBB.
Verified against real HTML from vekn.net on 2026-03-08.

Key HTML structure (Kunena crypsis template):
  - Post content: <div class="kmsg">...</div>
  - Line breaks: <br> tags (not newlines) inside the div
  - Section separators in decks: <hr class="bbcode_rule"> (not plain text dashes)
  - Topic links on index page: <a> with href matching /forum/event-reports-and-twd/DIGITS-slug
  - Pagination: ?limitstart=N (Kunena/Joomla convention)

Strategy:
  1. Paginate the forum index to collect thread URLs.
  2. For each thread, fetch the first post (div.kmsg) and convert to plain text.
  3. Pass the raw text to parser.parse_twd_text().
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from datetime import date
from typing import cast
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from vtes_scraper.models import Tournament
from vtes_scraper.parser import parse_twd_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FORUM_BASE = "https://www.vekn.net"
FORUM_INDEX = "https://www.vekn.net/forum/event-reports-and-twd"

# Kunena paginates with ?limitstart=N
TOPICS_PER_PAGE = 20

DEFAULT_DELAY_SECONDS = 1.5

HEADERS = {
    "User-Agent": (
        "vtes-twd-scraper/0.1 "
        "(tournament data archiver; contact via github.com/YOUR_HANDLE/vtes-twd-scraper)"
    )
}

# Matches thread URLs like /forum/event-reports-and-twd/12345-some-title
# MUST start with digits immediately after the category path (no ?start= variants)
# Excludes pagination (?start=, ?limitstart=) and anchor (#) variants
_THREAD_HREF_RE = re.compile(r"^/forum/event-reports-and-twd/(\d+)-[^\"'?#]+$")

# Thread slugs that are meta/admin posts, not TWD reports — skip them
_SKIP_SLUGS = {
    "2119-how-to-report-a-twd",
    "79623-contributing-to-the-twd",
    "63835-howto-use-the-archon-correctly",
}


# ---------------------------------------------------------------------------
# Low-level HTTP helpers
# ---------------------------------------------------------------------------


def _get(
    client: httpx.Client, url: str, delay: float = DEFAULT_DELAY_SECONDS
) -> BeautifulSoup:
    """Fetch a URL and return parsed HTML. Raises on HTTP errors."""
    logger.debug("GET %s", url)
    response = client.get(url, follow_redirects=True)
    response.raise_for_status()
    time.sleep(delay)
    return BeautifulSoup(response.text, "lxml")


def _kunena_div_to_text(div: Tag) -> str:
    """
    Convert a Kunena <div class="kmsg"> to plain text.

    Kunena uses <br> for line breaks and <hr> as section separators.
    BeautifulSoup's get_text() ignores both by default — we handle them
    explicitly before extraction.
    """
    # Replace <hr> with an empty line marker (section separator in library blocks)
    for hr in div.find_all("hr"):
        hr.replace_with("\n")

    # Replace <br> with newline markers
    for br in div.find_all("br"):
        br.replace_with("\n")

    # Normalise URLs: some posts omit the scheme, e.g. "www.vekn.net/event-calendar/..."
    text = div.get_text()
    text = re.sub(r"(?<![:/])www\.vekn\.net", "https://www.vekn.net", text)

    return text


# ---------------------------------------------------------------------------
# Forum index traversal
# ---------------------------------------------------------------------------


def iter_thread_urls(
    client: httpx.Client,
    max_pages: int | None = None,
    delay: float = DEFAULT_DELAY_SECONDS,
) -> Iterator[str]:
    """
    Yield all thread URLs from the forum index, paginating automatically.

    Kunena pagination: ?limitstart=0, ?limitstart=20, ?limitstart=40, ...
    Topic links are <a href="/forum/event-reports-and-twd/DIGITS-slug">
    """
    page = 0
    seen: set[str] = set()

    while True:
        limitstart = page * TOPICS_PER_PAGE
        url = (
            FORUM_INDEX if limitstart == 0 else f"{FORUM_INDEX}?limitstart={limitstart}"
        )
        soup = _get(client, url, delay)

        # Collect all <a> tags whose href matches a clean thread URL pattern
        found_new = False
        for tag in soup.find_all("a", href=True):
            href = cast(str, tag.get("href", ""))
            # Strip query params and anchors before matching — avoids ?start= and #anchor variants
            clean_href = href.split("?")[0].split("#")[0]
            if not _THREAD_HREF_RE.match(clean_href):
                continue
            # Extract the slug (last path segment) and skip meta/admin threads
            slug = clean_href.rsplit("/", 1)[-1]
            if slug in _SKIP_SLUGS:
                continue
            full_url = urljoin(FORUM_BASE, clean_href)
            if full_url not in seen:
                seen.add(full_url)
                found_new = True
                yield full_url

        if not found_new:
            logger.info("No new topics found at limitstart=%d, stopping.", limitstart)
            break

        page += 1
        if max_pages is not None and page >= max_pages:
            logger.info("Reached max_pages=%d, stopping.", max_pages)
            break


# ---------------------------------------------------------------------------
# Per-thread extraction
# ---------------------------------------------------------------------------


def extract_twd_from_thread(
    client: httpx.Client,
    thread_url: str,
    delay: float = DEFAULT_DELAY_SECONDS,
) -> Tournament | None:
    """
    Fetch a thread page and extract the TWD block from the first post.

    The first <div class="kmsg"> on the page is the opening post.
    Returns a Tournament or None if no parseable TWD block is found.
    """
    soup = _get(client, thread_url, delay)

    # Kunena post content lives in <div class="kmsg">
    # The first occurrence is always the opening post
    kmsg = soup.select_one("div.kmsg")
    if not kmsg:
        logger.warning("No div.kmsg found in %s", thread_url)
        return None

    raw_text = _kunena_div_to_text(kmsg)

    if not raw_text.strip():
        logger.warning("Empty post content in %s", thread_url)
        return None

    logger.debug("Raw text preview:\n%s", raw_text[:300])

    try:
        tournament = parse_twd_text(raw_text, forum_post_url=thread_url)
        return tournament
    except (ValueError, Exception) as exc:
        logger.warning("Failed to parse TWD from %s: %s", thread_url, exc)
        logger.debug("Parse traceback:", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Main scrape functions
# ---------------------------------------------------------------------------


def fetch_event_date(
    client: httpx.Client,
    event_url: str,
    delay: float = DEFAULT_DELAY_SECONDS,
) -> date | None:
    """
    Fetch the official start date from a VEKN event calendar page.
    Tries three strategies in order:
      1. JSON-LD structured data (``<script type="application/ld+json">``
         with ``startDate`` key).
      2. HTML ``<time>`` element with a ``datetime`` attribute.
      3. Regex scan of visible page text for an ISO-format date (``YYYY-MM-DD``)
         near a "date" label.
    Returns a ``date`` object, or ``None`` if the date cannot be extracted.
    """
    from datetime import datetime

    soup = _get(client, event_url, delay)

    # --- Strategy 1: JSON-LD ---
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        except AttributeError:
            continue
        # data may be a single object or a list
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            start = item.get("startDate") or item.get("start_date")
            if start and isinstance(start, str):
                # startDate may include time: "2026-01-31T..." — take date part
                date_part = start[:10]
                try:
                    return datetime.strptime(date_part, "%Y-%m-%d").date()
                except ValueError:
                    pass

    # --- Strategy 2: <time datetime="..."> ---
    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag:
        dt_str = cast(str, time_tag.get("datetime", ""))[:10]
        try:
            return datetime.strptime(dt_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    # --- Strategy 3: text scan near a "date" label ---
    page_text = soup.get_text(separator=" ")
    # Look for "date" followed within 60 chars by an ISO date
    iso_near_label = re.search(r"(?i)\bdate[:\s]+(\d{4}-\d{2}-\d{2})", page_text)
    if iso_near_label:
        try:
            return datetime.strptime(iso_near_label.group(1), "%Y-%m-%d").date()
        except ValueError:
            pass

    logger.warning("Could not extract date from event page: %s", event_url)
    return None


def scrape_forum(
    max_pages: int | None = None,
    delay: float = DEFAULT_DELAY_SECONDS,
) -> Iterator[Tournament]:
    """
    Full scrape pipeline: index → threads → parsed Tournament objects.

    Args:
        max_pages: limit forum index pages scraped (None = all)
        delay: polite crawl delay in seconds between requests

    Yields:
        Tournament objects for each successfully parsed TWD post.
    """
    with httpx.Client(headers=HEADERS, timeout=60.0) as client:
        for thread_url in iter_thread_urls(client, max_pages=max_pages, delay=delay):
            tournament = extract_twd_from_thread(client, thread_url, delay=delay)
            if tournament:
                logger.info(
                    "Scraped: [%s] %s — %s",
                    tournament.event_id,
                    tournament.name,
                    tournament.date_start,
                )
                yield tournament
            else:
                logger.debug("Skipped (no valid TWD): %s", thread_url)
