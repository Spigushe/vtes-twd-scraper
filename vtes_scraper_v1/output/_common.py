from pathlib import Path

from vtes_scraper_v1.models import Tournament


def _date_subdir(tournament: Tournament) -> Path:
    """Return a Path(YYYY/MM) derived from tournament.date_start."""
    d = tournament.date_start
    return Path(f"{d.year:04d}/{d.month:02d}")
