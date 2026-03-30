"""CLI subcommand: parse.

Bidirectional conversion between TWD text format and YAML:
  - .txt  → YAML
  - .yaml / .yml → TXT
"""

import argparse
from pathlib import Path

from ruamel.yaml import YAML

from vtes_scraper.cli._common import SubParsersAction, console, setup_logging
from vtes_scraper.models import Tournament
from vtes_scraper.output import (
    tournament_to_txt,
    tournament_to_yaml_str,
    write_tournament_txt,
    write_tournament_yaml,
)
from vtes_scraper.parser import parse_twd_text

_YAML_EXTENSIONS = {".yaml", ".yml"}
_TXT_EXTENSIONS = {".txt"}


def register(sub: SubParsersAction) -> None:
    p = sub.add_parser(
        "parse",
        help="Convert between TWD text and YAML formats.",
    )
    p.add_argument(
        "input_file",
        type=Path,
        help="Path to a .txt or .yaml file. Direction is inferred from the extension.",
    )
    p.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=None,
        dest="output_dir",
        help="Directory to write the output file. If omitted, prints to stdout.",
    )
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(func=run)


def _parse_txt_to_yaml(args: argparse.Namespace) -> int:
    """Convert a TWD .txt file to YAML."""
    raw = args.input_file.read_text(encoding="utf-8")
    try:
        tournament = parse_twd_text(raw)
    except ValueError as exc:
        console.print(f"[red]Parse error:[/red] {exc}")
        return 1

    if args.output_dir is None:
        console.print(tournament_to_yaml_str(tournament))
    else:
        try:
            path = write_tournament_yaml(tournament, args.output_dir, overwrite=args.overwrite)
            console.print(f"[green]✓[/green] Written to {path}")
        except FileExistsError as exc:
            console.print(f"[yellow]─[/yellow] {exc}")
    return 0


def _parse_yaml_to_txt(args: argparse.Namespace) -> int:
    """Convert a YAML tournament file to TWD .txt format."""
    yaml = YAML()
    try:
        data = yaml.load(  # pyright: ignore[reportUnknownMemberType]
            args.input_file.read_text(encoding="utf-8")
        )
        tournament = Tournament.model_validate(data)
    except Exception as exc:
        console.print(f"[red]Parse error:[/red] {exc}")
        return 1

    if args.output_dir is None:
        console.print(tournament_to_txt(tournament))
    else:
        try:
            path = write_tournament_txt(tournament, args.output_dir, overwrite=args.overwrite)
            console.print(f"[green]✓[/green] Written to {path}")
        except FileExistsError as exc:
            console.print(f"[yellow]─[/yellow] {exc}")
    return 0


def run(args: argparse.Namespace) -> int:
    """Convert between TWD text and YAML formats."""
    setup_logging(args.verbose)

    ext = args.input_file.suffix.lower()
    if ext in _TXT_EXTENSIONS:
        return _parse_txt_to_yaml(args)
    if ext in _YAML_EXTENSIONS:
        return _parse_yaml_to_txt(args)

    console.print(
        f"[red]Error:[/red] Unsupported file extension '{ext}'. Expected .txt, .yaml, or .yml."
    )
    return 1
