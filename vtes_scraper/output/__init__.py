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

from vtes_scraper.output.txt import tournament_to_txt, write_tournament_txt
from vtes_scraper.output.yaml import tournament_to_yaml_str, write_tournament_yaml

__all__ = [
    "tournament_to_yaml_str",
    "write_tournament_yaml",
    "tournament_to_txt",
    "write_tournament_txt",
]
