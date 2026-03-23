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
  - Topic icons: <img src=".../media/kunena/topic_icons/default/user/<name>.png">
      - idea.png    → informational post only, skip scraping
      - merged.png  → changes requested, scrape to changes_required/
      - solved.png  → already in TWD, scrape as usual
      - default.png → not yet in TWD, scrape as usual

Strategy:
  1. Paginate the forum index to collect thread URLs + their topic icon.
  2. Skip topics with idea icon (info only).
  3. For each remaining thread, fetch the first page and parse only the first post
     (div.kmsg), which is where the TWD content is always posted.
  4. Pass the raw text to parser.parse_twd_text().
  5. Merged topics are flagged so the caller can write them to changes_required/.
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from difflib import SequenceMatcher
from collections.abc import Iterator
from datetime import date
from typing import cast
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from vtes_scraper.models import Tournament
from vtes_scraper.parser import parse_twd_text

# ---------------------------------------------------------------------------
# Topic icon types
# ---------------------------------------------------------------------------
# Icons are served from https://www.vekn.net/media/kunena/topic_icons/default/user/
# Each constant's value matches the icon filename stem.

#: Changes have been requested — scrape and store in changes_required/.
ICON_MERGED = "merged"

#: Deck already added to the official TWD — scrape and store as usual.
ICON_SOLVED = "solved"

#: Informational post only — do not scrape.
ICON_IDEA = "idea"

#: Not yet in TWD — scrape and store as usual.
ICON_DEFAULT = "default"


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FORUM_BASE = "https://www.vekn.net"
FORUM_INDEX = "https://www.vekn.net/forum/event-reports-and-twd"
VEKN_PLAYERS_URL = "https://www.vekn.net/event-calendar/players"

# Kunena paginates with ?limitstart=N
TOPICS_PER_PAGE = 20
POSTS_PER_THREAD_PAGE = 6

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
# Topic icon detection
# ---------------------------------------------------------------------------

# Base URL prefix for Kunena user topic icons on vekn.net
_ICON_BASE = "media/kunena/topic_icons/default/user/"

# Ordered mapping: icon filename stem → constant.
# Checked against <img src="..."> in the topic row.
_ICON_SRC_MAP: tuple[tuple[str, str], ...] = (
    ("merged", ICON_MERGED),
    ("solved", ICON_SOLVED),
    ("idea", ICON_IDEA),
    ("default", ICON_DEFAULT),
)


def _detect_topic_icon(link_tag: Tag) -> str | None:
    """
    Given a topic ``<a>`` tag from the forum index, detect its icon type.

    Walks up the DOM tree to find the nearest row container (``<tr>``,
    ``<li>``, or ``<div>`` whose class hints at a topic row), then looks
    for an ``<img>`` whose ``src`` contains the Kunena user-icon path.

    Returns one of :data:`ICON_MERGED`, :data:`ICON_SOLVED`,
    :data:`ICON_IDEA`, :data:`ICON_DEFAULT`, or ``None`` if no
    recognised icon is found.
    """
    # Walk up to find the row container
    row: Tag | None = None
    node = link_tag.parent
    for _ in range(8):
        if node is None or node.name in ("html", "body", "[document]"):
            break
        name = getattr(node, "name", "") or ""
        classes = " ".join(node.get("class") or []).lower()
        if name in ("tr", "li") or any(
            kw in classes for kw in ("krow", "ktopic", "row", "topic-item", "klist")
        ):
            row = node
            break
        node = node.parent

    search_root = row if row is not None else link_tag.parent
    if not search_root:
        return None

    for img in search_root.find_all("img"):
        src = str(img.get("src") or "").lower()
        if _ICON_BASE not in src:
            continue
        for stem, icon_type in _ICON_SRC_MAP:
            if f"{stem}.png" in src:
                return icon_type

    return None


# ---------------------------------------------------------------------------
# Forum index traversal
# ---------------------------------------------------------------------------


def iter_thread_urls(
    client: httpx.Client,
    max_pages: int | None = None,
    start_page: int = 0,
    delay: float = DEFAULT_DELAY_SECONDS,
) -> Iterator[tuple[str, str | None]]:
    """
    Yield ``(thread_url, icon_type)`` pairs from the forum index.

    Kunena pagination: ?limitstart=0, ?limitstart=20, ?limitstart=40, ...
    Topic links are <a href="/forum/event-reports-and-twd/DIGITS-slug">

    ``icon_type`` is one of :data:`ICON_IDEA`, :data:`ICON_MERGED`, or ``None``
    (no recognised icon).
    """
    page = start_page
    seen: set[str] = set()

    while True:
        limitstart = page * TOPICS_PER_PAGE
        url = (
            FORUM_INDEX if limitstart == 0 else f"{FORUM_INDEX}?limitstart={limitstart}"
        )
        logger.info(
            "Scraping forum index page %d (limitstart=%d).", page + 1, limitstart
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
                icon = _detect_topic_icon(tag)
                yield full_url, icon

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
    fast_check: bool = True,
) -> Tournament | None:
    """
    Fetch a thread and extract the TWD block from its posts.

    Two modes are available:

    * **fast_check=True** (default): fetch only the first page and parse only
      the first ``<div class="kmsg">``.  TWD content is almost always in the
      opening post, so this is sufficient for the vast majority of threads.

    * **fast_check=False**: paginate through all thread pages and try every
      post in order, returning the first one that parses successfully.  Use
      this as a fallback when the opening post is not the TWD (e.g. the
      original post was edited and the deck moved to a reply).

    Returns a Tournament or None if no parseable TWD block is found.
    """
    if fast_check:
        return _extract_twd_fast(client, thread_url, delay)
    return _extract_twd_slow(client, thread_url, delay)


