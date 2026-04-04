"""
Data models for VTES Tournament Winning Decks.
Based on: https://github.com/GiottoVerducci/TWD/blob/master/README.md
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TypedDict

from pydantic import BaseModel, field_validator, model_validator

DATE_FORMATS = (
    "%B %d %Y",
    "%b %d %Y",
    "%d %B %Y",
    "%d %b %Y",
    "%Y-%m-%d",
    "%d/%m/%Y",
)


class Library_Card_Dict(TypedDict, total=False):
    count: int
    name: str
    comment: str | None


class Library_Section_Dict(TypedDict, total=False):
    name: str
    count: int
    cards: list[Library_Card_Dict]


class Crypt_Card_Dict(TypedDict, total=False):
    count: int
    name: str
    capacity: int
    disciplines: str
    title: str | None
    clan: str
    grouping: int | str
    comment: str | None


class Deck_Dict(TypedDict, total=False):
    name: str | None
    created_by: str | None
    description: str
    crypt_count: int
    crypt_min: int
    crypt_max: int
    crypt_avg: float
    crypt: list[Crypt_Card_Dict]
    library_count: int
    library_sections: list[Library_Section_Dict]


class Tournament_Dict(TypedDict, total=False):
    name: str
    location: str
    date_start: date
    date_end: date | None
    rounds_format: str
    players_count: int
    winner: str
    vekn_number: int | None
    event_url: str
    event_id: int | None
    vp_comment: str | None
    forum_post_url: str | None
    deck: Deck_Dict


class CryptCard(BaseModel):
    count: int
    name: str
    capacity: int
    disciplines: str  # raw string, e.g. "PRO ani cel for"
    title: str | None = None  # e.g. "Primogen" (not always present)
    clan: str
    grouping: int | str  # int for normal groups (1–8); "ANY" for group-independent cards
    comment: str | None = None  # after ' -- '


class LibraryCard(BaseModel):
    count: int
    name: str
    comment: str | None = None  # after ' -- '


class LibrarySection(BaseModel):
    """A named section inside the Library block, e.g. 'Master (14; 2 trifle)'."""

    name: str
    count: int
    cards: list[LibraryCard] = []


class Deck(BaseModel):
    name: str | None = None
    created_by: str | None = None  # only when different from winner
    description: str = ""
    crypt_count: int = 0
    crypt_min: int = 0
    crypt_max: int = 0
    crypt_avg: float = 0.0
    crypt: list[CryptCard] = []
    library_count: int = 0
    library_sections: list[LibrarySection] = []


class Tournament(BaseModel):
    """
    Represents one TWD entry.

    Mandatory fields (in order per README spec):
      1. name
      2. location
      3. date (or date_start -- date_end)
      4. rounds_format (e.g. "3R+F")
      5. players_count
      6. winner
      7. event_url  →  event_id is derived from this

    Optional:
      - vp_comment (e.g. "-- 5VP in final")
      - deck
    """

    # --- Mandatory ---
    name: str
    location: str  # "Online" or "City, Country" or "Place, City, Country"
    date_start: date
    date_end: date | None = None  # only for multi-day events
    rounds_format: str  # "2R+F" or "3R+F"
    players_count: int
    winner: str
    vekn_number: int | None = None  # VEKN member number, e.g. 3940009
    event_url: str  # https://www.vekn.net/event-calendar/event/XXXX

    # --- Derived ---
    event_id: int | None = None  # extracted from event_url

    # --- Optional ---
    vp_comment: str | None = None
    forum_post_url: str | None = None  # source forum URL (for traceability)

    # --- Keep at the end to keep tournament data together ---
    deck: Deck

    @model_validator(mode="after")
    def derive_event_id(self) -> Tournament:
        """Extract numeric id from event_url and normalise the URL.

        Any vekn.net URL containing '/event/<id>' is accepted; the stored
        ``event_url`` is always rewritten to the canonical form
        ``https://www.vekn.net/event-calendar/event/<id>``.
        """
        if self.event_url:
            match = re.search(r"/event/(\d+)", self.event_url)
            if match:
                self.event_id = int(match.group(1))
                self.event_url = f"https://www.vekn.net/event-calendar/event/{self.event_id}"
        return self

    @field_validator("rounds_format")
    @classmethod
    def validate_rounds_format(cls, v: str) -> str:
        if not re.fullmatch(r"\d+R\+F", v):
            raise ValueError(f"rounds_format must match 'NR+F' (e.g. '3R+F'), got: '{v}'")
        return v

    @field_validator("players_count", mode="before")
    @classmethod
    def coerce_players(cls, v: str | int) -> int:
        """Accept '13 players' or 13."""
        if isinstance(v, str):
            match = re.search(r"\d+", v)
            if match:
                return int(match.group())
        return int(v)

    @field_validator("date_start", "date_end", mode="before")
    @classmethod
    def parse_date(cls, v: str | date | None) -> date | None:
        """Parse date strings in various formats into a date object.

        Supported formats:
          - ISO:            2026-02-28
          - DD/MM/YYYY:     28/02/2026
          - Month DD YYYY:  February 22 2026  (ordinal suffixes stripped)
          - DD Month YYYY:  22 February 2026  (ordinal suffixes stripped)
          - Abbreviated:    Feb 22 2026 / 22 Feb 2026
        """
        if v is None or isinstance(v, date):
            return v
        clean = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", v).replace(",", "").strip()
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(clean, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Cannot parse date: {v!r}")

    @property
    def yaml_filename(self) -> str:
        """TWD convention: {event_id}.yaml"""
        if self.event_id:
            return f"{self.event_id}.yaml"
        # Fallback: should not happen if event_url is valid
        raise ValueError("Cannot derive filename: event_id is missing")

    @property
    def txt_filename(self) -> str:
        """TWD convention: {event_id}.txt"""
        if self.event_id:
            return f"{self.event_id}.txt"
        # Fallback: should not happen if event_url is valid
        raise ValueError("Cannot derive filename: event_id is missing")
