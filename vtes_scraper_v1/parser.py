"""
Parser for TWD posts scraped from the VEKN forum.

The README defines a strict 7-line template, but real forum posts deviate
significantly. This parser uses two strategies in order:

  1. STRICT mode  — expects exact 7-line header (name, location, date, format,
                    players, winner, url) with no blank lines between them.
  2. LENIENT mode — scans for labeled fields anywhere in the header block
                    (e.g. "Winner: X", "Author: Y") and infers unlabeled ones
                    by their content (URL pattern, player count, rounds format).

Both modes then call _parse_deck_block() for the Crypt + Library section.

Observed real-world deviations (documented from scraping 2026-03-08):
  - "Winner: Name" labeled line instead of bare name
  - "Author:" instead of "Created by:"
  - "3R+Final" or "2R + Final" instead of canonical "3R+F"
  - URL under player-registry instead of event-calendar
  - Extra unlabeled text lines (VP comment embedded in header)
  - Fields out of canonical order (e.g. players before rounds)
"""

from __future__ import annotations

import re

from vtes_scraper_v1.models import (
    CryptCard,
    Deck,
    LibraryCard,
    LibrarySection,
    Tournament,
)

# ---------------------------------------------------------------------------
# Regex constants
# ---------------------------------------------------------------------------

CRYPT_HEADER_RE = re.compile(
    r"Crypt\s*\((?P<count>\d+)\s*cards?,\s*min=(?P<min>\d+),?\s*max=(?P<max>\d+),?\s*avg=(?P<avg>[\d.]+)\)"
)
LIBRARY_HEADER_RE = re.compile(r"Library\s*\((?P<count>\d+)\s*cards?\)")

# Regex for crypt line parsing (handles both compact and column-aligned formats):
#   <Qty>x <Name> <Capacity>( <discipline:3chars>)+ <Clan>:<grouping>
CRYPT_LINE_RE = re.compile(
    r"^(?P<count>\d+)x\s+"
    r"(?P<name>.+?)\s+"
    r"(?P<capacity>\d{1,2})"
    r"(?P<disciplines>(?:\s+[a-zA-Z]{3})+)\s+"
    r"(?P<clan>[^:]+):(?P<grouping>\d+)\s*$"
)
LIBRARY_LINE_RE = re.compile(r"^(?P<count>\d+)x\s+(?P<name>.+)$")
SECTION_HEADER_RE = re.compile(r"^(?P<name>[A-Za-z /,()]+)\s*\((?P<count>\d+).*\)$")

# Known VTES titles that appear between disciplines and clan name in crypt lines
_TITLE_RE = re.compile(
    r"^(Baron|Prince|Primogen|Justicar|Inner Circle"
    r"|Archbishop|Bishop|Priscus|Cardinal|Regent"
    r"|Magaji|1 vote|2 votes)\s+",
    re.IGNORECASE,
)

