"""
Data models for VTES Tournament Winning Decks.
Based on: https://github.com/GiottoVerducci/TWD/blob/master/README.md
"""

from __future__ import annotations

import re

from pydantic import BaseModel, field_validator, model_validator


class CryptCard(BaseModel):
    count: int
    name: str
    capacity: int
    disciplines: str  # raw string, e.g. "PRO ani cel for"
    title: str | None = None  # e.g. "Primogen" (not always present)
    clan: str
    grouping: int
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
    date_start: str  # "March 25th 2023"
    date_end: str | None = None  # only for multi-day events
    rounds_format: str  # "2R+F" or "3R+F"
    players_count: int
    winner: str
    event_url: str  # https://www.vekn.net/event-calendar/event/XXXX

    # --- Derived ---
    event_id: str | None = None  # extracted from event_url

    # --- Optional ---
    vp_comment: str | None = None
    forum_post_url: str | None = None  # source forum URL (for traceability)
    deck: Deck

    @model_validator(mode="after")
    def derive_event_id(self) -> Tournament:
        """Extract numeric id from event_url, e.g. '.../event/8470' → '8470'."""
        if self.event_url:
            match = re.search(r"/event/(\d+)", self.event_url)
            if match:
                self.event_id = match.group(1)
        return self

    @field_validator("rounds_format")
    @classmethod
    def validate_rounds_format(cls, v: str) -> str:
        if not re.fullmatch(r"\d+R\+F", v):
            raise ValueError(f"rounds_format must match 'NR+F' (e.g. '3R+F'), got: '{v}'")
        return v

    @field_validator("players_count", mode="before")
    @classmethod
    def coerce_players(cls, v):
        """Accept '13 players' or 13."""
        if isinstance(v, str):
            match = re.search(r"\d+", v)
            if match:
                return int(match.group())
        return v

    @property
    def output_filename(self) -> str:
        """TWD convention: {event_id}.yaml"""
        if self.event_id:
            return f"{self.event_id}.yaml"
        # Fallback: should not happen if event_url is valid
        raise ValueError("Cannot derive filename: event_id is missing")
