import io
import json

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

from vtes_scraper.models import Tournament


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
