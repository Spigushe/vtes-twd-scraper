"""Regex constants and line-level helper functions for TWD parsing."""

import re

from vtes_scraper.models import CryptCard, LibraryCard

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
# Line-level helpers
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