def _extract_twd_fast(
    client: httpx.Client,
    thread_url: str,
    delay: float,
) -> Tournament | None:
    """Check only the first post on the first page."""
    logger.info("Scraping thread (fast): %s", thread_url)
    soup = _get(client, thread_url, delay)

    posts = soup.select("div.kmsg")
    if not posts:
        logger.warning("No div.kmsg found in %s", thread_url)
        return None

    kmsg = posts[0]
    raw_text = _kunena_div_to_text(kmsg)
    if not raw_text.strip():
        logger.debug("First post is empty in %s", thread_url)
        return None

    logger.debug("Raw text preview:\n%s", raw_text[:300])
    try:
        return parse_twd_text(raw_text, forum_post_url=thread_url)
    except (ValueError, Exception) as exc:
        logger.warning("First post not parseable in %s: %s", thread_url, exc)
        return None


def _extract_twd_slow(
    client: httpx.Client,
    thread_url: str,
    delay: float,
) -> Tournament | None:
    """Paginate through all thread pages and check every post."""
    page = 0
    seen_posts: set[str] = set()

    while True:
        limitstart = page * POSTS_PER_THREAD_PAGE
        url = thread_url if limitstart == 0 else f"{thread_url}?limitstart={limitstart}"
        logger.info("Scraping thread (slow) page %d: %s", page + 1, url)
        soup = _get(client, url, delay)

        posts = soup.select("div.kmsg")
        if not posts:
            logger.warning("No div.kmsg found on page %d of %s", page + 1, thread_url)
            break

        found_new = False
        for post_idx, kmsg in enumerate(posts, start=1):
            post_key = str(kmsg)
            if post_key in seen_posts:
                continue
            seen_posts.add(post_key)
            found_new = True

            logger.debug(
                "Checking post %d on thread page %d of %s",
                post_idx,
                page + 1,
                thread_url,
            )
            raw_text = _kunena_div_to_text(kmsg)
            if not raw_text.strip():
                logger.debug("Empty post %d on page %d, skipping.", post_idx, page + 1)
                continue

            logger.debug("Raw text preview:\n%s", raw_text[:300])
            try:
                tournament = parse_twd_text(raw_text, forum_post_url=thread_url)
                return tournament
            except (ValueError, Exception) as exc:
                logger.debug(
                    "Post %d on page %d not parseable: %s", post_idx, page + 1, exc
                )

        if not found_new:
            logger.info(
                "No new posts on page %d of %s, stopping.", page + 1, thread_url
            )
            break

        page += 1

    logger.warning("No parseable TWD post found in %s", thread_url)
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


_NAME_SIMILARITY_THRESHOLD = 0.80
"""
Minimum SequenceMatcher ratio for a fuzzy name match to be accepted in
:func:`fetch_player`.  Only used when exactly one result scores at or above
this threshold; ambiguous cases (≥ 2 high-scoring results) are always skipped.
"""


def _strip_accents_lower(s: str) -> str:
    """Return *s* with diacritics stripped and lower-cased (used for comparison only)."""
    return (
        re.sub(
            r"[^\w\s]",
            "",
            unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("ascii"),
        )
        .strip()
        .lower()
    )


def _name_similarity(a: str, b: str) -> float:
    """Return SequenceMatcher ratio between the accent-stripped lower-case forms of *a* and *b*."""
    return SequenceMatcher(
        None, _strip_accents_lower(a), _strip_accents_lower(b)
    ).ratio()


