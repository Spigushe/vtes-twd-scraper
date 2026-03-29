"""
Parser for TWD posts scraped from the VEKN forum.

Submodules:
  _helpers — regex constants and line-level helper functions
  _header  — strict and lenient header parsers
  _deck    — deck block parser (crypt + library sections)
  _twd     — main entry point (parse_twd_text)
"""

from vtes_scraper.parser._helpers import (
    CRYPT_HEADER_RE,
    CRYPT_LINE_RE,
    LIBRARY_HEADER_RE,
    LIBRARY_LINE_RE,
    PLAYERS_RE,
    ROUNDS_RE,
    SECTION_HEADER_RE,
    VEKN_URL_RE,
    _extract_vekn_url,
    _normalize_rounds,
    _parse_crypt_line,
    _parse_library_line,
    _split_date,
    _strip_hash_comment,
    _strip_inline_comment,
)
from vtes_scraper.parser._twd import parse_twd_text

__all__ = [
    # Regex constants
    "CRYPT_HEADER_RE",
    "CRYPT_LINE_RE",
    "LIBRARY_HEADER_RE",
    "LIBRARY_LINE_RE",
    "PLAYERS_RE",
    "ROUNDS_RE",
    "SECTION_HEADER_RE",
    "VEKN_URL_RE",
    # Helpers
    "_extract_vekn_url",
    "_normalize_rounds",
    "_parse_crypt_line",
    "_parse_library_line",
    "_split_date",
    "_strip_hash_comment",
    "_strip_inline_comment",
    # Main entry point
    "parse_twd_text",
]
