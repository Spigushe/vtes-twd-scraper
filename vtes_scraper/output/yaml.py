import io
import json
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

from vtes_scraper.models import Tournament
from vtes_scraper.output._common import _date_subdir


def _to_serializable(obj) -> dict:
    """Convert a Pydantic model to a plain dict, recursively."""
    return json.loads(obj.model_dump_json(exclude_none=True))


def _prepare_yaml_dict(tournament: Tournament) -> dict:
    """
    Build an ordered dict suitable for YAML output.
    Handles multiline description as a literal block scalar (|).
    """
    d = _to_serializable(tournament)

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

    buf = io.StringIO()
    yaml.dump(_prepare_yaml_dict(tournament), buf)
    return buf.getvalue()


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
    dest = output_dir / _date_subdir(tournament)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / tournament.yaml_filename

    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Output file already exists: {path}. Use --overwrite to replace."
        )

    path.write_text(tournament_to_yaml_str(tournament), encoding="utf-8")
    return path