ROUNDS_RE = re.compile(r"(\d+)\s*R\s*\+\s*F(?:inal)?", re.IGNORECASE)
PLAYERS_RE = re.compile(r"(\d+)\s*[Pp]layers?")
VEKN_URL_RE = re.compile(r"https?://(?:www\.)?vekn\.net/\S+?/(\d+)\b")
WINNER_LABEL_RE = re.compile(r"^Winner\s*:\s*(.+)$", re.IGNORECASE)
DECK_NAME_RE = re.compile(r"^Deck\s*Name\s*[:\s]\s*(.+)$", re.IGNORECASE)
CREATED_BY_RE = re.compile(r"^(?:Created\s*by|Author)\s*:\s*(.+)$", re.IGNORECASE)
DESCRIPTION_RE = re.compile(r"^Description\s*:\s*(.*)$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_inline_comment(line: str) -> tuple[str, str | None]:
    if " -- " in line:
        parts = line.split(" -- ", 1)
        return parts[0].rstrip(), parts[1].strip()
    return line.strip(), None


def _strip_hash_comment(line: str) -> str:
    idx = line.find("#")
    if idx >= 0:
        return line[:idx].rstrip()
    return line.rstrip()


def _normalize_rounds(raw: str) -> str:
    """Normalize '3R+Final', '2R + F', '2 R+F' -> '3R+F'."""
    m = ROUNDS_RE.search(raw)
    if m:
        return f"{m.group(1)}R+F"
    return raw.strip()


def _extract_vekn_url(line: str) -> str | None:
    m = VEKN_URL_RE.search(line)
    if m:
        return m.group(0)
    bare = re.search(r"(?<![:/])www\.vekn\.net/\S+?/(\d+)\b", line)
    if bare:
        return "https://" + bare.group(0)
    return None


def _split_date(raw: str) -> tuple[str, str | None]:
    raw = re.split(r",?\s*\d{1,2}:\d{2}", raw)[0].strip()
    if " -- " in raw:
        parts = raw.split(" -- ", 1)
        return parts[0].strip(), parts[1].strip()
    return raw, None


# ---------------------------------------------------------------------------
# Card line parsers
# ---------------------------------------------------------------------------


def _parse_crypt_line(line: str) -> CryptCard | None:
    """
    Parse a VTES crypt line.

    Handles both compact and column-aligned formats:
        <Qty>x <Name> <Capacity> <disc1> [<disc2> ...] <Clan>:<grouping>

    Examples:
        2x Nathan Turner 4 PRO ani Gangrel:6
        2x Nathan Turner      4 PRO ani                 Gangrel:6
    """
    line, comment = _strip_inline_comment(line)
    line = line.strip()

    m = CRYPT_LINE_RE.match(line)
    if not m:
        return None
    raw_clan = m.group("clan").strip()
    title_m = _TITLE_RE.match(raw_clan)
    if title_m:
        title: str | None = title_m.group(1)
        clan = raw_clan[title_m.end() :].strip()
    else:
        title = None
        clan = raw_clan
    return CryptCard(
        count=int(m.group("count")),
        name=m.group("name").strip(),
        capacity=int(m.group("capacity")),
        disciplines=m.group("disciplines").strip(),
        clan=clan,
        grouping=int(m.group("grouping")),
        title=title,
        comment=comment,
    )


def _parse_library_line(line: str) -> LibraryCard | None:
    line, comment = _strip_inline_comment(line)
    m = LIBRARY_LINE_RE.match(line.strip())
    if not m:
        return None
    return LibraryCard(
        count=int(m.group("count")),
        name=m.group("name").strip(),
        comment=comment,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def parse_twd_text(raw: str, forum_post_url: str | None = None) -> Tournament:
    lines = [_strip_hash_comment(line) for line in raw.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    if len(lines) < 7:
        raise ValueError(f"TWD block has fewer than 7 mandatory lines (got {len(lines)})")

    deck_start = next((i for i, line in enumerate(lines) if CRYPT_HEADER_RE.search(line)), None)
    if deck_start is None:
        raise ValueError("Mandatory 'Crypt (N cards, ...)' block not found")

    header_lines = lines[:deck_start]

    try:
        fields = _parse_header_strict(header_lines)
    except ValueError:
        fields = _parse_header_lenient(header_lines)

    deck = _parse_deck_block(lines)  # receives full lines; finds crypt idx itself
    return Tournament(forum_post_url=forum_post_url, deck=deck, **fields)


# ---------------------------------------------------------------------------
# Header parsers
# ---------------------------------------------------------------------------


def _parse_header_strict(lines: list[str]) -> dict:
    non_blank = [line.strip() for line in lines if line.strip()]
    if len(non_blank) < 7:
        raise ValueError(f"Strict: need 7 non-blank lines, got {len(non_blank)}")

    name, location, raw_date, rounds_raw, players_raw, winner, event_url = non_blank[:7]

    if not PLAYERS_RE.search(players_raw):
        raise ValueError(f"Strict: line 4 not player count: {players_raw!r}")
    if not ROUNDS_RE.search(rounds_raw):
        raise ValueError(f"Strict: line 3 not rounds format: {rounds_raw!r}")
    if "vekn.net" not in event_url:
        raise ValueError(f"Strict: line 6 not vekn URL: {event_url!r}")

    date_start, date_end = _split_date(raw_date)

    vp_comment: str | None = None
    for line in non_blank[7:]:
        if line.startswith("-") or re.search(r"vp|gw|final", line, re.IGNORECASE):
            vp_comment = line.lstrip("- ").strip()
            break

    return dict(
        name=name,
        location=location,
        date_start=date_start,
        date_end=date_end,
        rounds_format=_normalize_rounds(rounds_raw),
        players_count=players_raw,
        winner=winner,
        event_url=_extract_vekn_url(event_url) or event_url,
        vp_comment=vp_comment,
    )


def _parse_header_lenient(lines: list[str]) -> dict:
    non_blank = [line.strip() for line in lines if line.strip()]

    name = location = date_start = date_end = None
    rounds_format = players_count = winner = event_url = vp_comment = None
    unlabeled: list[str] = []

    for line in non_blank:
        # Rounds
        if ROUNDS_RE.search(line) and not PLAYERS_RE.search(line):
            rounds_format = _normalize_rounds(line)
            continue
        # Players (short line only — avoids matching "X players won with...")
        pm = PLAYERS_RE.search(line)
        if pm and len(line) < 30:
            players_count = line
            continue
        # Winner labeled
        wm = WINNER_LABEL_RE.match(line)
        if wm:
            winner = wm.group(1).strip()
            continue
        # VEKN URL
        url = _extract_vekn_url(line)
        if url:
            if event_url is None:
                event_url = url
            continue
        # VP/GW comment
        if re.match(r"^[-\d]", line) and re.search(r"vp|gw|final", line, re.IGNORECASE):
            vp_comment = line.lstrip("- ").strip()
            continue
        # Stop at deck metadata
        if DECK_NAME_RE.match(line) or CREATED_BY_RE.match(line) or DESCRIPTION_RE.match(line):
            break

        unlabeled.append(line)

    if unlabeled:
        name = unlabeled[0]
    if len(unlabeled) >= 2:
        location = unlabeled[1]
    if len(unlabeled) >= 3:
        date_start, date_end = _split_date(unlabeled[2])
    if winner is None and len(unlabeled) >= 4:
        winner = unlabeled[3]

    missing = [
        f
        for f, v in [
            ("name", name),
            ("location", location),
            ("date_start", date_start),
            ("rounds_format", rounds_format),
            ("players_count", players_count),
            ("winner", winner),
            ("event_url", event_url),
        ]
        if not v
    ]
    if missing:
        raise ValueError(f"Lenient parse: missing fields {missing}")

    return dict(
        name=name,
        location=location,
        date_start=date_start,
        date_end=date_end,
        rounds_format=rounds_format,
        players_count=players_count,
        winner=winner,
        event_url=event_url,
        vp_comment=vp_comment,
    )


# ---------------------------------------------------------------------------
# Deck block parser
# ---------------------------------------------------------------------------


def _parse_deck_block(lines: list[str]) -> Deck:
    deck_name: str | None = None
    created_by: str | None = None
    description: str = ""
    crypt_count = crypt_min = crypt_max = 0
    crypt_avg = 0.0
    crypt_cards: list[CryptCard] = []
    library_count = 0
    library_sections: list[LibrarySection] = []

    # Lines before the Crypt header = deck metadata (Deck Name, Author, Description)
    crypt_header_idx = next((i for i, line in enumerate(lines) if CRYPT_HEADER_RE.search(line)), 0)
    _collecting_description = False
    for line in lines[:crypt_header_idx]:
        s = line.strip()
        if not s:
            _collecting_description = False  # blank line ends multiline description
            continue
        # Multiline description continuation (line after "Description:" with empty value)
        if _collecting_description:
            description = s
            _collecting_description = False
            continue
        m = DECK_NAME_RE.match(s)
        if m:
            deck_name = m.group(1).strip() or None
            continue
        m = CREATED_BY_RE.match(s)
        if m:
            created_by = m.group(1).strip() or None
            continue
        m = DESCRIPTION_RE.match(s)
        if m:
            value = m.group(1).strip()
            if value:
                description = value
            else:
                _collecting_description = True  # value on next line
            continue
        # All other lines (tournament header, VP comments, unlabeled text) are ignored

    idx = crypt_header_idx
    n = len(lines)

    # --- Crypt (mandatory) ---
    m = CRYPT_HEADER_RE.search(lines[idx])
    if not m:
        raise ValueError("Mandatory 'Crypt (N cards, ...)' block not found in deck")

    crypt_count = int(m.group("count"))
    crypt_min = int(m.group("min"))
    crypt_max = int(m.group("max"))
    crypt_avg = float(m.group("avg"))
    idx += 1

    if idx < n and lines[idx].strip() and lines[idx].strip()[0] in ("-", "="):
        idx += 1

    while idx < n:
        line = lines[idx]
        if LIBRARY_HEADER_RE.search(line):
            break
        if not line.strip():  # empty lines between cards — skip, don't break
            idx += 1
            continue
        crypt_card = _parse_crypt_line(line)
        if crypt_card:
            crypt_cards.append(crypt_card)
        idx += 1

    # --- Library (mandatory) ---
    library_found = False
    while idx < n:
        line = lines[idx]
        m = LIBRARY_HEADER_RE.search(line)
        if m:
            library_found = True
            library_count = int(m.group("count"))
            idx += 1
            current_section: LibrarySection | None = None
            while idx < n:
                line = lines[idx]
                if not line.strip():
                    idx += 1
                    continue
                sm = SECTION_HEADER_RE.match(line.strip())
                if sm and not line.strip()[0].isdigit():
                    current_section = LibrarySection(
                        name=sm.group("name").strip(),
                        count=int(sm.group("count")),
                    )
                    library_sections.append(current_section)
                    idx += 1
                    continue
                library_card = _parse_library_line(line)
                if library_card:
                    if current_section is None:
                        current_section = LibrarySection(name="", count=0)
                        library_sections.append(current_section)
                    current_section.cards.append(library_card)
                idx += 1
            break
        idx += 1

    if not library_found:
        raise ValueError("Mandatory 'Library (N cards)' block not found in deck")

    return Deck(
        name=deck_name,
        created_by=created_by,
        description=description,
        crypt_count=crypt_count,
        crypt_min=crypt_min,
        crypt_max=crypt_max,
        crypt_avg=crypt_avg,
        crypt=crypt_cards,
        library_count=library_count,
        library_sections=library_sections,
    )