def fetch_player(
    client: httpx.Client,
    name: str,
    delay: float = DEFAULT_DELAY_SECONDS,
) -> tuple[str, str] | None:
    """
    Look up a player by name in the VEKN member database.

    Queries ``https://www.vekn.net/event-calendar/players?name=<name>&sort=constructed``
    and parses the result table for a matching entry.

    Returns:
        ``(player_name, vekn_number)`` if exactly one player is found, ``None`` otherwise.
    """
    url = f"{VEKN_PLAYERS_URL}?name={quote(name)}&sort=constructed"
    soup = _get(client, url, delay)

    # The VEKN player search renders results in an HTML table.
    # We look for the first <table> that contains player rows and extract
    # the name and member number columns.
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        # Need at least a header row and one data row
        if len(rows) < 2:
            continue

        # Determine column indices from header row
        header_cells = rows[0].find_all(["th", "td"])
        header_texts = [cell.get_text(strip=True).lower() for cell in header_cells]

        name_col: int | None = None
        number_col: int | None = None
        for idx, text in enumerate(header_texts):
            if "name" in text and name_col is None:
                name_col = idx
            if "number" in text or "vekn" in text or "member" in text:
                if number_col is None:
                    number_col = idx

        if name_col is None or number_col is None:
            continue

        # Collect data rows
        results: list[tuple[str, str]] = []
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= max(name_col, number_col):
                continue
            player_name = cells[name_col].get_text(strip=True)
            player_number = cells[number_col].get_text(strip=True)
            if player_name and player_number:
                results.append((player_name, player_number))

        if len(results) == 1:
            return results[0]

        # Multiple results — try exact case-insensitive name match.
        name_lower = name.lower()
        exact = [r for r in results if r[0].lower() == name_lower]
        if len(exact) == 1:
            return exact[0]

        # NFC-normalised match: the VEKN DB may return names in NFD form (decomposed
        # accents) while our query string is NFC, making the plain .lower() comparison
        # fail despite the names being canonically identical.
        name_nfc = unicodedata.normalize("NFC", name).lower()
        nfc_match = [
            r for r in results if unicodedata.normalize("NFC", r[0]).lower() == name_nfc
        ]
        if len(nfc_match) == 1:
            return nfc_match[0]

        # Accent-stripped match: handles cases where the VEKN DB stores ASCII-only
        # names (e.g. "David Valles Gomez") while the query uses diacritics
        # ("David Vallès Gómez"), or vice-versa.
        name_ascii = _strip_accents_lower(name)
        accent_match = [r for r in results if _strip_accents_lower(r[0]) == name_ascii]
        if len(accent_match) == 1:
            return accent_match[0]

        # Similarity match: handles the case where the query name is a shorter form of
        # the canonical VEKN name (e.g. "Rafael Barbosa" matching "Rafael Barbosa Santos").
        # Only accepted when exactly one result scores at or above the threshold so that
        # genuinely ambiguous cases (two different "Rafael Barbosa X" members) are still
        # skipped.
        similar = [
            r
            for r in results
            if _name_similarity(name, r[0]) >= _NAME_SIMILARITY_THRESHOLD
        ]
        if len(similar) == 1:
            logger.debug(
                "Player %r matched by similarity to %r (%.2f)",
                name,
                similar[0][0],
                _name_similarity(name, similar[0][0]),
            )
            return similar[0]

        if results:
            logger.debug(
                "Player search for %r returned %d results — skipping ambiguous match",
                name,
                len(results),
            )

    logger.debug("No player found for %r", name)
    return None


def scrape_forum(
    max_pages: int | None = None,
    start_page: int = 0,
    delay: float = DEFAULT_DELAY_SECONDS,
    fast_check: bool = True,
) -> Iterator[tuple[Tournament, str | None]]:
    """
    Full scrape pipeline: index pages → threads → posts → parsed Tournament objects.

    Topics with an idea icon (:data:`ICON_IDEA`) are skipped entirely —
    they contain informational content, not TWD reports.

    Args:
        max_pages: limit forum index pages scraped (None = all)
        start_page: forum index page to start from (0-indexed, default: 0)
        delay: polite crawl delay in seconds between requests
        fast_check: when True (default) only the first post of each thread is
            parsed; when False every post on every page is tried in order.

    Yields:
        ``(Tournament, icon_type)`` pairs for each successfully parsed TWD post.
        ``icon_type`` is :data:`ICON_MERGED` when changes are requested
        (caller should write to ``changes_required/``), or one of
        :data:`ICON_SOLVED` / :data:`ICON_DEFAULT` / ``None`` for normal topics.
    """
    with httpx.Client(headers=HEADERS, timeout=60.0) as client:
        for thread_url, icon in iter_thread_urls(
            client, max_pages=max_pages, start_page=start_page, delay=delay
        ):
            if icon == ICON_IDEA:
                logger.info("Skipped (idea/info icon): %s", thread_url)
                continue

            tournament = extract_twd_from_thread(
                client, thread_url, delay=delay, fast_check=fast_check
            )
            if tournament:
                logger.info(
                    "Scraped%s: [%s] %s — %s",
                    " (fix required)" if icon == ICON_MERGED else "",
                    tournament.event_id,
                    tournament.name,
                    tournament.date_start,
                )
                yield tournament, icon
            else:
                logger.debug("Skipped (no valid TWD): %s", thread_url)
