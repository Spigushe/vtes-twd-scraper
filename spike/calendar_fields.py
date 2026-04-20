#!/usr/bin/env python3
"""
Spike: VEKN calendar field extraction feasibility.

Tests whether the VEKN event calendar reliably exposes the fields
claimed in the design document as source=Calendar:

    location, rounds_format, players_count,
    winner, vekn_number, winner_gw, winner_vp, winner_vp_final

For each event the script fetches the calendar page once, then runs
every extraction strategy and records success/failure and the value
found.  A summary matrix at the end shows success rates per field.

Usage
-----
    python spike/calendar_fields.py
    python spike/calendar_fields.py --event-ids 8470 12012 13096
    python spike/calendar_fields.py --events-file spike/test_events.txt
    python spike/calendar_fields.py --delay 2.0

The script respects the same User-Agent and delay policy as the main
scraper.  Set --delay 0 only in local/CI environments where the server
is not being hit.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CALENDAR_BASE = "https://www.vekn.net/event-calendar/event"
USER_AGENT = (
    "vtes-twd-scraper/spike "
    "(feasibility probe; contact via github.com/spigushe/vtes-twd-scraper)"
)
DEFAULT_DELAY = 2.0

# Regex patterns for rounds format (e.g. "3R+F", "2R+F")
_ROUNDS_PATTERNS = [
    re.compile(r"\b(\d+R\+F)\b"),                    # canonical: "3R+F"
    re.compile(r"\b(\d+)\s*rounds?\s*\+\s*final", re.I),  # "3 rounds + final"
    re.compile(r"\b(\d+)\s*R\s*\+\s*F\b", re.I),    # "3 R + F"
]

# Column header synonyms for the standings table
_POS_HEADERS   = {"pos.", "pos", "rank", "#", "position"}
_PLAYER_HEADERS = {"player", "name", "joueur", "jugador"}
_VEKN_HEADERS  = {"vekn", "vekn#", "member", "number", "vekn number"}
_GW_HEADERS    = {"gw", "game wins", "game win", "wins"}
_VP_HEADERS    = {"vp", "victory points", "points"}
_FINAL_HEADERS = {"final", "final vp", "final round", "finals"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FieldResult:
    found: bool
    value: Any = None
    strategy: str = ""

    def __str__(self) -> str:
        if self.found:
            return f"✓  {self.value!r}  [{self.strategy}]"
        return f"✗  not found"


@dataclass
class EventResult:
    event_id: int
    url: str
    fetch_error: str | None = None
    location: FieldResult = field(default_factory=lambda: FieldResult(False))
    rounds_format: FieldResult = field(default_factory=lambda: FieldResult(False))
    players_count: FieldResult = field(default_factory=lambda: FieldResult(False))
    winner: FieldResult = field(default_factory=lambda: FieldResult(False))
    vekn_number: FieldResult = field(default_factory=lambda: FieldResult(False))
    winner_gw: FieldResult = field(default_factory=lambda: FieldResult(False))
    winner_vp: FieldResult = field(default_factory=lambda: FieldResult(False))
    winner_vp_final: FieldResult = field(default_factory=lambda: FieldResult(False))

    # Raw page text and soup — populated by probe(), used by all extractors
    _soup: BeautifulSoup | None = field(default=None, repr=False)
    _page_text: str = field(default="", repr=False)
    _json_ld: list[dict[str, Any]] = field(default_factory=list, repr=False)


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _load_json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, AttributeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                results.append(item)
    return results


def _col_index(headers: list[str], synonyms: set[str]) -> int | None:
    for idx, h in enumerate(headers):
        if h.strip().lower() in synonyms:
            return idx
    return None


def _find_standings_table(
    soup: BeautifulSoup,
) -> tuple[list[str], list[list[str]]] | None:
    """
    Return (header_texts, data_rows) for the first table that looks like
    a standings table (has a position column and a player column).
    Returns None if no such table is found.
    """
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        header_cells = rows[0].find_all(["th", "td"])
        headers = [c.get_text(strip=True).lower() for c in header_cells]
        if _col_index(headers, _POS_HEADERS) is None:
            continue
        if _col_index(headers, _PLAYER_HEADERS) is None:
            continue
        data_rows = [
            [c.get_text(strip=True) for c in r.find_all(["td", "th"])]
            for r in rows[1:]
            if r.find_all(["td", "th"])
        ]
        return headers, data_rows
    return None


# ---------------------------------------------------------------------------
# Per-field extractors
# ---------------------------------------------------------------------------

def extract_location(r: EventResult) -> FieldResult:
    soup = r._soup
    assert soup is not None

    # Strategy 1: JSON-LD "location" field
    for item in r._json_ld:
        loc = item.get("location")
        if isinstance(loc, dict):
            # Schema.org Place: {"@type":"Place","name":"...","address":{...}}
            name = loc.get("name", "")
            addr = loc.get("address", {})
            city = addr.get("addressLocality", "") if isinstance(addr, dict) else ""
            country = addr.get("addressCountry", "") if isinstance(addr, dict) else ""
            parts = [p for p in [name, city, country] if p]
            if parts:
                return FieldResult(True, ", ".join(parts), "json-ld location object")
        if isinstance(loc, str) and loc:
            return FieldResult(True, loc, "json-ld location string")

    # Strategy 2: <meta name="geo.placename"> or similar
    for meta in soup.find_all("meta"):
        name_attr = (meta.get("name") or meta.get("property") or "").lower()
        if "location" in name_attr or "place" in name_attr or "geo" in name_attr:
            content = meta.get("content", "").strip()
            if content:
                return FieldResult(True, content, f"meta[{name_attr}]")

    # Strategy 3: element with class/id containing "location" or "venue"
    for kw in ("location", "venue", "address", "place"):
        tag = soup.find(class_=re.compile(kw, re.I)) or soup.find(id=re.compile(kw, re.I))
        if tag and isinstance(tag, Tag):
            text = tag.get_text(separator=", ", strip=True)
            if text:
                return FieldResult(True, text, f"element.{kw}")

    # Strategy 4: text scan near "location" or "venue" label
    m = re.search(
        r"(?i)(?:location|venue|lieu|lugar)[:\s]+([A-Za-z\u00C0-\u024F][^\n<]{3,60})",
        r._page_text,
    )
    if m:
        return FieldResult(True, m.group(1).strip(), "text-scan label")

    return FieldResult(False)


def extract_rounds_format(r: EventResult) -> FieldResult:
    # Strategy 1: JSON-LD description or name field
    for item in r._json_ld:
        for key in ("description", "name", "about"):
            text = item.get(key, "")
            if not isinstance(text, str):
                continue
            for pat in _ROUNDS_PATTERNS:
                m = pat.search(text)
                if m:
                    return FieldResult(True, m.group(1) if pat.groups else m.group(0), f"json-ld.{key}")

    # Strategy 2: page text regex scan
    for pat in _ROUNDS_PATTERNS:
        m = pat.search(r._page_text)
        if m:
            raw = m.group(1) if pat.groups else m.group(0)
            # Normalise "3 rounds + final" → "3R+F"
            rounds_m = re.match(r"(\d+)", raw)
            if rounds_m and "round" in raw.lower():
                normalised = f"{rounds_m.group(1)}R+F"
                return FieldResult(True, normalised, "text-scan normalised")
            return FieldResult(True, raw.upper().replace(" ", ""), "text-scan raw")

    return FieldResult(False)


def extract_players_count(
    r: EventResult,
    headers: list[str] | None,
    data_rows: list[list[str]] | None,
) -> FieldResult:
    # Strategy 1: explicit field in JSON-LD
    for item in r._json_ld:
        for key in ("attendeeCount", "maximumAttendeeCapacity", "remainingAttendeeCapacity"):
            val = item.get(key)
            if isinstance(val, int) and val > 0:
                return FieldResult(True, val, f"json-ld.{key}")

    # Strategy 2: element or label
    soup = r._soup
    assert soup is not None
    for kw in ("attendee", "participant", "player"):
        tag = soup.find(class_=re.compile(kw, re.I)) or soup.find(id=re.compile(kw, re.I))
        if tag and isinstance(tag, Tag):
            m = re.search(r"\b(\d+)\b", tag.get_text())
            if m:
                return FieldResult(True, int(m.group(1)), f"element.{kw}")

    m = re.search(r"(?i)(?:players?|participants?)[:\s]+(\d+)", r._page_text)
    if m:
        return FieldResult(True, int(m.group(1)), "text-scan label")

    # Strategy 3: count standings rows (proxy — not the same as registered count)
    if data_rows is not None:
        count = len(data_rows)
        if count > 0:
            return FieldResult(True, count, "standings-row-count (proxy)")

    return FieldResult(False)


def extract_winner_and_score(
    r: EventResult,
    headers: list[str] | None,
    data_rows: list[list[str]] | None,
) -> tuple[FieldResult, FieldResult, FieldResult, FieldResult, FieldResult]:
    """
    Returns (winner, vekn_number, winner_gw, winner_vp, winner_vp_final).
    All derived from the same standings table pass.
    """
    no = FieldResult(False)
    if headers is None or data_rows is None:
        return no, no, no, no, no

    pos_col    = _col_index(headers, _POS_HEADERS)
    player_col = _col_index(headers, _PLAYER_HEADERS)
    vekn_col   = _col_index(headers, _VEKN_HEADERS)
    gw_col     = _col_index(headers, _GW_HEADERS)
    vp_col     = _col_index(headers, _VP_HEADERS)
    final_col  = _col_index(headers, _FINAL_HEADERS)

    # Find first-place row
    first_row: list[str] | None = None
    for row in data_rows:
        if pos_col is not None and pos_col < len(row) and row[pos_col].strip() == "1":
            first_row = row
            break
    if first_row is None and data_rows:
        first_row = data_rows[0]  # fallback: assume sorted

    if first_row is None:
        return no, no, no, no, no

    def _cell(col: int | None) -> str | None:
        if col is not None and col < len(first_row):  # type: ignore[arg-type]
            return first_row[col].strip() or None      # type: ignore[index]
        return None

    def _float(val: str | None) -> float | None:
        if val is None:
            return None
        try:
            return float(val)
        except ValueError:
            return None

    def _int(val: str | None) -> int | None:
        if val is None:
            return None
        try:
            return int(val)
        except ValueError:
            return None

    winner_val = _cell(player_col)
    vekn_val   = _cell(vekn_col)
    gw_val     = _cell(gw_col)
    vp_val     = _cell(vp_col)
    final_val  = _cell(final_col)

    r_winner = FieldResult(bool(winner_val), winner_val, "standings[Player]") if winner_val else no
    r_vekn   = FieldResult(bool(vekn_val and vekn_val.isdigit()), _int(vekn_val), "standings[VEKN#]") if vekn_val else no
    r_gw     = FieldResult(_int(gw_val) is not None, _int(gw_val), "standings[GW]") if gw_val else FieldResult(False, None, f"no GW column (headers: {headers})")
    r_vp     = FieldResult(_float(vp_val) is not None, _float(vp_val), "standings[VP]") if vp_val else FieldResult(False, None, f"no VP column (headers: {headers})")
    r_final  = FieldResult(_float(final_val) is not None, _float(final_val), "standings[Final]") if final_val else FieldResult(False, None, f"no Final column (headers: {headers})")

    return r_winner, r_vekn, r_gw, r_vp, r_final


# ---------------------------------------------------------------------------
# Main probe
# ---------------------------------------------------------------------------

def probe(client: httpx.Client, event_id: int, delay: float) -> EventResult:
    url = f"{CALENDAR_BASE}/{event_id}"
    r = EventResult(event_id=event_id, url=url)

    try:
        response = client.get(url, follow_redirects=True)
        response.raise_for_status()
        time.sleep(delay)
    except Exception as exc:
        r.fetch_error = str(exc)
        return r

    soup = BeautifulSoup(response.text, "lxml")
    r._soup = soup
    r._page_text = soup.get_text(separator=" ")
    r._json_ld = _load_json_ld(soup)

    standings = _find_standings_table(soup)
    headers, data_rows = (standings if standings else (None, None))

    r.location      = extract_location(r)
    r.rounds_format = extract_rounds_format(r)
    r.players_count = extract_players_count(r, headers, data_rows)

    r.winner, r.vekn_number, r.winner_gw, r.winner_vp, r.winner_vp_final = (
        extract_winner_and_score(r, headers, data_rows)
    )

    return r


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

FIELDS = [
    "location",
    "rounds_format",
    "players_count",
    "winner",
    "vekn_number",
    "winner_gw",
    "winner_vp",
    "winner_vp_final",
]


def print_report(results: list[EventResult]) -> None:
    sep = "─" * 72

    for r in results:
        print(f"\n{sep}")
        print(f"Event {r.event_id}  —  {r.url}")
        if r.fetch_error:
            print(f"  FETCH ERROR: {r.fetch_error}")
            continue
        for f in FIELDS:
            fr: FieldResult = getattr(r, f)
            print(f"  {f:<18} {fr}")

    # Summary
    print(f"\n{sep}")
    print(f"SUMMARY  ({len(results)} events)\n")
    print(f"  {'Field':<18} {'Found':>6}  {'Rate':>6}  Notes")
    print(f"  {'─'*18}  {'─'*6}  {'─'*6}  {'─'*30}")

    for f in FIELDS:
        fetched = [r for r in results if not r.fetch_error]
        found = [r for r in fetched if getattr(r, f).found]
        total = len(fetched)
        rate = len(found) / total * 100 if total else 0
        strategies = {getattr(r, f).strategy for r in found}
        note = ", ".join(sorted(strategies)) if strategies else "—"
        print(f"  {f:<18} {len(found):>6}  {rate:>5.0f}%  {note}")

    print()

    # Highlight failures
    critical = ["rounds_format", "location", "players_count", "winner_vp_final"]
    fetched = [r for r in results if not r.fetch_error]
    print("RISK FLAGS (design-doc fields with <100% extraction rate):")
    any_flag = False
    for f in critical:
        found = [r for r in fetched if getattr(r, f).found]
        if len(found) < len(fetched):
            missing = [r.event_id for r in fetched if not getattr(r, f).found]
            print(f"  ⚠  {f:<18} missing on event(s): {missing}")
            any_flag = True
    if not any_flag:
        print("  (none — all critical fields extracted on every tested event)")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_event_ids(path: Path) -> list[int]:
    ids: list[int] = []
    for line in path.read_text().splitlines():
        line = line.split("#")[0].strip()
        if line and line.isdigit():
            ids.append(int(line))
    return ids


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--event-ids", nargs="+", type=int, metavar="ID",
        help="Event IDs to probe (overrides --events-file)",
    )
    parser.add_argument(
        "--events-file", type=Path,
        default=Path(__file__).parent / "test_events.txt",
        help="File with one event ID per line (default: spike/test_events.txt)",
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY,
        help=f"Seconds between requests (default: {DEFAULT_DELAY})",
    )
    args = parser.parse_args(argv)

    if args.event_ids:
        event_ids = args.event_ids
    else:
        event_ids = _load_event_ids(args.events_file)

    if not event_ids:
        print("No event IDs to probe.", file=sys.stderr)
        sys.exit(1)

    print(f"Probing {len(event_ids)} event(s) with {args.delay}s delay…\n")

    headers = {"User-Agent": USER_AGENT}
    results: list[EventResult] = []

    with httpx.Client(headers=headers, timeout=30) as client:
        for event_id in event_ids:
            print(f"  → event {event_id}…", end=" ", flush=True)
            result = probe(client, event_id, args.delay)
            results.append(result)
            status = "ERROR" if result.fetch_error else "ok"
            print(status)

    print_report(results)


if __name__ == "__main__":
    main()
