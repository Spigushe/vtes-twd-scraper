"""Main entry point for TWD text parsing."""

from vtes_scraper.models import Tournament
from vtes_scraper.parser._deck import _parse_deck_block
from vtes_scraper.parser._header import (
    _parse_header_lenient,
    _parse_header_strict,
)
from vtes_scraper.parser._helpers import CRYPT_HEADER_RE, _strip_hash_comment


def parse_twd_text(raw: str, forum_post_url: str | None = None) -> Tournament:
    lines = [_strip_hash_comment(line) for line in raw.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    if len(lines) < 7:
        raise ValueError(f"TWD block has fewer than 7 mandatory lines (got {len(lines)})")

    deck_start = next(
        (i for i, line in enumerate(lines) if CRYPT_HEADER_RE.search(line)),
        None,
    )
    if deck_start is None:
        raise ValueError("Mandatory 'Crypt (N cards, ...)' block not found")

    header_lines = lines[:deck_start]

    try:
        fields = _parse_header_strict(header_lines)
    except ValueError:
        fields = _parse_header_lenient(header_lines)

    deck = _parse_deck_block(lines)  # receives full lines; finds crypt idx itself
    return Tournament(forum_post_url=forum_post_url, deck=deck, **fields)
