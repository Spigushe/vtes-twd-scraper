"""
Scraper for https://www.vekn.net/forum/event-reports-and-twd

Submodules:
  _http   — low-level HTTP helpers and shared constants
  _icons  — topic icon detection
  _forum  — forum index traversal and per-thread TWD extraction
  _vekn   — VEKN event calendar and player registry lookups
"""

from vtes_scraper.scraper._forum import (
    extract_twd_from_thread,
    iter_thread_urls,
    scrape_forum,
)
from vtes_scraper.scraper._http import (
    DEFAULT_DELAY_SECONDS,
    HEADERS,
    _get,
    _kunena_div_to_text,
)
from vtes_scraper.scraper._icons import (
    ICON_DEFAULT,
    ICON_IDEA,
    ICON_MERGED,
    ICON_SOLVED,
    _detect_topic_icon,
)
from vtes_scraper.scraper._vekn import (
    fetch_event_date,
    fetch_event_winner,
    fetch_player,
)
import time  # Ensure time module is available for patching in tests

__all__ = [
    # Constants
    "DEFAULT_DELAY_SECONDS",
    "HEADERS",
    "ICON_DEFAULT",
    "ICON_IDEA",
    "ICON_MERGED",
    "ICON_SOLVED",
    # HTTP helpers
    "_get",
    "_kunena_div_to_text",
    # Icons
    "_detect_topic_icon",
    # Forum
    "extract_twd_from_thread",
    "iter_thread_urls",
    "scrape_forum",
    # VEKN
    "fetch_event_date",
    "fetch_event_winner",
    "fetch_player",
]
