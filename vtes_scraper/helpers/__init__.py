import re
from datetime import datetime
from pathlib import Path

from vtes_scraper.helpers.txt import tournament_to_txt
from vtes_scraper.helpers.yaml import tournament_to_yaml_str
from vtes_scraper.models import Tournament


def date_subdir(tournament: Tournament) -> Path:
    """Return a Path(YYYY/MM) derived from tournament.date_start.

    Handles ordinal suffixes (1st, 2nd, 3rd, 4th … 31st).
    Falls back to "unknown/unknown" if the date cannot be parsed.
    """
    clean = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", tournament.date_start)
    for fmt in ("%B %d %Y", "%b %d %Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(clean.strip(), fmt)
            return Path(f"{dt.year:04d}/{dt.month:02d}")
        except ValueError:
            continue
    return Path("unknown/unknown")


__all__ = [
    "date_subdir",
    "tournament_to_yaml_str",
    "tournament_to_txt",
]
