"""Deck block parser — extracts crypt and library sections from TWD text."""

from vtes_scraper.models import CryptCard, Deck, LibrarySection
from vtes_scraper.parser._helpers import (
    CREATED_BY_RE,
    CRYPT_HEADER_RE,
    DECK_NAME_RE,
    DESCRIPTION_RE,
    LIBRARY_HEADER_RE,
    SECTION_HEADER_RE,
    _parse_crypt_line,
    _parse_library_line,
)


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
    crypt_header_idx = next(
        (i for i, line in enumerate(lines) if CRYPT_HEADER_RE.search(line)), 0
    )
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
