"""
Output serializers for Tournament objects.

Supports two formats:
  - YAML  (ruamel.yaml, preserves field order and multiline strings)
  - TXT   (TWD text format expected by https://github.com/GiottoVerducci/TWD)

TXT format reference:

    Event Name
    Event Location
    Event Date
    Number of Rounds (e.g. 3R+F)
    Number of Players (e.g. 13 players)
    Winner
    Event URL

    Deck Name: ...          # optional
    Created by: ...         # optional, only when different from winner
    Description:            # optional
    ...description text...

    Crypt (N cards, min=X max=Y avg=Z.ZZ)
    ----------------------------------
    Nx Vampire Name  capacity  disciplines  Clan:group
    ...

    Library (N cards)
    Section Name (count)
    Nx Card Name
    ...
"""

from __future__ import annotations

from pathlib import Path

from vtes_scraper.helpers import date_subdir, tournament_to_txt, tournament_to_yaml_str
from vtes_scraper.models import Tournament


def write_tournament_yaml(
    tournament: Tournament,
    output_dir: Path,
    overwrite: bool = False,
) -> Path:
    """
    Write a Tournament to {output_dir}/YYYY/MM/{event_id}.yaml

    Raises:
        FileExistsError: if file exists and overwrite=False
    """
    dest = output_dir / date_subdir(tournament)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / tournament.yaml_filename

    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Output file already exists: {path}. Use --overwrite to replace."
        )

    path.write_text(tournament_to_yaml_str(tournament), encoding="utf-8")
    return path


def write_tournament_txt(
    tournament: Tournament,
    output_dir: Path,
    overwrite: bool = False,
) -> Path:
    """
    Write a Tournament to {output_dir}/YYYY/MM/{event_id}.txt

    Raises:
        FileExistsError: if file exists and overwrite=False
        ValueError: if tournament has no event_id
    """
    dest = output_dir / date_subdir(tournament)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / tournament.txt_filename

    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Output file already exists: {path}. Use --overwrite to replace."
        )

    path.write_text(tournament_to_txt(tournament), encoding="utf-8")
    return path
