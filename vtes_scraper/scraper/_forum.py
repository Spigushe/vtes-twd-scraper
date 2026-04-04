"""Forum index traversal and per-thread TWD extraction."""

import logging
from collections.abc import Iterator
from typing import cast
from urllib.parse import urljoin

import httpx

from vtes_scraper.models import Tournament
from vtes_scraper.parser import parse_twd_text
from vtes_scraper.scraper._http import (
    DEFAULT_DELAY_SECONDS,
    FORUM_BASE,
    FORUM_INDEX,
    SKIP_SLUGS,
    THREAD_HREF_RE,
    TOPICS_PER_PAGE,
    get_soup,
    kunena_div_to_text,
)
from vtes_scraper.scraper._icons import (
    ICON_IDEA,
    ICON_MERGED,
    detect_topic_icon,
)

logger = logging.getLogger(__name__)


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
        url = FORUM_INDEX if limitstart == 0 else f"{FORUM_INDEX}?limitstart={limitstart}"
        logger.info(
            "Scraping forum index page %d (limitstart=%d).",
            page + 1,
            limitstart,
        )
        soup = get_soup(client, url, delay)

        # Collect all <a> tags whose href matches a clean thread URL pattern
        found_new = False
        for tag in soup.find_all("a", href=True):
            href = cast(str, tag.get("href", ""))
            # Strip query params and anchors before matching
            clean_href = href.split("?")[0].split("#")[0]
            if not THREAD_HREF_RE.match(clean_href):
                continue
            # Extract the slug (last path segment) and skip meta/admin threads
            slug = clean_href.rsplit("/", 1)[-1]
            if slug in SKIP_SLUGS:
                continue
            full_url = urljoin(FORUM_BASE, clean_href)
            if full_url not in seen:
                seen.add(full_url)
                found_new = True
                icon = detect_topic_icon(tag)
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
) -> Tournament | None:
    """
    Fetch a thread and extract the TWD block from its first post.

    TWD content is almost always in the opening post, so only the first
    ``<div class="kmsg">`` on the first page is checked.

    Returns a Tournament or None if no parseable TWD block is found.
    """
    logger.info("Scraping thread: %s", thread_url)
    soup = get_soup(client, thread_url, delay)

    posts = soup.select("div.kmsg")
    if not posts:
        logger.warning("No div.kmsg found in %s", thread_url)
        return None

    kmsg = posts[0]
    raw_text = kunena_div_to_text(kmsg)
    if not raw_text.strip():
        logger.info("First post is empty in %s", thread_url)
        return None

    logger.debug("Raw text preview:\n%s", raw_text[:300])
    try:
        tournament = parse_twd_text(raw_text, forum_post_url=thread_url)
    except (ValueError, Exception) as exc:
        logger.warning("First post not parseable in %s: %s", thread_url, exc)
        return None

    return tournament


def scrape_forum(
    client: httpx.Client,
    max_pages: int | None = None,
    start_page: int = 0,
    delay: float = DEFAULT_DELAY_SECONDS,
) -> Iterator[tuple[Tournament, str | None]]:
    """
    Scrape the forum index and yield parsed Tournament objects.

    Topics with an idea icon (:data:`ICON_IDEA`) are skipped entirely.
    Only the first post of each thread is checked for TWD content.

    Args:
        client: HTTP client to use for all requests.
        max_pages: limit forum index pages scraped (None = all).
        start_page: forum index page to start from (0-indexed, default: 0).
        delay: polite crawl delay in seconds between requests.

    Yields:
        ``(Tournament, icon_type)`` pairs for each successfully parsed TWD post.
    """
    for thread_url, icon in iter_thread_urls(
        client, max_pages=max_pages, start_page=start_page, delay=delay
    ):
        if icon == ICON_IDEA:
            logger.debug("Skipped (idea/info icon): %s", thread_url)
            continue

        tournament = extract_twd_from_thread(client, thread_url, delay=delay)
        if tournament:
            logger.debug(
                "Scraped%s: [%s] %s — %s",
                " (fix required)" if icon == ICON_MERGED else "",
                tournament.event_id,
                tournament.name,
                tournament.date_start,
            )
            yield tournament, icon
        else:
            logger.debug("Skipped (no valid TWD): %s", thread_url)
