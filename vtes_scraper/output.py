"""
YAML output — uses ruamel.yaml to preserve:
  - field order (defined by model)
  - multiline strings (description block)
  - consistent formatting
"""

from __future__ import annotations

import json
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

from vtes_scraper.models import Tournament


def _to_serializable(obj) -> dict:
    """Convert a Pydantic model to a plain dict, recursively."""
    # Use model_dump() (Pydantic v2) — exclude None values for cleanliness
    return json.loads(obj.model_dump_json(exclude_none=True))


def _prepare_yaml_dict(tournament: Tournament) -> dict:
    """
    Build an ordered dict suitable for YAML output.
    Handles multiline description as a literal block scalar (|).
    """
    d = _to_serializable(tournament)

    # Promote description to literal block scalar so YAML renders it
    # with the '|' style instead of a quoted single-line string.
    if "deck" in d and d["deck"] and "description" in d["deck"]:
        desc = d["deck"]["description"]
        if desc and "\n" in desc:
            d["deck"]["description"] = LiteralScalarString(desc)

    return d


def tournament_to_yaml_str(tournament: Tournament) -> str:
    """Serialize a Tournament to a YAML string."""
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    yaml.width = 120

    import io

    buf = io.StringIO()
    yaml.dump(_prepare_yaml_dict(tournament), buf)
    return buf.getvalue()


def write_tournament_yaml(
    tournament: Tournament,
    output_dir: Path,
    overwrite: bool = False,
) -> Path:
    """
    Write a Tournament to {output_dir}/{event_id}.yaml

    Args:
        tournament: parsed Tournament object
        output_dir: directory to write into (created if missing)
        overwrite: if False, skip existing files

    Returns:
        Path of the written file.

    Raises:
        FileExistsError: if file exists and overwrite=False
        ValueError: if tournament has no event_id
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = tournament.output_filename
    path = output_dir / filename

    if path.exists() and not overwrite:
        raise FileExistsError(f"Output file already exists: {path}. Use --overwrite to replace.")

    content = tournament_to_yaml_str(tournament)
    path.write_text(content, encoding="utf-8")
    return path
