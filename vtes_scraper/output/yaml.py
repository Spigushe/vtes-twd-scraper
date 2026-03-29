import io
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

from vtes_scraper.models import Tournament
from vtes_scraper.output._common import _date_subdir


def _to_serializable(obj) -> dict:
    """Convert a Pydantic model to a plain dict, preserving Python native types.

    Uses model_dump() (not JSON round-trip) so that date objects remain as
    datetime.date instances — ruamel.yaml then renders them as bare YAML dates
    (2026-03-15) rather than quoted strings ('2026-03-15').
    """

    def _filter_none(value: object) -> object:
        if isinstance(value, dict):
            return {k: _filter_none(v) for k, v in value.items() if v is not None}
        if isinstance(value, list):
            return [_filter_none(item) for item in value]
        return value

    result = _filter_none(obj.model_dump())
    assert isinstance(result, dict)
    return result


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


def _find_existing_yaml(output_dir: Path, filename: str) -> Path | None:
    """Search for *filename* anywhere under *output_dir* and return the first match."""
    for match in output_dir.rglob(filename):
        return match
    return None


def write_tournament_yaml(
    tournament: Tournament,
    output_dir: Path,
    overwrite: bool = False,
) -> Path:
    """
    Write a Tournament to {output_dir}/YYYY/MM/{event_id}.yaml

    Before writing, the whole output_dir tree (including error sub-folders) is
    searched for an existing file with the same event_id:

    * Same content  → skip silently (raise FileExistsError).
    * Different content → unlink the old file (wherever it lives) and write the
      new one at the canonical YYYY/MM location.
    * No prior file  → write normally.

    Raises:
        FileExistsError: if an identical file already exists and overwrite=False
    """
    new_content = tournament_to_yaml_str(tournament)

    existing = _find_existing_yaml(output_dir, tournament.yaml_filename)
    if existing is not None:
        if existing.read_text(encoding="utf-8") == new_content and not overwrite:
            raise FileExistsError(
                f"Output file already exists with identical content: {existing}. "
                "Use --overwrite to replace."
            )
        existing.unlink()

    dest = output_dir / _date_subdir(tournament)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / tournament.yaml_filename
    path.write_text(new_content, encoding="utf-8")
    return path
