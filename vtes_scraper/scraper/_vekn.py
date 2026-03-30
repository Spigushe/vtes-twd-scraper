"""VEKN event calendar and player registry lookups."""

import json
import logging
import re
import unicodedata
from datetime import date
from typing import cast
from urllib.parse import quote

import httpx

from vtes_scraper.scraper._http import DEFAULT_DELAY_SECONDS, VEKN_PLAYERS_URL, get_soup

logger = logging.getLogger(__name__)
JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


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

    soup = get_soup(client, event_url, delay)

    # --- Strategy 1: JSON-LD ---
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data: JsonValue = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        except AttributeError:
            continue
        # data may be a single object or a list
        items: list[JsonValue] = data if isinstance(data, list) else [data]
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


def fetch_event_winner(
    client: httpx.Client,
    event_url: str,
    delay: float = DEFAULT_DELAY_SECONDS,
) -> str | None:
    """
    Fetch the winner from a VEKN event calendar page.

    Looks for a standings/results table whose header contains a position column
    (``Pos.``, ``Pos``, ``Rank``, ``#``) and a player column (``Player``).
    Returns the player name at position ``1``, or ``None`` if not found.
    """
    soup = get_soup(client, event_url, delay)

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        header_cells = rows[0].find_all(["th", "td"])
        header_texts = [cell.get_text(strip=True).lower() for cell in header_cells]

        pos_col: int | None = None
        player_col: int | None = None
        for idx, text in enumerate(header_texts):
            if pos_col is None and text in ("pos.", "pos", "rank", "#", "position"):
                pos_col = idx
            if player_col is None and "player" in text:
                player_col = idx

        if pos_col is None or player_col is None:
            continue

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= max(pos_col, player_col):
                continue
            pos_text = cells[pos_col].get_text(strip=True)
            if pos_text == "1":
                player = cells[player_col].get_text(strip=True)
                if player:
                    logger.debug("Calendar winner found: %r at %s", player, event_url)
                    return player

    logger.debug("No winner table found in event page: %s", event_url)
    return None


def fetch_player(
    client: httpx.Client,
    name: str,
    delay: float = DEFAULT_DELAY_SECONDS,
) -> tuple[str, int] | None:
    """
    Look up a player by name in the VEKN member database.

    Queries ``https://www.vekn.net/event-calendar/players?name=<name>&sort=constructed``
    and parses the result table for a matching entry.

    Returns:
        ``(player_name, vekn_number)`` if exactly one player is found, ``None`` otherwise.
    """
    url = f"{VEKN_PLAYERS_URL}?name={quote(name)}&sort=constructed"
    soup = get_soup(client, url, delay)

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
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
        results: list[tuple[str, int]] = []
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= max(name_col, number_col):
                continue
            player_name = cells[name_col].get_text(strip=True)
            player_number_str = cells[number_col].get_text(strip=True)
            if player_name and player_number_str and player_number_str.isdigit():
                results.append((player_name, int(player_number_str)))

        if len(results) == 1:
            return results[0]

        # Multiple results — try exact case-insensitive name match.
        name_lower = name.lower()
        exact = [r for r in results if r[0].lower() == name_lower]
        if len(exact) == 1:
            return exact[0]

        # NFC-normalised match: the VEKN DB may return names in NFD form
        name_nfc = unicodedata.normalize("NFC", name).lower()
        nfc_match = [r for r in results if unicodedata.normalize("NFC", r[0]).lower() == name_nfc]
        if len(nfc_match) == 1:
            return nfc_match[0]

        if results:
            logger.debug(
                "Player search for %r returned %d ambiguous results — skipping",
                name,
                len(results),
            )

    logger.debug("No player found for %r", name)
    return None
